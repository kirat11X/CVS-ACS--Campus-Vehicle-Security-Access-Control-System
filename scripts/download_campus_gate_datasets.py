#!/usr/bin/env python3
"""
scripts/download_campus_gate_datasets.py
========================================
Automated downloader, extractor, and verification manager for all 5 Campus Gate
ANPR and Vehicle Classification datasets and checkpoints.

Datasets & Checkpoints:
  - DS-01 (ocr): umar1103/final-licence (Kaggle)
  - DS-02 (checkpoint): Awiros/anpr-ocr (Hugging Face)
  - DS-03 (ev): manu-mfyra/electric-vehicle-number-plate-bwvra (Roboflow)
  - DS-04 (detector): ronakgohil/license-plate-dataset (Kaggle)
  - DS-05 (detector): kedarsai/indian-license-plates-with-labels (Kaggle)
  - DS-06 (character): mohamedgobara/plate-license-recognition-dataset (Kaggle)
  - DS-07 (mendeley): sxrnr7hwtk - Indian Number Plate Dataset (NPDS)
  - DS-08 (mendeley): znghtgfnnf - Indian Number Plate Character Dataset (ANPRINR)
  - DS-09 (vehicle_class): tanzimmostafa14/dhaka-occluded-objects-dataset (Kaggle)

Usage:
  python3 scripts/download_campus_gate_datasets.py --group ocr
  python3 scripts/download_campus_gate_datasets.py --group checkpoint
  python3 scripts/download_campus_gate_datasets.py --group detector
  python3 scripts/download_campus_gate_datasets.py --group character
  python3 scripts/download_campus_gate_datasets.py --group ev
  python3 scripts/download_campus_gate_datasets.py --group vehicle_class
  python3 scripts/download_campus_gate_datasets.py --group all
  python3 scripts/download_campus_gate_datasets.py --verify
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("campus_gate_datasets")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_DIR = REPO_ROOT / "data" / "campus_gate_datasets"

# File extensions for verification
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
LABEL_EXTENSIONS = {".txt", ".xml", ".json", ".csv"}
CHECKPOINT_EXTENSIONS = {".safetensors", ".pt", ".pth", ".onnx", ".bin"}


def load_env_credentials() -> dict[str, str]:
    """Load credentials from .env file into os.environ if not already present."""
    creds = {}
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and v:
                            creds[k] = v
                            if k not in os.environ:
                                os.environ[k] = v
        except Exception as e:
            logger.warning(f"Error reading .env file: {e}")

    # Fallback/specific check for Kaggle API Token commented format
    if "KAGGLE_API_TOKEN" not in os.environ:
        if env_file.is_file():
            try:
                content = env_file.read_text(encoding="utf-8")
                import re
                m = re.search(r"KAGGLE_API_TOKEN=([a-zA-Z0-9_\-]+)", content)
                if m:
                    token = m.group(1).strip()
                    os.environ["KAGGLE_API_TOKEN"] = token
                    creds["KAGGLE_API_TOKEN"] = token
            except Exception:
                pass

    return creds


def get_kaggle_api():
    """Initialize and authenticate KaggleApi."""
    load_env_credentials()
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        logger.info(f"Kaggle authenticated successfully as user: {api.config_values.get(api.CONFIG_NAME_USER, 'authenticated')}")
        return api
    except Exception as e:
        logger.error(f"Failed to authenticate Kaggle API: {e}")
        logger.error("Please ensure KAGGLE_API_TOKEN or ~/.kaggle/kaggle.json is configured.")
        raise


def extract_nested_zips(directory: Path):
    """Extract any leftover zip files inside directory."""
    for zip_path in list(directory.glob("*.zip")) + list(directory.glob("**/*.zip")):
        if zip_path.is_file():
            try:
                logger.info(f"Extracting nested archive {zip_path.name}...")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(zip_path.parent)
                zip_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to extract {zip_path}: {e}")


def download_kaggle_dataset(dataset_slug: str, target_dir: Path, force: bool = False) -> bool:
    """Download and extract a Kaggle dataset."""
    target_dir.mkdir(parents=True, exist_ok=True)
    existing_files = [f for f in target_dir.rglob("*") if f.is_file()]
    if existing_files and not force:
        logger.info(f"Dataset '{dataset_slug}' already exists in {target_dir} ({len(existing_files)} files). Skipping download.")
        return True

    api = get_kaggle_api()
    logger.info(f"Downloading Kaggle dataset '{dataset_slug}' to {target_dir}...")
    try:
        api.dataset_download_files(dataset_slug, path=str(target_dir), force=force, quiet=False, unzip=True)
        extract_nested_zips(target_dir)
        logger.info(f"Successfully downloaded and extracted '{dataset_slug}'.")
        return True
    except Exception as e:
        logger.error(f"Error downloading Kaggle dataset '{dataset_slug}': {e}")
        return False


def download_hf_checkpoint(repo_id: str, target_dir: Path, force: bool = False) -> bool:
    """Download Hugging Face checkpoint repository."""
    target_dir.mkdir(parents=True, exist_ok=True)
    existing_files = [f for f in target_dir.rglob("*") if f.is_file()]
    if existing_files and not force:
        logger.info(f"Checkpoint '{repo_id}' already exists in {target_dir} ({len(existing_files)} files). Skipping.")
        return True

    try:
        from huggingface_hub import snapshot_download
        logger.info(f"Downloading Hugging Face repo '{repo_id}' to {target_dir}...")
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        logger.info(f"Successfully downloaded '{repo_id}'.")
        return True
    except Exception as e:
        logger.error(f"Error downloading Hugging Face repo '{repo_id}': {e}")
        return False


def download_roboflow_ev(target_dir: Path, force: bool = False) -> bool:
    """Download electric-vehicle-number-plate-bwvra dataset from Roboflow."""
    target_dir.mkdir(parents=True, exist_ok=True)
    existing_files = [f for f in target_dir.rglob("*") if f.is_file()]
    if existing_files and not force:
        logger.info(f"Roboflow EV dataset already exists in {target_dir} ({len(existing_files)} files). Skipping.")
        return True

    load_env_credentials()
    api_key = os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        logger.error("ROBOFLOW_API_KEY environment variable is missing. Cannot download Roboflow dataset.")
        return False

    try:
        from roboflow import Roboflow
        logger.info("Connecting to Roboflow API...")
        rf = Roboflow(api_key=api_key)
        workspace = rf.workspace("manu-mfyra")
        project = workspace.project("electric-vehicle-number-plate-bwvra")
        # Version 4 contains the 162 annotated EV plate images
        logger.info(f"Downloading Roboflow dataset 'electric-vehicle-number-plate-bwvra' v4 to {target_dir}...")
        version = project.version(4)
        version.download("yolov8", location=str(target_dir), overwrite=True)
        logger.info("Successfully downloaded Roboflow EV dataset.")
        return True
    except Exception as e:
        logger.error(f"Error downloading Roboflow EV dataset: {e}")
        return False


# ---------------------------------------------------------------------------
# Group Dispatchers
# ---------------------------------------------------------------------------

def run_group_ocr(base_dir: Path, force: bool = False) -> bool:
    """DS-01: umar1103/final-licence"""
    dest = base_dir / "ocr" / "umar1103_final_licence"
    return download_kaggle_dataset("umar1103/final-licence", dest, force=force)


def run_group_checkpoint(base_dir: Path, force: bool = False) -> bool:
    """DS-02: Awiros/anpr-ocr"""
    dest = base_dir / "checkpoints" / "awiros_anpr_ocr"
    return download_hf_checkpoint("Awiros/anpr-ocr", dest, force=force)


def run_group_detector(base_dir: Path, force: bool = False) -> bool:
    """DS-04 & DS-05: Indian plate detectors"""
    ok1 = download_kaggle_dataset("ronakgohil/license-plate-dataset", base_dir / "detector" / "ronakgohil_license_plate", force=force)
    ok2 = download_kaggle_dataset("kedarsai/indian-license-plates-with-labels", base_dir / "detector" / "kedarsai_indian_plates", force=force)
    return ok1 and ok2


def run_group_character(base_dir: Path, force: bool = False) -> bool:
    """DS-06: mohamedgobara/plate-license-recognition-dataset"""
    dest = base_dir / "character" / "mohamedgobara_plate_license"
    return download_kaggle_dataset("mohamedgobara/plate-license-recognition-dataset", dest, force=force)


def run_group_ev(base_dir: Path, force: bool = False) -> bool:
    """DS-03: manu-mfyra/electric-vehicle-number-plate-bwvra"""
    dest = base_dir / "ev" / "roboflow_ev_bwvra"
    return download_roboflow_ev(dest, force=force)


def run_group_vehicle_class(base_dir: Path, force: bool = False) -> bool:
    """DS-09: tanzimmostafa14/dhaka-occluded-objects-dataset"""
    dest = base_dir / "vehicle_class" / "dhaka_occluded_objects"
    return download_kaggle_dataset("tanzimmostafa14/dhaka-occluded-objects-dataset", dest, force=force)


# ---------------------------------------------------------------------------
# Verification & Audit
# ---------------------------------------------------------------------------

def verify_datasets(base_dir: Path):
    """Audit all dataset folders and print a detailed verification report."""
    load_env_credentials()

    DATASETS = [
        ("DS-01", "umar1103/final-licence", "ocr/umar1103_final_licence", "Solution 2 & 4: Sequence OCR"),
        ("DS-02", "Awiros/anpr-ocr", "checkpoints/awiros_anpr_ocr", "Solution 4: PP-OCRv5 Indian Seed Weights"),
        ("DS-03", "Roboflow EV Plates", "ev/roboflow_ev_bwvra", "Solution 1, 2 & 3: Green EV Detection & Polarity"),
        ("DS-04", "ronakgohil/license-plate-dataset", "detector/ronakgohil_license_plate", "Solution 2: YOLO Plate Detector"),
        ("DS-05", "kedarsai/indian-license-plates", "detector/kedarsai_indian_plates", "Solution 2: Clean CC0 Plate Labels"),
        ("DS-06", "mohamedgobara/plate-license", "character/mohamedgobara_plate_license", "Solution 2: 36-Class Character Detector"),
        ("DS-07", "Mendeley NPDS (sxrnr7hwtk)", "mendeley/sxrnr7hwtk", "Solution 2: Indian Plate Augmentation (Manual ZIP)"),
        ("DS-08", "Mendeley ANPRINR (znghtgfnnf)", "mendeley/znghtgfnnf", "Solution 2: Indian HSRP Font Char Set (Manual ZIP)"),
        ("DS-09", "Dhaka Occluded Objects", "vehicle_class/dhaka_occluded_objects", "Vehicle Class: Auto-Rickshaw & 2W Detection"),
    ]

    print("\n" + "=" * 105)
    print("CAMPUS GATE ANPR & VEHICLE CLASS DATASETS VERIFICATION REPORT")
    print("=" * 105)
    print(f"Target Base Directory: {base_dir}")
    print(f"Kaggle Auth Token: {'[DETECTED]' if os.environ.get('KAGGLE_API_TOKEN') else '[MISSING]'}")
    print(f"Roboflow API Key:  {'[DETECTED]' if os.environ.get('ROBOFLOW_API_KEY') else '[MISSING]'}")
    print(f"HuggingFace Token: {'[DETECTED]' if os.environ.get('HF_TOKEN') else '[OPTIONAL/PUBLIC]'}")

    # Check .gitignore
    gitignore_file = REPO_ROOT / ".gitignore"
    gitignore_has_dir = False
    if gitignore_file.is_file():
        content = gitignore_file.read_text(encoding="utf-8")
        if "data/campus_gate_datasets" in content or "data/" in content:
            gitignore_has_dir = True
    print(f"Git Protection:    {'[SECURE - Ignored in .gitignore]' if gitignore_has_dir else '[WARNING - Not ignored in .gitignore]'}")
    print("-" * 105)
    print(f"{'ID':<7} | {'Dataset Name':<32} | {'Status':<14} | {'Images':<8} | {'Labels/Files':<14} | {'Total Size':<10}")
    print("-" * 105)

    summary_counts = {"READY": 0, "PARTIAL": 0, "MISSING": 0, "MANUAL": 0}

    for ds_id, name, rel_path, role in DATASETS:
        full_path = base_dir / rel_path
        if not full_path.exists():
            if "Mendeley" in name:
                status = "[MANUAL_REQ]"
                summary_counts["MANUAL"] += 1
            else:
                status = "[MISSING]"
                summary_counts["MISSING"] += 1
            print(f"{ds_id:<7} | {name:<32} | {status:<14} | {'0':<8} | {'0':<14} | {'0 B':<10}")
            continue

        num_images = 0
        num_labels = 0
        num_checkpoints = 0
        total_bytes = 0
        total_files = 0

        for f in full_path.rglob("*"):
            if f.is_file():
                total_files += 1
                try:
                    total_bytes += f.stat().st_size
                except OSError:
                    pass
                suffix = f.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    num_images += 1
                elif suffix in LABEL_EXTENSIONS:
                    num_labels += 1
                elif suffix in CHECKPOINT_EXTENSIONS:
                    num_checkpoints += 1

        size_mb = total_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"

        if num_images > 0 or num_checkpoints > 0 or total_files > 0:
            status = "[READY]"
            summary_counts["READY"] += 1
        else:
            status = "[EMPTY]"
            summary_counts["MISSING"] += 1

        labels_or_files = f"{num_labels} lbls" if num_labels > 0 else (f"{num_checkpoints} ckpts" if num_checkpoints > 0 else f"{total_files} files")
        print(f"{ds_id:<7} | {name:<32} | {status:<14} | {num_images:<8} | {labels_or_files:<14} | {size_str:<10}")

    print("=" * 105)
    print(f"Summary: {summary_counts['READY']} Ready | {summary_counts['MISSING']} Missing | {summary_counts['MANUAL']} Manual Required")
    if summary_counts["MANUAL"] > 0:
        print("\nManual Mendeley Datasets Download Instructions:")
        print("  - DS-07 (NPDS):    Download zip from https://data.mendeley.com/datasets/sxrnr7hwtk/1 and place in data/campus_gate_datasets/mendeley/sxrnr7hwtk/")
        print("  - DS-08 (ANPRINR): Download zip from https://data.mendeley.com/datasets/znghtgfnnf/1 and place in data/campus_gate_datasets/mendeley/znghtgfnnf/")
    print("=" * 105 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Campus Gate ANPR & Vehicle Class Dataset Downloader")
    parser.add_argument(
        "--group",
        choices=["all", "ocr", "checkpoint", "detector", "character", "ev", "vehicle_class"],
        help="Dataset group to download and unpack",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=DEFAULT_TARGET_DIR,
        help=f"Root target directory for datasets (default: {DEFAULT_TARGET_DIR})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Scan and verify existing dataset downloads and report inventory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if dataset directory exists",
    )

    args = parser.parse_args()
    base_dir = args.target_dir.resolve()

    if args.verify or not args.group:
        verify_datasets(base_dir)
        if not args.group:
            return

    group = args.group
    logger.info(f"Executing dataset download group: '{group}' to '{base_dir}'...")

    success = True
    if group in ("ocr", "all"):
        success = run_group_ocr(base_dir, force=args.force) and success
    if group in ("checkpoint", "all"):
        success = run_group_checkpoint(base_dir, force=args.force) and success
    if group in ("detector", "all"):
        success = run_group_detector(base_dir, force=args.force) and success
    if group in ("character", "all"):
        success = run_group_character(base_dir, force=args.force) and success
    if group in ("ev", "all"):
        success = run_group_ev(base_dir, force=args.force) and success
    if group in ("vehicle_class", "all"):
        success = run_group_vehicle_class(base_dir, force=args.force) and success

    if success:
        logger.info(f"Group '{group}' completed successfully.")
    else:
        logger.error(f"Group '{group}' completed with errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
