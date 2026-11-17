"""Export a registered model for deployment and check that the exports behave like the .pt.

Frigate 0.18 (read from the local image's source, frigate/util/model.py and detectors/plugins/openvino.py):
  * `model_type: yolo-generic` decodes ONE output shaped (1, 4 + classes, anchors) = cx, cy, w, h, class scores
    in input pixels, keeps scores >= 0.4 (hard-coded), runs NMS at IoU 0.4 and returns at most 20 boxes.
    So the export carries the raw head (Ultralytics' default `nms=None`); an end-to-end (NMS-free) export would
    be decoded wrongly.
  * Inputs: width = height = export.imgsz, `input_tensor: nchw`, `input_dtype: float` (Frigate divides by 255),
    `input_pixel_format: rgb`.
  * `license_plate` is an attribute label: Frigate attaches it to car / motorcycle / bus / truck objects, or
    tracks it directly on a dedicated LPR camera (`type: lpr`). Frigate runs one detector model for every camera,
    so a plate-only model fits only an instance whose cameras are all dedicated LPR cameras.
Checks:
  * parity on GOLD at the deployment size: each .pt box (conf >= predict.conf) must have an export box at
    IoU >= parity_iou with |conf difference| <= parity_max_conf_drift, and vice versa;
  * Frigate decoding: the ONNX output is decoded the way Frigate does and compared with the .pt;
  * GOLD accuracy of the .pt at the deployment size (versus the training size).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from anpr_hitl.config import Config
from anpr_hitl.evaluate import box_iou_matrix, evaluate_detector
from anpr_hitl.hashing import sha256_file
from anpr_hitl.manifest import read_manifest
from anpr_hitl.store import Store, atomic_write_json, atomic_write_text

FRIGATE_SCORE, FRIGATE_NMS, FRIGATE_MAX = 0.4, 0.4, 20


def frigate_decode(output: np.ndarray, width: int, height: int) -> np.ndarray:
    """Frigate 0.18's single-output yolo-generic decoder: rows of (class, score, y1, x1, y2, x2), coords 0..1."""
    pred = np.squeeze(output)
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T
    scores = pred[:, 4:].max(axis=1)
    keep = scores > FRIGATE_SCORE
    pred, scores = pred[keep], scores[keep]
    classes = pred[:, 4:].argmax(axis=1)
    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    out = np.zeros((FRIGATE_MAX, 6), np.float32)
    if len(xyxy):
        xywh = [[float(a), float(b), float(c - a), float(d - b)] for a, b, c, d in xyxy]
        idx = cv2.dnn.NMSBoxes(xywh, scores.tolist(), FRIGATE_SCORE, FRIGATE_NMS)
        for i, j in enumerate(np.asarray(idx).flatten()[:FRIGATE_MAX]):
            x1, y1, x2, y2 = xyxy[j]
            out[i] = [classes[j], scores[j], y1 / height, x1 / width, y2 / height, x2 / width]
    return out


def match_sets(a_boxes, a_conf, b_boxes, b_conf, min_iou: float, max_drift: float) -> dict:
    """Greedy one-to-one matching of two detection sets; counts matches that also agree on confidence."""
    iou = box_iou_matrix(np.asarray(a_boxes).reshape(-1, 4), np.asarray(b_boxes).reshape(-1, 4))
    pairs = sorted(((iou[i, j], i, j) for i in range(iou.shape[0]) for j in range(iou.shape[1]) if iou[i, j] >= min_iou),
                   reverse=True)
    used_a, used_b, drifts = set(), set(), []
    for _, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        drifts.append(abs(float(a_conf[i]) - float(b_conf[j])))
    ok = sum(d <= max_drift for d in drifts)
    return {"a": len(a_conf), "b": len(b_conf), "matched": len(drifts), "matched_within_drift": ok,
            "max_drift": round(max(drifts), 4) if drifts else 0.0}


def _square(img: np.ndarray, size: int) -> np.ndarray:
    """A Frigate-like detector input: the region resized to size x size (Frigate's regions are square)."""
    h, w = img.shape[:2]
    side = max(h, w)
    canvas = np.full((side, side, 3), 114, np.uint8)
    canvas[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = img
    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_LINEAR)


EXPORT_SCRIPT = """
import sys
from openvino_telemetry.utils.opt_in_checker import ConsentCheckResult, OptInChecker
OptInChecker().update_result(ConsentCheckResult.DECLINED)
from anpr_hitl.yolo import YOLO
print(YOLO(sys.argv[1]).export(format=sys.argv[2], imgsz=int(sys.argv[3]), dynamic=False, simplify=True, device="cpu"))
"""


