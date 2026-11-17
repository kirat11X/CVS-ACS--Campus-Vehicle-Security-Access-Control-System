"""
Extracts frames from one TRAINING_VIDEOS clip, detects the number plates, reads them with OCR, and writes a folder
you can look at and correct:  training/<video>/

    research_track/hitl_anpr/.venv/bin/python scripts/extract_plates.py 5
    research_track/hitl_anpr/.venv/bin/python scripts/extract_plates.py 5 --fps 1 --start 10 --end 40
    research_track/hitl_anpr/.venv/bin/python scripts/extract_plates.py 5 --refresh       # after editing boxes
    research_track/hitl_anpr/.venv/bin/python scripts/extract_plates.py 5 --tracks-only   # redo tracks/ only

    training/5/
        images/              5_000120.jpg + 5_000120.json   frames + plate boxes: open in AnyLabeling
        preview/             5_000120.jpg                   the frame with boxes and OCR text drawn on it
        crops/               5_000120_1.jpg                 one cropped plate per box
        plates.csv           plate_id, plate_text, confidence   <- the sheet you edit
        plates_detailed.csv  raw OCR read, flags, suggested fixes, box, time ... for every plate
        tracks/              FOR THE SYSTEM AND EVALS: every plate tracked across all frames at the video's native
                             rate, its sharpest crops read, one row per physical plate (tracks.csv)
        enhanced/            crops enlarged 4x with contrast boost: for your eyes only, never for labels or training
        super_res/           Real-ESRGAN crops (scripts/super_resolve_crops.py): for your eyes only
        run_info.json        which model and settings produced the proposals

Indian standard: plate_text holds the OCR read only when it is a valid Indian plate: standard (state + RTO zone + series
letters + 4 digits, with the Delhi and Karnataka exceptions), Bharat series, vintage, armed forces, diplomatic,
temporary or trade (research_track/hitl_anpr/INDIAN_PLATE_FORMATS.md, src/anpr_hitl/indian_plates.py). Anything else
is written as `nil` with confidence 0. plates_detailed.csv keeps the raw read, the plate kind, its state / zone /
series / number, the reasons it failed, and a likely O/0, I/1, B/8, S/5 fix (`suggestions`, never applied).
Everything is a model PROPOSAL until you review it.

Frames where no plate was found are kept on purpose (add the plates the detector missed in AnyLabeling); delete them
if you do not want them. File names start with the video name so folders of several videos can be merged.

Open the frames with `python3 scripts/anylabel.py <video>`: unticking an object in its Objects list saves
"excluded": true, which means "do not train on this box". After you move, add, delete or exclude boxes, run with --refresh: crops, previews, enhanced/ and both CSVs are
rebuilt from your boxes. Text you typed in plates.csv is kept; rows you did not touch follow the new OCR read.
Plate text is written to files only, never printed.
"""
import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HITL_SRC = PROJECT_ROOT / "research_track" / "hitl_anpr" / "src"
VIDEOS_DIR = PROJECT_ROOT / "TRAINING_VIDEOS"
DEFAULT_OUT = PROJECT_ROOT / "training"
ANYLABELING_VERSION = "0.4.36"  # the `version` AnyLabeling writes; it only warns when the key is missing
PREVIEW_MAX_SIDE = 1920
MIN_CROP_SIDE = 4
BATCH = 8
NESTED_FRACTION = 0.8   # a box with this share of its area inside a more confident box is the same plate found twice
MATCH_IOU = 0.5         # --refresh: an edited box this close to an old one is still that plate
NIL = "nil"
ENHANCE_SCALE = 4
# What --force may delete (folders and files this script or its sibling script creates).
OWNED = ("images", "preview", "crops", "enhanced", "super_res", "tracks", "plates.csv", "plates_detailed.csv", "run_info.json")

sys.path.insert(0, str(HITL_SRC))
try:
    import cv2
    from PIL import Image

    from anpr_hitl.config import load_config
    from anpr_hitl.hashing import hamming, phash, sha256_file
    from anpr_hitl.indian_plates import classify_plate, suggest_repairs
    from anpr_hitl.ingest import VIDEO_EXTS, encode_jpeg_without_metadata, sample_indices
    from anpr_hitl.ocr import OcrRead, crop_box, read_plate
    from anpr_hitl.plates import check_plate
    from anpr_hitl.predict import TRACK_MIN_CONF, YoloDetector, track_video
    from anpr_hitl.registry import Registry
    from anpr_hitl.store import Store
