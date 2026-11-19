#!/usr/bin/env python3
"""
scripts/export_uvh26_to_onnx.py
===============================
Exports IISc AIM UVH-26 YOLOv11-S Indian Vehicle Gatekeeper weights to ONNX.

Source: https://huggingface.co/iisc-aim/UVH-26 (Apache-2.0)
Weights: weights/YOLOv11-S/UVH-26-MV-YOLOv11-S.pt -> weights/uvh26_vehicle_yolo11s.onnx
Fallback: yolo11n.onnx
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import shutil
import sys
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_uvh26")

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = REPO_ROOT / "weights"
DEFAULT_PT = WEIGHTS_DIR / "UVH-26-MV-YOLOv11-S.pt"
DEFAULT_ONNX = WEIGHTS_DIR / "uvh26_vehicle_yolo11s.onnx"
FALLBACK_ONNX = WEIGHTS_DIR / "yolo11n.onnx"

UVH26_CLASS_NAMES = {
    0: "Hatchback",
    1: "Sedan",
    2: "SUV",
    3: "MUV",
    4: "Bus",
    5: "Truck",
    6: "Three-wheeler",
    7: "Two-wheeler",
    8: "LCV",
    9: "Mini-bus",
    10: "Tempo-traveller",
    11: "Bicycle",
    12: "Van",
    13: "Others",
}

# Unified 5-class Indian vehicle mapping:
# two_wheeler, auto_rickshaw, car, bus, truck (ignoring pedestrians)
UVH26_TO_UNIFIED = {
    0: "car",            # Hatchback
    1: "car",            # Sedan
    2: "car",            # SUV
    3: "car",            # MUV
    4: "bus",            # Bus
    5: "truck",          # Truck
    6: "auto_rickshaw",  # Three-wheeler
    7: "two_wheeler",    # Two-wheeler
    8: "truck",          # LCV (Light Commercial Vehicle)
    9: "bus",            # Mini-bus
    10: "bus",           # Tempo-traveller
    11: "two_wheeler",   # Bicycle
    12: "car",           # Van
    13: "car",           # Others (default to vehicle/car)
}

# COCO fallback mapping
COCO_VEHICLE_MAP = {
    1: "two_wheeler",    # bicycle
    2: "car",            # car
    3: "two_wheeler",    # motorcycle
    5: "bus",            # bus
    7: "truck",          # truck
}


def download_uvh26_pt_if_missing(pt_path: Path) -> bool:
    """Download UVH-26-MV-YOLOv11-S.pt from Hugging Face if not present."""
    if pt_path.exists() and pt_path.stat().st_size > 10 * 1024 * 1024:
        logger.info(f"Checkpoint already exists at {pt_path} ({pt_path.stat().st_size / (1024*1024):.2f} MB)")
        return True

    logger.info("Downloading UVH-26-MV-YOLOv11-S.pt from Hugging Face iisc-aim/UVH-26...")
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id="iisc-aim/UVH-26",
            filename="weights/YOLOv11-S/UVH-26-MV-YOLOv11-S.pt",
        )
        pt_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(downloaded, pt_path)
        logger.info(f"Downloaded successfully to {pt_path} ({pt_path.stat().st_size / (1024*1024):.2f} MB)")
        return True
    except Exception as e:
        logger.error(f"Failed to download UVH-26 weights from Hugging Face: {e}")
        return False


def export_pt_to_onnx(pt_path: Path, onnx_target: Path) -> bool:
    """Export PyTorch YOLO model to ONNX format."""
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics package is required for exporting .pt models to ONNX.")
        return False

    logger.info(f"Loading YOLO model from {pt_path}...")
    model = YOLO(str(pt_path))
    logger.info(f"Model classes: {model.names}")

    logger.info(f"Exporting to ONNX format (imgsz=640, dynamic=False)...")
    try:
        exported_path = model.export(
            format="onnx",
            imgsz=640,
            dynamic=False,
            opset=17,
            simplify=False,
        )
        exported_path = Path(exported_path)
        if exported_path.resolve() != onnx_target.resolve():
            shutil.move(exported_path, onnx_target)
        logger.info(f"ONNX model saved to {onnx_target} ({onnx_target.stat().st_size / (1024*1024):.2f} MB)")
        return True
    except Exception as e:
        logger.error(f"Error during ONNX export: {e}")
        return False


def export_fallback_yolo11n(onnx_target: Path) -> bool:
    """Export standard YOLO11n as a fallback vehicle detector."""
    try:
        from ultralytics import YOLO
        logger.info("Exporting fallback yolo11n.pt to ONNX...")
        model = YOLO("yolo11n.pt")
        exported = model.export(format="onnx", imgsz=640, dynamic=False, opset=17)
        if Path(exported).resolve() != onnx_target.resolve():
            shutil.move(exported, onnx_target)
        logger.info(f"Fallback ONNX saved to {onnx_target}")
        return True
    except Exception as e:
        logger.error(f"Failed to export fallback yolo11n: {e}")
        return False


def verify_onnx_model(onnx_path: Path) -> bool:
    """Verify that ONNX model loads and runs inference on a dummy tensor."""
    if not onnx_path.exists():
        logger.error(f"Model file does not exist: {onnx_path}")
        return False

    try:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(str(onnx_path), opts, providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        input_shape = session.get_inputs()[0].shape
        logger.info(f"ONNX Model input: '{input_name}', shape: {input_shape}")

        dummy = np.zeros((1, 3, 640, 640), dtype=np.float32)
        outputs = session.run(None, {input_name: dummy})
        out_shape = outputs[0].shape
        logger.info(f"ONNX Model output shape: {out_shape} (verified valid)")
        return True
    except Exception as e:
        logger.error(f"ONNX verification failed for {onnx_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Export UVH-26 YOLOv11-S to ONNX")
    parser.add_argument("--pt-path", type=Path, default=DEFAULT_PT, help=f"Path to .pt weights (default: {DEFAULT_PT})")
    parser.add_argument("--onnx-path", type=Path, default=DEFAULT_ONNX, help=f"Target ONNX path (default: {DEFAULT_ONNX})")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing ONNX model")
    args = parser.parse_args()

    if args.verify_only:
        ok = verify_onnx_model(args.onnx_path)
        sys.exit(0 if ok else 1)

    pt_path = args.pt_path
    onnx_target = args.onnx_path

    if onnx_target.exists() and onnx_target.stat().st_size > 10 * 1024 * 1024:
        logger.info(f"Target ONNX model already exists: {onnx_target}")
        if verify_onnx_model(onnx_target):
            logger.info("Verification succeeded.")
            return

    # Attempt UVH-26 download & export
    download_ok = download_uvh26_pt_if_missing(pt_path)
    if download_ok:
        export_ok = export_pt_to_onnx(pt_path, onnx_target)
        if export_ok and verify_onnx_model(onnx_target):
            logger.info("UVH-26 ONNX export and verification complete!")
            return

    # Fallback to yolo11n.onnx if UVH-26 fails or is offline
    logger.warning("Falling back to yolo11n.onnx vehicle detector...")
    fallback_ok = export_fallback_yolo11n(FALLBACK_ONNX)
    if fallback_ok and verify_onnx_model(FALLBACK_ONNX):
        logger.info(f"Fallback detector successfully exported to {FALLBACK_ONNX}")
        return

    logger.error("Failed to export either UVH-26 or fallback YOLO model.")
    sys.exit(1)


if __name__ == "__main__":
    main()
