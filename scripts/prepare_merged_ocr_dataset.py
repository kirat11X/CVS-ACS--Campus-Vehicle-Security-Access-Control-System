#!/usr/bin/env python3
"""
scripts/prepare_merged_ocr_dataset.py
======================================
Merges prepared/ocr_in_v1 + umar1103/final-licence into prepared/ocr_in_v2
with strict zero-leakage plate-text grouping.

- Retains held-out test split (2,075 crops) untouched.
- Filters umar1103 plate crops to valid Indian plate format (length 6-11, A-Z0-9).
- Excludes any umar1103 plates matching test set.
- Assigns new umar1103 plates: 85% train, 15% val grouped strictly by plate_text.
- Exports train.csv, val.csv, test.csv, manifest.json.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
import random
import re
import shutil
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_merged_ocr_dataset")

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_OCR_DIR = REPO_ROOT / "data" / "datasets" / "prepared" / "ocr_in_v1"
UMAR_DIR = REPO_ROOT / "data" / "campus_gate_datasets" / "ocr" / "umar1103_final_licence" / "ALL"
OUTPUT_DIR = REPO_ROOT / "prepared" / "ocr_in_v2"
SEED = 42

def clean_plate(text: str) -> str:
    norm = re.sub(r"[^A-Za-z0-9]", "", str(text)).upper().strip()
    return norm

def is_valid_plate_text(text: str) -> bool:
    if len(text) < 6 or len(text) > 11:
        return False
    # Must have at least 2 letters and 2 digits
    n_letters = sum(1 for c in text if c.isalpha())
    n_digits = sum(1 for c in text if c.isdigit())
    return n_letters >= 2 and n_digits >= 2

def main():
    logger.info("Initializing OCR Dataset Merger...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)

    # 1. Load baseline splits
    splits_data: Dict[str, List[Tuple[str, str]]] = {"train": [], "val": [], "test": []}
    splits_texts: Dict[str, Set[str]] = {"train": set(), "val": set(), "test": set()}

    for split in ["train", "val", "test"]:
        csv_path = BASE_OCR_DIR / f"{split}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing base CSV: {csv_path}")

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rel_img = row["image_path"]
                full_img = (BASE_OCR_DIR / rel_img).resolve()
                p_text = clean_plate(row["plate_text"])
                if full_img.is_file() and p_text:
                    splits_data[split].append((str(full_img), p_text))
                    splits_texts[split].add(p_text)

        logger.info(f"Loaded baseline {split}: {len(splits_data[split])} crops, {len(splits_texts[split])} unique texts")

    test_texts = splits_texts["test"]

    # 2. Collect umar1103 crops
    umar_new_by_text: Dict[str, List[str]] = {}
    umar_added_to_train = 0
    umar_added_to_val = 0
    umar_excluded_test = 0
    umar_invalid = 0

    if UMAR_DIR.exists():
        for p in UMAR_DIR.iterdir():
            if p.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                plate_cand = clean_plate(p.stem)
                if not is_valid_plate_text(plate_cand):
                    umar_invalid += 1
                    continue

                if plate_cand in test_texts:
                    umar_excluded_test += 1
                    continue

                if plate_cand in splits_texts["train"]:
                    splits_data["train"].append((str(p.resolve()), plate_cand))
                    umar_added_to_train += 1
                elif plate_cand in splits_texts["val"]:
                    splits_data["val"].append((str(p.resolve()), plate_cand))
                    umar_added_to_val += 1
                else:
                    if plate_cand not in umar_new_by_text:
                        umar_new_by_text[plate_cand] = []
                    umar_new_by_text[plate_cand].append(str(p.resolve()))

    logger.info(f"umar1103 stats: {umar_added_to_train} joined train, {umar_added_to_val} joined val, {umar_excluded_test} excluded (test overlap), {umar_invalid} invalid")
    logger.info(f"umar1103 new unique texts to allocate: {len(umar_new_by_text)}")

    # 3. Grouped split of new umar1103 texts (85% train, 15% val)
    unique_new_texts = list(umar_new_by_text.keys())
    random.shuffle(unique_new_texts)
    n_train_split = int(round(0.85 * len(unique_new_texts)))
    new_train_texts = set(unique_new_texts[:n_train_split])
    new_val_texts = set(unique_new_texts[n_train_split:])

    for t in new_train_texts:
        for img_path in umar_new_by_text[t]:
            splits_data["train"].append((img_path, t))
            splits_texts["train"].add(t)

    for t in new_val_texts:
        for img_path in umar_new_by_text[t]:
            splits_data["val"].append((img_path, t))
            splits_texts["val"].add(t)

    # 4. Leakage Verification
    leak_train_val = splits_texts["train"] & splits_texts["val"]
    leak_train_test = splits_texts["train"] & splits_texts["test"]
    leak_val_test = splits_texts["val"] & splits_texts["test"]

    if leak_train_val or leak_train_test or leak_val_test:
        raise ValueError(f"LEAK DETECTED! train-val: {len(leak_train_val)}, train-test: {len(leak_train_test)}, val-test: {len(leak_val_test)}")

    logger.info("Zero-leakage verification PASSED:")
    logger.info(f"  train-val overlap: {len(leak_train_val)}")
    logger.info(f"  train-test overlap: {len(leak_train_test)}")
    logger.info(f"  val-test overlap: {len(leak_val_test)}")

    # 5. Write CSVs with paths relative to OUTPUT_DIR
    import os
    for split in ["train", "val", "test"]:
        out_csv = OUTPUT_DIR / f"{split}.csv"
        # Shuffle rows within split
        random.shuffle(splits_data[split])
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["image_path", "plate_text"])
            writer.writeheader()
            for img_path, p_text in splits_data[split]:
                rel_path = os.path.relpath(img_path, OUTPUT_DIR)
                writer.writerow({"image_path": rel_path, "plate_text": p_text})
        logger.info(f"Wrote {out_csv}: {len(splits_data[split])} crops ({len(splits_texts[split])} unique texts)")

    # 6. Write manifest
    manifest = {
        "dataset_name": "prepared/ocr_in_v2",
        "description": "Merged prepared/ocr_in_v1 + umar1103/final-licence with zero-leakage plate-text grouping",
        "splits": {
            "train": {"crops": len(splits_data["train"]), "unique_texts": len(splits_texts["train"])},
            "val": {"crops": len(splits_data["val"]), "unique_texts": len(splits_texts["val"])},
            "test": {"crops": len(splits_data["test"]), "unique_texts": len(splits_texts["test"])},
        },
        "text_leakage": {
            "train_val": 0,
            "train_test": 0,
            "val_test": 0,
        },
        "total_crops": len(splits_data["train"]) + len(splits_data["val"]) + len(splits_data["test"]),
    }
    with open(OUTPUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Merged OCR dataset successfully created at {OUTPUT_DIR} (Total {manifest['total_crops']} crops)")

if __name__ == "__main__":
    main()
