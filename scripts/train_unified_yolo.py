#!/usr/bin/env python3
"""
Trains Ultralytics YOLO11n on the unified license plate dataset for 100 epochs on GPU.
Saves checkpoints and logs progress into runs/detect/plate_detector_yolo11n.
Upon completion, exports the best model to ONNX and copies it to weights/.
"""

import sys
import time
import json
import shutil
from pathlib import Path
from ultralytics import YOLO

ROOT_DIR = Path("/home/kirat/coding/honours")
DATA_YAML = ROOT_DIR / "training_1" / "unified_plate_dataset" / "data.yaml"
BASE_WEIGHTS = ROOT_DIR / "yolo11n.pt"
PROJECT_DIR = ROOT_DIR / "runs" / "detect"
RUN_NAME = "plate_detector_yolo11n"
DEST_WEIGHTS = ROOT_DIR / "weights" / "yolo11n_plate_detector_best.pt"
DEST_ONNX = ROOT_DIR / "weights" / "yolo11n_plate_detector_best.onnx"

def main():
    print("=" * 60)
    print("Starting YOLO11n License Plate Training")
    print(f"Data YAML:    {DATA_YAML}")
    print(f"Base Weights: {BASE_WEIGHTS}")
    print(f"Destination:  {PROJECT_DIR / RUN_NAME}")
    print("=" * 60)
    
    start_time = time.time()
    
    # Initialize YOLO model
    model = YOLO(str(BASE_WEIGHTS))
    
    # Train
    results = model.train(
        data=str(DATA_YAML),
        epochs=100,
        imgsz=640,
        batch=16,
        device=0,
        workers=4,
        patience=20,
        project=str(PROJECT_DIR),
        name=RUN_NAME,
        exist_ok=True,
        amp=True,
        plots=True,
        save=True,
        save_period=5,
        degrees=5.0,
        perspective=0.0005,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        fliplr=0.5,
        flipud=0.0,
        mosaic=1.0,
        mixup=0.1,
        verbose=True
    )
    
    elapsed = time.time() - start_time
    print(f"\nTraining completed in {elapsed / 60:.1f} minutes.")
    
    # Check best model weights
    best_pt = PROJECT_DIR / RUN_NAME / "weights" / "best.pt"
    if best_pt.is_file():
        print(f"Found best model at {best_pt}. Copying to {DEST_WEIGHTS}...")
        DEST_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best_pt, DEST_WEIGHTS)
        
        # Export to ONNX
        print("Exporting best model to ONNX format...")
        try:
            best_model = YOLO(str(best_pt))
            onnx_path = best_model.export(format="onnx", imgsz=640, dynamic=False)
            if Path(onnx_path).is_file():
                shutil.copyfile(onnx_path, DEST_ONNX)
                print(f"Saved ONNX model to {DEST_ONNX}")
        except Exception as e:
            print(f"ONNX export warning: {e}")
            
    print("\nTraining & Export Pipeline Finished Successfully!")

if __name__ == "__main__":
    main()