except ImportError as exc:
    sys.exit(f"{exc}\nRun this with the HITL environment: research_track/hitl_anpr/.venv/bin/python {sys.argv[0]} ...")

DETAIL_COLUMNS = [
    "plate_id", "ocr_text", "ocr_conf", "indian_valid", "plate_kind", "state", "rto", "series", "number", "reasons",
    "notes", "flags", "suggestions", "alt_ocr_text", "det_conf", "crop", "image", "frame", "time_s", "x1", "y1", "x2", "y2",
]
SLIM_COLUMNS = ["plate_id", "plate_text", "confidence"]
OCR_FLAGS = ("empty", "low_char_conf", "char_conf_misaligned")  # the per-character confidence flags of plates.check_plate
TRACK_COLUMNS = [
    "track_id", "plate_text", "confidence", "indian_valid", "plate_kind", "raw_consensus", "agreement", "reads", "frames_seen",
    "first_frame", "last_frame", "first_s", "last_s", "best_frame", "best_crop",
]
VIEW_ONLY_README = (
    "For human viewing only. These images are {what}; they add no real information and must never be used to write\n"
    "labels or to train a model. Use ../crops/ (the original pixels) for that.\n"
)


# ---- small helpers -------------------------------------------------------------------------------------------------

def find_video(arg):
    path = Path(arg)
    if path.is_file():
        return path
    matches = sorted(p for p in VIDEOS_DIR.glob(f"{arg}.*") if p.suffix.lower() in VIDEO_EXTS)
    if not matches:
        sys.exit(f"No video called {arg!r} in {VIDEOS_DIR} (and it is not a file path).")
    return matches[0]


def resolve_weights(cfg, weights_arg):
    if weights_arg:
        path = Path(weights_arg).expanduser()
        if not path.is_file():
            sys.exit(f"Weights not found: {path}")
        return path, None
    champion = Registry(Store(cfg.data_root)).champion()
    if champion is None:
        sys.exit("The registry has no champion model; pass --weights <best.pt>.")
    return Path(champion["weights_path"]), champion["version"]


def load_detector(cfg, conf, weights_arg):
    import torch

    weights, version = resolve_weights(cfg, weights_arg)
    device = cfg.predict.device if torch.cuda.is_available() else "cpu"
    return YoloDetector(weights, cfg.predict.imgsz, conf, cfg.predict.iou, device), weights, version


def write_jpeg(path, img, cfg):
    path.write_bytes(encode_jpeg_without_metadata(img, cfg.ingest.jpeg_quality))


def read_csv(path):
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plate_number(plate_id):
    return int(plate_id.rsplit("_", 1)[1])


def iou(a, b):
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(iw, 0) * max(ih, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def clip_box(points, width, height):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x1, y1, x2, y2 = max(min(xs), 0.0), max(min(ys), 0.0), min(max(xs), width), min(max(ys), height)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)


# ---- Indian standard + OCR ----------------------------------------------------------------------------------------

def indian_valid(text):
    """A read is an Indian plate only if it is one of the recognised formats (indian_plates.py)."""
    return classify_plate(text).valid


def slim_values(ocr_text, ocr_conf):
    """What plates.csv shows for a read: the text and its confidence if valid, else nil and 0."""
    return (ocr_text, round(float(ocr_conf), 3)) if indian_valid(ocr_text) else (NIL, 0)


def generated_by_script(typed, ocr_text, ocr_conf):
    """True if a plates.csv (text, confidence) pair is what the script wrote, under the current rule or the strict
    SS NN AAA NNNN rule it used before indian_plates.py existed: i.e. not something you typed."""
    check = check_plate(ocr_text)
    earlier = (ocr_text, round(float(ocr_conf), 3)) if check.regex_valid and check.state_code_known else (NIL, 0)
    return typed in (slim_values(ocr_text, ocr_conf), earlier)


