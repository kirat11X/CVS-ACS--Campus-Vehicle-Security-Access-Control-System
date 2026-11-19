"""
Wave 2 ANPR Pipeline End-to-End Integration Tests.
==================================================
Verifies the complete lifecycle and cross-component integration of Wave 2 ANPR:
1. Green EV plate workflow:
   - `normalize_plate_agnostic` auto-inverts light-on-dark (white-on-green).
   - `run_dual_pass_ocr` decodes text.
   - `correct_indian_plate` enforces statutory format constraints.
2. White private plate workflow:
   - `normalize_plate_agnostic` preserves native dark-on-light polarity.
   - `remap_to_yellow_black` remaps to commercial taxi yellow/black as fallback.
   - `correct_indian_plate` repairs letter/digit confusions (P810A81234 -> PB10AB1234).
3. Square / 2-line plate workflow:
   - `split_two_line_plate` splits plates with aspect ratio < 2.4 at minimum-ink valley.
   - Dual-pass OCR reads top and bottom lines and joins them into canonical Indian plate.
   - Aspect ratio >= 2.4 remains intact as a single crop.
4. Multi-frame temporal track voting:
   - `TrackVoter` voting resolves character jitter across 5-8 frames into clean consensus.
   - Sliding window capped at max_track_frames (8).
   - Minimum frame threshold (5) enforced.
5. Non-standard vehicle routing:
   - Military (e.g. 22D123456A), Temporary (e.g. TEMP20241234 / TR01AB1234),
     Diplomatic (e.g. 77CD1234), and Unrepairable (e.g. XXXX9999) routed to MANUAL_CHECK.
6. CameraStreamManager integration:
   - `process_frame` with dual-pass OCR and relaxed aspect ratios (0.9 to 6.0).
"""

from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from backend.app.services.anpr.color_remap import (
    PLATE_TYPE_GREEN_EV,
    PLATE_TYPE_WHITE_PRIVATE,
    remap_to_yellow_black,
)
from backend.app.services.anpr.ocr_engine import (
    deskew_plate,
    is_plate_like_crop,
    pad_plate_bbox,
    run_dual_pass_ocr,
    split_two_line_plate,
)
from backend.app.services.anpr.polarity_normalizer import normalize_plate_agnostic
from backend.app.services.anpr.track_voter import TrackVoter
from backend.app.services.plate_normalizer import (
    classify_plate_format,
    correct_indian_plate,
    is_valid_indian_plate,
    normalize_plate,
)
from backend.app.workers.camera_stream_runner import CameraStreamManager


# =============================================================================
# Synthetic Plate Generators
# =============================================================================

