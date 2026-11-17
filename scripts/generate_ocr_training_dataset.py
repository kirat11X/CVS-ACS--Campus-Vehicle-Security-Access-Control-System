#!/usr/bin/env python3
"""
Generates an image-to-text dataset specifically for training and refining OCR models
on valid Indian license plates.

Statutory Rules Enforced:
1. Standard Indian Format: State (2 letters) + RTO (1-2 digits, 1 digit only for DL) + Series (0-3 letters, no I/O) + Number (4 digits, 0001-9999).
2. Bharat Series (BH): YY BH #### XX (YY >= 21, no I/O).
3. Karnataka blank series: KA NN #### (no series letters permitted for KA).
4. Vintage: SS VA XX ####.
5. Diplomatic: NNN (CD|CC|UN|IOD) NNNN.
6. Military: YY [A-Z] ###### [A-Z].
7. All 36 current states/UTs + 4 former legal codes (TS, OR, UA, DN) permitted.

Any image that does not strictly satisfy these statutory formats is excluded.
Outputs:
- training_1/ocr_dataset/images/<id>.jpg
- training_1/ocr_dataset/labels/<id>.txt
- training_1/ocr_dataset/labels.csv (image_path, plate_text, formatted_display, state, kind)
- training_1/ocr_dataset/gt.txt (tab-separated: image_relpath\tplate_text)
"""

import os
import sys
import glob
import shutil
import yaml
import cv2
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter

ROOT_DIR = Path("/home/kirat/coding/honours")
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "research_track" / "hitl_anpr" / "src"))

from anpr_hitl.indian_plates import classify_plate, is_indian_plate
from anpr_hitl.ocr import RapidOcrReader
import importlib.util

spec = importlib.util.spec_from_file_location("plate_normalizer", str(ROOT_DIR / "backend" / "app" / "services" / "plate_normalizer.py"))
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)
format_plate_display = pn.format_plate_display
is_valid_indian_plate = pn.is_valid_indian_plate

OUTPUT_DIR = ROOT_DIR / "training_1" / "ocr_dataset"
IMAGES_DIR = OUTPUT_DIR / "images"
LABELS_DIR = OUTPUT_DIR / "labels"

def setup_dirs():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)

def is_strictly_indian(text: str) -> tuple[bool, str, str]:
    """Check text using both anpr_hitl.indian_plates and backend.app.services.plate_normalizer."""
    if not text:
        return False, "", ""
    info = classify_plate(text)
    backend_valid = is_valid_indian_plate(text)
    if info.valid or backend_valid:
        kind = info.kind or "standard"
        state = info.state or (text[:2] if len(text) >= 2 else "")
        return True, state, kind
    return False, "", ""

