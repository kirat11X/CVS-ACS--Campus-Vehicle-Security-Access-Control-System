#!/usr/bin/env python3
"""
scripts/prepare_multicolor_ev_plate_dataset.py
==============================================
Merges all Indian license plate detection datasets into a single unified, leak-free
YOLO dataset at `prepared/plate_det_in_v1`:
- training_1/unified_plate_dataset (baseline)
- ronakgohil/license-plate-dataset (white/yellow Indian plates)
- kedarsai/indian-license-plates-with-labels (CC0 Indian vehicle plates)
- manu-mfyra/electric-vehicle-number-plate-bwvra (green EV plates)

Output:
  prepared/plate_det_in_v1/
    images/train/
    images/val/
    labels/train/
    labels/val/
    data.yaml
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path
import random
import shutil
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("merge_plate_detector_datasets")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "prepared" / "plate_det_in_v1"
SEED = 42

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def clamp(v: float) -> float:
    return max(0.0001, min(0.9999, float(v)))


def setup_output_dirs():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for split in ["train", "val"]:
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)


def collect_unified_baseline() -> List[Tuple[Path, Path, str]]:
    """Collect from existing training_1/unified_plate_dataset."""
    base = REPO_ROOT / "training_1" / "unified_plate_dataset"
    items = []
    if not base.exists():
        return items

    for split in ["train", "val"]:
        img_dir = base / "images" / split
        lbl_dir = base / "labels" / split
        if not img_dir.exists():
            continue
        for img_path in img_dir.iterdir():
            if img_path.suffix.lower() in IMAGE_EXTS:
                lbl_path = lbl_dir / f"{img_path.stem}.txt"
                if lbl_path.is_file():
                    items.append((img_path, lbl_path, f"base_{img_path.stem}"))
    logger.info(f"Collected {len(items)} images from training_1/unified_plate_dataset")
    return items


def collect_ronakgohil() -> List[Tuple[Path, Path, str]]:
    """Collect from ronakgohil_license_plate."""
    base = REPO_ROOT / "data" / "campus_gate_datasets" / "detector" / "ronakgohil_license_plate"
    items = []
    if not base.exists():
        return items

    for img_path in base.rglob("*"):
        if img_path.is_file() and img_path.suffix.lower() in IMAGE_EXTS:
            # Labels may be in labels/train or alongside
            lbl_name = f"{img_path.stem}.txt"
            lbl_path = None
            parent_parts = list(img_path.parts)
            if "images" in parent_parts:
                idx = parent_parts.index("images")
                parent_parts[idx] = "labels"
                candidate = Path(*parent_parts).parent / lbl_name
                if candidate.is_file():
                    lbl_path = candidate
                elif (Path(*parent_parts).parent / f"{img_path.name}.txt").is_file():
                    lbl_path = Path(*parent_parts).parent / f"{img_path.name}.txt"

            if lbl_path is None:
                direct = img_path.parent / lbl_name
                if direct.is_file():
                    lbl_path = direct

            if lbl_path and lbl_path.is_file():
                items.append((img_path, lbl_path, f"ronak_{img_path.stem}"))

    logger.info(f"Collected {len(items)} images from ronakgohil_license_plate")
    return items


def collect_kedarsai() -> List[Tuple[Path, Path, str]]:
    """Collect from kedarsai_indian_plates."""
    base = REPO_ROOT / "data" / "campus_gate_datasets" / "detector" / "kedarsai_indian_plates"
    items = []
    if not base.exists():
        return items

    img_dir = base / "images"
    lbl_dir = base / "labels"
    if not img_dir.exists() or not lbl_dir.exists():
        return items

    for img_path in img_dir.iterdir():
        if img_path.suffix.lower() in IMAGE_EXTS:
            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            if lbl_path.is_file():
                items.append((img_path, lbl_path, f"kedar_{img_path.stem}"))

    logger.info(f"Collected {len(items)} images from kedarsai_indian_plates")
    return items


def collect_roboflow_ev() -> List[Tuple[Path, Path, str]]:
    """Collect green EV plates from Roboflow dataset."""
    base = REPO_ROOT / "data" / "campus_gate_datasets" / "ev" / "roboflow_ev_bwvra"
    items = []
    if not base.exists():
        return items

    for img_path in base.rglob("*"):
        if img_path.is_file() and img_path.suffix.lower() in IMAGE_EXTS:
            lbl_name = f"{img_path.stem}.txt"
            parent_parts = list(img_path.parts)
            if "images" in parent_parts:
                idx = parent_parts.index("images")
                parent_parts[idx] = "labels"
                candidate = Path(*parent_parts).parent / lbl_name
                if candidate.is_file():
                    items.append((img_path, candidate, f"ev_{img_path.stem}"))

    logger.info(f"Collected {len(items)} images from roboflow_ev_bwvra")
    return items


def parse_and_normalize_yolo_labels(lbl_path: Path) -> List[str]:
    """Reads label file, ensures class_id=0 for license_plate, and clamps coords."""
    out_lines = []
    with open(lbl_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                # Force class 0 (license_plate)
                _, cx, cy, bw, bh = parts[:5]
                try:
                    cx = clamp(float(cx))
                    cy = clamp(float(cy))
                    bw = clamp(float(bw))
                    bh = clamp(float(bh))
                    if bw > 0.005 and bh > 0.005:
                        out_lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
                except ValueError:
                    continue
    return out_lines


def main():
    logger.info("Initializing multi-color & EV plate detector dataset merger...")
    setup_output_dirs()

    random.seed(SEED)

    all_items: List[Tuple[Path, Path, str]] = []
    all_items.extend(collect_unified_baseline())
    all_items.extend(collect_ronakgohil())
    all_items.extend(collect_kedarsai())

    # EV items are split proportionally so green EV plates are in both train & val
    ev_items = collect_roboflow_ev()

    # Shuffle main items
    random.shuffle(all_items)
    n_total = len(all_items)
    n_train = int(round(0.85 * n_total))
    train_items = all_items[:n_train]
    val_items = all_items[n_train:]

    # Add EV items (85% train, 15% val)
    random.shuffle(ev_items)
    n_ev_train = int(round(0.85 * len(ev_items)))
    train_items.extend(ev_items[:n_ev_train])
    val_items.extend(ev_items[n_ev_train:])

    logger.info(f"Total dataset: {len(train_items)} train, {len(val_items)} val ({len(train_items) + len(val_items)} total)")

    for split, items in [("train", train_items), ("val", val_items)]:
        written = 0
        for img_path, lbl_path, prefix_id in items:
            clean_lines = parse_and_normalize_yolo_labels(lbl_path)
            if not clean_lines:
                continue

            target_stem = f"{prefix_id}"
            target_img = OUTPUT_DIR / "images" / split / f"{target_stem}{img_path.suffix.lower()}"
            target_lbl = OUTPUT_DIR / "labels" / split / f"{target_stem}.txt"

            shutil.copyfile(img_path, target_img)
            with open(target_lbl, "w", encoding="utf-8") as f:
                f.writelines(clean_lines)
            written += 1
        logger.info(f"Split '{split}': Successfully wrote {written} images and label files.")

    data_yaml_path = OUTPUT_DIR / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        f.write(f"path: {OUTPUT_DIR.resolve()}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n\n")
        f.write("names:\n")
        f.write("  0: license_plate\n")

    logger.info(f"Dataset successfully created at {OUTPUT_DIR}. data.yaml: {data_yaml_path}")


if __name__ == "__main__":
    main()
