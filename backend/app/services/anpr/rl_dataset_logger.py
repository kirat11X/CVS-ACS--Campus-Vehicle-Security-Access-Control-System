"""
Persistent Reinforcement Learning & Active Learning Dataset Logger.
==================================================================
Stores full vehicle images, plate crops, detected bounding boxes, OCR predictions,
and human-verified ground-truth edits permanently to disk.

Data is NEVER purged, providing continuous training data for offline and
reinforcement learning loops.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

import cv2
import numpy as np

from backend.app.config import BASE_DIR, MEDIA_ROOT

logger = logging.getLogger("campus_security.rl_dataset")

RL_DATASET_DIR = Path(BASE_DIR) / "data" / "rl_dataset"
RL_IMAGES_DIR = RL_DATASET_DIR / "images"
RL_MANIFEST_PATH = RL_DATASET_DIR / "manifest.jsonl"


def _ensure_dirs() -> None:
    RL_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    RL_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def log_anpr_observation_sample(
    observation_id: str,
    gate_id: str,
    raw_text: str,
    normalized_plate: str,
    confidence: float,
    vehicle_class: str,
    full_frame: Optional[np.ndarray] = None,
    plate_crop: Optional[np.ndarray] = None,
    vehicle_bbox: Optional[List[int]] = None,
    plate_bbox: Optional[List[int]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Saves an observation sample permanently to data/rl_dataset/ for active learning and RL.
    """
    try:
        _ensure_dirs()
        ts_str = datetime.now(timezone.utc).isoformat()
        sample_id = f"{observation_id}_{int(datetime.now(timezone.utc).timestamp())}"

        frame_rel_path: Optional[str] = None
        crop_rel_path: Optional[str] = None

        if full_frame is not None and full_frame.size > 0:
            frame_filename = f"{sample_id}_full.jpg"
            frame_path = RL_IMAGES_DIR / frame_filename
            cv2.imwrite(str(frame_path), full_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            frame_rel_path = f"data/rl_dataset/images/{frame_filename}"

        if plate_crop is not None and plate_crop.size > 0:
            crop_filename = f"{sample_id}_crop.jpg"
            crop_path = RL_IMAGES_DIR / crop_filename
            cv2.imwrite(str(crop_path), plate_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            crop_rel_path = f"data/rl_dataset/images/{crop_filename}"

        record = {
            "id": sample_id,
            "observation_id": str(observation_id),
            "timestamp": ts_str,
            "gate_id": gate_id,
            "ocr_raw": raw_text,
            "ocr_normalized": normalized_plate,
            "ground_truth_plate": normalized_plate,
            "confidence": float(confidence),
            "vehicle_class": vehicle_class,
            "vehicle_bbox": vehicle_bbox,
            "plate_bbox": plate_bbox,
            "full_frame_path": frame_rel_path,
            "plate_crop_path": crop_rel_path,
            "was_manually_corrected": False,
            "correction_note": None,
            "extra_meta": extra_meta or {},
        }

        with open(RL_MANIFEST_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record
    except Exception as exc:
        logger.warning("Failed to log RL observation sample: %s", exc)
        return None


def log_human_plate_correction(
    observation_id: str,
    original_plate: str,
    corrected_plate: str,
    guard_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    """
    Appends a human ground-truth correction event to the RL dataset manifest.
    Provides hard negative/positive feedback signals for Reinforcement Learning from Human Feedback (RLHF).
    """
    try:
        _ensure_dirs()
        ts_str = datetime.now(timezone.utc).isoformat()
        record = {
            "id": f"corr_{uuid.uuid4().hex[:12]}",
            "observation_id": str(observation_id),
            "timestamp": ts_str,
            "ocr_normalized": original_plate,
            "ground_truth_plate": corrected_plate,
            "was_manually_corrected": True,
            "guard_user_id": str(guard_user_id) if guard_user_id else None,
            "correction_note": note,
            "event_type": "HUMAN_GUARD_CORRECTION",
        }

        with open(RL_MANIFEST_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info("RL dataset logged correction for %s: '%s' -> '%s'", observation_id, original_plate, corrected_plate)
        return True
    except Exception as exc:
        logger.warning("Failed to log human correction to RL manifest: %s", exc)
        return False


def get_rl_dataset_stats() -> Dict[str, Any]:
    """Returns dataset summary metrics for active learning monitoring."""
    _ensure_dirs()
    if not RL_MANIFEST_PATH.exists():
        return {"total_records": 0, "corrections": 0, "images_stored": 0}

    total = 0
    corrections = 0
    try:
        with open(RL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    total += 1
                    data = json.loads(line)
                    if data.get("was_manually_corrected"):
                        corrections += 1
        img_count = len(list(RL_IMAGES_DIR.glob("*.jpg")))
        return {
            "total_records": total,
            "corrections": corrections,
            "images_stored": img_count,
            "manifest_path": str(RL_MANIFEST_PATH),
        }
    except Exception as exc:
        return {"error": str(exc), "total_records": 0, "corrections": 0}
