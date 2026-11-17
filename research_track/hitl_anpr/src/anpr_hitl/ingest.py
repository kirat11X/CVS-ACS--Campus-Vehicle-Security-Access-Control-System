"""Ingest: register a video (its split is fixed before any frame is used), sample frames at a fixed rate,
drop blurry and near-duplicate frames, and write EXIF-free JPEGs plus a manifest."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from anpr_hitl.config import Config
from anpr_hitl.hashing import dhash, hamming, phash, sha256_bytes, sha256_file
from anpr_hitl.manifest import read_manifest, write_manifest
from anpr_hitl.splits import VideoRegistry
from anpr_hitl.store import Store, atomic_write_bytes, file_lock

BLUR_REFERENCE_SIDE = 1280  # the Laplacian is measured at this long side so thresholds do not depend on resolution
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


@dataclass
class IngestResult:
    video_id: str
    split: str
    native_fps: float
    frame_count: int
    width: int
    height: int
    sampled: int = 0
    kept: int = 0
    dropped_blur: int = 0
    dropped_duplicate: int = 0
    skipped_existing: bool = False
    rows: list[dict] = field(default_factory=list)


def video_id_for(path: Path, sha256: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:40] or "video"
    return f"{stem}-{sha256[:8]}"


def sample_indices(frame_count: int, native_fps: float, fps: float) -> list[int]:
    """Frame indices nearest to t = k / fps (deterministic; independent of decoder seeking)."""
    if frame_count <= 0 or native_fps <= 0:
        return []
    duration = frame_count / native_fps
    indices, k = [], 0
    while k / fps < duration:
        idx = min(round(k / fps * native_fps), frame_count - 1)
        if not indices or idx != indices[-1]:
            indices.append(idx)
        k += 1
    return indices


def laplacian_variance(bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    scale = BLUR_REFERENCE_SIDE / max(gray.shape)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def mean_luma(bgr: np.ndarray) -> float:
    return float(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)[..., 0].mean())


def encode_jpeg_without_metadata(bgr: np.ndarray, quality: int) -> bytes:
    """JPEG bytes with no EXIF/GPS/XMP: pixels only."""
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def _probe(path: Path) -> tuple[float, int, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"no decodable frame in {path}")
    h, w = frame.shape[:2]
    return fps, count, w, h


def ingest_video(path: Path, store: Store, cfg: Config, group: str | None = None, split: str | None = None,
                 source: str | None = None, licence: str | None = None, force: bool = False) -> IngestResult:
    path = Path(path)
    sha = sha256_file(path)
    video_id = video_id_for(path, sha)
    registry = VideoRegistry(store.videos_registry, cfg.seed, cfg.splits.gold_fraction, cfg.splits.val_fraction)
    meta = registry.register(video_id, group=group, split=split, file=path.name, sha256=sha,
                             source=source or "user-supplied", licence=licence or "unrecorded")
    native_fps, frame_count, width, height = _probe(path)
    result = IngestResult(video_id, meta["split"], native_fps, frame_count, width, height)

    existing = [r for r in read_manifest(store.frames_manifest) if r["video_id"] == video_id]
    if existing and not force:
        result.skipped_existing, result.kept, result.rows = True, len(existing), existing
        return result

    wanted = set(sample_indices(frame_count, native_fps, cfg.ingest.fps))
    kept_hashes: list[int] = []
    out_dir = store.frames_dir(video_id)
    cap = cv2.VideoCapture(str(path))
    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx not in wanted:
            continue
        result.sampled += 1
        blur = laplacian_variance(frame)
        if blur < cfg.ingest.blur_min_laplacian_var:
            result.dropped_blur += 1
            continue
        rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        p_hash = phash(rgb)
        if any(hamming(p_hash, h) <= cfg.ingest.dedup_max_bits for h in kept_hashes):
            result.dropped_duplicate += 1
            continue
        kept_hashes.append(p_hash)
        data = encode_jpeg_without_metadata(frame, cfg.ingest.jpeg_quality)
        frame_path = out_dir / f"{idx:06d}.jpg"
        atomic_write_bytes(frame_path, data)
        result.rows.append({
            "frame_id": f"{video_id}/{idx:06d}", "video_id": video_id, "frame_idx": idx,
            "timestamp": round(idx / native_fps, 4), "path": str(frame_path.relative_to(store.root)),
            "sha256": sha256_bytes(data), "phash": f"{p_hash:016x}", "dhash": f"{dhash(rgb):016x}",
            "blur": round(blur, 2), "luma": round(mean_luma(frame), 2), "width": frame.shape[1],
            "height": frame.shape[0], "split": meta["split"], "group": meta["group"],
        })
    cap.release()
    result.kept = len(result.rows)

    with file_lock(store.frames_manifest):
        others = [r for r in read_manifest(store.frames_manifest) if r["video_id"] != video_id]
        write_manifest(store.frames_manifest, others + result.rows)
    return result


def find_videos(paths: list[Path]) -> list[Path]:
    found = []
    for p in map(Path, paths):
        if p.is_dir():
            found += sorted(q for q in p.iterdir() if q.suffix.lower() in VIDEO_EXTS)
        elif p.suffix.lower() in VIDEO_EXTS:
            found.append(p)
    return found
