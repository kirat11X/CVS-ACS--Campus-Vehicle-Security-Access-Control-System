"""Predict: plate boxes (+ ByteTrack ids on video), OCR reads with per-character confidence, and plate checks.

Model output is a proposal for the reviewer and is never written as a training label. Per round:
  rounds/<id>/predictions/predictions.jsonl   one row per frame (pixel boxes, scores, track ids, reads, flags)
  rounds/<id>/predictions/labels/<key>.txt    YOLO pre-labels (proposals) for CVAT / Label Studio import
  rounds/<id>/crops/<key>__b<i>.jpg           plate crops for the review app

Video: the detector and ByteTrack run on a denser stream (track_fps) that always contains the ingested frames, so
each ingested frame carries track ids. Every track's best crops (detector score x sharpness) are read and
compared: disagreement between them is a review signal, never an automatic correction.
"""

from __future__ import annotations

import heapq
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from anpr_hitl.config import Config
from anpr_hitl.hashing import sha256_file
from anpr_hitl.ingest import mean_luma, sample_indices
from anpr_hitl.labels import write_yolo_labels, xyxy_to_yolo
from anpr_hitl.ocr import OcrRead, crop_box, read_plate, sharpness
from anpr_hitl.plates import check_plate
from anpr_hitl.store import Store, atomic_write_bytes, write_jsonl

TRACK_MIN_CONF = 0.10   # ByteTrack's second association uses detections below the proposal threshold
DETECT_BATCH = 8