def read_one(crop, cfg, stats):
    if min(crop.shape[:2]) < MIN_CROP_SIDE:
        return OcrRead("", 0.0, [], "none"), []
    try:
        return read_plate(crop, cfg.ocr), []
    except Exception as exc:  # one odd crop must not lose the rest of the run
        stats["ocr_errors"] += 1
        print(f"  OCR failed on a crop ({type(exc).__name__}); it is flagged ocr_error", file=sys.stderr)
        return OcrRead("", 0.0, [], "error"), ["ocr_error"]


def describe_plate(frame, box, det_conf, plate_id, cfg, stats):
    crop = crop_box(frame, box, cfg.predict.crop_pad)
    read, extra_flags = read_one(crop, cfg, stats)
    check = check_plate(read.text, read.char_confs, cfg.ocr.low_char_conf)  # only for the per-character confidence flags
    info = classify_plate(read.text)
    return {
        "plate_id": plate_id, "n": plate_number(plate_id), "box": box, "det_conf": det_conf, "text": read.text,
        "ocr_conf": read.conf, "valid": info.valid, "kind": info.kind or "", "state": info.state, "rto": info.rto,
        "series": info.series, "number": info.number, "reasons": list(info.reasons), "notes": list(info.notes),
        "flags": [f for f in check.flags if f in OCR_FLAGS] + extra_flags, "suggestions": suggest_repairs(read.text),
        "alt": next((a["text"] for a in read.alternatives if a["text"] != read.text), ""), "crop": crop,
    }


def detail_row(p, name, frame_idx, native_fps):
    return {
        "plate_id": p["plate_id"], "ocr_text": p["text"], "ocr_conf": round(p["ocr_conf"], 3),
        "indian_valid": "yes" if p["valid"] else "no", "plate_kind": p["kind"], "state": p["state"], "rto": p["rto"],
        "series": p["series"], "number": p["number"], "reasons": ";".join(p["reasons"]), "notes": ";".join(p["notes"]),
        "flags": ";".join(p["flags"]),
        "suggestions": " | ".join(p["suggestions"]), "alt_ocr_text": p["alt"],
        "det_conf": "" if p["det_conf"] is None else round(p["det_conf"], 3), "crop": f"crops/{p['plate_id']}.jpg",
        "image": f"images/{name}.jpg", "frame": frame_idx, "time_s": round(frame_idx / native_fps, 3) if native_fps else "",
        "x1": round(p["box"][0]), "y1": round(p["box"][1]), "x2": round(p["box"][2]), "y2": round(p["box"][3]),
    }


def write_tables(out, rows, edited=None):
    """plates_detailed.csv (everything) and plates.csv (id, text, confidence). `edited` holds text you typed."""
    edited = edited or {}
    rows = sorted(rows, key=lambda r: (int(r["frame"]), plate_number(r["plate_id"])))
    slim = []
    for r in rows:
        text, conf = edited.get(r["plate_id"]) or slim_values(r["ocr_text"], r["ocr_conf"])
        slim.append({"plate_id": r["plate_id"], "plate_text": text, "confidence": conf})
    write_csv(out / "plates_detailed.csv", DETAIL_COLUMNS, rows)
    write_csv(out / "plates.csv", SLIM_COLUMNS, slim)


# ---- images --------------------------------------------------------------------------------------------------------

def enhance_for_viewing(crop):
    """4x Lanczos enlargement + gentle unsharp mask + local contrast (CLAHE). Adds no information."""
    big = cv2.resize(crop, None, fx=ENHANCE_SCALE, fy=ENHANCE_SCALE, interpolation=cv2.INTER_LANCZOS4)
    big = cv2.addWeighted(big, 1.8, cv2.GaussianBlur(big, (0, 0), 2.0), -0.8, 0)
    lab = cv2.cvtColor(big, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def draw_preview(frame, plates):
    scale = min(1.0, PREVIEW_MAX_SIDE / max(frame.shape[:2]))
    img = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame.copy()
    thick = max(2, round(img.shape[1] / 640))
    font_scale = img.shape[1] / 1400
    for p in plates:
        x1, y1, x2, y2 = (int(round(v * scale)) for v in p["box"])
        color = (60, 200, 60) if p["valid"] else (0, 140, 255)  # green: valid Indian plate; orange: becomes nil in plates.csv
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick)
        conf = "manual" if p["det_conf"] is None else f"{p['det_conf']:.2f}"
        label = f"{p['n']}: {p['text'] or '?'}  {conf}"
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
        ty = y1 - 6 if y1 - th - base - 6 >= 0 else y2 + th + 6
        cv2.rectangle(img, (x1, ty - th - base), (x1 + tw + 4, ty + base), color, -1)
        cv2.putText(img, label, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thick, cv2.LINE_AA)
    return img


