"""Evaluate on GOLD only. GOLD integrity (every file against its frozen SHA-256) is checked first.

Detection: precision / recall at the operating threshold (IoU 0.5), mAP50 and mAP50-95 (Ultralytics' matching
and AP code, so the numbers are comparable with `yolo val`), image-level slices (value = mAP50; a slice's n is its
number of GOLD plates) and bootstrap 95% CIs over images.
OCR: exact match and character error rate on the OCR GOLD crops, with slices by format, state, layout, source.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from anpr_hitl.config import Config, OcrConfig
from anpr_hitl.hashing import sha256_file
from anpr_hitl.labels import read_yolo_labels, yolo_to_xyxy
from anpr_hitl.manifest import read_manifest
from anpr_hitl.plates import check_plate
from anpr_hitl.store import Store, atomic_write_json, read_json

IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)
EVAL_CONF = 0.001          # mAP integrates over all confidences, as `yolo val` does
SMALL_PLATE_PX = 24        # an image whose smallest plate is shorter than this (native pixels) is in det:small
MANY_PLATES = 3
TWO_LINE_MAX_ASPECT = 2.2  # width / height of a two-row plate crop is about 1.5-2


class GoldIntegrityError(RuntimeError):
    pass


# ---------------------------------------------------------------- GOLD

def verify_gold(store: Store) -> dict:
    """Re-hash every GOLD image, label and crop against its manifest; raise on any difference."""
    det_dir, ocr_dir = store.gold_dir / "det", store.gold_dir / "ocr"
    det_meta, ocr_meta = read_json(det_dir / "gold.json"), read_json(ocr_dir / "gold.json")
    if not det_meta or not ocr_meta:
        raise GoldIntegrityError("GOLD is missing (run `anpr bootstrap-data`)")
    problems = []
    det_rows = read_manifest(det_dir / "manifest.jsonl")
    for row in det_rows:
        image = store.root / row["path"]
        label = det_dir / "labels" / f"{row['image_id']}.txt"
        if not image.is_file() or sha256_file(image) != row["sha256"]:
            problems.append(f"det image {row['image_id']} missing or modified")
        if not label.is_file() or sha256_file(label) != row["label_sha256"]:
            problems.append(f"det label {row['image_id']} missing or modified")
    ocr_rows = read_manifest(ocr_dir / "manifest.jsonl")
    for row in ocr_rows:
        crop = store.root / row["path"]
        if not crop.is_file() or sha256_file(crop) != row["sha256"]:
            problems.append(f"OCR crop {row['crop_id']} missing or modified")
    from anpr_hitl.manifest import manifest_hash

    if manifest_hash(det_rows) != det_meta["manifest_sha256"]:
        problems.append("det manifest does not match gold.json")
    if manifest_hash(ocr_rows) != ocr_meta["manifest_sha256"]:
        problems.append("OCR manifest does not match gold.json")
    extra = {p.name for p in (det_dir / "images").iterdir()} - {Path(r["path"]).name for r in det_rows}
    if extra:
        problems.append(f"{len(extra)} unlisted files in GOLD images/")
    if problems:
        raise GoldIntegrityError(f"{len(problems)} GOLD problems, e.g. {problems[:3]}")
    combined = hashlib.sha256(f"{det_meta['manifest_sha256']}:{ocr_meta['manifest_sha256']}".encode()).hexdigest()
    return {"gold_manifest_sha256": combined, "det_manifest_sha256": det_meta["manifest_sha256"],
            "ocr_manifest_sha256": ocr_meta["manifest_sha256"], "det_images": len(det_rows), "ocr_crops": len(ocr_rows)}


# ---------------------------------------------------------------- detection

def box_iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(len(a), len(b)) IoU for xyxy boxes."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    tl = np.maximum(a[:, None, :2], b[None, :, :2])
    br = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(br - tl, 0, None).prod(-1)
    area_a = (a[:, 2:] - a[:, :2]).prod(-1)
    area_b = (b[:, 2:] - b[:, :2]).prod(-1)
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def match_predictions(gt: np.ndarray, pred: np.ndarray, iouv: np.ndarray = IOU_THRESHOLDS) -> np.ndarray:
    """(len(pred), len(iouv)) true-positive matrix; the same greedy IoU matching as Ultralytics' validator."""
    correct = np.zeros((len(pred), len(iouv)), dtype=bool)
    iou = box_iou_matrix(gt, pred)  # rows: labels, columns: predictions
    for i, threshold in enumerate(iouv):
        matches = np.array(np.nonzero(iou >= threshold)).T
        if matches.shape[0]:
            if matches.shape[0] > 1:
                matches = matches[iou[matches[:, 0], matches[:, 1]].argsort()[::-1]]
                matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
                matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
            correct[matches[:, 1].astype(int), i] = True
    return correct


