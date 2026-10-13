"""Evaluate plate detectors on one split of the prepared detector set, new model vs baseline.

Reports Ultralytics P/R/mAP plus per-source precision/recall at IoU 0.5 (conf >= 0.25) with image-level
bootstrap 95% CIs. The test split may be evaluated exactly once per run directory (TEST_EVALUATED.lock).

    python eval_plate_detector.py --run-dir <run> --model <run>/full/weights/best.pt --split test \
        --baseline ~/ml-assets/campus/runs/track_a/20261009_detector_full/plate_detector_smoke/weights/best.pt
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

PROVENANCE = "Merged licence-cleared Indian plate sets (CC0/CC BY 4.0/Apache-2.0), grouped split; NOT PEC gate performance"


def iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(gt: list, pred: list, thr: float = 0.5) -> tuple[int, int, int]:
    """Greedy one-to-one matching by confidence. Returns (tp, fp, fn)."""
    used, tp = set(), 0
    for box in sorted(pred, key=lambda p: -p[4]):
        best = max(((iou(box, g), j) for j, g in enumerate(gt) if j not in used), default=(0.0, None))
        if best[0] >= thr:
            used.add(best[1])
            tp += 1
    return tp, len(pred) - tp, len(gt) - tp


def bootstrap(per_image: list[tuple[int, int, int]], n_boot: int = 2000, seed: int = 42) -> dict:
    rng = random.Random(seed)

    def pr(sample):
        tp, fp, fn = (sum(x[i] for x in sample) for i in range(3))
        return tp / max(1, tp + fp), tp / max(1, tp + fn)

    p, r = pr(per_image)
    boots = [pr([rng.choice(per_image) for _ in per_image]) for _ in range(n_boot)]
    ps, rs = sorted(b[0] for b in boots), sorted(b[1] for b in boots)
    lo, hi = int(0.025 * n_boot), int(0.975 * n_boot) - 1
    return {"precision": round(p, 4), "precision_95ci": [round(ps[lo], 4), round(ps[hi], 4)],
            "recall": round(r, 4), "recall_95ci": [round(rs[lo], 4), round(rs[hi], 4)], "images": len(per_image)}


def evaluate(weights: Path, data: Path, split: str, out_dir: Path) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    val = model.val(data=str(data / "data.yaml"), split=split, imgsz=640, batch=16, device=0, plots=False,
                    project=str(out_dir), name=weights.parent.parent.name, exist_ok=True, verbose=False)
    images = sorted((data / "images" / split).iterdir())
    per_source = defaultdict(list)
    for result in model.predict([str(p) for p in images], imgsz=640, conf=0.25, device=0, verbose=False, stream=True):
        path = Path(result.path)
        h, w = result.orig_shape
        gt = []
        for line in (data / "labels" / split / f"{path.stem}.txt").read_text().splitlines():
            _, cx, cy, bw, bh = (float(v) for v in line.split())
            gt.append(((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
        pred = [(*b.xyxy[0].tolist(), float(b.conf)) for b in result.boxes]
        counts = match(gt, pred)
        per_source[path.name.split("__")[0]].append(counts)
        per_source["all"].append(counts)
    return {
        "ultralytics": {"precision": round(float(val.box.mp), 4), "recall": round(float(val.box.mr), 4),
                        "mAP50": round(float(val.box.map50), 4), "mAP50_95": round(float(val.box.map), 4)},
        "iou50_conf25": {s: bootstrap(v) for s, v in sorted(per_source.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path.home() / "ml-assets/campus/datasets/prepared/plate_det_in_v1")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    args = parser.parse_args()

    lock = args.run_dir / "TEST_EVALUATED.lock"
    if args.split == "test":
        if lock.exists():
            raise SystemExit(f"REFUSED: test split already evaluated once ({lock.read_text().strip()})")
        lock.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} model={args.model}\n")
    out_dir = args.run_dir / f"eval_{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = {"provenance": PROVENANCE, "split": args.split,
               "new": {"weights": str(args.model), **evaluate(args.model, args.data, args.split, out_dir)},
               "baseline": {"weights": str(args.baseline), **evaluate(args.baseline, args.data, args.split, out_dir)}}
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    for name in ("new", "baseline"):
        print(name, json.dumps(metrics[name]["ultralytics"]), json.dumps(metrics[name]["iou50_conf25"]["all"]))


if __name__ == "__main__":
    main()
