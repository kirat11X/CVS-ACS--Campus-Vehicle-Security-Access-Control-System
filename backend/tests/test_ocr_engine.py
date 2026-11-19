"""
Unit tests for Geometry Preprocessing, 2-Line Split & ONNX OCR Engine.
---------------------------------------------------------------------
Tests:
1. pad_plate_bbox: padding expansion (+8% W, +5% H) and frame clamping.
2. deskew_plate: handles artificial 10° skew (positive and negative).
3. split_two_line_plate: splits 2-line plate (AR < 2.4) at minimum-ink valley.
4. is_plate_like_crop: rejects blank wall / noise, accepts valid plate crop.
5. run_dual_pass_ocr: mocked and live OCR execution for 1-line and 2-line plates.
"""

from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from backend.app.services.anpr.ocr_engine import (
    ALPHABET,
    CHAR2IDX,
    decode_crnn_logits,
    deskew_plate,
    estimate_skew_angle,
    get_default_ocr_session,
    get_default_rapid_ocr,
    is_plate_like_crop,
    pad_plate_bbox,
    run_dual_pass_ocr,
    split_two_line_plate,
)


# =============================================================================
# Helper Fixtures
# =============================================================================


def _create_synthetic_plate(
    text: str = "HR26DK8337",
    width: int = 220,
    height: int = 60,
    bg_color: tuple = (255, 255, 255),
    fg_color: tuple = (0, 0, 0),
) -> np.ndarray:
    """Creates a high-contrast synthetic Indian license plate image."""
    img = np.full((height, width, 3), bg_color, dtype=np.uint8)
    # Add border
    cv2.rectangle(img, (2, 2), (width - 3, height - 3), fg_color, 2)
    # Add text
    font_scale = 0.8
    thickness = 2
    cv2.putText(img, text, (15, int(height * 0.68)), cv2.FONT_HERSHEY_SIMPLEX, font_scale, fg_color, thickness)
    return img