def det_metrics(tp: np.ndarray, conf: np.ndarray, n_gt: int, op_conf: float) -> dict:
    """mAP50 / mAP50-95 over all confidences; precision / recall at op_conf and IoU 0.5."""
    from ultralytics.utils.metrics import ap_per_class

    if n_gt == 0:
        return {"map50": None, "map50_95": None, "precision": None, "recall": None, "n": 0}
    if len(conf) == 0:
        return {"map50": 0.0, "map50_95": 0.0, "precision": 0.0, "recall": 0.0, "n": n_gt}
    ap = ap_per_class(tp, conf, np.zeros(len(conf)), np.zeros(n_gt))[5]
    at_op = conf >= op_conf
    tp50 = int(tp[at_op, 0].sum())
    return {"map50": float(ap[0, 0]), "map50_95": float(ap[0].mean()),
            "precision": tp50 / max(int(at_op.sum()), 1), "recall": tp50 / n_gt, "n": n_gt}


class DetEval:
    """Per-image matches for one model on det GOLD (kept for slices and paired bootstrap)."""

    def __init__(self, image_ids: list[str], tp: list[np.ndarray], conf: list[np.ndarray], n_gt: list[int],
                 attrs: list[dict]):
        self.image_ids, self.tp, self.conf, self.n_gt, self.attrs = image_ids, tp, conf, n_gt, attrs

    def metrics(self, idx=None, op_conf: float = 0.25) -> dict:
        idx = range(len(self.image_ids)) if idx is None else idx
        tp = [self.tp[i] for i in idx]
        conf = [self.conf[i] for i in idx]
        return det_metrics(np.concatenate(tp) if tp else np.zeros((0, 10), bool),
                           np.concatenate(conf) if conf else np.zeros(0), sum(self.n_gt[i] for i in idx), op_conf)

    def save(self, path: Path) -> None:
        lengths = np.array([len(c) for c in self.conf])
        np.savez_compressed(path, image_ids=np.array(self.image_ids), lengths=lengths,
                            tp=np.concatenate(self.tp) if self.tp else np.zeros((0, 10), bool),
                            conf=np.concatenate(self.conf) if self.conf else np.zeros(0), n_gt=np.array(self.n_gt),
                            attrs=np.array([json.dumps(a, sort_keys=True) for a in self.attrs]))

    @classmethod
    def load(cls, path: Path) -> "DetEval":
        z = np.load(path, allow_pickle=False)
        splits = np.cumsum(z["lengths"])[:-1]
        return cls([str(s) for s in z["image_ids"]], np.split(z["tp"], splits), np.split(z["conf"], splits),
                   [int(n) for n in z["n_gt"]], [json.loads(a) for a in z["attrs"]])


