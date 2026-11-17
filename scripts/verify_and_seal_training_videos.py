#!/usr/bin/env python3
"""
Automates frame capture from TRAINING_VIDEOS using weights/yolo11n_plate_detector_best.pt,
performs OCR, verifies both YOLO bounding boxes and OCR Indian plate text formatting,
excludes false detections (sealing background hard negatives), and writes out verified
labels so further training eliminates false alarms.
"""

import os
import sys
import json
import glob
import shutil
import csv
import subprocess
from pathlib import Path
from collections import defaultdict, Counter

ROOT_DIR = Path("/home/kirat/coding/honours")
sys.path.insert(0, str(ROOT_DIR / "research_track" / "hitl_anpr" / "src"))

import importlib.util
spec = importlib.util.spec_from_file_location("plate_normalizer", str(ROOT_DIR / "backend" / "app" / "services" / "plate_normalizer.py"))
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)
format_plate_display = pn.format_plate_display
is_valid_indian_plate = pn.is_valid_indian_plate

from anpr_hitl.indian_plates import classify_plate, suggest_repairs

WEIGHTS_PATH = ROOT_DIR / "weights" / "yolo11n_plate_detector_best.pt"
PYTHON_BIN = ROOT_DIR / "research_track" / "hitl_anpr" / ".venv" / "bin" / "python"
EXTRACT_SCRIPT = ROOT_DIR / "scripts" / "extract_plates.py"

def extract_video(v_id: int):
    """Run extract_plates.py on a video with our trained weights."""
    print(f"\n--- Extracting frames & detecting plates for Video {v_id} ---")
    cmd = [
        str(PYTHON_BIN),
        str(EXTRACT_SCRIPT),
        str(v_id),
        "--weights", str(WEIGHTS_PATH),
        "--no-tracks",
        "--force"
    ]
    res = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Extraction failed for Video {v_id}: {res.stderr[:200]}")
        return False
    print(f"Extraction successful for Video {v_id}.")
    return True

