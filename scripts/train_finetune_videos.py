#!/usr/bin/env python3
"""
Fine-tunes the newly trained YOLO11n plate detector (weights/yolo11n_plate_detector_best.pt)
on the verified video frames and sealed hard-negative background frames from TRAINING_VIDEOS
to minimize false detections.
"""

import sys
import time
import shutil
from pathlib import Path
from ultralytics import YOLO

ROOT_DIR = Path("/home/kirat/coding/honours")
DATA_YAML = Path("/home/kirat/ml-assets/campus/hitl/datasets/ft_videos1-8/data.yaml")
BASE_WEIGHTS = ROOT_DIR / "weights" / "yolo11n_plate_detector_best.pt"
PROJECT_DIR = ROOT_DIR / "runs" / "detect"
RUN_NAME = "plate_detector_yolo11n_finetuned"
DEST_WEIGHTS = ROOT_DIR / "weights" / "yolo11n_plate_detector_finetuned.pt"
DEST_ONNX = ROOT_DIR / "weights" / "yolo11n_plate_detector_finetuned.onnx"

def main():
    print("=" * 70)
    print("Starting YOLO11n Video Fine-Tuning & False Detection Suppression")
    print(f"Base Weights: {BASE_WEIGHTS}")
    print(f"Dataset YAML: {DATA_YAML}")
    print(f"Run Output:   {PROJECT_DIR / RUN_NAME}")
    print("=" * 70)

    start_time = time.time()

    model = YOLO(str(BASE_WEIGHTS))

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
        project=str(PROJECT_DIR),
        name=RUN_NAME,
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

    elapsed = time.time() - start_time
    print(f"\nFine-tuning completed in {elapsed / 60:.1f} minutes.")

    best_pt = PROJECT_DIR / RUN_NAME / "weights" / "best.pt"
    if best_pt.is_file():
        print(f"Saving best fine-tuned model to {DEST_WEIGHTS}...")
        DEST_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best_pt, DEST_WEIGHTS)

        print("Exporting fine-tuned model to ONNX format...")
        try:
            best_model = YOLO(str(best_pt))
            onnx_path = best_model.export(format="onnx", imgsz=640, dynamic=False)
            if Path(onnx_path).is_file():
                shutil.copyfile(onnx_path, DEST_ONNX)
                print(f"Saved ONNX model to {DEST_ONNX}")
        except Exception as e:
            print(f"ONNX export warning: {e}")

    print("\nFine-tuning & False Detection Minimization Finished Successfully!")

if __name__ == "__main__":
    main()