def _gold_det_items(store: Store) -> list[dict]:
    det_dir = store.gold_dir / "det"
    items = []
    for row in sorted(read_manifest(det_dir / "manifest.jsonl"), key=lambda r: r["image_id"]):
        path = store.root / row["path"]
        with Image.open(path) as img:
            w, h = img.size
            luma = float(np.asarray(img.convert("L").resize((64, 64))).mean())
        gt = np.array([yolo_to_xyxy(cx, cy, bw, bh, w, h)
                       for _, cx, cy, bw, bh in read_yolo_labels(det_dir / "labels" / f"{row['image_id']}.txt")])
        items.append({"image_id": row["image_id"], "path": path, "gt": gt.reshape(-1, 4), "source": row["source"],
                      "luma": luma, "min_plate_h": float((gt[:, 3] - gt[:, 1]).min()) if len(gt) else None})
    return items


def predict_boxes(weights: Path, paths: list[Path], imgsz: int, conf: float, device, batch: int = 8):
    """xyxy boxes and confidences per image (original pixel coordinates)."""
    from anpr_hitl.yolo import YOLO

    model = YOLO(str(weights))
    out = []
    for start in range(0, len(paths), batch):
        chunk = [str(p) for p in paths[start:start + batch]]
        for r in model.predict(chunk, imgsz=imgsz, conf=conf, iou=0.7, max_det=300, device=device, verbose=False):
            b = r.boxes.cpu().numpy()
            out.append((b.xyxy.astype(np.float64), b.conf.astype(np.float64)))
    return out


def evaluate_detector(weights: Path, store: Store, cfg: Config, imgsz: int | None = None) -> DetEval:
    items = _gold_det_items(store)
    preds = predict_boxes(weights, [it["path"] for it in items], imgsz or cfg.evaluate.imgsz, EVAL_CONF,
                          cfg.predict.device)
    tps, confs, attrs = [], [], []
    for it, (boxes, conf) in zip(items, preds, strict=True):
        order = np.argsort(-conf)
        boxes, conf = boxes[order], conf[order]
        tps.append(match_predictions(it["gt"], boxes))
        confs.append(conf)
        attrs.append({"source": it["source"], "luma": round(it["luma"], 2), "min_plate_h": it["min_plate_h"]})
    return DetEval([it["image_id"] for it in items], tps, confs, [len(it["gt"]) for it in items], attrs)


def det_slices(ev: DetEval, cfg: Config) -> dict[str, list[int]]:
    slices = defaultdict(list)
    for i, a in enumerate(ev.attrs):
        slices["det:night" if a["luma"] < cfg.select.night_max_luma else "det:day"].append(i)
        slices[f"det:source={a['source']}"].append(i)
        if a["min_plate_h"] is not None and a["min_plate_h"] < SMALL_PLATE_PX:
            slices["det:small_plates"].append(i)
        if ev.n_gt[i] >= MANY_PLATES:
            slices["det:many_plates"].append(i)
        if ev.n_gt[i] == 0:
            slices["det:no_plates"].append(i)
    return dict(slices)


def bootstrap_det(ev: DetEval, n_boot: int, seed: int, op_conf: float, other: DetEval | None = None) -> dict:
    """95% percentile CIs over images for mAP50 / mAP50-95; with `other`, CIs of (ev - other) in points."""
    if n_boot == 0:
        return {}
    rng = np.random.default_rng(seed)
    n = len(ev.image_ids)
    keys = ("map50", "map50_95")
    samples = {k: [] for k in keys}
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        m = ev.metrics(idx, op_conf)
        if other is None:
            for k in keys:
                samples[k].append(m[k])
        else:
            o = other.metrics(idx, op_conf)
            for k in keys:
                samples[k].append((m[k] - o[k]) * 100)
    return {k: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]
            for k, v in samples.items()}


# ---------------------------------------------------------------- OCR