def verify_and_seal_video(v_id: int):
    """
    Verify detected boxes and OCR reads for one video:
    - Eliminate false detections (anomalous aspect ratios, tiny noise, background signage).
    - Track plate consensus across consecutive frames.
    - Validate OCR against statutory Indian plate rules.
    - Write clean YOLO labels (labels/*.txt) and updated AnyLabeling JSONs.
    """
    vdir = ROOT_DIR / "training" / str(v_id)
    if not vdir.is_dir():
        print(f"Directory {vdir} not found.")
        return None

    images_dir = vdir / "images"
    crops_dir = vdir / "crops"
    labels_dir = vdir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    detailed_csv = vdir / "plates_detailed.csv"
    plates_csv = vdir / "plates.csv"

    detailed_rows = []
    if detailed_csv.is_file():
        with open(detailed_csv, "r", encoding="utf-8") as f:
            detailed_rows = list(csv.DictReader(f))

    # Index detailed rows by plate_id
    detail_by_id = {r["plate_id"]: r for r in detailed_rows}

    # Step A: Identify valid Indian plates from detailed OCR reads
    confirmed_by_id = {}
    verified_plate_strings = set()

    for pid, r in detail_by_id.items():
        ocr_text = r.get("ocr_text", "").strip().upper()
        if not ocr_text:
            continue
        
        # 1. Direct validation
        if is_valid_indian_plate(ocr_text) or classify_plate(ocr_text).valid:
            confirmed_by_id[pid] = ocr_text
            verified_plate_strings.add(ocr_text)
            continue
            
        # 2. Confusion repair check
        repairs = suggest_repairs(ocr_text)
        for rep in repairs:
            if is_valid_indian_plate(rep) or classify_plate(rep).valid:
                confirmed_by_id[pid] = rep
                verified_plate_strings.add(rep)
                break

    print(f"  Video {v_id}: Directly identified {len(confirmed_by_id)} high-confidence Indian plate reads: {sorted(list(verified_plate_strings))}")

    # Step B: Temporal vehicle trajectory consensus
    # If a vehicle's plate is verified in certain frames, propagate to adjacent frames tracking the same vehicle
    json_files = sorted(list(images_dir.glob("*.json")))
    
    # Map frame -> boxes
    frame_boxes = {}
    for jp in json_files:
        data = json.loads(jp.read_text())
        frame_name = jp.stem
        w, h = data["imageWidth"], data["imageHeight"]
        boxes = []
        for i, s in enumerate(data.get("shapes", [])):
            if s.get("shape_type") == "rectangle" and len(s.get("points", [])) == 2:
                xs = [p[0] for p in s["points"]]
                ys = [p[1] for p in s["points"]]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                pid = f"{frame_name}_{i+1}"
                boxes.append({
                    "shape_idx": i,
                    "plate_id": pid,
                    "box": (x1, y1, x2, y2),
                    "shape": s
                })
        frame_boxes[frame_name] = {"data": data, "path": jp, "w": w, "h": h, "boxes": boxes}

    # Temporal propagation:
    # If verified_plate_strings has exactly 1 dominant plate (typical in a single vehicle passing clip),
    # associate vehicle bumper boxes with this plate.
    dominant_plate = None
    if len(verified_plate_strings) == 1:
        dominant_plate = list(verified_plate_strings)[0]
    elif len(verified_plate_strings) > 1:
        # Most frequent plate
        counts = Counter(confirmed_by_id.values())
        dominant_plate = counts.most_common(1)[0][0]

    # Step C: Geometric and false detection verification
    stats = {
        "total_frames": len(json_files),
        "total_boxes": 0,
        "verified_plates": 0,
        "false_positives_excluded": 0,
        "background_frames": 0,
        "confirmed_plates": set()
    }

    updated_plates_rows = []
    
    for frame_name, finfo in frame_boxes.items():
        data = finfo["data"]
        w, h = finfo["w"], finfo["h"]
        valid_yolo_boxes = []

        for binfo in finfo["boxes"]:
            stats["total_boxes"] += 1
            x1, y1, x2, y2 = binfo["box"]
            bw = x2 - x1
            bh = y2 - y1
            area = bw * bh
            aspect = bw / max(bh, 1.0)
            pid = binfo["plate_id"]
            shape = binfo["shape"]

            # False Detection Checks:
            # 1. Abnormal aspect ratio (< 1.1 or > 6.5)
            # 2. Too small (area < 180 px^2)
            # 3. Known background false triggers (e.g. signage, road markers)
            is_false_alarm = False
            rejection_reason = ""

            if aspect < 1.1:
                is_false_alarm = True
                rejection_reason = "vertical_aspect_ratio"
            elif aspect > 6.5:
                is_false_alarm = True
                rejection_reason = "excessive_aspect_ratio"
            elif area < 180:
                is_false_alarm = True
                rejection_reason = "subpixel_tiny_noise"

            # Check if this box has a confirmed plate read
            resolved_text = confirmed_by_id.get(pid)
            if not resolved_text and not is_false_alarm:
                # If dominant plate exists and box is in the road/vehicle area
                if dominant_plate and y1 > h * 0.2:
                    resolved_text = dominant_plate

            # If it's a known background false trigger with no plate
            row = detail_by_id.get(pid)
            if row:
                det_conf = float(row.get("det_conf") or 0.0)
                if det_conf < 0.40 and not resolved_text:
                    is_false_alarm = True
                    rejection_reason = "low_conf_unverified_background"

            if is_false_alarm or (not resolved_text and det_conf < 0.45):
                # Mark as excluded so YOLO retraining knows this is NOT a plate
                shape["excluded"] = True
                shape["flags"] = [rejection_reason]
                stats["false_positives_excluded"] += 1
                updated_plates_rows.append({"plate_id": pid, "plate_text": "nil", "confidence": "0"})
            else:
                shape["excluded"] = False
                if resolved_text:
                    shape["description"] = resolved_text
                    stats["confirmed_plates"].add(resolved_text)
                    stats["verified_plates"] += 1
                    updated_plates_rows.append({
                        "plate_id": pid,
                        "plate_text": resolved_text,
                        "confidence": str(round(float(row.get("ocr_conf") or 0.90), 3)) if row else "0.900"
                    })
                else:
                    updated_plates_rows.append({"plate_id": pid, "plate_text": "nil", "confidence": "0"})

                # Valid normalized YOLO format: class cx cy w h
                cx = ((x1 + x2) / 2.0) / w
                cy = ((y1 + y2) / 2.0) / h
                nw = bw / w
                nh = bh / h
                valid_yolo_boxes.append(f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")

        # Write updated JSON
        finfo["path"].write_text(json.dumps(data, indent=2))

        # Write YOLO label file: labels/<frame_name>.txt
        lbl_file = labels_dir / f"{frame_name}.txt"
        with open(lbl_file, "w") as lf:
            for ybox in valid_yolo_boxes:
                lf.write(ybox + "\n")

        if not valid_yolo_boxes:
            stats["background_frames"] += 1

    # Write updated plates.csv
    with open(plates_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["plate_id", "plate_text", "confidence"])
        writer.writeheader()
        writer.writerows(updated_plates_rows)

    # Collect confirmed plate crops into ocr_dataset
    new_ocr_crops = 0
    ocr_dataset_dir = ROOT_DIR / "training_1" / "ocr_dataset"
    ocr_images = ocr_dataset_dir / "images"
    ocr_labels = ocr_dataset_dir / "labels"
    ocr_csv = ocr_dataset_dir / "labels.csv"
    ocr_gt = ocr_dataset_dir / "gt.txt"

    if ocr_dataset_dir.is_dir():
        for pid, text in confirmed_by_id.items():
            crop_path = crops_dir / f"{pid}.jpg"
            if crop_path.is_file():
                dest_crop = ocr_images / f"vid_{pid}.jpg"
                dest_txt = ocr_labels / f"vid_{pid}.txt"
                if not dest_crop.is_file():
                    shutil.copyfile(crop_path, dest_crop)
                    dest_txt.write_text(text + "\n")
                    disp = format_plate_display(text)
                    info = classify_plate(text)
                    with open(ocr_csv, "a", newline="", encoding="utf-8") as cf:
                        writer = csv.DictWriter(cf, fieldnames=["image_filename", "plate_text", "formatted_display", "state", "kind", "source"])
                        writer.writerow({
                            "image_filename": dest_crop.name,
                            "plate_text": text,
                            "formatted_display": disp,
                            "state": info.state,
                            "kind": info.kind,
                            "source": f"training_video_{v_id}"
                        })
                    with open(ocr_gt, "a", encoding="utf-8") as gf:
                        gf.write(f"images/{dest_crop.name}\t{text}\n")
                    new_ocr_crops += 1

    print(f"\n[VIDEO {v_id} VERIFICATION COMPLETE]")
    print(f"  Frames Processed:            {stats['total_frames']}")
    print(f"  YOLO Detections Evaluated:   {stats['total_boxes']}")
    print(f"  Verified Valid Plate Boxes:  {stats['verified_plates']}")
    print(f"  False Detections Excluded:   {stats['false_positives_excluded']}")
    print(f"  Hard-Negative Frames Sealed: {stats['background_frames']}")
    print(f"  Confirmed Indian Plates:     {sorted(list(stats['confirmed_plates']))}")
    print(f"  New Crops Added to OCR Set:  {new_ocr_crops}")

    return stats

def main():
    print("=" * 70)
    print("YOLO + OCR Pipeline Verification & False Detection Suppression")
    print("=" * 70)

    # Videos to process: 1, 2, 3, 4, 5, 6, 7, 8, 10
    video_ids = [1, 2, 3, 4, 5, 6, 7, 8, 10]

    all_stats = {}
    for vid in video_ids:
        # Step 1: Extract frames if not already freshly extracted
        extract_video(vid)
        # Step 2: Verify YOLO boxes & OCR text, exclude false detections, seal labels
        st = verify_and_seal_video(vid)
        if st:
            all_stats[vid] = st

    print("\n" + "=" * 70)
    print("OVERALL SUMMARY ACROSS ALL TRAINING VIDEOS")
    print("=" * 70)
    total_frames = sum(s["total_frames"] for s in all_stats.values())
    total_boxes = sum(s["total_boxes"] for s in all_stats.values())
    total_verified = sum(s["verified_plates"] for s in all_stats.values())
    total_excluded = sum(s["false_positives_excluded"] for s in all_stats.values())
    total_hard_neg = sum(s["background_frames"] for s in all_stats.values())
    all_plates = sorted(list(set.union(*(s["confirmed_plates"] for s in all_stats.values()))))

    print(f"Total Videos Processed:         {len(all_stats)}")
    print(f"Total Video Frames Captured:    {total_frames}")
    print(f"Total Raw YOLO Detections:      {total_boxes}")
    print(f"Verified True License Plates:   {total_verified}")
    print(f"False Detections Eliminated:    {total_excluded}")
    print(f"Hard Negative Frames Generated: {total_hard_neg}")
    print(f"Confirmed Indian Plates List:   {all_plates}")
    print("=" * 70)

if __name__ == "__main__":
    main()
