#!/usr/bin/env python3
"""
Prepares a unified, single-class license plate dataset from all annotated sources in training_1.
Combines:
1. archive/License-Plate-Data (433 images) - Full car photos with plate bounding boxes
2. archive(5) (47 images) - Indian car photos with Pascal VOC XML number_plate annotations
3. archive(7)/Traffic Dataset (398 images) - Traffic/road scenes with plate annotations (Class 1)
4. Indian Number Plates.v8i.yolov11 (641 images) - Diverse Indian number plates
Plus ~50 background (negative) frames from traffic dataset to prevent false positives on car grilles/signs.

Splits: 85% train, 15% val (seeded for reproducibility).
All labels are single-class: 0 = license_plate.
"""

import os
import glob
import shutil
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image

SEED = 42
random.seed(SEED)

ROOT_DIR = Path("/home/kirat/coding/honours")
TRAINING_1_DIR = ROOT_DIR / "training_1"
OUTPUT_DIR = TRAINING_1_DIR / "unified_plate_dataset"

def ensure_dirs():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for split in ["train", "val"]:
        (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

def clamp(val, min_v=0.0, max_v=1.0):
    return max(min_v, min(max_v, float(val)))

def collect_source1():
    """Source 1: License-Plate-Data (Kaggle)"""
    items = []
    base = TRAINING_1_DIR / "archive" / "License-Plate-Data"
    for img_path in base.glob("**/images/*.*"):
        if img_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
            continue
        lbl_path = img_path.parent.parent / "labels" / f"{img_path.stem}.txt"
        if not lbl_path.is_file():
            continue
        boxes = []
        with open(lbl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    _, cx, cy, w, h = parts[:5]
                    boxes.append((0, clamp(cx), clamp(cy), clamp(w), clamp(h)))
        if boxes:
            items.append({
                "source": "lpd",
                "id": f"lpd_{img_path.stem}",
                "img_path": img_path,
                "boxes": boxes
            })
    print(f"Collected {len(items)} items from License-Plate-Data")
    return items

def collect_source2():
    """Source 2: archive(5) Pascal VOC XMLs for Indian Number Plates"""
    items = []
    base = TRAINING_1_DIR / "archive(5)"
    xml_files = list(base.glob("**/*.xml"))
    for xml_path in xml_files:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            fname = root.find("filename").text
            # Find image
            matching_imgs = list(base.glob(f"**/{fname}"))
            if not matching_imgs:
                continue
            img_path = matching_imgs[0]
            with Image.open(img_path) as im:
                img_w, img_h = im.size

            boxes = []
            for obj in root.findall("object"):
                name = obj.find("name").text
                if "plate" in name.lower():
                    b = obj.find("bndbox")
                    xmin = float(b.find("xmin").text)
                    ymin = float(b.find("ymin").text)
                    xmax = float(b.find("xmax").text)
                    ymax = float(b.find("ymax").text)
                    
                    bw = (xmax - xmin) / img_w
                    bh = (ymax - ymin) / img_h
                    cx = (xmin + xmax) / (2.0 * img_w)
                    cy = (ymin + ymax) / (2.0 * img_h)
                    
                    if bw > 0.005 and bh > 0.005:
                        boxes.append((0, clamp(cx), clamp(cy), clamp(bw), clamp(bh)))
            if boxes:
                clean_stem = "".join(c if c.isalnum() else "_" for c in img_path.stem)
                items.append({
                    "source": "ac5",
                    "id": f"ac5_{clean_stem}",
                    "img_path": img_path,
                    "boxes": boxes
                })
        except Exception as e:
            continue
    print(f"Collected {len(items)} items from archive(5)")
    return items

def collect_source3():
    """Source 3: archive(7) Traffic Dataset (Class 1 = Plate) + small background set"""
    items = []
    base = TRAINING_1_DIR / "archive(7)" / "Traffic Dataset"
    lbl_files = list(base.glob("labels/**/*.txt"))
    bg_candidates = []
    for lbl_path in lbl_files:
        # Find corresponding image
        rel = lbl_path.relative_to(base / "labels")
        img_cand1 = base / "images" / rel.parent / f"{lbl_path.stem}.jpg"
        img_cand2 = base / "images" / rel.parent / f"{lbl_path.stem}.png"
        img_path = img_cand1 if img_cand1.is_file() else (img_cand2 if img_cand2.is_file() else None)
        if not img_path:
            continue
        
        boxes = []
        with open(lbl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5 and int(parts[0]) == 1:
                    _, cx, cy, w, h = parts[:5]
                    boxes.append((0, clamp(cx), clamp(cy), clamp(w), clamp(h)))
        
        clean_stem = "".join(c if c.isalnum() else "_" for c in lbl_path.stem)
        if boxes:
            items.append({
                "source": "traf",
                "id": f"traf_{clean_stem}",
                "img_path": img_path,
                "boxes": boxes
            })
        else:
            bg_candidates.append({
                "source": "traf_bg",
                "id": f"traf_bg_{clean_stem}",
                "img_path": img_path,
                "boxes": []
            })
    
    # Sample 50 background images
    random.shuffle(bg_candidates)
    sampled_bg = bg_candidates[:50]
    print(f"Collected {len(items)} positive items and {len(sampled_bg)} background items from Traffic Dataset")
    return items + sampled_bg

def collect_source4():
    """Source 4: Indian Number Plates.v8i.yolov11"""
    items = []
    base = TRAINING_1_DIR / "Indian Number Plates.v8i.yolov11"
    for img_path in base.glob("**/images/*.*"):
        if img_path.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
            continue
        lbl_path = img_path.parent.parent / "labels" / f"{img_path.stem}.txt"
        if not lbl_path.is_file():
            continue
        
        char_boxes = []
        with open(lbl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    _, cx, cy, w, h = parts[:5]
                    cx, cy, w, h = float(cx), float(cy), float(w), float(h)
                    x1 = cx - w / 2.0
                    y1 = cy - h / 2.0
                    x2 = cx + w / 2.0
                    y2 = cy + h / 2.0
                    char_boxes.append((x1, y1, x2, y2))
        
        if char_boxes:
            min_x = max(0.005, min(b[0] for b in char_boxes) - 0.02)
            min_y = max(0.005, min(b[1] for b in char_boxes) - 0.04)
            max_x = min(0.995, max(b[2] for b in char_boxes) + 0.02)
            max_y = min(0.995, max(b[3] for b in char_boxes) + 0.04)
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            bw = max_x - min_x
            bh = max_y - min_y
            boxes = [(0, clamp(cx), clamp(cy), clamp(bw), clamp(bh))]
        else:
            boxes = [(0, 0.5, 0.5, 0.96, 0.92)]
        
        clean_stem = "".join(c if c.isalnum() else "_" for c in img_path.stem)
        items.append({
            "source": "inp",
            "id": f"inp_{clean_stem}",
            "img_path": img_path,
            "boxes": boxes
        })
    print(f"Collected {len(items)} items from Indian Number Plates")
    return items

def build_dataset():
    ensure_dirs()
    all_items = []
    all_items.extend(collect_source1())
    all_items.extend(collect_source2())
    all_items.extend(collect_source3())
    all_items.extend(collect_source4())
    
    print(f"\nTotal unified items: {len(all_items)}")
    random.shuffle(all_items)
    
    val_count = int(len(all_items) * 0.15)
    val_items = all_items[:val_count]
    train_items = all_items[val_count:]
    
    print(f"Train split: {len(train_items)} | Val split: {len(val_items)}")
    
    for split_name, items in [("train", train_items), ("val", val_items)]:
        for it in items:
            ext = it["img_path"].suffix.lower()
            dst_img = OUTPUT_DIR / "images" / split_name / f"{it['id']}{ext}"
            dst_lbl = OUTPUT_DIR / "labels" / split_name / f"{it['id']}.txt"
            
            # Copy image
            shutil.copyfile(it["img_path"], dst_img)
            
            # Write label
            with open(dst_lbl, "w") as f:
                for b in it["boxes"]:
                    f.write(f"{b[0]} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f} {b[4]:.6f}\n")
    
    # Write data.yaml
    yaml_content = f"""path: {OUTPUT_DIR.resolve()}
train: images/train
val: images/val

names:
  0: license_plate
"""
    yaml_path = OUTPUT_DIR / "data.yaml"
    with open(yaml_path, "w") as f:
        f.write(yaml_content)
    print(f"Successfully generated dataset at: {OUTPUT_DIR}")
    print(f"Configuration written to: {yaml_path}")

if __name__ == "__main__":
    build_dataset()