def write_plate_images(out, cfg, name, frame, plates):
    """crops/, enhanced/ and preview/ for the plates of one frame."""
    for p in plates:
        if p["crop"].size:
            write_jpeg(out / "crops" / f"{p['plate_id']}.jpg", p["crop"], cfg)
            write_jpeg(out / "enhanced" / f"{p['plate_id']}.jpg", enhance_for_viewing(p["crop"]), cfg)
    if plates:
        ok, buf = cv2.imencode(".jpg", draw_preview(frame, plates), [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            (out / "preview" / f"{name}.jpg").write_bytes(buf.tobytes())


def make_output_dirs(out, subs=("images", "preview", "crops", "enhanced")):
    for sub in subs:
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "enhanced" / "README.txt").write_text(
        VIEW_ONLY_README.format(what="enlarged 4x with a contrast boost for easier reading by eye"))


def anylabeling_json(image_name, width, height, plates, label):
    shapes = [{
        "label": label, "score": round(p["det_conf"], 4), "points": [[p["box"][0], p["box"][1]], [p["box"][2], p["box"][3]]],
        "group_id": None, "description": p["plate_id"], "difficult": False, "shape_type": "rectangle", "flags": {},
        "attributes": {}, "kie_linking": [],
    } for p in plates]
    return {"version": ANYLABELING_VERSION, "flags": {}, "shapes": shapes, "imagePath": image_name, "imageData": None,
            "imageHeight": height, "imageWidth": width, "text": ""}


# ---- fresh run: sample frames, detect, read ------------------------------------------------------------------------

def pick_frames(cap, indices):
    """Yield (index, frame) for the wanted indices, only decoding those frames."""
    wanted, last, idx = set(indices), max(indices), -1
    while idx < last and cap.grab():
        idx += 1
        if idx in wanted:
            ok, frame = cap.retrieve()
            if ok:
                yield idx, frame


def small_phash(frame):
    thumb = cv2.resize(frame, (256, max(1, round(frame.shape[0] * 256 / frame.shape[1]))), interpolation=cv2.INTER_AREA)
    return phash(Image.fromarray(cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)))


def drop_nested(boxes):
    """Keep the most confident of boxes sitting (mostly) inside one another; returns (kept, number dropped)."""
    def overlap(a, b):
        iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
        smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
        return max(iw, 0) * max(ih, 0) / smaller

    kept = []
    for box, conf in sorted(boxes, key=lambda b: -b[1]):
        if all(overlap(box, k) < NESTED_FRACTION for k, _ in kept):
            kept.append((box, conf))
    return kept, len(boxes) - len(kept)


def process_frame(idx, frame, boxes, ctx):
    cfg, out, stem, stats = ctx["cfg"], ctx["out"], ctx["stem"], ctx["stats"]
    h, w = frame.shape[:2]
    name = f"{stem}_{idx:06d}"
    clipped = []
    for xyxy, conf in boxes:
        box = clip_box([(xyxy[0], xyxy[1]), (xyxy[2], xyxy[3])], w, h)
        if box:
            clipped.append((box, float(conf)))
    if ctx["drop_nested"]:
        clipped, dropped = drop_nested(clipped)
        stats["nested_dropped"] += dropped
    clipped.sort(key=lambda b: (b[0][0], b[0][1]))  # left to right

    if not clipped and ctx["drop_empty"]:
        stats["dropped_empty"] += 1
        return
    stats["frames"] += 1

    plates = [describe_plate(frame, box, conf, f"{name}_{n}", cfg, stats) for n, (box, conf) in enumerate(clipped, 1)]
    for p in plates:
        stats["plates"] += 1
        stats["nil"] += not p["valid"]
        ctx["rows"].append(detail_row(p, name, idx, ctx["native_fps"]))
    write_jpeg(out / "images" / f"{name}.jpg", frame, cfg)
    label_json = anylabeling_json(f"{name}.jpg", w, h, plates, cfg.class_names[0])
    (out / "images" / f"{name}.json").write_text(json.dumps(label_json, ensure_ascii=False, indent=2))
    write_plate_images(out, cfg, name, frame, plates)


