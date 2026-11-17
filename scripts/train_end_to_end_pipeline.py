#!/usr/bin/env python3
"""
End-to-End Retraining Pipeline for Indian ANPR (YOLO11n Detector + CRNN OCR).

Sequentially executes:
1. Full Fleet YOLO Dataset Synthesis (Replay base + 2,535 video frames across all 99 clips,
   including 683 sealed hard-negative background frames).
2. YOLO11n Detector Retraining (30 epochs, AMP, RTX 4050 GPU) with ONNX export.
3. Expanded CRNN OCR Retraining (40 epochs, Cosine Annealing, 13,285 train crops including
   2,208 freshly harvested video crops) with ONNX export.
4. Summary persistence and telemetry logging.
"""

import os
import sys
import time
import json
import shutil
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR

ROOT_DIR = Path("/home/kirat/coding/honours")
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "research_track" / "hitl_anpr" / "src"))

from ultralytics import YOLO
from scripts.train_ocr_extended import (
    CRNN,
    EnhancedIndianPlateOCRDataset,
    collate_fn,
    ctc_decode,
    evaluate,
    ALPHABET,
    NUM_CLASSES,
    CHAR2IDX,
    OCR_IN_V1_DIR,
    OCR_T1_DIR
)

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

YOLO_BASE_WEIGHTS = ROOT_DIR / "weights" / "yolo11n_plate_detector_best.pt"
YOLO_DEST_PT = ROOT_DIR / "weights" / "yolo11n_plate_detector_finetuned.pt"
YOLO_DEST_ONNX = ROOT_DIR / "weights" / "yolo11n_plate_detector_finetuned.onnx"
YOLO_FLEET_PT = ROOT_DIR / "weights" / "yolo11n_plate_detector_fleet_best.pt"
YOLO_FLEET_ONNX = ROOT_DIR / "weights" / "yolo11n_plate_detector_fleet_best.onnx"

CRNN_DEST_PT = ROOT_DIR / "weights" / "indian_plate_crnn_best.pt"
CRNN_DEST_ONNX = ROOT_DIR / "weights" / "indian_plate_crnn_best.onnx"

DATASET_ROOT = ROOT_DIR / "runs" / "datasets" / "full_fleet_plate_dataset"
DATA_YAML = DATASET_ROOT / "data.yaml"
SUMMARY_JSON = ROOT_DIR / "runs" / "end_to_end_retraining_summary.json"

# =========================================================================
# STEP 1: ASSEMBLE FULL FLEET YOLO DATASET
# =========================================================================

