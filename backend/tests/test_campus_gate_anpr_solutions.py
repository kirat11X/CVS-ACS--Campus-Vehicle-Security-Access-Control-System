"""
backend/tests/test_campus_gate_anpr_solutions.py
================================================
Comprehensive verification suite for all 5 Campus Gate ANPR Solutions:
- Solution 1: Soft CIE LAB Color Remapper (remap_to_yellow_black)
- Solution 2: Stage-0 UVH-26 Gatekeeper & Stage-1 YOLO11n Multi-Color Plate Detector
- Solution 3: Dynamic Contrast Normalization & CLAHE/Otsu Polarity Inversion
- Solution 4: Plate-Specialized OCR & 2-Line Split Mechanism
- Solution 5: CMVR Rule 50 Positional Repair & Multi-Frame Track Voting
"""

import cv2
import numpy as np
import pytest
from pathlib import Path

from backend.app.services.anpr.color_remap import (
    remap_to_yellow_black,
    PLATE_TYPE_GREEN_EV,
    PLATE_TYPE_WHITE_PRIVATE,
    PLATE_TYPE_YELLOW_COMMERCIAL,
)
from backend.app.services.anpr.polarity_normalizer import (
    normalize_plate_agnostic,
)
from backend.app.services.anpr.ocr_engine import (
    split_two_line_plate,
    pad_plate_bbox,
    is_plate_like_crop,
    deskew_plate,
)
from backend.app.services.anpr.track_voter import TrackVoter
from backend.app.services.plate_normalizer import (
    correct_indian_plate,
    is_valid_indian_plate,
    classify_plate_format,
    normalize_plate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dummy_crop(h=64, w=200, bg_color=(255, 255, 255), fg_color=(0, 0, 0), text="DL10AB1234"):
    crop = np.full((h, w, 3), bg_color, dtype=np.uint8)
    cv2.putText(crop, text, (15, int(h * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, fg_color, 2)
    return crop


# ---------------------------------------------------------------------------
# Test Solution 1: Soft CIE LAB Color Remapper
# ---------------------------------------------------------------------------

class TestSolution1ColorRemap:
    def test_white_private_plate_remapping(self):
        crop = _make_dummy_crop(bg_color=(240, 240, 240), fg_color=(20, 20, 20))
        remapped, plate_type = remap_to_yellow_black(crop)
        assert plate_type == PLATE_TYPE_WHITE_PRIVATE
        assert remapped.shape == crop.shape
        assert remapped.dtype == np.uint8

    def test_green_ev_plate_remapping(self):
        crop = _make_dummy_crop(bg_color=(30, 160, 30), fg_color=(250, 250, 250))
        remapped, plate_type = remap_to_yellow_black(crop)
        assert plate_type == PLATE_TYPE_GREEN_EV
        assert remapped.shape == crop.shape

    def test_commercial_yellow_plate_passthrough(self):
        crop = _make_dummy_crop(bg_color=(30, 220, 240), fg_color=(10, 10, 10))
        remapped, plate_type = remap_to_yellow_black(crop)
        assert plate_type == PLATE_TYPE_YELLOW_COMMERCIAL


# ---------------------------------------------------------------------------
# Test Solution 2: Stage-0 & Stage-1 Model Weights & Pipeline Artifacts
# ---------------------------------------------------------------------------

class TestSolution2ModelsAndArtifacts:
    def test_model_files_exist(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        weights_dir = repo_root / "weights"

        uvh26_onnx = weights_dir / "uvh26_vehicle_yolo11s.onnx"
        detector_onnx = weights_dir / "yolo11n_plate_detector_finetuned.onnx"
        detector_pt = weights_dir / "yolo11n_plate_detector_finetuned.pt"

        assert uvh26_onnx.is_file(), f"Missing {uvh26_onnx}"
        assert detector_onnx.is_file(), f"Missing {detector_onnx}"
        assert detector_pt.is_file(), f"Missing {detector_pt}"
        assert uvh26_onnx.stat().st_size > 10_000_000
        assert detector_onnx.stat().st_size > 5_000_000

    def test_detector_metrics_recorded(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        metrics_file = repo_root / "weights" / "track_a_detector_metrics.json"
        assert metrics_file.is_file(), f"Missing {metrics_file}"


# ---------------------------------------------------------------------------
# Test Solution 3: CLAHE + Otsu Polarity Normalization
# ---------------------------------------------------------------------------

class TestSolution3PolarityNormalization:
    def test_white_plate_preserves_dark_on_light(self):
        crop = _make_dummy_crop(bg_color=(250, 250, 250), fg_color=(10, 10, 10))
        norm, was_inverted = normalize_plate_agnostic(crop)
        assert was_inverted is False
        assert norm.shape == crop.shape

    def test_green_ev_inverts_light_on_dark(self):
        crop = _make_dummy_crop(bg_color=(20, 140, 20), fg_color=(255, 255, 255))
        norm, was_inverted = normalize_plate_agnostic(crop)
        assert was_inverted is True
        assert norm.shape == crop.shape


# ---------------------------------------------------------------------------
# Test Solution 4: OCR Engine & Two-Line Plate Split
# ---------------------------------------------------------------------------

class TestSolution4OCREngineAndSplit:
    def test_aspect_ratio_split_two_line(self):
        # Square plate with aspect ratio ~ 1.2
        square_crop = np.zeros((150, 180, 3), dtype=np.uint8)
        cv2.putText(square_crop, "HR26", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        cv2.putText(square_crop, "DK8337", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        lines = split_two_line_plate(square_crop)
        assert len(lines) == 2
        assert lines[0].shape[0] < square_crop.shape[0]
        assert lines[1].shape[0] < square_crop.shape[0]

    def test_single_line_plate_does_not_split(self):
        # Standard rectangular plate with aspect ratio ~ 3.5
        rect_crop = np.zeros((50, 175, 3), dtype=np.uint8)
        lines = split_two_line_plate(rect_crop)
        assert len(lines) == 1
        assert lines[0].shape == rect_crop.shape

    def test_bounding_box_padding(self):
        padded = pad_plate_bbox([10, 10, 100, 50], frame_shape=(480, 640, 3), pad_w_pct=0.08, pad_h_pct=0.05)
        assert padded[0] < 10
        assert padded[1] < 10
        assert padded[2] > 100
        assert padded[3] > 50


# ---------------------------------------------------------------------------
# Test Solution 5: CMVR Rule 50 Grammar Repair & Track Voting
# ---------------------------------------------------------------------------

class TestSolution5RepairAndVoting:
    def test_standard_state_positional_repair(self):
        # P810A81234 -> PB10AB1234
        repaired, confidence, meta = correct_indian_plate("P810A81234")
        assert repaired.startswith("PB10AB") or repaired == "PB10AB1234"
        assert is_valid_indian_plate("PB10AB1234")

    def test_bharat_series_repair(self):
        # 228H1234AA -> 22BH1234AA
        repaired, confidence, meta = correct_indian_plate("228H1234AA")
        assert repaired == "22BH1234AA"
        assert is_valid_indian_plate(repaired)

    def test_multi_frame_track_voting_consensus(self):
        voter = TrackVoter(min_consensus_frames=3, max_track_frames=8)
        # Jitter sequence over multiple frames
        reads = [
            ("DL10AB1234", 0.88),
            ("DL10A81234", 0.72),
            ("DL10AB1234", 0.91),
            ("DL1OAB1234", 0.75),
        ]
        for idx, (txt, conf) in enumerate(reads):
            voter.add_observation(
                track_id="trk_42",
                plate_text=txt,
                confidence=conf,
                bbox=[10, 10, 100, 50],
                frame_ts=100.0 + idx * 0.1,
            )

        consensus = voter.get_consensus(track_id="trk_42")
        assert consensus is not None
        assert consensus["fused_plate"] == "DL10AB1234"
        assert consensus["frame_count"] == 4
        assert consensus["confidence"] >= 0.75