# ---- --refresh: rebuild everything derived from the boxes you edited in AnyLabeling --------------------------------

def load_previous(out):
    """(detail rows by id, text you typed by id). Folders made before the CSV split kept everything in plates.csv."""
    detail, slim = read_csv(out / "plates_detailed.csv"), read_csv(out / "plates.csv")
    if slim and "x1" in slim[0]:
        detail, slim = slim, [{"plate_id": r["plate_id"], "plate_text": r["plate_text"], "confidence": r["ocr_conf"]}
                              for r in slim if r["plate_text"] != r["ocr_text"]]
    return {r["plate_id"]: r for r in detail}, {r["plate_id"]: (r["plate_text"], round(float(r["confidence"] or 0), 3))
                                                 for r in slim}


def assign_ids(boxes, frame_idx, name, old_rows):
    """Give each current box the plate_id of the old plate it is: same description first, then the best overlap."""
    old = {i: r for i, r in old_rows.items() if str(r["frame"]) == str(frame_idx)}
    used = set()
    for b in boxes:
        if b["hint"] in old and b["hint"] not in used:
            b["plate_id"] = b["hint"]
            used.add(b["hint"])
    for b in boxes:
        if "plate_id" in b:
            continue
        best = max(((iou(b["box"], tuple(float(old[i][k]) for k in ("x1", "y1", "x2", "y2"))), i)
                    for i in old if i not in used), default=(0.0, None))
        if best[0] >= MATCH_IOU:
            b["plate_id"] = best[1]
            used.add(best[1])
    taken = [plate_number(i) for i in list(old) + [b["plate_id"] for b in boxes if "plate_id" in b]]
    for b in boxes:
        if "plate_id" not in b:
            taken.append(max(taken, default=0) + 1)
            b["plate_id"] = f"{name}_{taken[-1]}"
    return len(used)


