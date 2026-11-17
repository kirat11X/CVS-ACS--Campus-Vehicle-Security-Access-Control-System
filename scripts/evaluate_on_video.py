"""
Scores plate detectors (and the OCR behind them) against the boxes a HUMAN drew for one video.

    PY=research_track/hitl_anpr/.venv/bin/python
    $PY scripts/evaluate_on_video.py 1                                    # champion only
    $PY scripts/evaluate_on_video.py 1 --weights cand=<path/to/best.pt>    # champion vs a candidate

Ground truth = training/<video>/images/*.json: every rectangle labelled license_plate. Boxes marked "excluded" are
"don't care": a detection on one is neither a hit nor a false alarm, and missing it costs nothing. Boxes carrying a
"reviewer" key were written by AI review, not a human: the script refuses to use such a video as ground truth.

Per model, at the operating threshold (predict.conf) and IoU >= 0.5:
  precision, recall, F1, mean IoU of hits, recall by plate size (small / medium / large by box width),
  AP50 over all confidences, and the OCR on the model's matched boxes: how many reads are valid Indian plates
  (indian_plates.py), and, where you typed the plate text in plates.csv, how many reads match it exactly.
Writes training/<video>/eval/<name>.json and a side-by-side summary to the terminal.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "research_track" / "hitl_anpr" / "src"))
import cv2  # noqa: E402

from anpr_hitl.config import load_config  # noqa: E402
from anpr_hitl.indian_plates import classify_plate  # noqa: E402
from anpr_hitl.ocr import crop_box, read_plate  # noqa: E402
from anpr_hitl.plates import normalize_plate  # noqa: E402
from anpr_hitl.predict import YoloDetector  # noqa: E402
from anpr_hitl.registry import Registry  # noqa: E402
from anpr_hitl.store import Store  # noqa: E402

IOU_MATCH = 0.5
EVAL_CONF = 0.01  # detect low so AP can be computed; precision/recall use the operating threshold
SIZE_BINS = (("small (<60px)", 0, 60), ("medium (60-120px)", 60, 120), ("large (>=120px)", 120, 1e9))


def iou(a, b):
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(iw, 0) * max(ih, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def load_truth(folder, label):
    frames = []
    for jpath in sorted((folder / "images").glob("*.json")):
        data = json.loads(jpath.read_text())
        gt, dontcare = [], []
        for s in data.get("shapes", []):
            if s.get("label") != label or s.get("shape_type") != "rectangle":
                continue
            if s.get("reviewer"):
                sys.exit(f"{jpath.name} has AI-reviewed boxes ({s['reviewer']}): not human ground truth.")
            (xa, ya), (xb, yb) = s["points"]
            box = (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))
            (dontcare if s.get("excluded") else gt).append((box, s.get("description") or ""))
        frames.append({"name": jpath.stem, "image": jpath.parent / data["imagePath"], "gt": gt, "dontcare": dontcare})
    return frames


def typed_text(folder):
    """plate_id -> text you typed in plates.csv (only cells that differ from what the script generated)."""
    slim = folder / "plates.csv"
    detail = folder / "plates_detailed.csv"
    if not slim.is_file() or not detail.is_file():
        return {}
    ocr = {r["plate_id"]: r["ocr_text"] for r in csv.DictReader(open(detail))}
    out = {}
    for r in csv.DictReader(open(slim)):
        text = normalize_plate(r["plate_text"])
        if text and r["plate_text"] != "nil" and text != normalize_plate(ocr.get(r["plate_id"], "")):
            out[r["plate_id"]] = text
        elif text and r["plate_text"] != "nil" and classify_plate(text).valid:
            out[r["plate_id"]] = text  # an OCR read you left as is and that is a valid plate counts as confirmed
    return out


def match(dets, gt, dontcare):
    """Greedy by confidence. Returns per-detection (tp, fp, ignored, gt_index, iou) and matched gt set."""
    used, results = set(), []
    for box, conf in sorted(dets, key=lambda d: -d[1]):
        best, best_i = 0.0, None
        for i, (g, _) in enumerate(gt):
            if i in used:
                continue
            v = iou(box, g)
            if v > best:
                best, best_i = v, i
        if best >= IOU_MATCH:
            used.add(best_i)
            results.append((box, conf, "tp", best_i, best))
        elif any(iou(box, d) >= IOU_MATCH * 0.6 or _inside(box, d) for d, _ in dontcare):
            results.append((box, conf, "ignore", None, 0.0))
        else:
            results.append((box, conf, "fp", None, best))
    return results


def _inside(a, b):
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return max(iw, 0) * max(ih, 0) / max((a[2] - a[0]) * (a[3] - a[1]), 1e-6) >= 0.7


def average_precision(scored, n_gt):
    """VOC-style all-points AP from (confidence, is_tp) pairs."""
    if not n_gt:
        return 0.0
    scored = sorted(scored, key=lambda x: -x[0])
    tp = np.cumsum([s[1] for s in scored])
    fp = np.cumsum([not s[1] for s in scored])
    recall = tp / n_gt
    precision = tp / np.maximum(tp + fp, 1e-9)
    mrec = np.concatenate([[0], recall, [1]])
    mpre = np.concatenate([[0], precision, [0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def evaluate(name, weights, frames, typed, cfg, out_dir):
    det = YoloDetector(weights, cfg.predict.imgsz, EVAL_CONF, cfg.predict.iou, 0)
    op = cfg.predict.conf
    n_gt = sum(len(f["gt"]) for f in frames)
    scored, fp = [], 0
    tp, ious, size_hits, size_tot = 0, [], {b[0]: 0 for b in SIZE_BINS}, {b[0]: 0 for b in SIZE_BINS}
    ocr_reads = ocr_valid = ocr_checked = ocr_exact = 0
    for f in frames:
        img = cv2.imread(str(f["image"]))
        xyxy, conf = det([img])[0]
        dets = [(tuple(map(float, b)), float(c)) for b, c in zip(xyxy, conf)]
        for box, c, kind, _, _ in match(dets, f["gt"], f["dontcare"]):
            if kind != "ignore":
                scored.append((c, kind == "tp"))
        op_results = match([d for d in dets if d[1] >= op], f["gt"], f["dontcare"])
        hit_gt = {}
        for box, c, kind, gi, v in op_results:
            if kind == "tp":
                tp += 1
                ious.append(v)
                hit_gt[gi] = box
            elif kind == "fp":
                fp += 1
        for i, (g, plate_id) in enumerate(f["gt"]):
            w = g[2] - g[0]
            for label, lo, hi in SIZE_BINS:
                if lo <= w < hi:
                    size_tot[label] += 1
                    size_hits[label] += i in hit_gt
            if i in hit_gt:
                read = read_plate(crop_box(img, hit_gt[i], cfg.predict.crop_pad), cfg.ocr)
                ocr_reads += bool(read.text)
                ocr_valid += classify_plate(read.text).valid
                if plate_id in typed:
                    ocr_checked += 1
                    ocr_exact += read.text == typed[plate_id]
    precision = tp / max(tp + fp, 1)
    recall = tp / max(n_gt, 1)
    result = {
        "model": name, "weights": str(weights), "ground_truth_boxes": n_gt, "operating_conf": op, "iou_match": IOU_MATCH,
        "tp": tp, "fp": fp, "fn": n_gt - tp, "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 4),
        "ap50": round(average_precision(scored, n_gt), 4), "mean_iou_of_hits": round(float(np.mean(ious)), 4) if ious else 0.0,
        "recall_by_size": {k: f"{size_hits[k]}/{size_tot[k]}" for k in size_tot},
        "ocr_on_hits": {"hits": tp, "non_empty": ocr_reads, "valid_indian": ocr_valid,
                        "checked_against_your_text": ocr_checked, "exact_match": ocr_exact},
    }
    (out_dir / f"{name}.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="the human-labelled video to test on")
    parser.add_argument("--weights", action="append", default=[], help="NAME=PATH, repeatable")
    parser.add_argument("--no-champion", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    folder = PROJECT_ROOT / "training" / args.video
    frames = load_truth(folder, cfg.class_names[0])
    typed = typed_text(folder)
    out_dir = folder / "eval"
    out_dir.mkdir(exist_ok=True)
    models = [] if args.no_champion else [("champion_" + Registry(Store(cfg.data_root)).champion()["version"],
                                            Registry(Store(cfg.data_root)).champion()["weights_path"])]
    for spec in args.weights:
        name, path = spec.split("=", 1)
        models.append((name, path))
    results = [evaluate(n, w, frames, typed, cfg, out_dir) for n, w in models]

    n_gt, n_dc = sum(len(f["gt"]) for f in frames), sum(len(f["dontcare"]) for f in frames)
    print(f"video {args.video}: {len(frames)} frames, {n_gt} human boxes ({n_dc} don't-care), "
          f"{len(typed)} plate texts confirmed by you")
    keys = ["precision", "recall", "f1", "ap50", "mean_iou_of_hits", "tp", "fp", "fn"]
    width = max(len(r["model"]) for r in results) + 2
    print("".ljust(18) + "".join(r["model"].rjust(width) for r in results))
    for k in keys:
        print(k.ljust(18) + "".join(str(r[k]).rjust(width) for r in results))
    for label, _, _ in SIZE_BINS:
        print(f"recall {label}".ljust(18)[:18] + "".join(r["recall_by_size"][label].rjust(width) for r in results))
    for k in ("non_empty", "valid_indian", "exact_match"):
        print(f"OCR {k}".ljust(18) + "".join(
            (f"{r['ocr_on_hits'][k]}/{r['ocr_on_hits']['checked_against_your_text' if k == 'exact_match' else 'hits']}").rjust(width)
            for r in results))
    print(f"\nper-model details: {out_dir}")


if __name__ == "__main__":
    main()