def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def ocr_metrics(rows: list[dict]) -> dict:
    """rows: {'text': truth, 'pred': read}. Exact match rate and corpus CER (edits / truth characters)."""
    if not rows:
        return {"exact": None, "cer": None, "n": 0}
    exact = sum(r["pred"] == r["text"] for r in rows) / len(rows)
    edits = sum(levenshtein(r["pred"], r["text"]) for r in rows)
    return {"exact": exact, "cer": edits / max(sum(len(r["text"]) for r in rows), 1), "n": len(rows)}


def ocr_slices(rows: list[dict]) -> dict[str, list[int]]:
    slices = defaultdict(list)
    for i, r in enumerate(rows):
        check = check_plate(r["text"])
        slices[f"ocr:format={check.format or 'nonstandard'}"].append(i)
        if check.format == "standard":
            slices[f"ocr:state={check.state}"].append(i)
        slices[f"ocr:source={r['source']}"].append(i)
        slices["ocr:two_line" if r["aspect"] < TWO_LINE_MAX_ASPECT else "ocr:one_line"].append(i)
    return dict(slices)


def run_ocr(rows: list[dict], root: Path, ocr_cfg: OcrConfig, with_fallback: bool = False) -> tuple[list[dict], float]:
    """Read every crop. with_fallback=False reads with the primary engine alone (engine comparisons);
    True runs the configured pipeline (primary + fallback), as predictions do. Returns rows + ms per crop."""
    import cv2

    from anpr_hitl.ocr import get_reader, read_plate

    reader = get_reader(ocr_cfg)
    out, started = [], time.time()
    for r in rows:
        img = cv2.imread(str(root / r["path"]))
        read = read_plate(img, ocr_cfg) if with_fallback else reader.read(img)
        out.append({"crop_id": r["crop_id"], "text": r["text"], "pred": read.text, "conf": round(read.conf, 4),
                    "source": r["source"], "aspect": round(img.shape[1] / img.shape[0], 3)})
    return out, (time.time() - started) * 1000 / max(len(rows), 1)


def bootstrap_ocr(rows: list[dict], n_boot: int, seed: int) -> dict:
    if n_boot == 0 or not rows:
        return {}
    rng = np.random.default_rng(seed)
    hit = np.array([r["pred"] == r["text"] for r in rows], dtype=float)
    means = [hit[rng.integers(0, len(hit), len(hit))].mean() for _ in range(n_boot)]
    return {"exact": [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]}


# ---------------------------------------------------------------- model-level

def _slice_table(index: dict[str, list[int]], value_fn) -> dict:
    return {name: {"n": n, "value": v} for name, idx in sorted(index.items())
            for n, v in [value_fn(idx)] if v is not None}


def evaluate_model(weights: Path, store: Store, cfg: Config, out_dir: Path, imgsz: int | None = None) -> dict:
    """GOLD metrics for a detector + the configured OCR engine; writes metrics.json and det_eval.npz to out_dir."""
    gold = verify_gold(store)
    out_dir.mkdir(parents=True, exist_ok=True)
    op = cfg.evaluate.conf
    det = evaluate_detector(weights, store, cfg, imgsz)
    det.save(out_dir / "det_eval.npz")
    det_all = det.metrics(op_conf=op)
    det_index = det_slices(det, cfg)

    def det_value(idx):
        m = det.metrics(idx, op)
        return m["n"], m["map50"]

    ocr = evaluate_ocr_gold(store, cfg)
    ocr_rows = ocr.pop("rows")
    ocr_index = ocr_slices(ocr_rows)

    def ocr_value(idx):
        m = ocr_metrics([ocr_rows[i] for i in idx])
        return m["n"], m["exact"]

    metrics = {
        **gold, "weights_sha256": sha256_file(weights), "imgsz": imgsz or cfg.evaluate.imgsz, "op_conf": op,
        "detection": {**{k: round(v, 5) if isinstance(v, float) else v for k, v in det_all.items()},
                      "images": len(det.image_ids),
                      "ci95": bootstrap_det(det, cfg.evaluate.bootstrap, cfg.seed, op)},
        "ocr": {k: v for k, v in ocr.items()},
        "slices": {**_slice_table(det_index, det_value), **_slice_table(ocr_index, ocr_value)},
        "slice_metric": {"det": "mAP50", "ocr": "exact"},
    }
    atomic_write_json(out_dir / "metrics.json", metrics)
    return metrics