def export_isolated(pt: Path, fmt: str, imgsz: int, home: Path) -> Path:
    """Export in a child process whose HOME is a private folder holding a declined OpenVINO telemetry consent:
    OpenVINO counts a missing consent file as consent, and the user's real home directory stays untouched."""
    home.mkdir(parents=True, exist_ok=True)
    res = subprocess.run([sys.executable, "-c", EXPORT_SCRIPT, str(pt), fmt, str(imgsz)],
                         env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{fmt} export failed:\n{res.stderr[-3000:]}")
    return Path(res.stdout.strip().splitlines()[-1])


def _hash_export(path: Path) -> dict | str:
    """SHA-256 of an exported file, or of every file in an exported directory (OpenVINO: .xml + .bin)."""
    if path.is_dir():
        return {f.name: sha256_file(f) for f in sorted(path.iterdir()) if f.is_file()}
    return sha256_file(path)


def frigate_config_snippet(version: str, imgsz: int, fmt: str) -> str:
    path = f"/config/model_cache/anpr_hitl/{version}/" + ("best.onnx" if fmt == "onnx" else "best_openvino_model/best.xml")
    return f"""# Frigate 0.18 detector config for {version} (NOT applied automatically; review before use).
# A plate-only model: every camera of this Frigate instance must be a dedicated LPR camera.
detectors:
  {"ov" if fmt == "openvino" else "onnx"}:
    type: {"openvino" if fmt == "openvino" else "onnx"}{chr(10) + "    device: GPU" if fmt == "openvino" else ""}
model:
  model_type: yolo-generic
  width: {imgsz}
  height: {imgsz}
  input_tensor: nchw
  input_dtype: float
  input_pixel_format: rgb
  path: {path}
  labelmap_path: /config/model_cache/anpr_hitl/labelmap.txt
cameras:
  gate_lpr:            # example name
    type: lpr
    objects:
      track: [license_plate]
    lpr:
      enabled: true
# Frigate keeps only boxes scoring >= 0.4 from this decoder (hard-coded), at most 20 per region.
"""


def export_and_check(weights: Path, version: str | None, store: Store, cfg: Config, max_images: int | None = None) -> dict:
    from anpr_hitl.yolo import YOLO

    version = version or Path(weights).parent.name
    out = store.exports_dir / version
    out.mkdir(parents=True, exist_ok=True)
    pt = out / "best.pt"
    shutil.copyfile(weights, pt)
    imgsz = cfg.export.imgsz
    exported = {fmt: export_isolated(pt, fmt, imgsz, store.exports_dir / ".export_home") for fmt in cfg.export.formats}
    atomic_write_text(out / "labelmap.txt", f"0 {cfg.class_names[0]}\n")
    for fmt in exported:
        atomic_write_text(out / f"frigate_{fmt}.yml", frigate_config_snippet(version, imgsz, fmt))

    rows = sorted(read_manifest(store.gold_dir / "det" / "manifest.jsonl"), key=lambda r: r["image_id"])
    paths = [store.root / r["path"] for r in rows][:max_images]
    conf = cfg.predict.conf
    models = {"pt": YOLO(str(pt)), **{fmt: YOLO(str(p), task="detect") for fmt, p in exported.items()}}
    dets = {name: [] for name in models}
    for p in paths:
        for name, model in models.items():
            r = model.predict(str(p), imgsz=imgsz, conf=conf, device="cpu", verbose=False)[0].boxes.cpu().numpy()
            dets[name].append((r.xyxy, r.conf))

    parity = {}
    for fmt in exported:
        tot = {"pt_boxes": 0, "export_boxes": 0, "matched": 0, "matched_within_drift": 0, "max_drift": 0.0}
        for (a_b, a_c), (b_b, b_c) in zip(dets["pt"], dets[fmt], strict=True):
            m = match_sets(a_b, a_c, b_b, b_c, cfg.export.parity_iou, cfg.export.parity_max_conf_drift)
            tot["pt_boxes"] += m["a"]
            tot["export_boxes"] += m["b"]
            tot["matched"] += m["matched"]
            tot["matched_within_drift"] += m["matched_within_drift"]
            tot["max_drift"] = max(tot["max_drift"], m["max_drift"])
        denom = max(tot["pt_boxes"], tot["export_boxes"], 1)
        tot["agreement"] = round(tot["matched_within_drift"] / denom, 4)
        tot["pass"] = tot["agreement"] >= 0.99
        parity[fmt] = tot

    frigate = None
    if "onnx" in exported:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(exported["onnx"]), providers=["CPUExecutionProvider"])
        name = sess.get_inputs()[0].name
        tot = {"pt_boxes": 0, "frigate_boxes": 0, "matched": 0, "pt_boxes_below_0.4": 0}
        for p in paths:
            sq = _square(cv2.imread(str(p)), imgsz)
            tensor = cv2.cvtColor(sq, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255
            dec = frigate_decode(sess.run(None, {name: tensor})[0], imgsz, imgsz)
            dec = dec[dec[:, 1] > 0]
            f_boxes = np.stack([dec[:, 3], dec[:, 2], dec[:, 5], dec[:, 4]], axis=1) * imgsz if len(dec) else np.zeros((0, 4))
            r = models["pt"].predict(sq, imgsz=imgsz, conf=conf, device="cpu", verbose=False)[0].boxes.cpu().numpy()
            tot["pt_boxes_below_0.4"] += int((r.conf < FRIGATE_SCORE).sum())
            keep = r.conf >= FRIGATE_SCORE
            m = match_sets(r.xyxy[keep], r.conf[keep], f_boxes, dec[:, 1], cfg.export.parity_iou, 1.0)
            tot["pt_boxes"] += m["a"]
            tot["frigate_boxes"] += m["b"]
            tot["matched"] += m["matched"]
        tot["agreement"] = round(tot["matched"] / max(tot["pt_boxes"], tot["frigate_boxes"], 1), 4)
        frigate = tot

    deploy = evaluate_detector(pt, store, cfg, imgsz=imgsz).metrics(op_conf=cfg.evaluate.conf)
    report = {"version": version, "imgsz": imgsz, "images": len(paths),
              "files": {fmt: {"path": str(p), "sha256": _hash_export(p)} for fmt, p in exported.items()},
              "parity": parity, "frigate_decoder": frigate,
              "gold_at_deploy_size": {k: round(v, 5) if isinstance(v, float) else v for k, v in deploy.items()},
              "licence": "Ultralytics YOLO is AGPL-3.0: deployment beyond academic use needs a licence or release of "
                         "the source under AGPL"}
    atomic_write_json(out / "export_report.json", report)
    return report
