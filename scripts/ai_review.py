"""
AI-assisted review of plate boxes (Claude looks at the images; every decision is recorded and tagged).

    PY=research_track/hitl_anpr/.venv/bin/python
    $PY scripts/ai_review.py propose 3        # candidate boxes from several detectors at a low threshold
    $PY scripts/ai_review.py sheets 3         # numbered contact sheets of the candidates, to look at
    $PY scripts/ai_review.py decide 3 "p: 1-12,15  n: 13,14  u: 16"   # record the verdicts for candidates
    $PY scripts/ai_review.py apply 3          # write the verdicts into training/3/images/*.json
    $PY scripts/ai_review.py textsheets 3     # enlarged crops of the accepted plates with their OCR read

Why candidates: the champion misses many plates (it found 25 of the 81 boxes in the human-labelled video 1), and
reviewing only its own proposals would teach the detector that the plates it misses are background. So the champion
at a low threshold, an independent plate detector (open-image-models YOLOv9-s-608), the current boxes and tiled
passes for small plates all propose; duplicates are merged; a reviewer says, per candidate:
    p = a number plate          -> kept as a training box
    n = not a plate             -> dropped
    u = unsure / too unclear    -> kept with "excluded": true (ignored by training, not taught as background)
Boxes come from the detectors (pixel-accurate); the decision is the reviewer's.

Provenance: every shape written by `apply` carries "reviewer": REVIEWER. Frames a human already edited are never
touched (for video 2: the label files changed after the run that produced them, listed in ai_review/human_frames.json).
The original label files are copied to ai_review/json_before/ before anything is written.
"""
import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "research_track" / "hitl_anpr" / "src"))
import cv2  # noqa: E402

from anpr_hitl.config import load_config  # noqa: E402
from anpr_hitl.predict import YoloDetector  # noqa: E402
from anpr_hitl.registry import Registry  # noqa: E402
from anpr_hitl.store import Store  # noqa: E402

REVIEWER = "claude-opus-5.5 (vision)"
OIM_WEIGHTS = Path("~/ml-assets/campus/models/open-image-models/yolo-v9-s-608-license-plates-end2end.onnx").expanduser()
CHAMPION_CONF, OIM_CONF = 0.05, 0.10
TILE, OVERLAP = 1024, 160
MERGE_IOU, MERGE_CONTAIN = 0.4, 0.7
MIN_W, MIN_H = 10, 5
BOX_PREFERENCE = ("champion", "current", "oim608")
SHEET_COLS, SHEET_ROWS, TILE_W, TILE_H = 5, 6, 256, 160


def folder_of(video):
    return PROJECT_ROOT / "training" / str(video)


def review_dir(video):
    d = folder_of(video) / "ai_review"
    d.mkdir(exist_ok=True)
    return d


def human_frames(video):
    """Frames whose label file changed after the run that produced it: a human edited them, do not touch."""
    folder = folder_of(video)
    path = review_dir(video) / "human_frames.json"
    if path.is_file():
        return set(json.loads(path.read_text()))
    run_time = (folder / "run_info.json").stat().st_mtime
    frames = sorted(j.stem for j in (folder / "images").glob("*.json") if j.stat().st_mtime > run_time + 1)
    path.write_text(json.dumps(frames, indent=1))
    return set(frames)


def iou(a, b):
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(iw, 0) * max(ih, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def contain(a, b):
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(iw, 0) * max(ih, 0)
    return inter / max(min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])), 1e-6)


def tiles(w, h):
    """Overlapping windows of about TILE px covering the frame (none if the frame is small)."""
    if max(w, h) <= TILE * 1.2:
        return []
    out = []
    nx, ny = max(1, math.ceil((w - OVERLAP) / (TILE - OVERLAP))), max(1, math.ceil((h - OVERLAP) / (TILE - OVERLAP)))
    sx, sy = (w - TILE) / max(nx - 1, 1), (h - TILE) / max(ny - 1, 1)
    for j in range(ny):
        for i in range(nx):
            x0, y0 = int(round(i * sx)) if nx > 1 else 0, int(round(j * sy)) if ny > 1 else 0
            out.append((x0, y0, min(x0 + TILE, w), min(y0 + TILE, h)))
    return out


class OimDetector:
    """open-image-models end-to-end YOLOv9 (letterboxed RGB 0-1 in; [batch, x1, y1, x2, y2, cls, score] out)."""

    def __init__(self, path, size=608):
        import onnxruntime as ort

        self.session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.name, self.size = self.session.get_inputs()[0].name, size

    def __call__(self, img, conf):
        h, w = img.shape[:2]
        r = self.size / max(h, w)
        nw, nh = int(round(w * r)), int(round(h * r))
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        dx, dy = (self.size - nw) // 2, (self.size - nh) // 2
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        x = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255
        out = self.session.run(None, {self.name: x})[0]
        return [((b[1] - dx) / r, (b[2] - dy) / r, (b[3] - dx) / r, (b[4] - dy) / r, float(b[6])) for b in out if b[6] >= conf]