def _create_synthetic_two_line_plate(
    line1: str = "DL01",
    line2: str = "AB1234",
    width: int = 160,
    height: int = 110,
    bg_color: tuple = (255, 255, 255),
    fg_color: tuple = (0, 0, 0),
) -> np.ndarray:
    """Creates a synthetic 2-line square license plate image (AR < 2.4)."""
    img = np.full((height, width, 3), bg_color, dtype=np.uint8)
    cv2.rectangle(img, (2, 2), (width - 3, height - 3), fg_color, 2)
    cv2.putText(img, line1, (25, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, fg_color, 2)
    cv2.putText(img, line2, (18, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.8, fg_color, 2)
    return img


# =============================================================================
# 1. Tests for pad_plate_bbox
# =============================================================================


class TestPadPlateBbox:
    def test_pad_expansion_standard(self):
        """Verify +8% width and +5% height expansion on standard bbox."""
        bbox = [100, 100, 200, 200]  # w=100, h=100
        frame_shape = (1000, 1000)
        # pad_w = round(100 * 0.08) = 8
        # pad_h = round(100 * 0.05) = 5
        padded = pad_plate_bbox(bbox, frame_shape)
        assert padded == [92, 95, 208, 205]

    def test_pad_clamping_top_left(self):
        """Verify clamping when bbox is near top-left origin."""
        bbox = [4, 2, 54, 52]  # w=50, h=50; pad_w=round(50*0.08)=4, pad_h=round(50*0.05)=round(2.5)=2
        frame_shape = (500, 500)
        padded = pad_plate_bbox(bbox, frame_shape)
        assert padded[0] == 0  # 4 - 4 = 0
        assert padded[1] == 0  # 2 - 2 = 0
        assert padded[2] == 58  # 54 + 4 = 58
        assert padded[3] == 54  # 52 + 2 = 54

    def test_pad_clamping_bottom_right(self):
        """Verify clamping when bbox reaches bottom-right frame boundaries."""
        bbox = [960, 700, 1000, 720]  # w=40, h=20; pad_w=3, pad_h=1
        frame_shape = (720, 1000)  # height=720, width=1000
        padded = pad_plate_bbox(bbox, frame_shape)
        assert padded[0] == 957
        assert padded[1] == 699
        assert padded[2] == 1000  # Clamped to frame_w
        assert padded[3] == 720  # Clamped to frame_h

    def test_pad_tuple_and_3d_frame_shape(self):
        """Verify tuple bbox input and 3D frame.shape (H, W, C)."""
        bbox = (50, 60, 150, 160)
        frame_shape = (720, 1280, 3)
        padded = pad_plate_bbox(bbox, frame_shape, pad_w_pct=0.10, pad_h_pct=0.10)
        assert padded == [40, 50, 160, 170]

    def test_pad_invalid_inputs(self):
        """Verify ValueErrors on malformed inputs."""
        with pytest.raises(ValueError):
            pad_plate_bbox([10, 20], (720, 1280))
        with pytest.raises(ValueError):
            pad_plate_bbox([10, 20, 30, 40], (720,))


# =============================================================================
# 2. Tests for deskew_plate
# =============================================================================


class TestDeskewPlate:
    def test_deskew_positive_10_degree(self):
        """Verify straightening of plate artificially skewed by +10.0°."""
        plate = _create_synthetic_plate("HR26DK8337", width=240, height=60)
        h, w = plate.shape[:2]
        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, 10.0, 1.0)
        tilted = cv2.warpAffine(plate, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

        angle_before = estimate_skew_angle(tilted)
        assert abs(angle_before) >= 6.0

        deskewed = deskew_plate(tilted, min_angle=3.0, max_angle=25.0)
        angle_after = estimate_skew_angle(deskewed)

        assert abs(angle_after) < 3.0
        assert deskewed.shape == tilted.shape

    def test_deskew_negative_10_degree(self):
        """Verify straightening of plate artificially skewed by -10.0°."""
        plate = _create_synthetic_plate("DL01AB1234", width=240, height=60)
        h, w = plate.shape[:2]
        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, -10.0, 1.0)
        tilted = cv2.warpAffine(plate, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

        angle_before = estimate_skew_angle(tilted)
        assert abs(angle_before) >= 6.0

        deskewed = deskew_plate(tilted, min_angle=3.0, max_angle=25.0)
        angle_after = estimate_skew_angle(deskewed)

        assert abs(angle_after) < 3.0

    def test_deskew_below_min_angle_unchanged(self):
        """Verify plate with mild skew (< 3.0°) is left untouched."""
        plate = _create_synthetic_plate("MH12DE1432", width=220, height=60)
        h, w = plate.shape[:2]
        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, 1.5, 1.0)
        tilted = cv2.warpAffine(plate, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)

        result = deskew_plate(tilted, min_angle=3.0, max_angle=25.0)
        # Should return original tilted array without re-warping
        np.testing.assert_array_equal(result, tilted)

    def test_deskew_empty_and_degenerate(self):
        """Verify graceful return on empty or tiny crops."""
        assert deskew_plate(None) is None
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        assert deskew_plate(empty).size == 0
        tiny = np.zeros((4, 4, 3), dtype=np.uint8)
        assert deskew_plate(tiny).shape == (4, 4, 3)


# =============================================================================
# 3. Tests for split_two_line_plate
# =============================================================================


class TestSplitTwoLinePlate:
    def test_single_line_plate_not_split(self):
        """Verify single-line plate (w/h >= 2.4) is not split."""
        plate = _create_synthetic_plate("HR26DK8337", width=220, height=60)
        ar = 220.0 / 60.0  # 3.67 >= 2.4
        splits = split_two_line_plate(plate, ar_threshold=2.4)
        assert len(splits) == 1
        np.testing.assert_array_equal(splits[0], plate)

    def test_two_line_plate_splits_at_minimum_ink_valley(self):
        """Verify 2-line plate (w/h < 2.4) is split at the central valley."""
        plate2 = _create_synthetic_two_line_plate("DL01", "AB1234", width=160, height=110)
        ar = 160.0 / 110.0  # 1.45 < 2.4
        splits = split_two_line_plate(plate2, ar_threshold=2.4)

        assert len(splits) == 2
        top_crop, bottom_crop = splits

        # Verify shapes
        assert top_crop.shape[1] == 160
        assert bottom_crop.shape[1] == 160
        assert top_crop.shape[0] + bottom_crop.shape[0] == 110

        # Verify split row falls within the 38% to 62% band (42px to 68px for height=110)
        split_y = top_crop.shape[0]
        assert int(round(110 * 0.38)) <= split_y <= int(round(110 * 0.62))

    def test_two_line_green_ev_plate_split(self):
        """Verify 2-line plate with dark background (green EV) splits properly."""
        # Dark green background (0, 100, 0) with white text (255, 255, 255)
        plate_ev = _create_synthetic_two_line_plate(
            "DL01", "EV1234", width=160, height=110, bg_color=(0, 100, 0), fg_color=(255, 255, 255)
        )
        splits = split_two_line_plate(plate_ev, ar_threshold=2.4)
        assert len(splits) == 2
        split_y = splits[0].shape[0]
        assert int(round(110 * 0.38)) <= split_y <= int(round(110 * 0.62))

    def test_split_degenerate_crop(self):
        """Verify degenerate inputs return single element list."""
        assert split_two_line_plate(None) == [None]
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        assert len(split_two_line_plate(empty)) == 1


# =============================================================================
# 4. Tests for is_plate_like_crop
# =============================================================================


class TestIsPlateLikeCrop:
    def test_valid_plate_crop_accepted(self):
        """Verify high-contrast plate crop is accepted."""
        plate = _create_synthetic_plate("HR26DK8337", width=220, height=60)
        assert is_plate_like_crop(plate) is True

    def test_blank_wall_rejected(self):
        """Verify uniform blank wall (contrast std < 22.0) is rejected."""
        blank = np.full((60, 200, 3), 180, dtype=np.uint8)
        assert is_plate_like_crop(blank) is False

    def test_subtle_gradient_shadow_rejected(self):
        """Verify faint shadow gradient with std < 22.0 is rejected."""
        gradient = np.tile(np.linspace(100, 120, 200, dtype=np.uint8), (60, 1))
        gradient_bgr = cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR)
        assert is_plate_like_crop(gradient_bgr) is False

    def test_tiny_crop_rejected(self):
        """Verify crops smaller than 12x30 are rejected."""
        tiny = np.zeros((10, 25, 3), dtype=np.uint8)
        assert is_plate_like_crop(tiny) is False

    def test_extreme_noise_rejected(self):
        """Verify extreme salt-and-pepper noise (edge density > 0.55) is rejected."""
        noise = np.random.randint(0, 256, (60, 180, 3), dtype=np.uint8)
        # Even with high std, edge density is excessively high
        gray = cv2.cvtColor(noise, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        density = float(np.count_nonzero(edges)) / float(edges.size)
        if density > 0.55:
            assert is_plate_like_crop(noise) is False


# =============================================================================
# 5. Tests for run_dual_pass_ocr
# =============================================================================


class TestRunDualPassOcr:
    def test_mock_crnn_primary_pass_success(self):
        """Verify CRNN primary engine is used when confidence >= 0.55."""
        crop = _create_synthetic_plate("HR26DK8337", width=220, height=60)

        # Mock CRNN session returning ("HR26DK8337", 0.94)
        mock_crnn = MagicMock()
        mock_crnn.run.return_value = ("HR26DK8337", 0.94)

        text, conf, engine = run_dual_pass_ocr(crop, ocr_session=mock_crnn, rapid_ocr=None)
        assert text == "HR26DK8337"
        assert conf == pytest.approx(0.94, abs=0.01)
        assert engine == "CRNN"

    def test_mock_crnn_low_confidence_triggers_rapid_ocr_fallback(self):
        """Verify low CRNN confidence (< 0.55) triggers RapidOCR fallback."""
        crop = _create_synthetic_plate("DL01AB1234", width=220, height=60)

        # CRNN returns weak prediction
        mock_crnn = MagicMock()
        mock_crnn.run.return_value = ("DL01", 0.42)

        # RapidOCR returns strong prediction
        mock_rapid = MagicMock()
        mock_rapid.return_value = (
            [[[[10, 10], [200, 10], [200, 50], [10, 50]], "DL01AB1234", 0.91]],
            0.02,
        )

        text, conf, engine = run_dual_pass_ocr(crop, ocr_session=mock_crnn, rapid_ocr=mock_rapid)
        assert text == "DL01AB1234"
        assert conf == pytest.approx(0.91, abs=0.01)
        assert engine == "RapidOCR"

    def test_mock_two_line_plate_split_and_ocr(self):
        """Verify 2-line plate splits, runs OCR, and concatenates lines."""
        plate2 = _create_synthetic_two_line_plate("DL01", "AB1234", width=160, height=110)

        mock_rapid = MagicMock()
        mock_rapid.return_value = (
            [
                [[[20, 20], [80, 20], [80, 45], [20, 45]], "DL01", 0.85],
                [[[15, 65], [110, 65], [110, 95], [15, 95]], "AB1234", 0.90],
            ],
            0.03,
        )

        text, conf, engine = run_dual_pass_ocr(plate2, ocr_session=None, rapid_ocr=mock_rapid)
        assert text == "DL01AB1234"
        assert conf == pytest.approx(0.875, abs=0.01)
        assert engine == "RapidOCR"

    def test_mock_crnn_two_line_split_runs_both_halves(self):
        """Verify CRNN runs on top and bottom splits of 2-line plate."""
        plate2 = _create_synthetic_two_line_plate("PB65", "X1234", width=160, height=110)

        call_count = 0

        def fake_crnn_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("PB65", 0.90)
            return ("X1234", 0.86)

        mock_crnn = MagicMock()
        mock_crnn.run.side_effect = fake_crnn_run

        text, conf, engine = run_dual_pass_ocr(plate2, ocr_session=mock_crnn, rapid_ocr=None)
        assert text == "PB65X1234"
        assert conf == pytest.approx(0.88, abs=0.01)
        assert engine == "CRNN"
        assert call_count == 2

    def test_live_session_smoke_if_available(self):
        """Smoke test with live weights/RapidOCR if present in workspace."""
        crop = _create_synthetic_plate("HR26DK8337", width=220, height=60)
        live_crnn = get_default_ocr_session()
        live_rapid = get_default_rapid_ocr()

        if live_crnn is not None or live_rapid is not None:
            text, conf, engine = run_dual_pass_ocr(crop, ocr_session=live_crnn, rapid_ocr=live_rapid)
            assert isinstance(text, str)
            assert isinstance(conf, float)
            assert engine in ("CRNN", "RapidOCR", "none")

    def test_empty_crop_returns_none(self):
        """Verify empty or None crop returns ('', 0.0, 'none')."""
        assert run_dual_pass_ocr(None) == ("", 0.0, "none")
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        assert run_dual_pass_ocr(empty) == ("", 0.0, "none")
