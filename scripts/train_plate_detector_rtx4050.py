#!/usr/bin/env python3
"""
scripts/train_plate_detector_rtx4050.py
=======================================
Stage 1: Fine-Tuning Multi-Color & Green-EV Plate Detector (YOLO11n).
Optimized for NVIDIA GeForce RTX 4050 Laptop GPU (6 GB VRAM).

Safe Training Configurations:
- imgsz: 640
- batch: 8
- workers: 2
- cache: False
- amp: True
- epochs: 60
- patience: 15
- device: 0

Exports:
- weights/yolo11n_plate_detector_finetuned.pt
- weights/yolo11n_plate_detector_finetuned.onnx
- weights/track_a_detector_metrics.json
"""

import os
import sys
from pathlib import Path
import json
import shutil
import time

# Enforce memory hygiene environment variables
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["YOLO_CONFIG_DIR"] = "/tmp/ultralytics"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

from ultralytics import YOLO
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = REPO_ROOT / "prepared" / "plate_det_in_v1" / "data.yaml"
OUTPUT_DIR = REPO_ROOT / "weights"
RUNS_DIR = REPO_ROOT / "runs" / "detect"
TARGET_PT = OUTPUT_DIR / "yolo11n_plate_detector_finetuned.pt"
TARGET_ONNX = OUTPUT_DIR / "yolo11n_plate_detector_finetuned.onnx"
METRICS_JSON = OUTPUT_DIR / "track_a_detector_metrics.json"

def main():
    print("=" * 70)
    print("STAGE 1: YOLO11n MULTI-COLOR & GREEN-EV PLATE DETECTOR FINE-TUNING")
    print("=" * 70)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. Please ensure NVIDIA drivers and CUDA are accessible.")

    gpu_name = torch.cuda.get_device_name(0)
    vram_mb = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
    print(f"[Device] GPU: {gpu_name} ({vram_mb:.1f} MB VRAM)")
    print(f"[Dataset] YAML: {DATA_YAML}")

    # Determine starting checkpoint
    candidate_pt = TARGET_PT
    if not candidate_pt.exists() or candidate_pt.stat().st_size < 100000:
        candidate_pt = REPO_ROOT / "weights" / "yolo11n.pt"
        if not candidate_pt.exists():
            candidate_pt = Path("yolo11n.pt")

    print(f"[Base Weights] Loading starting checkpoint from: {candidate_pt}")
    model = YOLO(str(candidate_pt))

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    print("\n[Training] Commencing YOLO11n training with RTX 4050 safe settings...")
    print("Parameters: imgsz=640, batch=8, workers=2, cache=False, amp=True, epochs=60, patience=15, device=0\n")

    train_results = model.train(
        data=str(DATA_YAML),
        epochs=60,
        patience=15,
        batch=8,
        imgsz=640,
        workers=2,
        cache=False,
        amp=True,
        device=0,
        project=str(RUNS_DIR),
        name="plate_detector_yolo11n_finetuned",
        exist_ok=True,
        verbose=True,
        save=True,
        val=True,
    )

    elapsed_sec = time.time() - start_time
    print(f"\n[Training Complete] Elapsed time: {elapsed_sec / 60:.2f} minutes")

    best_pt_path = RUNS_DIR / "plate_detector_yolo11n_finetuned" / "weights" / "best.pt"
    if not best_pt_path.exists():
        best_pt_path = RUNS_DIR / "plate_detector_yolo11n_finetuned" / "weights" / "last.pt"

    if not best_pt_path.exists():
        raise FileNotFoundError(f"Trained weights not found in {RUNS_DIR / 'plate_detector_yolo11n_finetuned' / 'weights'}")

    print(f"[Checkpoint] Best weights located at: {best_pt_path}")
    shutil.copyfile(best_pt_path, TARGET_PT)
    print(f"[Checkpoint] Copied best weights to: {TARGET_PT} ({TARGET_PT.stat().st_size / (1024*1024):.2f} MB)")

    # Validate best model
    print("\n[Validation] Evaluating best checkpoint on validation set...")
    best_model = YOLO(str(TARGET_PT))
    val_metrics = best_model.val(
        data=str(DATA_YAML),
        imgsz=640,
        batch=8,
        workers=2,
        device=0,
        split="val",
    )

    map50 = float(val_metrics.box.map50)
    map50_95 = float(val_metrics.box.map)
    precision = float(val_metrics.box.mp)
    recall = float(val_metrics.box.mr)

    print(f"\n[Validation Results]")
    print(f"  Precision (P):    {precision:.4f}")
    print(f"  Recall (R):       {recall:.4f}")
    print(f"  mAP@0.5:          {map50:.4f}")
    print(f"  mAP@0.5:0.95:     {map50_95:.4f}")

    # Export to ONNX
    print("\n[Export] Exporting best model to ONNX format (imgsz=640, opset=17, simplify=True)...")
    exported_onnx = best_model.export(
        format="onnx",
        imgsz=640,
        dynamic=False,
        opset=17,
        simplify=True,
    )

    exported_path = Path(exported_onnx)
    if exported_path.resolve() != TARGET_ONNX.resolve():
        shutil.copyfile(exported_path, TARGET_ONNX)

    print(f"[Export Complete] ONNX model saved at: {TARGET_ONNX} ({TARGET_ONNX.stat().st_size / (1024*1024):.2f} MB)")

    # Log metrics
    metrics_data = {
        "run_id": "plate_detector_yolo11n_finetuned",
        "architecture": "Ultralytics YOLO11n",
        "dataset": str(DATA_YAML),
        "dataset_split": {"train": 4585, "val": 812},
        "trained_epochs": int(getattr(train_results, "epoch", 60) if hasattr(train_results, "epoch") else 60),
        "batch_size": 8,
        "imgsz": 640,
        "mixed_precision_amp": True,
        "device": f"cuda:0 ({gpu_name})",
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "mAP50": round(map50, 4),
        "mAP50_95": round(map50_95, 4),
        "elapsed_minutes": round(elapsed_sec / 60, 2),
        "target_pt": str(TARGET_PT),
        "target_onnx": str(TARGET_ONNX),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(METRICS_JSON, "w", encoding="utf-8") as f:
        json.dump(metrics_data, f, indent=2)

    print(f"[Metrics Recorded] Saved to {METRICS_JSON}")
    print("=" * 70)

if __name__ == "__main__":
    main()