def propose(video):
    cfg = load_config()
    folder, rdir = folder_of(video), review_dir(video)
    skip = human_frames(video)
    champion = Registry(Store(cfg.data_root)).champion()["weights_path"]
    det = YoloDetector(champion, cfg.predict.imgsz, CHAMPION_CONF, cfg.predict.iou, 0)
    oim = OimDetector(OIM_WEIGHTS)
    cands, frames = [], 0
    for jpath in sorted((folder / "images").glob("*.json")):
        if jpath.stem in skip:
            continue
        data = json.loads(jpath.read_text())
        img = cv2.imread(str(jpath.parent / data["imagePath"]))
        h, w = img.shape[:2]
        raw = []  # (box, source, score, description)
        for s in data["shapes"]:
            (xa, ya), (xb, yb) = s["points"]
            raw.append(((min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)), "current", float(s.get("score") or 0),
                        s.get("description")))
        windows = [(0, 0, w, h)] + tiles(w, h)
        for (x0, y0, x1, y1) in windows:
            sub = img[y0:y1, x0:x1]
            if (x0, y0, x1, y1) == (0, 0, w, h) or max(w, h) > 2000:
                xyxy, conf = det([sub])[0]
                raw += [((b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0), "champion", float(c), None) for b, c in zip(xyxy, conf)]
            raw += [((b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0), "oim608", b[4], None) for b in oim(sub, OIM_CONF)]
        raw = [(tuple(map(float, (max(b[0], 0), max(b[1], 0), min(b[2], w), min(b[3], h)))), src, sc, d) for b, src, sc, d in raw]
        raw = [r for r in raw if r[0][2] - r[0][0] >= MIN_W and r[0][3] - r[0][1] >= MIN_H]
        clusters = []
        for r in sorted(raw, key=lambda r: (r[1] != "current", -r[2])):  # current boxes first, then by score
            for cl in clusters:
                if iou(r[0], cl["box"]) >= MERGE_IOU or contain(r[0], cl["box"]) >= MERGE_CONTAIN:
                    if r[1] not in cl["sources"]:
                        cl["sources"][r[1]], cl["boxes"][r[1]] = round(r[2], 3), r[0]
                    cl["description"] = cl["description"] or r[3]
                    break
            else:
                clusters.append({"box": r[0], "sources": {r[1]: round(r[2], 3)}, "boxes": {r[1]: r[0]}, "description": r[3]})
        for cl in clusters:
            # The box written is the champion's when it found the plate (tightest in practice), else the current
            # box, else the other detector's; the cluster is kept together by its first box.
            best = next(src for src in BOX_PREFERENCE if src in cl["boxes"])
            cands.append({"id": len(cands) + 1, "frame": jpath.stem, "box": [round(v, 1) for v in cl["boxes"][best]],
                          "box_from": best, "sources": cl["sources"], "description": cl["description"]})
        frames += 1
    (rdir / "candidates.json").write_text(json.dumps(cands, indent=1))
    by = {}
    for c in cands:
        for s in c["sources"]:
            by[s] = by.get(s, 0) + 1
    print(f"video {video}: {frames} frames reviewed by AI ({len(skip)} human-edited frames skipped), "
          f"{len(cands)} candidates; proposed by: {by}")


