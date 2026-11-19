"""
Multi-Frame Track Voter & Statutory Indian Plate Consensus.
-----------------------------------------------------------
Buffers multi-frame plate hypotheses for a given vehicle track_id,
calculates a confidence-weighted character frequency matrix for each position,
produces a voted candidate string, runs statutory positional repair (correct_indian_plate),
and routes non-standard statutory formats (military/diplomatic/temp/unrepairable) to MANUAL_CHECK.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from backend.app.services.plate_normalizer import (
    classify_plate_format,
    correct_indian_plate,
    normalize_plate,
    strip_ind_prefix,
)

logger = logging.getLogger("campus_security.anpr.track_voter")


@dataclass
class TrackObservation:
    plate_text: str
    confidence: float
    bbox: List[int]
    frame_ts: float
    frame_bgr: Optional[np.ndarray] = None
    sharpness: float = 0.0


class TrackVoter:
    """
    Accumulates multi-frame plate hypotheses for a given vehicle track_id.
    Performs confidence-weighted positional voting across 5-8 frames.
    Routes non-standard statutory formats (military/diplomatic/temp/unrepairable)
    to 'MANUAL_CHECK'.
    """

    def __init__(self, min_consensus_frames: int = 5, max_track_frames: int = 8) -> None:
        self.min_consensus_frames = min_consensus_frames
        self.max_track_frames = max_track_frames
        self._tracks: Dict[str, List[TrackObservation]] = defaultdict(list)

    def add_observation(
        self,
        track_id: str,
        plate_text: str,
        confidence: float,
        bbox: List[int],
        frame_ts: float,
        frame_bgr: Optional[np.ndarray] = None,
    ) -> None:
        """
        Buffers an observation for a given track_id.
        Maintains a sliding window capped at max_track_frames.
        """
        sharpness = 0.0
        if frame_bgr is not None and getattr(frame_bgr, "size", 0) > 0:
            try:
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            except Exception:
                sharpness = 0.0

        obs = TrackObservation(
            plate_text=str(plate_text or ""),
            confidence=max(0.01, float(confidence)),
            bbox=list(bbox) if bbox else [],
            frame_ts=float(frame_ts),
            frame_bgr=frame_bgr,
            sharpness=sharpness,
        )

        track_buffer = self._tracks[track_id]
        track_buffer.append(obs)
        if len(track_buffer) > self.max_track_frames:
            self._tracks[track_id] = track_buffer[-self.max_track_frames :]

    def get_consensus(self, track_id: str) -> Optional[Dict[str, Any]]:
        """
        Evaluates consensus when buffered frames >= min_consensus_frames.
        - Calculates confidence-weighted character frequency matrix for each position.
        - Produces voted candidate string.
        - Runs correct_indian_plate(voted).
        - If non-standard (military, diplomatic, temporary, or unrepairable non-statutory read),
          sets requires_manual_check=True and action="MANUAL_CHECK".
        - Returns consensus dict.
        """
        observations = self._tracks.get(track_id)
        if not observations or len(observations) < self.min_consensus_frames:
            return None

        # Prepare cleaned text for each observation
        cleaned_obs: List[tuple[str, TrackObservation]] = []
        for obs in observations:
            c = strip_ind_prefix(obs.plate_text)
            # If 5 trailing digits (e.g. GJ13UX35217), consider trimmed version
            if len(c) >= 11 and c[-5:].isdigit() and not c.startswith("22BH"):
                c = c[:-1]
            if c:
                cleaned_obs.append((c, obs))

        if not cleaned_obs:
            return None

        # 1. Determine consensus string length weighted by confidence
        len_weights: Counter[int] = Counter()
        for c_text, obs in cleaned_obs:
            len_weights[len(c_text)] += obs.confidence

        consensus_len = len_weights.most_common(1)[0][0]

        # 2. Confidence-weighted character frequency matrix for each position
        pos_matrix: List[Counter[str]] = [Counter() for _ in range(consensus_len)]
        for c_text, obs in cleaned_obs:
            if len(c_text) == consensus_len:
                for idx, ch in enumerate(c_text):
                    pos_matrix[idx][ch] += obs.confidence
            else:
                # Align overlapping prefix
                overlap = min(len(c_text), consensus_len)
                for idx in range(overlap):
                    pos_matrix[idx][c_text[idx]] += obs.confidence * 0.5

        voted_candidate = "".join(
            pos_matrix[idx].most_common(1)[0][0] if pos_matrix[idx] else "X"
            for idx in range(consensus_len)
        )

        # 3. Statutory positional correction & syntax verification
        canonical_plate, syntax_conf, format_category = correct_indian_plate(voted_candidate)

        # 4. Identify clearest frame & bounding box for snapshot evidence
        def _quality_score(o: TrackObservation) -> float:
            if o.frame_bgr is not None and getattr(o.frame_bgr, "size", 0) > 0:
                return o.confidence * (1.0 + min(o.sharpness / 100.0, 5.0))
            return o.confidence

        best_obs = max(observations, key=_quality_score)
        best_frame = best_obs.frame_bgr
        best_bbox = best_obs.bbox

        # 5. Routing of non-standard plates (military/diplomatic/temp/invalid)
        is_temporary = (
            "TEMP" in voted_candidate
            or "TEMP" in canonical_plate
            or voted_candidate.startswith("TR")
            or canonical_plate.startswith("TR")
            or "TC" in voted_candidate
            or "TC" in canonical_plate
        )

        is_non_standard = (
            format_category in ("MILITARY", "DIPLOMATIC", "INVALID")
            or is_temporary
            or syntax_conf < 0.40
        )

        requires_manual_check = bool(is_non_standard)
        action = "MANUAL_CHECK" if requires_manual_check else "PROCEED"

        # 6. Agreement rate across buffered frames
        agreed = 0
        for obs in observations:
            obs_clean = strip_ind_prefix(obs.plate_text)
            obs_canon, _, _ = correct_indian_plate(obs.plate_text)
            if obs_canon == canonical_plate or obs_clean == voted_candidate:
                agreed += 1
        agreement_rate = round(agreed / len(observations), 3)

        # 7. Overall confidence score
        avg_confidence = round(sum(o.confidence for o in observations) / len(observations), 3)

        return {
            "fused_plate": canonical_plate,
            "confidence": avg_confidence,
            "syntax_confidence": syntax_conf,
            "agreement_rate": agreement_rate,
            "format_category": format_category,
            "requires_manual_check": requires_manual_check,
            "action": action,
            "best_bbox": best_bbox,
            "best_frame": best_frame,
            "voted_raw": voted_candidate,
            "frame_count": len(observations),
            "is_valid": format_category in ("STANDARD", "BHARAT_SERIES", "VINTAGE"),
        }

    def clear_track(self, track_id: str) -> None:
        """Clears all buffered observations for a vehicle track."""
        self._tracks.pop(track_id, None)

    def get_track_frame_count(self, track_id: str) -> int:
        """Returns the number of buffered observations for a track."""
        return len(self._tracks.get(track_id, []))