class Detector(Protocol):
    def __call__(self, frames: list[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
        """For each BGR frame: (xyxy float array (N, 4), confidence (N,)), in frame pixels."""


class YoloDetector:
    def __init__(self, weights: Path, imgsz: int, conf: float, iou: float, device):
        from anpr_hitl.yolo import YOLO

        self.weights = Path(weights)
        self.model = YOLO(str(weights))
        self.imgsz, self.conf, self.iou, self.device = imgsz, conf, iou, device

    def __call__(self, frames):
        out = []
        for r in self.model.predict(frames, imgsz=self.imgsz, conf=self.conf, iou=self.iou, device=self.device,
                                    verbose=False):
            b = r.boxes.cpu().numpy()
            out.append((b.xyxy.astype(np.float64), b.conf.astype(np.float64)))
        return out


class _Dets:
    """The minimal Results-like view BYTETracker.update needs (conf, cls, xywh, boolean indexing)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray):
        self.xyxy, self.conf = xyxy.reshape(-1, 4), conf.reshape(-1)
        self.cls = np.zeros(len(self.conf))

    @property
    def xywh(self) -> np.ndarray:
        xy = (self.xyxy[:, :2] + self.xyxy[:, 2:]) / 2
        return np.concatenate([xy, self.xyxy[:, 2:] - self.xyxy[:, :2]], axis=1)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask) -> "_Dets":
        return _Dets(self.xyxy[mask], self.conf[mask])


def new_tracker(tracker_yaml: str):
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml

    return BYTETracker(IterableSimpleNamespace(**YAML.load(check_yaml(tracker_yaml))))


@dataclass
class TrackedVideo:
    frames: dict[int, list[dict]] = field(default_factory=dict)   # kept frame index -> boxes (xyxy, conf, track_id)
    best_crops: dict[int, list] = field(default_factory=dict)     # track id -> heap of (score, frame_idx, crop)
    processed: int = 0
    native_fps: float = 0.0


def track_video(video: Path, detector: Detector, keep: set[int], track_fps: float, proposal_conf: float,
                tracker_yaml: str, crop_pad: float, top_crops: int) -> TrackedVideo:
    """Detect + track on the denser stream; return boxes for the kept frames and each track's best crops."""
    cap = cv2.VideoCapture(str(video))
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    wanted = set(sample_indices(count, native_fps, track_fps)) | set(keep)
    tracker = new_tracker(tracker_yaml)
    out = TrackedVideo(native_fps=native_fps)
    pending: list[tuple[int, np.ndarray]] = []

    def flush():
        dets = detector([f for _, f in pending])
        for (idx, frame), (xyxy, conf) in zip(pending, dets, strict=True):
            mask = conf >= TRACK_MIN_CONF
            xyxy, conf = xyxy[mask], conf[mask]
            tracks = tracker.update(_Dets(xyxy, conf), frame)
            track_of = {int(t[7]): int(t[4]) for t in tracks} if len(tracks) else {}
            out.processed += 1
            for i in range(len(conf)):
                tid = track_of.get(i)
                if tid is None or conf[i] < proposal_conf:
                    continue
                crop = crop_box(frame, xyxy[i], crop_pad)
                score = float(conf[i]) * float(np.sqrt(max(sharpness(crop), 1e-6)))
                heap = out.best_crops.setdefault(tid, [])
                item = (score, idx, crop)
                if len(heap) < top_crops:
                    heapq.heappush(heap, item)
                elif score > heap[0][0]:
                    heapq.heapreplace(heap, item)
            if idx in keep:
                out.frames[idx] = [{"xyxy": xyxy[i].tolist(), "conf": float(conf[i]), "track_id": track_of.get(i)}
                                   for i in range(len(conf))]
        pending.clear()

    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx in wanted:
            pending.append((idx, frame))
            if len(pending) == DETECT_BATCH:
                flush()
    if pending:
        flush()
    cap.release()
    return out


def track_consensus(reads: list[OcrRead]) -> dict:
    """Most frequent non-empty read over a track's best crops (ties: higher mean confidence)."""
    texts = [r.text for r in reads if r.text]
    if not texts:
        return {"reads": len(reads), "consensus": "", "agreement": 0.0, "disagreement": False}
    counts = Counter(texts)
    conf = {t: np.mean([r.conf for r in reads if r.text == t]) for t in counts}
    best = max(counts, key=lambda t: (counts[t], conf[t]))
    return {"reads": len(reads), "consensus": best, "agreement": round(counts[best] / len(texts), 3),
            "disagreement": len(counts) > 1}


def _box_record(frame: np.ndarray, box: dict, cfg: Config, reader: Callable) -> tuple[dict, np.ndarray]:
    crop = crop_box(frame, box["xyxy"], cfg.predict.crop_pad)
    read = reader(crop)
    check = check_plate(read.text, read.char_confs, cfg.ocr.low_char_conf)
    rec = {**box, "xyxy": [round(v, 2) for v in box["xyxy"]], "conf": round(box["conf"], 4),
           "ocr": read.to_dict(),
           "check": {"format": check.format, "regex_valid": check.regex_valid, "state_known": check.state_code_known,
                     "suggestions": list(check.confusion_suggestions), "low_conf_positions": list(check.low_conf_positions),
                     "flags": list(check.flags)}}
    return rec, crop


def frame_flags(boxes: list[dict], near_misses: list[dict], luma: float, cfg: Config) -> list[str]:
    lo, hi = cfg.select.low_conf_band
    flags = set()
    for b in boxes:
        if lo <= b["conf"] < hi:
            flags.add("low_confidence")
        if not b["check"]["regex_valid"]:
            flags.add("regex_failure")
        if "low_char_conf" in b["check"]["flags"]:
            flags.add("low_char_conf")
        if b.get("track", {}).get("disagreement"):
            flags.add("track_disagreement")
        alts = b["ocr"].get("alternatives") or []
        if any(a["text"] != b["ocr"]["text"] for a in alts):
            flags.add("engine_disagreement")
    if near_misses:
        flags.add("near_miss")
    if not boxes:
        flags.add("no_detections")
    if luma < cfg.select.night_max_luma:
        flags.add("night")
    return sorted(flags)


def _key(frame_id: str) -> str:
    return frame_id.replace("/", "__")


def _finish_frame(row: dict, frame: np.ndarray, dets: list[dict], cfg: Config, reader: Callable, round_dir: Path,
                  track_reads: dict[int, dict] | None = None) -> dict:
    proposals = [d for d in dets if d["conf"] >= cfg.predict.conf]
    near = [{"xyxy": [round(v, 2) for v in d["xyxy"]], "conf": round(d["conf"], 4)}
            for d in dets if TRACK_MIN_CONF <= d["conf"] < cfg.predict.conf]
    boxes = []
    key = _key(row["frame_id"])
    for i, det in enumerate(sorted(proposals, key=lambda d: (d["xyxy"][0], d["xyxy"][1]))):
        rec, crop = _box_record(frame, det, cfg, reader)
        rec["box_id"] = f"b{i}"
        if track_reads is not None and det.get("track_id") is not None:
            rec["track"] = track_reads.get(det["track_id"], {})
        crop_path = round_dir / "crops" / f"{key}__b{i}.jpg"
        if crop.size:
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if ok:
                atomic_write_bytes(crop_path, buf.tobytes())
                rec["crop"] = str(crop_path.relative_to(round_dir))
        boxes.append(rec)
    h, w = frame.shape[:2]
    labels = [(0, *y) for b in boxes if (y := xyxy_to_yolo(b["xyxy"], w, h)) is not None]
    write_yolo_labels(round_dir / "predictions" / "labels" / f"{key}.txt", labels)
    luma = row.get("luma")
    luma = mean_luma(frame) if luma is None else luma
    return {**row, "width": w, "height": h, "luma": round(float(luma), 2), "boxes": boxes, "near_misses": near,
            "flags": frame_flags(boxes, near, luma, cfg)}


def predict_video(video: Path, frames: list[dict], detector: Detector, cfg: Config, store: Store, round_dir: Path,
                  reader: Callable | None = None) -> list[dict]:
    """frames: manifest rows of this video's ingested frames (frame_idx, frame_id, path, ...)."""
    reader = reader or (lambda crop: read_plate(crop, cfg.ocr))
    keep = {r["frame_idx"] for r in frames}
    tv = track_video(video, detector, keep, cfg.predict.track_fps, cfg.predict.conf, cfg.predict.tracker,
                     cfg.predict.crop_pad, cfg.predict.ocr_top_crops)
    track_reads = {}
    for tid, heap in tv.best_crops.items():
        reads = [reader(crop) for _, _, crop in sorted(heap, reverse=True)]
        track_reads[tid] = {"track_id": tid, **track_consensus(reads)}
    rows = []
    for r in sorted(frames, key=lambda r: r["frame_idx"]):
        if r["frame_idx"] not in tv.frames:
            continue  # the decoder ended early; the frame stays unpredicted rather than guessed
        frame = cv2.imread(str(store.root / r["path"]))  # the ingested JPEG: what the reviewer will see
        row = {k: r[k] for k in ("frame_id", "video_id", "path", "split", "group", "frame_idx", "luma", "sha256", "dhash") if k in r}
        rows.append(_finish_frame({**row, "kind": "video"}, frame, tv.frames.get(r["frame_idx"], []), cfg, reader,
                                  round_dir, track_reads))
    return rows


def predict_images(items: list[dict], detector: Detector, cfg: Config, store: Store, round_dir: Path,
                   reader: Callable | None = None) -> list[dict]:
    """items: {'frame_id', 'path' (relative to the data root), 'split', 'group', 'source'} for still images."""
    reader = reader or (lambda crop: read_plate(crop, cfg.ocr))
    rows = []
    for start in range(0, len(items), DETECT_BATCH):
        chunk = items[start:start + DETECT_BATCH]
        images = [cv2.imread(str(store.root / it["path"])) for it in chunk]
        valid = [(it, img) for it, img in zip(chunk, images, strict=True) if img is not None]
        dets = detector([img for _, img in valid])
        for (it, img), (xyxy, conf) in zip(valid, dets, strict=True):
            boxes = [{"xyxy": xyxy[i].tolist(), "conf": float(conf[i]), "track_id": None} for i in range(len(conf))
                     if conf[i] >= TRACK_MIN_CONF]
            rows.append(_finish_frame({**it, "kind": "image", "luma": None}, img, boxes, cfg, reader, round_dir))
    return rows


def model_info(weights: Path, version: str | None) -> dict:
    return {"version": version, "weights_sha256": sha256_file(weights)}


def write_predictions(round_dir: Path, rows: list[dict], model: dict) -> Path:
    path = round_dir / "predictions" / "predictions.jsonl"
    write_jsonl(path, [{**r, "model": model} for r in sorted(rows, key=lambda r: r["frame_id"])])
    return path