def sheets(video):
    folder, rdir = folder_of(video), review_dir(video)
    cands = json.loads((rdir / "candidates.json").read_text())
    out = rdir / "sheets"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    imgs, per = {}, SHEET_COLS * SHEET_ROWS
    for s in range(0, len(cands), per):
        sheet = np.full((SHEET_ROWS * (TILE_H + 22), SHEET_COLS * TILE_W, 3), 30, np.uint8)
        for k, c in enumerate(cands[s:s + per]):
            if c["frame"] not in imgs:
                imgs = {c["frame"]: cv2.imread(str(folder / "images" / f"{c['frame']}.jpg"))}
            img = imgs[c["frame"]]
            h, w = img.shape[:2]
            x1, y1, x2, y2 = c["box"]
            bw, bh = x2 - x1, y2 - y1
            cw, ch = max(bw * 3.2, 140), max(bh * 4.0, 90)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            X1, Y1 = int(max(cx - cw / 2, 0)), int(max(cy - ch / 2, 0))
            X2, Y2 = int(min(cx + cw / 2, w)), int(min(cy + ch / 2, h))
            crop = img[Y1:Y2, X1:X2].copy()
            sc = min(TILE_W / crop.shape[1], TILE_H / crop.shape[0])
            crop = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC if sc > 1 else cv2.INTER_AREA)
            bx1, by1 = int((x1 - X1) * sc), int((y1 - Y1) * sc)
            bx2, by2 = int((x2 - X1) * sc), int((y2 - Y1) * sc)
            cv2.rectangle(crop, (bx1 - 2, by1 - 2), (bx2 + 2, by2 + 2), (0, 0, 255), 1)
            r, col = divmod(k, SHEET_COLS)
            oy, ox = r * (TILE_H + 22) + 22, col * TILE_W
            sheet[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
            src = "".join(sorted({"current": "C", "champion": "Y", "oim608": "O"}[x] for x in c["sources"]))
            cv2.putText(sheet, f"{c['id']} [{src}]", (ox + 4, oy - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        path = out / f"sheet_{s // per + 1:02d}.jpg"
        cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"{len(cands)} candidates on {math.ceil(len(cands) / per)} sheet(s) in {out}")


def parse_ids(spec):
    ids = set()
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            ids.update(range(int(a), int(b) + 1))
        else:
            ids.add(int(part))
    return ids


def decide(video, spec):
    rdir = review_dir(video)
    path = rdir / "decisions.json"
    decisions = json.loads(path.read_text()) if path.is_file() else {}
    for verdict, ids in re.findall(r"([pnu])\s*:\s*([\d,\-\s]+?)(?=\s+[pnu]\s*:|$)", spec.strip()):
        for i in parse_ids(ids):
            decisions[str(i)] = verdict
    path.write_text(json.dumps(dict(sorted(decisions.items(), key=lambda kv: int(kv[0]))), indent=0))
    total = len(json.loads((rdir / "candidates.json").read_text()))
    counts = {v: sum(1 for d in decisions.values() if d == v) for v in "pnu"}
    print(f"video {video}: {len(decisions)}/{total} candidates decided {counts}")


def apply(video):
    cfg = load_config()
    folder, rdir = folder_of(video), review_dir(video)
    cands = json.loads((rdir / "candidates.json").read_text())
    decisions = json.loads((rdir / "decisions.json").read_text())
    missing = [c["id"] for c in cands if str(c["id"]) not in decisions]
    if missing:
        sys.exit(f"{len(missing)} candidates have no decision yet, e.g. {missing[:10]}")
    skip = human_frames(video)
    backup = rdir / "json_before"
    if not backup.exists():
        shutil.copytree(folder / "images", backup, ignore=shutil.ignore_patterns("*.jpg"))
    by_frame = {}
    for c in cands:
        by_frame.setdefault(c["frame"], []).append(c)
    counts = {"p": 0, "n": 0, "u": 0}
    for jpath in sorted((folder / "images").glob("*.json")):
        if jpath.stem in skip:
            continue
        data = json.loads(jpath.read_text())
        shapes = []
        for c in by_frame.get(jpath.stem, []):
            verdict = decisions[str(c["id"])]
            counts[verdict] += 1
            if verdict == "n":
                continue
            x1, y1, x2, y2 = c["box"]
            shape = {"label": cfg.class_names[0], "score": max(c["sources"].values()), "points": [[x1, y1], [x2, y2]],
                     "group_id": None, "description": c["description"] or "", "difficult": False,
                     "shape_type": "rectangle", "flags": {}, "attributes": {}, "kie_linking": [],
                     "reviewer": REVIEWER, "review_sources": sorted(c["sources"])}
            if verdict == "u":
                shape["excluded"] = True
            shapes.append(shape)
        data["shapes"] = shapes
        jpath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"video {video}: wrote {counts['p']} plates, {counts['u']} excluded (unsure), dropped {counts['n']}; "
          f"{len(skip)} human-edited frames untouched")


def textsheets(video):
    import csv

    folder, rdir = folder_of(video), review_dir(video)
    rows = list(csv.DictReader(open(folder / "plates_detailed.csv")))
    out = rdir / "text_sheets"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    cols, rows_per, tw, th = 4, 6, 320, 130
    per = cols * rows_per
    for s in range(0, len(rows), per):
        sheet = np.full((rows_per * (th + 24), cols * tw, 3), 30, np.uint8)
        for k, r in enumerate(rows[s:s + per]):
            crop = cv2.imread(str(folder / r["crop"]))
            if crop is None:
                continue
            sc = min(tw / crop.shape[1], th / crop.shape[0])
            crop = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
            rr, col = divmod(k, cols)
            oy, ox = rr * (th + 24) + 24, col * tw
            sheet[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
            ok = "ok" if r["indian_valid"] == "yes" else "x"
            cv2.putText(sheet, f"{s + k + 1}: {r['ocr_text'] or '-'} [{ok}]", (ox + 4, oy - 7), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imwrite(str(out / f"text_{s // per + 1:02d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    (out / "index.json").write_text(json.dumps([r["plate_id"] for r in rows]))
    print(f"{len(rows)} plates on {math.ceil(len(rows) / per)} text sheet(s) in {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["propose", "sheets", "decide", "apply", "textsheets"])
    parser.add_argument("video")
    parser.add_argument("spec", nargs="?", default="", help="for decide: e.g. 'p: 1-12,15 n: 13 u: 16'")
    args = parser.parse_args()
    if args.step == "decide":
        decide(args.video, args.spec)
    else:
        {"propose": propose, "sheets": sheets, "apply": apply, "textsheets": textsheets}[args.step](args.video)


if __name__ == "__main__":
    main()
