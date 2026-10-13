"""Track A: zero-shot pretrained plate readers on IN-02 plate crops (no training).

Models compared (all pretrained, none fine-tuned here):
  - lprnet_indian: Indian_LPR best_lprnet.pth (repo has no LICENSE -> local research eval only)
  - cct_s_v2_global: fast-plate-ocr global CCT-S v2 ONNX (MIT; India not in its training regions)
  - mobilevit_v2_european: fast-plate-ocr legacy european ONNX (MIT; 9 slots)

IN-02 has NO plate-text ground truth, so this script reports PROXY signals only:
Indian-format validity, valid state code, and cross-model agreement. These are not accuracy.
CPU only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import random
import re
import sys
import time
from importlib import metadata
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

ASSETS = Path.home() / "ml-assets/campus"
LPR_REPO = ASSETS / "code/Indian_LPR"
FPO_MODELS = ASSETS / "models/fast-plate-ocr"
LPR_CHARS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["-"]  # last = CTC blank, as in load_data.CHARS
STATES = set(
    "AN AP AR AS BR CH CG DD DL DN GA GJ HR HP JK JH KA KL LA LD MP MH MN ML MZ NL OD OR PY PB RJ SK TN TS TG TR UP UK UA WB".split()
)
STD_RE = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$")
BH_RE = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")
PROVENANCE = "IN-02 Kaggle CC0 plate crops, NO text ground truth; proxy signals only, NOT accuracy and NOT PEC gate performance"


def indian_format(text: str) -> tuple[bool, bool]:
    if BH_RE.match(text):
        return True, True
    m = STD_RE.match(text)
    return bool(m), bool(m and m.group(1) in STATES)


def load_lprnet():
    import torch

    spec = importlib.util.spec_from_file_location("lprnet_model", LPR_REPO / "src/License_Plate_Recognition/model/LPRNet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    net = mod.build_lprnet(lpr_max_len=16, class_num=len(LPR_CHARS)).eval()
    net.load_state_dict(torch.load(LPR_REPO / "weights/best_lprnet.pth", map_location="cpu"))
    return net


def lprnet_predict(net, paths: list[Path], bs: int = 64) -> list[str]:
    import torch

    blank = len(LPR_CHARS) - 1
    out: list[str] = []
    for i in range(0, len(paths), bs):
        ims = []
        for p in paths[i : i + bs]:
            im = cv2.resize(cv2.imread(str(p)), (94, 24)).astype("float32")  # BGR, as in infer_objectdet.py
            ims.append(np.transpose((im - 127.5) * 0.0078125, (2, 0, 1)))
        with torch.no_grad():
            logits = net(torch.from_numpy(np.ascontiguousarray(np.stack(ims)))).numpy()
        for seq in logits.argmax(axis=1):
            chars, prev = [], blank
            for c in seq:
                if c != blank and c != prev:
                    chars.append(LPR_CHARS[c])
                prev = c
            out.append("".join(chars))
    return out


def fpo_predict(onnx: Path, cfg: Path, paths: list[Path]) -> tuple[list[str], list[float]]:
    from fast_plate_ocr import LicensePlateRecognizer

    rec = LicensePlateRecognizer(onnx_model_path=onnx, plate_config_path=cfg, device="cpu")
    texts, confs = [], []
    for i in range(0, len(paths), 64):
        for pred in rec.run([str(p) for p in paths[i : i + 64]], return_confidence=True):
            texts.append(pred.plate)
            confs.append(float(np.mean(pred.char_probs)) if pred.char_probs is not None else float("nan"))
    return texts, confs


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crops", type=Path, default=ASSETS / "datasets/IN-02/extracted")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = all labelled PNG crops")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if "/ml-assets/campus/runs/" not in str(args.run_dir.resolve()):
        raise SystemExit("run-dir must be under ~/ml-assets/campus/runs/")
    args.run_dir.mkdir(parents=True, exist_ok=True)

    # Labelled PNGs only: these are single pre-cropped plates (YOLO box ~ whole image).
    paths = sorted(p for p in (args.crops / "images").glob("*.png") if (args.crops / "labels" / f"{p.stem}.txt").is_file())
    if args.limit:
        paths = random.Random(args.seed).sample(paths, args.limit)
    t0 = time.time()

    models = {
        "lprnet_indian": (lprnet_predict(load_lprnet(), paths), None),
        "cct_s_v2_global": fpo_predict(
            FPO_MODELS / "global-v2/cct_s_v2_global.onnx", FPO_MODELS / "global-v2/cct_s_v2_global_plate_config.yaml", paths
        ),
        "mobilevit_v2_european": fpo_predict(
            FPO_MODELS / "european_mobile_vit_v2_ocr.onnx", FPO_MODELS / "european_mobile_vit_v2_ocr_config.yaml", paths
        ),
    }

    rows = []
    for i, p in enumerate(paths):
        row = {"image": p.name}
        for name, (texts, confs) in models.items():
            row[name] = texts[i]
            row[f"{name}_conf"] = "" if confs is None else round(confs[i], 4)
        rows.append(row)
    with open(args.run_dir / "predictions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    n = len(paths)
    summary = {"provenance_label": PROVENANCE, "n_crops": n, "models": {}}
    for name, (texts, confs) in models.items():
        fmt = [indian_format(t) for t in texts]
        summary["models"][name] = {
            "indian_format_valid_rate": round(sum(a for a, _ in fmt) / n, 4),
            "valid_state_code_rate": round(sum(b for _, b in fmt) / n, 4),
            "empty_rate": round(sum(not t for t in texts) / n, 4),
            "mean_len": round(float(np.mean([len(t) for t in texts])), 2),
            "mean_char_conf": None if confs is None else round(float(np.nanmean(confs)), 4),
        }
    names = list(models)
    summary["pairwise_exact_agreement"] = {
        f"{a}|{b}": round(sum(models[a][0][i] == models[b][0][i] for i in range(n)) / n, 4)
        for ai, a in enumerate(names)
        for b in names[ai + 1 :]
    }
    summary["elapsed_s"] = round(time.time() - t0, 1)
    (args.run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Contact sheet: 24 random crops with all three predictions, for visual inspection.
    rng = random.Random(args.seed)
    pick = rng.sample(range(n), min(24, n))
    tiles = []
    for i in pick:
        im = cv2.imread(str(paths[i]))
        im = cv2.resize(im, (300, int(300 * im.shape[0] / im.shape[1])))[:110]
        tile = np.full((200, 300, 3), 255, np.uint8)
        tile[: im.shape[0]] = im
        for k, name in enumerate(names):
            cv2.putText(tile, f"{name[:6]}: {models[name][0][i]}", (4, 135 + 22 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        tiles.append(tile)
    while len(tiles) % 4:
        tiles.append(np.full((200, 300, 3), 255, np.uint8))
    sheet = np.vstack([np.hstack(tiles[r : r + 4]) for r in range(0, len(tiles), 4)])
    cv2.imwrite(str(args.run_dir / "contact_sheet.jpg"), sheet)
    (args.run_dir / "contact_sheet_index.json").write_text(json.dumps([paths[i].name for i in pick]))

    manifest = {
        "script": "a_pretrained_zeroshot.py",
        "seed": args.seed,
        "data_hash": hashlib.sha256("\n".join(p.name for p in paths).encode()).hexdigest(),
        "model_sha256": {
            "best_lprnet.pth": sha256(LPR_REPO / "weights/best_lprnet.pth"),
            "cct_s_v2_global.onnx": sha256(FPO_MODELS / "global-v2/cct_s_v2_global.onnx"),
            "european_mobile_vit_v2_ocr.onnx": sha256(FPO_MODELS / "european_mobile_vit_v2_ocr.onnx"),
        },
        "library_versions": {k: metadata.version(k) for k in ("torch", "onnxruntime", "fast-plate-ocr", "opencv-python-headless")},
        "git_sha": None,
        "python": sys.version.split()[0],
        "device": "cpu",
    }
    (args.run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