def ocr_config_hash(cfg: Config) -> str:
    return hashlib.sha256(cfg.ocr.model_dump_json().encode()).hexdigest()[:16]


def evaluate_ocr_gold(store: Store, cfg: Config) -> dict:
    """OCR GOLD metrics for the configured engine; cached per OCR-config hash (crops do not change)."""
    ocr_cfg_hash = ocr_config_hash(cfg)
    gold_rows = read_manifest(store.gold_dir / "ocr" / "manifest.jsonl")
    cache = store.root / "evals" / "ocr" / f"gold_{ocr_cfg_hash}.json"
    cached = read_json(cache)
    if cached is None:
        rows, ms = run_ocr(gold_rows, store.root, cfg.ocr, with_fallback=True)
        cached = {"engine": cfg.ocr.engine, "ocr_config": cfg.ocr.model_dump(), "ms_per_crop": round(ms, 1),
                  "rows": rows}
        atomic_write_json(cache, cached)
    rows = cached["rows"]
    m = ocr_metrics(rows)
    return {"exact": round(m["exact"], 5), "cer": round(m["cer"], 5), "n": m["n"], "engine": cached["engine"],
            "ocr_config_sha256": ocr_cfg_hash, "ci95": bootstrap_ocr(rows, cfg.evaluate.bootstrap, cfg.seed),
            "rows": rows}


OCR_VARIANTS = {
    "rapidocr-v4-en-mobile": {"engine": "rapidocr", "rapidocr_version": "PP-OCRv4", "rapidocr_rec_lang": "en",
                              "rapidocr_rec_model_type": "mobile"},
    "rapidocr-v6-ch-small": {"engine": "rapidocr", "rapidocr_version": "PP-OCRv6", "rapidocr_rec_lang": "ch",
                             "rapidocr_rec_model_type": "small"},
    "tesseract": {"engine": "tesseract"},
    "fast-plate-ocr": {"engine": "fast_plate_ocr"},
}


def benchmark_ocr(store: Store, cfg: Config, variants: list[str], dataset: str = "dev") -> list[dict]:
    """Compare OCR engines on the OCR dev set (never on GOLD, which would bias later GOLD numbers)."""
    if dataset != "dev":
        raise ValueError("engines are compared on the dev set only")
    rows = read_manifest(store.bootstrap_dir / "ocr_dev" / "manifest.jsonl")
    if not rows:
        raise FileNotFoundError("OCR dev set missing (run `anpr bootstrap-data --ocr-dev`)")
    results = []
    for name in variants:
        ocr_cfg = cfg.ocr.model_copy(update={**OCR_VARIANTS[name], "fallback": "none"})
        out, ms = run_ocr(rows, store.root, ocr_cfg)
        m = ocr_metrics(out)
        fmt = ocr_metrics([r for r in out if check_plate(r["text"]).regex_valid])
        two = ocr_metrics([r for r in out if r["aspect"] < TWO_LINE_MAX_ASPECT])
        results.append({"variant": name, "n": m["n"], "exact": round(m["exact"], 4), "cer": round(m["cer"], 4),
                        "exact_standard_format": round(fmt["exact"], 4) if fmt["n"] else None,
                        "exact_two_line": round(two["exact"], 4) if two["n"] else None, "two_line_n": two["n"],
                        "ms_per_crop": round(ms, 1),
                        "ci95": bootstrap_ocr(out, cfg.evaluate.bootstrap, cfg.seed)["exact"]})
    atomic_write_json(store.root / "evals" / "ocr" / "dev_benchmark.json", results)
    return results
