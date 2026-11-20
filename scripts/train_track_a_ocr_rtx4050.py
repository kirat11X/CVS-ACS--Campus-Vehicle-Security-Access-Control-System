#!/usr/bin/env python3
"""
scripts/train_track_a_ocr_rtx4050.py
====================================
Stage 2: Fine-Tuning CCT Indian Plate OCR on NVIDIA GeForce RTX 4050 GPU (6 GB VRAM).
Uses PyTorch backend for Keras (KERAS_BACKEND=torch) and safe batch settings:
- batch_size: 32
- epochs: 25
- workers: 2
- mixed_precision_policy: mixed_float16
- early_stopping_metric: val_plate_acc (patience 10)

Exports:
- weights/track_a_ocr_cct.onnx
- weights/track_a_ocr_metrics.json
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

# Enforce PyTorch backend & CUDA hygiene
os.environ["KERAS_BACKEND"] = "torch"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_CONFIG = REPO_ROOT / "research_track" / "finetune" / "track_a" / "configs" / "cct_s_v2_global_model_config.yaml"
PLATE_CONFIG = REPO_ROOT / "research_track" / "finetune" / "track_a" / "configs" / "in_plate_config_v1.yaml"
TRAIN_CSV = REPO_ROOT / "prepared" / "ocr_in_v2" / "train.csv"
VAL_CSV = REPO_ROOT / "prepared" / "ocr_in_v2" / "val.csv"
TEST_CSV = REPO_ROOT / "prepared" / "ocr_in_v2" / "test.csv"
RUNS_DIR = REPO_ROOT / "runs" / "ocr" / "track_a_cct_finetuned"
WEIGHTS_DIR = REPO_ROOT / "weights"
TARGET_ONNX = WEIGHTS_DIR / "track_a_ocr_cct.onnx"
METRICS_JSON = WEIGHTS_DIR / "track_a_ocr_metrics.json"

FAST_PLATE_OCR_BIN = Path(sys.executable).parent / "fast-plate-ocr"

def main():
    print("=" * 70)
    print("STAGE 2: CCT INDIAN PLATE OCR FINE-TUNING ON RTX 4050")
    print("=" * 70)

    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable for PyTorch.")

    gpu_name = torch.cuda.get_device_name(0)
    vram_mb = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
    print(f"[Device] GPU: {gpu_name} ({vram_mb:.1f} MB VRAM)")
    print(f"[Backend] KERAS_BACKEND=torch")
    print(f"[Dataset] Train: {TRAIN_CSV} | Val: {VAL_CSV}")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    base_weights = Path("/home/kirat/ml-assets/campus/models/fast-plate-ocr/global-v2/cct_s_v2_global.keras")
    cmd = [
        str(FAST_PLATE_OCR_BIN), "train",
        "--model-config-file", str(MODEL_CONFIG),
        "--plate-config-file", str(PLATE_CONFIG),
        "--annotations", str(TRAIN_CSV),
        "--val-annotations", str(VAL_CSV),
        "--epochs", "25",
        "--batch-size", "32",
        "--workers", "2",
        "--lr", "0.001",
        "--early-stopping-metric", "val_plate_acc",
        "--early-stopping-patience", "10",
        "--mixed-precision-policy", "mixed_float16",
        "--output-dir", str(RUNS_DIR),
        "--validate-dataset", "off",
    ]
    if base_weights.is_file() and base_weights.stat().st_size > 1000:
        print(f"[Base Model] Using pretrained weights: {base_weights}")
        cmd.extend(["--weights-path", str(base_weights)])

    print(f"\n[Command] {' '.join(cmd)}\n")
    t0 = time.time()
    proc = subprocess.run(cmd, env={**os.environ, "KERAS_BACKEND": "torch"}, check=False)
    elapsed_sec = time.time() - t0
    print(f"\n[Training Finished] Return code: {proc.returncode} | Elapsed: {elapsed_sec / 60:.2f} minutes")

    if proc.returncode != 0:
        raise RuntimeError(f"fast-plate-ocr training exited with non-zero status: {proc.returncode}")

    # Find the best checkpoint
    checkpoints = sorted(RUNS_DIR.glob("**/best.keras"), key=os.path.getmtime)
    if not checkpoints:
        checkpoints = sorted(RUNS_DIR.glob("**/*.keras"), key=os.path.getmtime)

    if not checkpoints:
        raise FileNotFoundError(f"No trained .keras checkpoint found in {RUNS_DIR}")

    best_ckpt = checkpoints[-1]
    print(f"[Best Checkpoint] Located at: {best_ckpt} ({best_ckpt.stat().st_size / (1024*1024):.2f} MB)")

    # Export to ONNX
    print("\n[Export] Exporting best model to ONNX format...")
    export_cmd = [
        str(FAST_PLATE_OCR_BIN), "export",
        "-m", str(best_ckpt),
        "-f", "onnx",
        "--plate-config-file", str(PLATE_CONFIG),
        "--save-dir", str(WEIGHTS_DIR),
        "--simplify",
    ]
    export_proc = subprocess.run(export_cmd, env={**os.environ, "KERAS_BACKEND": "torch"}, check=False)
    if export_proc.returncode != 0:
        print("[Warning] fast-plate-ocr export CLI returned non-zero, checking if file was produced...")

    # Look for exported onnx
    exported_candidates = list(WEIGHTS_DIR.glob("*best*.onnx")) + list(WEIGHTS_DIR.glob("*cct*.onnx"))
    candidate_onnx = None
    for cand in sorted(exported_candidates, key=os.path.getmtime, reverse=True):
        if cand.stat().st_size > 1000000:
            candidate_onnx = cand
            break

    if candidate_onnx and candidate_onnx.resolve() != TARGET_ONNX.resolve():
        shutil.copyfile(candidate_onnx, TARGET_ONNX)
        print(f"[Export Success] Copied {candidate_onnx} to {TARGET_ONNX}")

    if TARGET_ONNX.exists():
        print(f"[Artifact Ready] ONNX model at: {TARGET_ONNX} ({TARGET_ONNX.stat().st_size / (1024*1024):.2f} MB)")

    # Write metrics summary
    metrics = {
        "run_id": "track_a_ocr_cct_finetuned",
        "architecture": "Compact Convolutional Transformer (CCT)",
        "dataset": "prepared/ocr_in_v2",
        "dataset_split": {"train": 34813, "val": 6507, "test": 2075},
        "trained_epochs": 25,
        "batch_size": 32,
        "mixed_precision": "mixed_float16",
        "device": f"cuda:0 ({gpu_name})",
        "training_time_minutes": round(elapsed_sec / 60, 2),
        "target_onnx": str(TARGET_ONNX),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(METRICS_JSON, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"[Metrics Recorded] Saved to {METRICS_JSON}")
    print("=" * 70)

if __name__ == "__main__":
    main()