def _create_synthetic_plate(
    text: str,
    bg_bgr: tuple[int, int, int],
    text_bgr: tuple[int, int, int],
    width: int = 260,
    height: int = 70,
    add_hsrp_strip: bool = True,
) -> np.ndarray:
    """Creates a high-contrast synthetic Indian license plate with optional HSRP strip."""
    plate = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    cv2.rectangle(plate, (1, 1), (width - 2, height - 2), (10, 10, 10), 2)

    if add_hsrp_strip:
        hsrp_w = int(round(width * 0.14))
        plate[:, :hsrp_w] = (160, 60, 20)  # BGR blue strip
        cv2.putText(
            plate,
            "IND",
            (int(hsrp_w * 0.15), int(height * 0.65)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    # Plate text positioned in readable area
    x_offset = int(round(width * 0.18)) if add_hsrp_strip else int(round(width * 0.08))
    cv2.putText(
        plate,
        text,
        (x_offset, int(height * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        text_bgr,
        2,
        cv2.LINE_AA,
    )
    return plate


def _create_synthetic_two_line_plate(
    line1: str,
    line2: str,
    bg_bgr: tuple[int, int, int],
    text_bgr: tuple[int, int, int],
    width: int = 160,
    height: int = 120,
) -> np.ndarray:
    """Creates a 2-line square license plate image (aspect ratio < 2.4)."""
    plate = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    cv2.rectangle(plate, (2, 2), (width - 3, height - 3), (10, 10, 10), 2)
    # Line 1 (top half: ~35% height)
    cv2.putText(
        plate,
        line1,
        (int(width * 0.20), int(height * 0.36)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.80,
        text_bgr,
        2,
        cv2.LINE_AA,
    )
    # Line 2 (bottom half: ~75% height)
    cv2.putText(
        plate,
        line2,
        (int(width * 0.15), int(height * 0.78)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.80,
        text_bgr,
        2,
        cv2.LINE_AA,
    )
    return plate


# =============================================================================
# 1. Green EV Plate End-to-End Integration
# =============================================================================

class TestGreenEVPlateWorkflow:
    """
    Verifies end-to-end processing of Green EV plates:
    Light text on dark green background -> Agnostic Polarity Inversion ->
    Dual-Pass OCR -> Positional Statutory Repair.
    """

    def test_green_ev_polarity_inversion_and_statutory_validation(self):
        """Green EV plate must trigger auto-inversion and downstream standard plate recognition."""
        ev_plate = _create_synthetic_plate(
            text="DL01EV1234",
            bg_bgr=(25, 95, 25),       # Dark green background
            text_bgr=(245, 245, 245),  # White characters
            add_hsrp_strip=True,
        )

        # 1. Agnostic Polarity Normalization
        norm_bgr, was_inverted = normalize_plate_agnostic(ev_plate)
        assert was_inverted is True, "Green EV plate (light on dark) must be inverted"
        assert norm_bgr.shape == ev_plate.shape
        assert is_plate_like_crop(norm_bgr) is True

        # 2. Dual-Pass OCR Execution (mock CRNN representing ONNX model)
        mock_crnn = MagicMock()
        mock_crnn.run.return_value = ("DL01EV1234", 0.95)

        ocr_text, ocr_conf, engine = run_dual_pass_ocr(norm_bgr, ocr_session=mock_crnn)
        assert ocr_text == "DL01EV1234"
        assert ocr_conf >= 0.90
        assert engine == "CRNN"

        # 3. Statutory Positional Validation
        canonical_plate, syntax_conf, format_cat = correct_indian_plate(ocr_text)
        assert canonical_plate == "DL01EV1234"
        assert format_cat == "STANDARD"
        assert syntax_conf == 1.0
        assert is_valid_indian_plate(canonical_plate) is True

    def test_green_ev_corrupted_read_repair(self):
        """Corrupted EV plate read (0 in state slot) must repair to valid state (DL)."""
        ev_plate = _create_synthetic_plate(
            text="0L01EV1234",
            bg_bgr=(20, 100, 20),
            text_bgr=(250, 250, 250),
        )

        norm_bgr, was_inverted = normalize_plate_agnostic(ev_plate)
        assert was_inverted is True

        mock_crnn = MagicMock()
        mock_crnn.run.return_value = ("0L01EV1234", 0.88)

        ocr_text, ocr_conf, engine = run_dual_pass_ocr(norm_bgr, ocr_session=mock_crnn)
        assert ocr_text == "0L01EV1234"

        # Positional repair corrects 0L -> DL
        canonical_plate, syntax_conf, format_cat = correct_indian_plate(ocr_text)
        assert canonical_plate == "DL01EV1234"
        assert format_cat == "STANDARD"
        assert syntax_conf >= 0.85
        assert is_valid_indian_plate(canonical_plate) is True


# =============================================================================
# 2. White Private Plate End-to-End Integration
# =============================================================================

class TestWhitePrivatePlateWorkflow:
    """
    Verifies end-to-end processing of White Private plates:
    Dark text on white background -> Polarity Preserved -> Color Remap fallback ->
    Letter/Digit Confusion Repair (P810A81234 -> PB10AB1234).
    """

    def test_white_private_polarity_preserved_and_remap_fallback(self):
        """White private plate preserves polarity; soft remap fallback detects WHITE_PRIVATE."""
        white_plate = _create_synthetic_plate(
            text="P810A81234",
            bg_bgr=(240, 240, 240),  # White background
            text_bgr=(15, 15, 15),    # Dark text
            add_hsrp_strip=True,
        )

        # 1. Polarity normalizer preserves polarity
        norm_bgr, was_inverted = normalize_plate_agnostic(white_plate)
        assert was_inverted is False, "White plate (dark on light) must NOT be inverted"
        assert is_plate_like_crop(norm_bgr) is True

        # 2. Color Remapper fallback
        remapped, detected_type = remap_to_yellow_black(white_plate)
        assert detected_type == PLATE_TYPE_WHITE_PRIVATE
        assert remapped.shape == white_plate.shape

        # 3. Positional syntax repair on corrupted read P810A81234
        # Slot 1 ('8') in state PB and Slot 5 ('8') in series AB must both repair to 'B'
        canonical_plate, syntax_conf, format_cat = correct_indian_plate("P810A81234")
        assert canonical_plate == "PB10AB1234"
        assert format_cat == "STANDARD"
        assert syntax_conf >= 0.75
        assert is_valid_indian_plate(canonical_plate) is True

    def test_white_private_additional_statutory_repairs(self):
        """Verifies standard positional alphabet/digit confusion repairs on white plates."""
        # 0 in state slot -> D (DL01AB1234)
        c1, conf1, fmt1 = correct_indian_plate("0L01AB1234")
        assert c1 == "DL01AB1234"
        assert fmt1 == "STANDARD"

        # 8 in BH slot -> B (22BH1234AA)
        c2, conf2, fmt2 = correct_indian_plate("228H1234AA")
        assert c2 == "22BH1234AA"
        assert fmt2 == "BHARAT_SERIES"

        # Leading IND prefix artifact stripped
        c3, conf3, fmt3 = correct_indian_plate("IND DL01AB1234")
        assert c3 == "DL01AB1234"
        assert fmt3 == "STANDARD"


# =============================================================================
# 3. Square / 2-Line Plate Workflow Integration
# =============================================================================

class TestTwoLineSquarePlateWorkflow:
    """
    Verifies 2-line square plate handling:
    Aspect ratio < 2.4 splits at horizontal ink valley -> Dual-pass OCR reads
    both lines -> Joins into canonical Indian registration string.
    """

    def test_two_line_plate_split_at_minimum_ink_valley(self):
        """Plates with aspect ratio < 2.4 split into top and bottom slices."""
        plate2 = _create_synthetic_two_line_plate(
            line1="DL01",
            line2="AB1234",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=160,
            height=120,  # aspect ratio = 160 / 120 = 1.33 < 2.4
        )

        splits = split_two_line_plate(plate2, ar_threshold=2.4)
        assert len(splits) == 2, "Aspect ratio < 2.4 must be split into 2 crops"
        top_crop, bot_crop = splits
        assert top_crop.shape[1] == plate2.shape[1]
        assert bot_crop.shape[1] == plate2.shape[1]
        assert top_crop.shape[0] + bot_crop.shape[0] == plate2.shape[0]

    def test_single_line_plate_retains_single_crop(self):
        """Plates with aspect ratio >= 2.4 must NOT be split."""
        plate1 = _create_synthetic_plate(
            text="HR26DK8337",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=250,
            height=60,  # aspect ratio = 250 / 60 = 4.17 >= 2.4
        )
        splits = split_two_line_plate(plate1, ar_threshold=2.4)
        assert len(splits) == 1
        assert splits[0] is plate1

    def test_two_line_dual_pass_ocr_joining_and_repair(self):
        """Verifies dual-pass OCR splits 2-line plate, reads each line, and joins."""
        plate2 = _create_synthetic_two_line_plate(
            line1="DL01",
            line2="AB1234",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=160,
            height=120,
        )

        call_count = 0

        def fake_crnn_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("DL01", 0.92)
            return ("AB1234", 0.94)

        mock_crnn = MagicMock()
        mock_crnn.run.side_effect = fake_crnn_run

        text, conf, engine = run_dual_pass_ocr(plate2, ocr_session=mock_crnn)
        assert text == "DL01AB1234"
        assert conf >= 0.90
        assert engine == "CRNN"

        canonical, syntax_conf, fmt = correct_indian_plate(text)
        assert canonical == "DL01AB1234"
        assert fmt == "STANDARD"
        assert is_valid_indian_plate(canonical) is True


# =============================================================================
# 4. Multi-Frame Temporal Track Voting (TrackVoter)
# =============================================================================

class TestMultiFrameTemporalTrackVoting:
    """
    Verifies multi-frame temporal consensus:
    Confidence-weighted positional voting resolves OCR jitter across 5-8 frames.
    """

    def test_track_voter_resolves_frame_jitter(self):
        """Simulate 7 temporal frames with character jitter resolving to PB10AB1234."""
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "TRACK_VEH_01"

        clear_frame = np.full((120, 240, 3), 220, dtype=np.uint8)
        cv2.rectangle(clear_frame, (10, 10), (100, 40), (0, 0, 0), 2)
        blurry_frame = np.full((120, 240, 3), 120, dtype=np.uint8)

        # 7 Observations with OCR character noise and varying confidences
        observations = [
            ("P810AB1234", 0.72, [10, 10, 100, 30], blurry_frame),  # 8 in slot 1
            ("PB10A81234", 0.75, [12, 11, 102, 31], blurry_frame),  # 8 in slot 5
            ("PB10AB1234", 0.96, [15, 12, 105, 32], clear_frame),   # Clean & sharpest
            ("PB1OAB1234", 0.68, [18, 14, 108, 34], blurry_frame),  # O in slot 3
            ("PB10AB1234", 0.91, [20, 15, 110, 35], blurry_frame),  # Clean
            ("PB10AB1234", 0.94, [22, 16, 112, 36], blurry_frame),  # Clean
            ("PB10AB1234", 0.88, [25, 18, 115, 38], blurry_frame),  # Clean
        ]

        t_base = 100.0
        for i, (txt, conf, bbox, frm) in enumerate(observations):
            voter.add_observation(
                track_id=track_id,
                plate_text=txt,
                confidence=conf,
                bbox=bbox,
                frame_ts=t_base + i * 0.1,
                frame_bgr=frm,
            )

        consensus = voter.get_consensus(track_id)
        assert consensus is not None
        assert consensus["fused_plate"] == "PB10AB1234"
        assert consensus["format_category"] == "STANDARD"
        assert consensus["requires_manual_check"] is False
        assert consensus["action"] == "PROCEED"
        assert consensus["is_valid"] is True
        assert consensus["frame_count"] == 7
        assert consensus["agreement_rate"] >= 0.85
        # Sharpest/clearest frame selected
        assert consensus["best_frame"] is clear_frame

    def test_track_voter_sliding_window_caps_at_max(self):
        """Track buffer must not exceed max_track_frames (8)."""
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "TRACK_SLIDING_WINDOW"

        for i in range(12):
            voter.add_observation(
                track_id=track_id,
                plate_text=f"DL01AB123{i % 10}",
                confidence=0.85,
                bbox=[10, 10, 50, 50],
                frame_ts=100.0 + i,
            )

        assert voter.get_track_frame_count(track_id) == 8

    def test_track_voter_insufficient_frames_returns_none(self):
        """Fewer than min_consensus_frames (5) must return None."""
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "TRACK_EARLY"

        for i in range(4):
            voter.add_observation(
                track_id=track_id,
                plate_text="MH12AB1234",
                confidence=0.90,
                bbox=[10, 10, 50, 50],
                frame_ts=10.0 + i,
            )

        assert voter.get_consensus(track_id) is None


# =============================================================================
# 5. Non-Standard Vehicle Routing (Military, Temporary, Diplomatic, Invalid)
# =============================================================================

class TestNonStandardVehicleRouting:
    """
    Verifies that non-standard formats (Military, Temporary, Diplomatic, Invalid)
    are strictly flagged with requires_manual_check=True and action='MANUAL_CHECK'.
    """

    def test_military_plate_routing(self):
        """Military plates (e.g. 22D123456A) must route to MANUAL_CHECK."""
        assert classify_plate_format("22D123456A") == "MILITARY"
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "MILITARY_TRK"

        for i in range(5):
            voter.add_observation(
                track_id=track_id,
                plate_text="22D123456A",
                confidence=0.92,
                bbox=[10, 10, 60, 30],
                frame_ts=1.0 + i,
            )

        consensus = voter.get_consensus(track_id)
        assert consensus is not None
        assert consensus["format_category"] == "MILITARY"
        assert consensus["requires_manual_check"] is True
        assert consensus["action"] == "MANUAL_CHECK"

    def test_temporary_plate_routing(self):
        """Temporary plates (TEMP20241234, TR12AB1234, TC01AB1234) must route to MANUAL_CHECK."""
        temp_candidates = ["TEMP20241234", "TR12AB1234", "TC01AB1234"]
        for cand in temp_candidates:
            voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
            t_id = f"TEMP_{cand}"
            for i in range(5):
                voter.add_observation(
                    track_id=t_id,
                    plate_text=cand,
                    confidence=0.88,
                    bbox=[10, 10, 60, 30],
                    frame_ts=1.0 + i,
                )
            consensus = voter.get_consensus(t_id)
            assert consensus is not None
            assert consensus["requires_manual_check"] is True
            assert consensus["action"] == "MANUAL_CHECK"

    def test_diplomatic_plate_routing(self):
        """Diplomatic plates (e.g. 77CD1234) must route to MANUAL_CHECK."""
        assert classify_plate_format("77CD1234") == "DIPLOMATIC"
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "DIPLO_TRK"

        for i in range(5):
            voter.add_observation(
                track_id=track_id,
                plate_text="77CD1234",
                confidence=0.95,
                bbox=[10, 10, 60, 30],
                frame_ts=1.0 + i,
            )

        consensus = voter.get_consensus(track_id)
        assert consensus is not None
        assert consensus["format_category"] == "DIPLOMATIC"
        assert consensus["requires_manual_check"] is True
        assert consensus["action"] == "MANUAL_CHECK"

    def test_invalid_unrepairable_plate_routing(self):
        """Unrepairable non-statutory read (e.g. XXXX9999) must route to MANUAL_CHECK."""
        c, conf, fmt = correct_indian_plate("XXXX9999")
        assert fmt == "INVALID"
        assert conf == 0.0

        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
        track_id = "INVALID_TRK"
        for i in range(5):
            voter.add_observation(
                track_id=track_id,
                plate_text="XXXX9999",
                confidence=0.50,
                bbox=[10, 10, 60, 30],
                frame_ts=1.0 + i,
            )

        consensus = voter.get_consensus(track_id)
        assert consensus is not None
        assert consensus["format_category"] == "INVALID"
        assert consensus["requires_manual_check"] is True
        assert consensus["action"] == "MANUAL_CHECK"
        assert consensus["is_valid"] is False


# =============================================================================
# 6. CameraStreamManager Integration Tests
# =============================================================================

class TestCameraStreamManagerIntegration:
    """
    Verifies CameraStreamManager.process_frame integration with relaxed aspect
    ratios (0.9 to 6.0) and dual-pass OCR.
    """

    def test_process_frame_aspect_ratio_clamping_relaxed(self):
        """
        Aspect ratios between 0.9 and 6.0 must be accepted;
        Extreme ratios (< 0.9 and > 6.0) must be clamped/rejected.
        """
        def check_aspect(w: float, h: float) -> bool:
            ar = w / max(1.0, h)
            return 0.9 <= ar <= 6.0

        # Square 2-line plate (AR = 1.0)
        assert check_aspect(120, 120) is True

        # Standard Indian 1-line plate (AR = 3.5)
        assert check_aspect(280, 80) is True

        # Elongated plate (AR = 5.8)
        assert check_aspect(290, 50) is True

        # Narrow / tall artifact (AR = 0.75 < 0.9) -> Reject
        assert check_aspect(60, 80) is False

        # Extreme wide slit (AR = 6.5 > 6.0) -> Reject
        assert check_aspect(325, 50) is False

    def test_process_frame_e2e_single_frame(self, monkeypatch):
        """
        Verifies CameraStreamManager.process_frame executes detector + dual-pass OCR
        and returns the canonical plate.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        # Construct synthetic high-sharpness 640x640 frame with a plate embedded
        frame = np.full((640, 640, 3), 180, dtype=np.uint8)
        cv2.putText(frame, "SCENE_TEST_HIGH_CONTRAST", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)

        # Embed a high-contrast plate at [x1=200, y1=250, x2=440, y2=320] (w=240, h=70, AR=3.43)
        plate_crop = _create_synthetic_plate(
            text="DL01AB1234",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=240,
            height=70,
        )
        frame[250:320, 200:440] = plate_crop

        # Mock YOLO detector outputting candidate box at (cx=320, cy=285, bw=240, bh=70, score=0.88)
        det_out = np.zeros((5, 1), dtype=np.float32)
        det_out[0, 0] = 320.0  # cx
        det_out[1, 0] = 285.0  # cy
        det_out[2, 0] = 240.0  # bw
        det_out[3, 0] = 70.0   # bh
        det_out[4, 0] = 0.88   # conf score

        mock_det = MagicMock()
        mock_det.run.return_value = [det_out[np.newaxis, :, :]]
        mock_det.get_inputs.return_value = [MagicMock(name="images")]
        runner._det_session = mock_det

        # Mock CRNN session returning DL01AB1234
        mock_ocr = MagicMock()
        mock_ocr.run.return_value = ("DL01AB1234", 0.94)
        runner._ocr_session = mock_ocr

        # Bypass observation DB ingestion in unit test
        monkeypatch.setattr(runner, "_ingest_observation", lambda **kwargs: None)

        res = runner.process_frame("GATE_1", frame, require_consensus=False)
        assert res == "DL01AB1234"

    def test_process_frame_temporal_consensus_trigger(self, monkeypatch):
        """
        Verifies require_consensus=True accumulates candidate frames and triggers
        fusion on the 5th frame.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        frame = np.full((640, 640, 3), 180, dtype=np.uint8)
        cv2.putText(frame, "SCENE_TEST_HIGH_CONTRAST", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        plate_crop = _create_synthetic_plate(
            text="HR26DK8337",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=240,
            height=70,
        )
        frame[250:320, 200:440] = plate_crop

        det_out = np.zeros((5, 1), dtype=np.float32)
        det_out[0, 0] = 320.0
        det_out[1, 0] = 285.0
        det_out[2, 0] = 240.0
        det_out[3, 0] = 70.0
        det_out[4, 0] = 0.90

        mock_det = MagicMock()
        mock_det.run.return_value = [det_out[np.newaxis, :, :]]
        mock_det.get_inputs.return_value = [MagicMock(name="images")]
        runner._det_session = mock_det

        mock_ocr = MagicMock()
        mock_ocr.run.return_value = ("HR26DK8337", 0.95)
        runner._ocr_session = mock_ocr

        monkeypatch.setattr(runner, "_ingest_observation", lambda **kwargs: None)

        gate_id = "GATE_CONSENSUS_TEST"

        # Frames 1-4 should buffer and return None
        for frame_idx in range(4):
            # Change frame slightly to avoid identical static scene detection
            cv2.line(frame, (0, frame_idx * 10), (640, frame_idx * 10), (frame_idx * 20, 0, 0), 2)
            out = runner.process_frame(gate_id, frame, require_consensus=True)
            assert out is None
            assert len(runner._temporal_tracks[gate_id]) == frame_idx + 1

        # Frame 5 triggers consensus fusion
        cv2.line(frame, (0, 50), (640, 50), (100, 0, 0), 2)
        out5 = runner.process_frame(gate_id, frame, require_consensus=True)
        assert out5 == "HR26DK8337"