def assemble_yolo_dataset():
    print("=" * 75)
    print("Step 1: Assembling Full Fleet YOLO Dataset (Base + All 99 Videos)")
    print("=" * 75)

    if DATASET_ROOT.is_dir():
        shutil.rmtree(DATASET_ROOT, ignore_errors=True)

    img_train_dir = DATASET_ROOT / "images" / "train"
    img_val_dir = DATASET_ROOT / "images" / "val"
    lbl_train_dir = DATASET_ROOT / "labels" / "train"
    lbl_val_dir = DATASET_ROOT / "labels" / "val"

    for d in [img_train_dir, img_val_dir, lbl_train_dir, lbl_val_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Replay base unified dataset
    base_dir = ROOT_DIR / "training_1" / "unified_plate_dataset"
    base_train_imgs = sorted(list((base_dir / "images" / "train").glob("*.jpg")))
    base_val_imgs = sorted(list((base_dir / "images" / "val").glob("*.jpg")))

    print(f"Replaying base unified dataset: {len(base_train_imgs)} train, {len(base_val_imgs)} val images...")
    for p in base_train_imgs:
        os.symlink(p.resolve(), img_train_dir / p.name)
        lp = base_dir / "labels" / "train" / f"{p.stem}.txt"
        if lp.is_file():
            shutil.copyfile(lp, lbl_train_dir / f"{p.stem}.txt")
        else:
            (lbl_train_dir / f"{p.stem}.txt").touch()

    for p in base_val_imgs:
        os.symlink(p.resolve(), img_val_dir / p.name)
        lp = base_dir / "labels" / "val" / f"{p.stem}.txt"
        if lp.is_file():
            shutil.copyfile(lp, lbl_val_dir / f"{p.stem}.txt")
        else:
            (lbl_val_dir / f"{p.stem}.txt").touch()

    # 2. Ingest all 99 video folders
    all_video_frames = []
    hard_neg_count = 0
    box_count = 0

    for vid in range(1, 100):
        vdir = ROOT_DIR / "training" / str(vid)
        img_dir = vdir / "images"
        lbl_dir = vdir / "labels"
        if not img_dir.is_dir() or not lbl_dir.is_dir():
            continue

        for jpg_file in sorted(img_dir.glob("*.jpg")):
            txt_file = lbl_dir / f"{jpg_file.stem}.txt"
            if txt_file.is_file():
                content = txt_file.read_text().strip()
                n_boxes = len(content.splitlines()) if content else 0
                box_count += n_boxes
                if n_boxes == 0:
                    hard_neg_count += 1
                all_video_frames.append((jpg_file, txt_file, vid))

    random.shuffle(all_video_frames)
    val_n = int(len(all_video_frames) * 0.15)
    video_val = all_video_frames[:val_n]
    video_train = all_video_frames[val_n:]

    print(f"Ingesting Video Fleet: {len(all_video_frames)} frames ({len(video_train)} train, {len(video_val)} val)")
    print(f"Total Plate Boxes: {box_count} | Sealed Hard-Negative Background Frames: {hard_neg_count}")

    for jpg_path, txt_path, vid in video_train:
        dst_name = f"v{vid}_{jpg_path.name}"
        os.symlink(jpg_path.resolve(), img_train_dir / dst_name)
        shutil.copyfile(txt_path, lbl_train_dir / f"v{vid}_{jpg_path.stem}.txt")

    for jpg_path, txt_path, vid in video_val:
        dst_name = f"v{vid}_{jpg_path.name}"
        os.symlink(jpg_path.resolve(), img_val_dir / dst_name)
        shutil.copyfile(txt_path, lbl_val_dir / f"v{vid}_{jpg_path.stem}.txt")

    # 3. Write data.yaml
    yaml_content = f"""path: {DATASET_ROOT}
train: images/train
val: images/val

names:
  0: license_plate
"""
    DATA_YAML.write_text(yaml_content)

    total_train = len(list(img_train_dir.glob("*.jpg")))
    total_val = len(list(img_val_dir.glob("*.jpg")))
    print(f"YOLO Dataset Ready at: {DATASET_ROOT}")
    print(f"Total Combined Images: {total_train + total_val} ({total_train} Train, {total_val} Validation)")
    return total_train, total_val

# =========================================================================
# STEP 2: TRAIN YOLO11N DETECTOR
# =========================================================================

def train_yolo():
    print("\n" + "=" * 75)
    print("Step 2: Training YOLO11n Plate Detector (Full Fleet Retraining)")
    print(f"Base Weights: {YOLO_BASE_WEIGHTS}")
    print(f"Target Checkpoint: {YOLO_DEST_PT}")
    print("=" * 75)

    start_time = time.time()
    model = YOLO(str(YOLO_BASE_WEIGHTS))

    results = model.train(
        data=str(DATA_YAML),
        epochs=30,
        imgsz=640,
        batch=16,
        device=0,
        workers=4,
        patience=15,
        lr0=0.001,
        lrf=0.01,
        project=str(ROOT_DIR / "runs" / "detect"),
        name="plate_detector_yolo11n_fleet",
        exist_ok=True,
        amp=True,
        plots=True,
        save=True,
        degrees=4.0,
        perspective=0.0005,
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.4,
        fliplr=0.5,
        flipud=0.0,
        mosaic=0.5,
        mixup=0.05,
        verbose=True
    )

    elapsed_min = (time.time() - start_time) / 60.0
    print(f"\nYOLO Fleet Training completed in {elapsed_min:.1f} minutes.")

    best_pt = ROOT_DIR / "runs" / "detect" / "plate_detector_yolo11n_fleet" / "weights" / "best.pt"
    if best_pt.is_file():
        shutil.copyfile(best_pt, YOLO_FLEET_PT)
        shutil.copyfile(best_pt, YOLO_DEST_PT)
        print(f"Saved best weights to {YOLO_DEST_PT} and {YOLO_FLEET_PT}")

        # Export ONNX
        try:
            print("Exporting YOLO11n to ONNX...")
            best_model = YOLO(str(best_pt))
            onnx_path = best_model.export(format="onnx", imgsz=640, dynamic=False)
            if Path(onnx_path).is_file():
                shutil.copyfile(onnx_path, YOLO_FLEET_ONNX)
                shutil.copyfile(onnx_path, YOLO_DEST_ONNX)
                print(f"Saved ONNX model to {YOLO_DEST_ONNX}")
        except Exception as e:
            print(f"ONNX export warning: {e}")

    # Validation metrics
    val_metrics = {}
    try:
        val_res = model.val(data=str(DATA_YAML), imgsz=640, batch=16, device=0)
        val_metrics = {
            "precision": round(float(val_res.box.mp), 4),
            "recall": round(float(val_res.box.mr), 4),
            "map50": round(float(val_res.box.map50), 4),
            "map50_95": round(float(val_res.box.map), 4)
        }
        print(f"YOLO Validation Results: P={val_metrics['precision']*100:.1f}%, "
              f"R={val_metrics['recall']*100:.1f}%, mAP50={val_metrics['map50']*100:.1f}%, "
              f"mAP50-95={val_metrics['map50_95']*100:.1f}%")
    except Exception as e:
        print(f"Validation metrics calculation notice: {e}")

    return val_metrics, elapsed_min

# =========================================================================
# STEP 3: TRAIN CRNN OCR (ROUND 2)
# =========================================================================

def load_all_ocr_data():
    import csv
    train_items = []
    val_items = []

    # 1. Prepared ocr_in_v1
    if OCR_IN_V1_DIR.is_dir():
        t_csv = OCR_IN_V1_DIR / "train.csv"
        v_csv = OCR_IN_V1_DIR / "val.csv"
        if t_csv.is_file():
            with open(t_csv) as f:
                for r in csv.DictReader(f):
                    p = (OCR_IN_V1_DIR / r["image_path"]).resolve()
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            train_items.append((p, clean_text))
        if v_csv.is_file():
            with open(v_csv) as f:
                for r in csv.DictReader(f):
                    p = (OCR_IN_V1_DIR / r["image_path"]).resolve()
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            val_items.append((p, clean_text))

    # 2. Harvested video crops in training_1/ocr_dataset
    if OCR_T1_DIR.is_dir():
        lbl_csv = OCR_T1_DIR / "labels.csv"
        if lbl_csv.is_file():
            t1_items = []
            with open(lbl_csv) as f:
                for r in csv.DictReader(f):
                    p = OCR_T1_DIR / "images" / r["image_filename"]
                    if p.is_file() and r["plate_text"]:
                        clean_text = "".join(c for c in r["plate_text"].upper() if c in CHAR2IDX)
                        if len(clean_text) >= 4:
                            t1_items.append((p, clean_text))
            random.shuffle(t1_items)
            val_split_n = int(len(t1_items) * 0.15)
            val_items.extend(t1_items[:val_split_n])
            train_items.extend(t1_items[val_split_n:])

    random.shuffle(train_items)
    print(f"Total OCR Dataset Pool: {len(train_items)} Train crops, {len(val_items)} Validation crops.")
    return train_items, val_items

def train_crnn():
    print("\n" + "=" * 75)
    print("Step 3: Training PyTorch CRNN OCR Model (Round 2 on 3,290+ Harvested Crops)")
    print(f"Resuming weights from: {CRNN_DEST_PT}")
    print("=" * 75)

    train_items, val_items = load_all_ocr_data()
    train_dataset = EnhancedIndianPlateOCRDataset(train_items, is_train=True)
    val_dataset = EnhancedIndianPlateOCRDataset(val_items, is_train=False)

    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True, num_workers=4, collate_fn=collate_fn, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False, num_workers=4, collate_fn=collate_fn, pin_memory=True)

    model = CRNN(num_classes=NUM_CLASSES).to(DEVICE)
    best_exact_acc = 63.12
    start_epoch = 81
    total_epochs = 120

    if CRNN_DEST_PT.is_file():
        ckpt = torch.load(str(CRNN_DEST_PT), map_location=DEVICE)
        model.load_state_dict(ckpt["model_state_dict"])
        best_exact_acc = float(ckpt.get("best_exact_acc", 63.12))
        print(f"Loaded existing OCR weights! Baseline accuracy: {best_exact_acc:.2f}%")

    criterion = nn.CTCLoss(blank=0, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)

    remaining_epochs = total_epochs - start_epoch + 1
    scheduler = CosineAnnealingLR(optimizer, T_max=remaining_epochs, eta_min=1e-5)
    scaler = torch.amp.GradScaler('cuda')

    start_time = time.time()
    best_cer = 8.51

    for epoch in range(start_epoch, total_epochs + 1):
        model.train()
        train_loss = 0.0
        train_samples = 0
        ep_start = time.time()

        for imgs, targets, target_lengths, _ in train_loader:
            imgs = imgs.to(DEVICE, non_blocking=True)
            targets = targets.to(DEVICE, non_blocking=True)
            target_lengths = target_lengths.to(DEVICE, non_blocking=True)
            b_size = imgs.size(0)

            optimizer.zero_grad()
            with torch.amp.autocast('cuda'):
                logits = model(imgs)
                w_seq = logits.size(1)
                input_lengths = torch.full((b_size,), w_seq, dtype=torch.long, device=DEVICE)
                log_probs = logits.log_softmax(2).permute(1, 0, 2)
                loss = criterion(log_probs, targets, input_lengths, target_lengths)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()

            train_loss += loss.item() * b_size
            train_samples += b_size

        scheduler.step()
        ep_time = time.time() - ep_start
        train_loss /= max(train_samples, 1)

        # Validation
        val_loss, exact_acc, cer = evaluate(model, val_loader, criterion, DEVICE)

        is_best = exact_acc > best_exact_acc
        if is_best:
            best_exact_acc = exact_acc
            best_cer = cer
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "best_exact_acc": best_exact_acc,
                "cer": cer,
                "alphabet": ALPHABET,
                "num_classes": NUM_CLASSES
            }, str(CRNN_DEST_PT))

        print(f"Epoch {epoch:03d}/{total_epochs:03d} [{ep_time:.1f}s] - Train: {train_loss:.4f} | "
              f"Val: {val_loss:.4f} | Exact: {exact_acc:.2f}% | CER: {cer:.2f}% {'🌟 (New Best!)' if is_best else ''}")

    elapsed_min = (time.time() - start_time) / 60.0
    print(f"\nCRNN Round 2 training completed in {elapsed_min:.1f} minutes. Best Exact Match: {best_exact_acc:.2f}%, CER: {best_cer:.2f}%")

    # Re-export ONNX
    print("Re-exporting CRNN OCR model to ONNX...")
    try:
        best_ckpt = torch.load(str(CRNN_DEST_PT), map_location="cpu")
        export_model = CRNN(num_classes=NUM_CLASSES)
        export_model.load_state_dict(best_ckpt["model_state_dict"])
        export_model.eval()

        dummy_input = torch.randn(1, 3, 32, 128)
        torch.onnx.export(
            export_model,
            dummy_input,
            str(CRNN_DEST_ONNX),
            input_names=["input"],
            output_names=["logits"],
            dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=14,
            dynamo=False
        )
        print(f"Updated ONNX OCR Model: {CRNN_DEST_ONNX}")
    except Exception as e:
        print(f"Warning during CRNN ONNX export: {e}")

    return {
        "best_exact_acc": round(best_exact_acc, 2),
        "best_cer": round(best_cer, 2),
        "total_epochs": total_epochs,
        "elapsed_min": round(elapsed_min, 1)
    }

# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

def main():
    print("=" * 80)
    print("END-TO-END ANPR RETRAINING PIPELINE: YOLO11n + CRNN OCR")
    print(f"Compute Device: {DEVICE} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")
    print("=" * 80)

    total_pipeline_start = time.time()

    # Step 1: Assemble dataset
    train_n, val_n = assemble_yolo_dataset()

    # Step 2: Train YOLO11n detector
    yolo_metrics, yolo_time = train_yolo()

    # Step 3: Train CRNN OCR
    crnn_metrics = train_crnn()

    total_elapsed = (time.time() - total_pipeline_start) / 60.0

    print("\n" + "=" * 80)
    print("END-TO-END RETRAINING PIPELINE COMPLETED SUCCESSFULLY!")
    print(f"Total Pipeline Runtime: {total_elapsed:.1f} minutes")
    print("=" * 80)

    summary = {
        "pipeline_completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_runtime_minutes": round(total_elapsed, 1),
        "yolo_detector": {
            "dataset_images": train_n + val_n,
            "train_images": train_n,
            "val_images": val_n,
            "runtime_minutes": round(yolo_time, 1),
            "metrics": yolo_metrics,
            "weights_pt": str(YOLO_DEST_PT),
            "weights_onnx": str(YOLO_DEST_ONNX)
        },
        "crnn_ocr": {
            "metrics": crnn_metrics,
            "weights_pt": str(CRNN_DEST_PT),
            "weights_onnx": str(CRNN_DEST_ONNX)
        }
    }

    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Summary saved to: {SUMMARY_JSON}")

if __name__ == "__main__":
    main()