def refresh(out, cfg):
    images = out / "images"
    if not images.is_dir():
        sys.exit(f"{out} has no images/ folder; run the script without --refresh first.")
    old_rows, typed = load_previous(out)
    info_path = out / "run_info.json"
    native_fps = (json.loads(info_path.read_text()).get("native_fps") or 0) if info_path.is_file() else 0
    for n in ("plates.csv", "plates_detailed.csv"):
        if (out / n).is_file():
            shutil.copy2(out / n, out / f"{n}.bak")
    for sub in ("crops", "enhanced", "preview"):
        shutil.rmtree(out / sub, ignore_errors=True)
    make_output_dirs(out)

    stats = {"ocr_errors": 0}
    counts = Counter()
    rows, edited, current = [], {}, set()
    label = cfg.class_names[0]
    for jpath in sorted(images.glob("*.json")):
        data = json.loads(jpath.read_text())
        name, frame_idx = jpath.stem, plate_number(jpath.stem)
        frame = cv2.imread(str(images / data["imagePath"]))
        if frame is None:
            print(f"  skipping {jpath.name}: image not found", file=sys.stderr)
            continue
        h, w = frame.shape[:2]
        boxes = []
        for s in data.get("shapes", []):
            if s.get("excluded"):  # unticked in AnyLabeling (scripts/anylabel.py): not a box to list or train on
                counts["excluded"] += 1
                continue
            box = clip_box(s["points"], w, h) if s.get("shape_type") == "rectangle" and s.get("label") == label else None
            if box is None:
                counts["skipped_shapes"] += 1
                continue
            boxes.append({"box": box, "score": s.get("score"), "hint": s.get("description") or None})
        counts["matched"] += assign_ids(boxes, frame_idx, name, old_rows)
        plates = []
        for b in sorted(boxes, key=lambda b: plate_number(b["plate_id"])):
            p = describe_plate(frame, b["box"], b["score"], b["plate_id"], cfg, stats)
            plates.append(p)
            row = detail_row(p, name, frame_idx, native_fps)
            rows.append(row)
            current.add(p["plate_id"])
            counts["boxes"] += 1
            counts["nil"] += not p["valid"]
            old = old_rows.get(p["plate_id"])
            if old and p["plate_id"] in typed and not generated_by_script(typed[p["plate_id"]], old["ocr_text"], old["ocr_conf"]):
                edited[p["plate_id"]] = typed[p["plate_id"]]  # you changed this cell: keep your text, not the new read
        write_plate_images(out, cfg, name, frame, plates)

    gone = set(old_rows) - current
    write_tables(out, rows, edited)
    print(f"{counts['boxes']} boxes in your edited files: {counts['matched']} kept from before, "
          f"{counts['boxes'] - counts['matched']} new, {len(gone)} removed; {counts['nil']} are not valid Indian plates (nil)")
    if edited:
        print(f"{len(edited)} row(s) keep the text you typed")
    if gone & set(typed) and any(not generated_by_script(typed[i], old_rows[i]["ocr_text"], old_rows[i]["ocr_conf"]) for i in gone & set(typed)):
        print("text you typed for removed boxes is still in plates.csv.bak")
    if counts["excluded"]:
        print(f"{counts['excluded']} box(es) excluded in AnyLabeling (unticked) are not listed; their old rows are only in the .bak files")
    if counts["skipped_shapes"]:
        print(f"{counts['skipped_shapes']} shape(s) ignored (not a rectangle labelled {label!r}, or too small)")
    if stats["ocr_errors"]:
        print(f"{stats['ocr_errors']} crop(s) failed OCR (flag: ocr_error)")
    print("\nsuper_res/ is not rebuilt here: run scripts/super_resolve_crops.py if you use it.")


# ---- tracks/: the system / evaluation view -------------------------------------------------------------------------

class Progress:
    """Wraps a detector and reports how many frames it has seen (the tracking pass reads every frame)."""

    def __init__(self, detector, total):
        self.detector, self.total, self.done = detector, total, 0

    def __call__(self, frames):
        before, self.done = self.done, self.done + len(frames)
        if self.done // 100 != before // 100:
            print(f"  tracking: {self.done}/{self.total} frames", file=sys.stderr)
        return self.detector(frames)


def track_consensus_valid_first(reads):
    """Most common read among the track's crops, preferring reads that are valid Indian plates."""
    texts = [r.text for r in reads if r.text]
    pool = [t for t in texts if indian_valid(t)] or texts
    if not pool:
        return "", 0.0, 0.0
    counts = Counter(pool)
    conf = {t: float(np.mean([r.conf for r in reads if r.text == t])) for t in counts}
    best = max(counts, key=lambda t: (counts[t], conf[t]))
    return best, counts[best] / len(texts), conf[best]


