"""Evaluate a fine-tuned fast-plate-ocr model against the zero-shot pretrained reader on one split.

The test split may be evaluated exactly once per run directory: a lock file is written and re-runs refuse
(same rule as Track C's c_eval.py). Images are read with fast-plate-ocr's own training reader, so
preprocessing matches training exactly.

    KERAS_BACKEND=torch python eval_plate_ocr.py --run-dir ~/ml-assets/campus/runs/track_a/<run_id> \
        --model <run_dir>/<timestamp>/best.keras --split test
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("KERAS_BACKEND", "torch")

import numpy as np  # noqa: E402

try:
    from research_track.track_a.src.plate_normalizer import is_valid_indian_plate
except Exception:
    import re
    _STD_FMT = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")
    _BH_FMT = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")
    def is_valid_indian_plate(p: str) -> bool:
        return bool(_STD_FMT.match(p) or _BH_FMT.match(p))

CONFIGS = Path(__file__).resolve().parent / "configs"
FPO_MODELS = Path.home() / "ml-assets/campus/models/fast-plate-ocr"
PROVENANCE = "Kaggle avinash-6 (Apache-2.0) + kp00011 (MIT) held-out split, grouped by plate text; NOT PEC gate performance"


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p-value on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def score(gold: list[str], pred: list[str]) -> dict:
    exact = sum(g == p for g, p in zip(gold, pred))
    edits = sum(levenshtein(g, p) for g, p in zip(gold, pred))
    total_chars = sum(len(g) for g in gold)
    format_valid = sum(is_valid_indian_plate(p) for p in pred)
    n = len(gold)
    return {
        "n": n,
        "plate_accuracy": round(exact / n, 4) if n > 0 else 0.0,
        "plate_accuracy_95ci_wilson": wilson(exact, n),
        "cer": round(edits / max(1, total_chars), 4),
        "format_valid_rate": round(format_valid / n, 4) if n > 0 else 0.0,
        "within_one_edit": round(sum(levenshtein(g, p) <= 1 for g, p in zip(gold, pred)) / n, 4) if n > 0 else 0.0,
    }


def predict_finetuned(model_path: Path, plate_config_path: Path, paths: list[Path], batch: int = 256) -> list[str]:
    from fast_plate_ocr.core.process import read_and_resize_plate_image
    from fast_plate_ocr.train.model.config import load_plate_config_from_yaml
    from fast_plate_ocr.train.utilities.utils import load_keras_model

    cfg = load_plate_config_from_yaml(plate_config_path)
    model = load_keras_model(model_path, cfg)
    texts = []
    for i in range(0, len(paths), batch):
        x = np.stack([
            read_and_resize_plate_image(
                p, img_height=cfg.img_height, img_width=cfg.img_width, image_color_mode=cfg.image_color_mode,
                keep_aspect_ratio=cfg.keep_aspect_ratio, interpolation_method=cfg.interpolation,
                padding_color=cfg.padding_color,
            )
            for p in paths[i: i + batch]
        ])
        out = model.predict(x, verbose=0)
        out = out[0] if isinstance(out, (list, tuple)) else out.get("plate", out) if isinstance(out, dict) else out
        idx = np.asarray(out).reshape(len(x), cfg.max_plate_slots, cfg.vocabulary_size).argmax(-1)
        texts += ["".join(cfg.alphabet[j] for j in row).replace(cfg.pad_char, "") for row in idx]
    return texts


def predict_pretrained(onnx: Path, plate_config: Path, paths: list[Path]) -> list[str]:
    from fast_plate_ocr import LicensePlateRecognizer

    rec = LicensePlateRecognizer(onnx_model_path=onnx, plate_config_path=plate_config, device="cpu")
    texts = []
    for i in range(0, len(paths), 64):
        texts += [pred.plate.replace("_", "") for pred in rec.run([str(p) for p in paths[i: i + 64]])]
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True, help="fine-tuned best.keras")
    parser.add_argument("--plate-config", type=Path, default=CONFIGS / "in_plate_config_v1.yaml")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "ml-assets/campus/datasets/prepared/ocr_in_v1")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--baseline", default="global-v2/cct_s_v2_global", help="pretrained ONNX under models/fast-plate-ocr")
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir.is_dir():
        local_cand = Path(__file__).resolve().parents[3] / "data" / "datasets" / "prepared" / "ocr_in_v1"
        if local_cand.is_dir():
            data_dir = local_cand

    lock = args.run_dir / "TEST_EVALUATED.lock"
    if args.split == "test":
        if lock.exists():
            raise SystemExit(f"REFUSED: test split already evaluated once ({lock.read_text().strip()})")
        lock.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} model={args.model}\n")
    out_dir = args.run_dir / f"eval_{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / f"{args.split}.csv"
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    paths = [(csv_path.parent / r["image_path"]).resolve() for r in rows]
    gold = [r["plate_text"] for r in rows]

    t0 = time.time()
    preds = {"finetuned": predict_finetuned(args.model, args.plate_config, paths)}
    t1 = time.time()
    base = FPO_MODELS / args.baseline
    preds["pretrained_zero_shot"] = predict_pretrained(
        base.with_suffix(".onnx"), base.with_name(f"{base.name}_plate_config.yaml"), paths
    )

    metrics: dict = {"provenance": PROVENANCE, "split": args.split, "model": str(args.model), "models": {}}
    for name, pred in preds.items():
        by_source = defaultdict(lambda: ([], []))
        for r, g, p in zip(rows, gold, pred):
            by_source[r["source"]][0].append(g)
            by_source[r["source"]][1].append(p)
        metrics["models"][name] = {"all": score(gold, pred), **{s: score(*gp) for s, gp in sorted(by_source.items())}}
    ft_right = [g == p for g, p in zip(gold, preds["finetuned"])]
    base_right = [g == p for g, p in zip(gold, preds["pretrained_zero_shot"])]
    b = sum(f and not z for f, z in zip(ft_right, base_right))
    c = sum(z and not f for f, z in zip(ft_right, base_right))
    metrics["paired_vs_zero_shot"] = {"finetuned_only_right": b, "zero_shot_only_right": c, "mcnemar_exact_p": mcnemar_exact(b, c)}
    metrics["finetuned_inference_seconds"] = round(t1 - t0, 1)

    with (out_dir / "predictions.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_path", "source", "gold", *preds])
        for r, p, g, *ps in zip(rows, paths, gold, *preds.values()):
            writer.writerow([str(p), r["source"], g, *ps])
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v["all"] for k, v in metrics["models"].items()} | {"paired": metrics["paired_vs_zero_shot"]}, indent=2))


if __name__ == "__main__":
    main()