def process_indian_number_plates_roboflow():
    """Extract character annotations from Indian Number Plates.v8i.yolov11."""
    base = ROOT_DIR / "training_1" / "Indian Number Plates.v8i.yolov11"
    yaml_path = base / "data.yaml"
    if not yaml_path.is_file():
        return []
    with open(yaml_path) as f:
        names = yaml.safe_load(f)["names"]

    items = []
    lbl_files = sorted(list(base.glob("**/labels/*.txt")))
    print(f"\nProcessing {len(lbl_files)} files from Indian Number Plates.v8i.yolov11...")
    
    for lbl_path in lbl_files:
        img_cand1 = lbl_path.parent.parent / "images" / f"{lbl_path.stem}.jpg"
        img_cand2 = lbl_path.parent.parent / "images" / f"{lbl_path.stem}.png"
        img_path = img_cand1 if img_cand1.is_file() else (img_cand2 if img_cand2.is_file() else None)
        if not img_path:
            continue

        chars = []
        with open(lbl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                cls_idx = int(parts[0])
                name = names[cls_idx]
                if name not in ["Bounding-boxes", "Number-Plate"]:
                    cx = float(parts[1])
                    chars.append((cx, name))

        if not chars:
            continue

        chars.sort(key=lambda x: x[0])
        plate_str = "".join(c[1] for c in chars)
        
        valid, state, kind = is_strictly_indian(plate_str)
        if valid:
            items.append({
                "source": "inp_roboflow",
                "id": f"inp_{img_path.stem}",
                "img_path": img_path,
                "text": plate_str,
                "state": state,
                "kind": kind
            })
    print(f"-> Found {len(items)} valid Indian plate image-to-text pairs from Roboflow dataset.")
    return items

def process_archive5_xml():
    """Extract ground truth text and bounding boxes from archive(5)."""
    base = ROOT_DIR / "training_1" / "archive(5)"
    items = []
    xml_files = sorted(list(base.glob("**/*.xml")))
    print(f"\nProcessing {len(xml_files)} XML files from archive(5)...")
    
    for xml_path in xml_files:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            fname = root.find("filename").text
            matches = list(base.glob(f"**/{fname}"))
            if not matches:
                continue
            img_path = matches[0]
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            h, w = img.shape[:2]

            for i, obj in enumerate(root.findall("object")):
                text_val = None
                for attr in obj.findall("attributes/attribute"):
                    if attr.find("name") is not None and attr.find("name").text == "number_plate_text":
                        text_val = attr.find("value").text
                        break
                
                if not text_val:
                    continue

                valid, state, kind = is_strictly_indian(text_val)
                if not valid:
                    continue

                b = obj.find("bndbox")
                xmin = max(0, int(float(b.find("xmin").text)))
                ymin = max(0, int(float(b.find("ymin").text)))
                xmax = min(w, int(float(b.find("xmax").text)))
                ymax = min(h, int(float(b.find("ymax").text)))

                if xmax > xmin + 10 and ymax > ymin + 10:
                    crop = img[ymin:ymax, xmin:xmax]
                    clean_stem = "".join(c if c.isalnum() else "_" for c in img_path.stem)
                    crop_id = f"ac5_{clean_stem}_{i}"
                    crop_path = IMAGES_DIR / f"{crop_id}.jpg"
                    cv2.imwrite(str(crop_path), crop)

                    items.append({
                        "source": "archive5_gt",
                        "id": crop_id,
                        "img_path": crop_path,
                        "text": text_val,
                        "state": state,
                        "kind": kind
                    })
        except Exception:
            continue
    print(f"-> Found {len(items)} valid Indian plate crops with ground-truth from archive(5).")
    return items

def process_archive8_crops(reader: RapidOcrReader, max_samples: int = 1500):
    """Process high-resolution Indian cropped plates in archive(8)."""
    base = ROOT_DIR / "training_1" / "archive(8)" / "indian car number plate"
    items = []
    if not base.is_dir():
        return []
    
    img_files = sorted(list(base.glob("*.jpg")))
    print(f"\nProcessing up to {min(max_samples, len(img_files))} cropped plates from archive(8)...")
    
    count_scanned = 0
    count_valid = 0
    
    for img_path in img_files[:max_samples]:
        count_scanned += 1
        img = cv2.imread(str(img_path))
        if img is None or min(img.shape[:2]) < 15:
            continue

        read = reader.read(img)
        if not read.text or read.conf < 0.85:
            continue

        valid, state, kind = is_strictly_indian(read.text)
        if valid:
            count_valid += 1
            items.append({
                "source": "archive8_indian_plates",
                "id": f"ac8_{img_path.stem}",
                "img_path": img_path,
                "text": read.text,
                "state": state,
                "kind": kind
            })
            
        if count_scanned % 300 == 0:
            print(f"  ... scanned {count_scanned}/{min(max_samples, len(img_files))} images, found {count_valid} valid Indian plates so far.")

    print(f"-> Found {len(items)} valid Indian plate image-to-text pairs from archive(8).")
    return items

def process_project_video_crops():
    """Extract verified Indian plate crops from honours training/1 to 10."""
    items = []
    training_root = ROOT_DIR / "training"
    print(f"\nChecking verified video crops in {training_root}...")
    
    for i in range(1, 11):
        vdir = training_root / str(i)
        csv_path = vdir / "plates.csv"
        crops_dir = vdir / "crops"
        if not (csv_path.is_file() and crops_dir.is_dir()):
            continue

        import csv
        with open(csv_path, "r", encoding="utf-8") as f:
            reader_csv = csv.DictReader(f)
            for row in reader_csv:
                pid = row.get("plate_id")
                text = row.get("plate_text")
                if not pid or not text or text.lower() == "nil":
                    continue

                valid, state, kind = is_strictly_indian(text)
                if not valid:
                    continue

                crop_file = crops_dir / f"{pid}.jpg"
                if crop_file.is_file():
                    items.append({
                        "source": f"video_{i}",
                        "id": f"vid_{pid}",
                        "img_path": crop_file,
                        "text": text,
                        "state": state,
                        "kind": kind
                    })
    print(f"-> Found {len(items)} verified valid Indian plate crops from campus gate videos.")
    return items

def main():
    print("=" * 70)
    print("Generating Indian License Plate Image-to-Text Dataset for OCR Training")
    print("=" * 70)
    setup_dirs()

    reader = RapidOcrReader()

    all_items = []
    # 1. Roboflow character annotations
    all_items.extend(process_indian_number_plates_roboflow())
    # 2. Archive 5 ground truth
    all_items.extend(process_archive5_xml())
    # 3. Archive 8 Indian car plate crops
    all_items.extend(process_archive8_crops(reader, max_samples=1500))
    # 4. Project campus gate video crops
    all_items.extend(process_project_video_crops())

    print(f"\nTotal Valid Indian Plate Image-to-Text Pairs: {len(all_items)}")

    # Deduplicate by image id
    seen = set()
    unique_items = []
    for it in all_items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique_items.append(it)

    print(f"Unique Items after deduplication: {len(unique_items)}")

    # Write out images, per-image .txt files, master CSV, and master gt.txt
    import csv
    csv_rows = []
    gt_lines = []
    state_distribution = Counter()

    for it in unique_items:
        ext = it["img_path"].suffix.lower() if it["img_path"].suffix else ".jpg"
        dst_img = IMAGES_DIR / f"{it['id']}{ext}"
        dst_txt = LABELS_DIR / f"{it['id']}.txt"

        # Copy image if not already placed
        if it["img_path"].resolve() != dst_img.resolve():
            shutil.copyfile(it["img_path"], dst_img)

        # Write text file
        with open(dst_txt, "w", encoding="utf-8") as f:
            f.write(it["text"].strip() + "\n")

        disp = format_plate_display(it["text"])
        state_distribution[it["state"]] += 1

        csv_rows.append({
            "image_filename": dst_img.name,
            "plate_text": it["text"],
            "formatted_display": disp,
            "state": it["state"],
            "kind": it["kind"],
            "source": it["source"]
        })

        gt_lines.append(f"images/{dst_img.name}\t{it['text']}")

    # Write CSV
    csv_out = OUTPUT_DIR / "labels.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["image_filename", "plate_text", "formatted_display", "state", "kind", "source"])
        writer.writeheader()
        writer.writerows(csv_rows)

    # Write gt.txt
    gt_out = OUTPUT_DIR / "gt.txt"
    with open(gt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(gt_lines) + "\n")

    print("\n" + "=" * 70)
    print("DATASET GENERATION SUMMARY")
    print("=" * 70)
    print(f"Total Valid Indian Plate Pairs: {len(unique_items)}")
    print(f"Saved images directory:        {IMAGES_DIR}")
    print(f"Saved text labels directory:   {LABELS_DIR}")
    print(f"Master CSV mapping:            {csv_out}")
    print(f"Master PaddleOCR gt.txt:       {gt_out}")
    print("\nTop State Distribution:")
    for st, count in state_distribution.most_common(12):
        print(f"  {st}: {count} plates")
    print("=" * 70)

if __name__ == "__main__":
    main()