def run_tracks(video, out, cfg, detector, conf, native_fps, frame_count, stats):
    """Detect on every frame, follow each plate with ByteTrack, read each track's sharpest crops, one row per plate."""
    tdir = out / "tracks"
    shutil.rmtree(tdir, ignore_errors=True)
    (tdir / "crops").mkdir(parents=True)
    sampling_conf, detector.conf = detector.conf, min(conf, TRACK_MIN_CONF)  # the tracker also uses weak boxes
    try:
        tv = track_video(video, Progress(detector, frame_count), set(range(frame_count)), native_fps, conf,
                         cfg.predict.tracker, cfg.predict.crop_pad, cfg.predict.ocr_top_crops)
    finally:
        detector.conf = sampling_conf

    seen = {}
    for idx, boxes in tv.frames.items():
        for b in boxes:
            if b["track_id"] is not None and b["conf"] >= conf:
                seen.setdefault(b["track_id"], []).append(idx)
    rows = []
    for tid, heap in sorted(tv.best_crops.items()):
        best_first = sorted(heap, key=lambda item: -item[0])
        reads = []
        for k, (_, idx, crop) in enumerate(best_first, 1):
            reads.append(read_one(crop, cfg, stats)[0])
            if crop.size:
                write_jpeg(tdir / "crops" / f"{out.name}_t{tid}_{k}.jpg", crop, cfg)
        text, agreement, text_conf = track_consensus_valid_first(reads)
        valid = bool(text) and indian_valid(text)
        frames = sorted(seen.get(tid, []))
        rows.append({
            "track_id": f"{out.name}_t{tid}", "plate_text": text if valid else NIL, "confidence": round(text_conf, 3) if valid else 0,
            "indian_valid": "yes" if valid else "no", "plate_kind": classify_plate(text).kind or "", "raw_consensus": text, "agreement": round(agreement, 3),
            "reads": " | ".join(r.text for r in reads), "frames_seen": len(frames), "first_frame": frames[0] if frames else "",
            "last_frame": frames[-1] if frames else "", "first_s": round(frames[0] / native_fps, 3) if frames else "",
            "last_s": round(frames[-1] / native_fps, 3) if frames else "", "best_frame": best_first[0][1],
            "best_crop": f"tracks/crops/{out.name}_t{tid}_1.jpg",
        })
    write_csv(tdir / "tracks.csv", TRACK_COLUMNS, rows)
    (tdir / "info.json").write_text(json.dumps({
        "weights": str(detector.weights), "min_detection_conf": conf, "tracker": cfg.predict.tracker,
        "frames": tv.processed, "tracks": len(rows), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Independent of the boxes in images/: this pass detects on every frame with the weights above.",
    }, indent=2))
    stats["tracks"] = len(rows)
    stats["tracks_valid"] = sum(r["indian_valid"] == "yes" for r in rows)
    stats["tracks_frames"] = tv.processed
    return rows


# ---- main ----------------------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="video number/name in TRAINING_VIDEOS (e.g. 5), or a path to a video file")
    parser.add_argument("--fps", type=float, help="frames to sample per second of video (default: ingest.fps in config.yaml)")
    parser.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    parser.add_argument("--end", type=float, help="end time in seconds")
    parser.add_argument("--max-frames", type=int, help="stop after this many sampled frames")
    parser.add_argument("--conf", type=float, help="minimum plate detection confidence (default: predict.conf)")
    parser.add_argument("--weights", help="plate detector weights (default: the registry champion)")
    parser.add_argument("--keep-duplicates", action="store_true", help="do not drop near-identical frames")
    parser.add_argument("--keep-overlaps", action="store_true", help="keep boxes nested inside a more confident box")
    parser.add_argument("--drop-empty", action="store_true", help="do not keep frames where no plate was found")
    parser.add_argument("--no-tracks", action="store_true", help="skip the tracks/ pass (it reads every frame of the video)")
    parser.add_argument("--tracks-only", action="store_true", help="only (re)build tracks/ in an existing folder")
    parser.add_argument("--refresh", action="store_true", help="rebuild crops, previews, enhanced/ and the CSVs from the boxes "
                                                              "currently in images/*.json (your AnyLabeling edits)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="parent folder (default: training/); output goes to <out>/<video>/")
    parser.add_argument("--force", action="store_true", help="replace an existing output folder (discards any edits in it)")
    args = parser.parse_args()

    video = find_video(args.video)
    cfg = load_config()
    fps = args.fps or cfg.ingest.fps
    conf = args.conf if args.conf is not None else cfg.predict.conf
    out = Path(args.out).expanduser().resolve() / video.stem

    if args.refresh:
        return refresh(out, cfg)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"Cannot open video {video}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if native_fps <= 0 or frame_count <= 0:
        sys.exit("The video has no readable frame rate or length.")

    if args.tracks_only:
        if not (out / "images").is_dir():
            sys.exit(f"{out} does not exist yet; run the script without --tracks-only first.")
        cap.release()
        detector, weights, version = load_detector(cfg, conf, args.weights)
        stats = {"ocr_errors": 0}
        run_tracks(video, out, cfg, detector, conf, native_fps, frame_count, stats)
        print(f"{stats['tracks']} tracks over {stats['tracks_frames']} frames ({stats['tracks_valid']} valid Indian plates) -> {out / 'tracks'}")
        return

    if out.exists() and any((out / n).exists() for n in OWNED):
        if not args.force:
            sys.exit(f"{out} already exists and may hold your edits. Use --force to replace it, or --out for another folder.")
        for n in OWNED:
            target = out / n
            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    make_output_dirs(out)

    detector, weights, version = load_detector(cfg, conf, args.weights)
    indices = [i for i in sample_indices(frame_count, native_fps, fps)
               if i / native_fps >= args.start and (args.end is None or i / native_fps < args.end)]
    if args.max_frames:
        indices = indices[:args.max_frames]
    if not indices:
        sys.exit("No frames to sample (check --start/--end).")
    print(f"{video.name}: {frame_count} frames @ {native_fps:g} fps; sampling {len(indices)} at {fps:g}/s -> {out}")

    stats = {"sampled": 0, "duplicates": 0, "frames": 0, "dropped_empty": 0, "nested_dropped": 0, "plates": 0, "nil": 0,
             "ocr_errors": 0}
    ctx = {"cfg": cfg, "out": out, "stem": video.stem, "stats": stats, "rows": [], "native_fps": native_fps,
           "drop_empty": args.drop_empty, "drop_nested": not args.keep_overlaps}
    kept_hashes, batch = [], []

    def flush():
        for (idx, frame), (xyxy, c) in zip(batch, detector([f for _, f in batch]), strict=True):
            process_frame(idx, frame, list(zip(xyxy, c)), ctx)
        print(f"  {stats['sampled']}/{len(indices)} frames, {stats['plates']} plates", file=sys.stderr)
        batch.clear()

    for idx, frame in pick_frames(cap, indices):
        stats["sampled"] += 1
        if not args.keep_duplicates:
            h = small_phash(frame)
            if any(hamming(h, k) <= cfg.ingest.dedup_max_bits for k in kept_hashes):
                stats["duplicates"] += 1
                continue
            kept_hashes.append(h)
        batch.append((idx, frame))
        if len(batch) == BATCH:
            flush()
    if batch:
        flush()
    cap.release()

    write_tables(out, ctx["rows"])
    if not args.no_tracks:
        run_tracks(video, out, cfg, detector, conf, native_fps, frame_count, stats)
    (out / "run_info.json").write_text(json.dumps({
        "video": video.name, "native_fps": native_fps, "frame_count": frame_count, "sample_fps": fps,
        "start_s": args.start, "end_s": args.end, "min_detection_conf": conf, "dedup_dropped": stats["duplicates"],
        "model_version": version, "weights": str(weights), "weights_sha256": sha256_file(weights),
        "ocr": cfg.ocr.model_dump(mode="json"), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Boxes and text are model proposals until reviewed.", **stats,
    }, indent=2))

    print(f"\n{stats['frames']} frames kept ({stats['duplicates']} near-duplicates dropped"
          + (f", {stats['dropped_empty']} without plates dropped" if args.drop_empty else "") + f"), {stats['plates']} plates found;"
          f" {stats['nil']} are not valid Indian plates and show as {NIL} in plates.csv")
    if "tracks" in stats:
        print(f"tracks/: {stats['tracks']} physical plates tracked ({stats['tracks_valid']} read as valid Indian plates)")
    if stats["nested_dropped"]:
        print(f"{stats['nested_dropped']} duplicate box(es) nested inside a more confident one were dropped (--keep-overlaps to keep them)")
    if stats["ocr_errors"]:
        print(f"{stats['ocr_errors']} crop(s) failed OCR (flag: ocr_error)")
    print(f"\n  look at     {out / 'preview'}  (and {out / 'enhanced'} to read small plates)"
          f"\n  edit boxes  python3 scripts/anylabel.py {video.stem}   (untick a box = exclude it from training)"
          f"\n  edit text   {out / 'plates.csv'}   then, after editing boxes: extract_plates.py {video.stem} --refresh")


if __name__ == "__main__":
    main()
