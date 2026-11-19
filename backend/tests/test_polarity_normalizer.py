"""
Unit tests for Color-Agnostic CLAHE + Otsu Polarity Normalizer.
Verifies compliance with research/ANPR_INTERFACE_CONTRACT.md.
"""

import cv2
import numpy as np
import pytest

from backend.app.services.anpr.polarity_normalizer import (
    CENTRAL_ROI_X_MAX_PCT,
    CENTRAL_ROI_X_MIN_PCT,
    CENTRAL_ROI_Y_MAX_PCT,
    CENTRAL_ROI_Y_MIN_PCT,
    get_central_roi_bounds,
    normalize_plate_agnostic,
)


def _draw_synthetic_plate(
    bg_bgr: tuple[int, int, int],
    text_bgr: tuple[int, int, int],
    text: str = "DL01EV1234",
    width: int = 300,
    height: int = 100,
    add_hsrp_strip: bool = True,
    add_black_border: bool = True,
) -> np.ndarray:
    """Helper to synthesize realistic Indian license plates."""
    plate = np.full((height, width, 3), bg_bgr, dtype=np.uint8)

    # Add optional black border around perimeter
    if add_black_border:
        cv2.rectangle(plate, (0, 0), (width - 1, height - 1), (10, 10, 10), 2)

    # Add optional blue HSRP 'IND' strip on the leftmost 14%
    if add_hsrp_strip:
        hsrp_w = int(width * 0.14)
        plate[:, :hsrp_w] = (160, 60, 20)  # BGR blue strip

    # Draw registration characters in the center
    cv2.putText(
        plate,
        text,
        (int(width * 0.18), int(height * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        text_bgr,
        3,
        cv2.LINE_AA,
    )
    return plate


class TestPolarityNormalizer:
    """Test suite for normalize_plate_agnostic."""

    def test_green_ev_plate_triggers_inversion(self):
        """
        Green EV plate (light/white characters on dark green background)
        must trigger auto-inversion (was_inverted == True) so downstream OCR
        receives standard dark characters on light background.
        """
        # Road-standard dark green background and white text
        ev_plate = _draw_synthetic_plate(
            bg_bgr=(25, 95, 25),       # Dark green
            text_bgr=(245, 245, 245),  # White text
            text="DL01EV1234",
            add_hsrp_strip=True,
        )

        norm_bgr, was_inverted = normalize_plate_agnostic(ev_plate)

        assert was_inverted is True, "Green EV plate must be inverted"
        assert norm_bgr.shape == ev_plate.shape
        assert norm_bgr.dtype == np.uint8

        # After inversion, characters should be darker than background
        # Background pixel sample in central region (away from text)
        bg_sample = int(np.mean(norm_bgr[25:35, 100:150]))
        # Text pixel sample (where text strokes were drawn)
        text_sample = int(np.min(norm_bgr[50:70, 70:220]))
        assert text_sample < bg_sample, "Characters must be darker than background after inversion"

    def test_standard_white_plate_preserves_polarity(self):
        """
        Standard private vehicle plate (black characters on white background)
        must preserve polarity (was_inverted == False).
        """
        white_plate = _draw_synthetic_plate(
            bg_bgr=(240, 240, 240),  # White background
            text_bgr=(20, 20, 20),   # Black text
            text="HR26DK8338",
            add_hsrp_strip=True,
        )

        norm_bgr, was_inverted = normalize_plate_agnostic(white_plate)

        assert was_inverted is False, "White plate must NOT be inverted"
        assert norm_bgr.shape == white_plate.shape
        assert norm_bgr.dtype == np.uint8

        # Characters remain darker than background
        bg_sample = int(np.mean(norm_bgr[25:35, 100:150]))
        text_sample = int(np.min(norm_bgr[50:70, 70:220]))
        assert text_sample < bg_sample, "Characters must remain darker than background"

    def test_yellow_commercial_plate_preserves_polarity(self):
        """
        Yellow commercial taxi/transport plate (black characters on yellow background)
        must preserve polarity (was_inverted == False).
        """
        yellow_plate = _draw_synthetic_plate(
            bg_bgr=(0, 215, 255),  # Taxi Yellow (BGR)
            text_bgr=(20, 20, 20), # Black text
            text="DL01T1234",
            add_hsrp_strip=True,
        )

        norm_bgr, was_inverted = normalize_plate_agnostic(yellow_plate)

        assert was_inverted is False, "Yellow commercial plate must NOT be inverted"
        assert norm_bgr.shape == yellow_plate.shape
        assert norm_bgr.dtype == np.uint8

        # Characters remain darker than background
        bg_sample = int(np.mean(norm_bgr[25:35, 100:150]))
        text_sample = int(np.min(norm_bgr[50:70, 70:220]))
        assert text_sample < bg_sample, "Characters must remain darker than background"

    def test_central_roi_bounds(self):
        """
        Verifies that get_central_roi_bounds calculates y: 15%-85% and x: 15%-92%
        accurately across multiple resolutions.
        """
        # 100x300
        y1, y2, x1, x2 = get_central_roi_bounds(100, 300)
        assert y1 == int(round(100 * CENTRAL_ROI_Y_MIN_PCT))  # 15
        assert y2 == int(round(100 * CENTRAL_ROI_Y_MAX_PCT))  # 85
        assert x1 == int(round(300 * CENTRAL_ROI_X_MIN_PCT))  # 45
        assert x2 == int(round(300 * CENTRAL_ROI_X_MAX_PCT))  # 276

        # 75x250
        y1, y2, x1, x2 = get_central_roi_bounds(75, 250)
        assert (y1, y2) == (11, 64)
        assert (x1, x2) == (38, 230)

        # Degenerate tiny image bounds fallback
        y1, y2, x1, x2 = get_central_roi_bounds(1, 1)
        assert (y1, y2, x1, x2) == (0, 1, 0, 1)

    def test_border_artifacts_and_hsrp_strip_do_not_skew_polarity(self):
        """
        Tests that peripheral artifacts (mounting screws, outer black borders,
        and leftmost blue HSRP strip) are excluded by the central ROI and do
        not distort Otsu thresholding or polarity inversion.
        """
        # White plate with severe peripheral dark artifacts:
        # e.g., heavy top/bottom black borders and large black mounting bolts
        white_plate = np.full((100, 300, 3), (240, 240, 240), dtype=np.uint8)
        # Heavy border at top and bottom (outside central ROI y: 15%-85%)
        white_plate[:14, :] = (0, 0, 0)
        white_plate[86:, :] = (0, 0, 0)
        # Heavy blue strip on left (outside central ROI x: 15%-92%)
        white_plate[:, :44] = (180, 50, 10)
        # Black mounting screws on far right edge
        white_plate[40:60, 280:] = (0, 0, 0)
        # Text inside central ROI
        cv2.putText(white_plate, "PB65AB1234", (55, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)

        _, was_inverted = normalize_plate_agnostic(white_plate)
        assert was_inverted is False, "Peripheral border/screw artifacts must not cause false inversion"

        # Green EV plate with peripheral bright artifacts:
        # e.g. bright mounting screws and white outer frame
        green_plate = np.full((100, 300, 3), (25, 90, 25), dtype=np.uint8)
        green_plate[:14, :] = (255, 255, 255)
        green_plate[86:, :] = (255, 255, 255)
        green_plate[:, :44] = (255, 255, 255)
        green_plate[40:60, 280:] = (255, 255, 255)
        cv2.putText(green_plate, "KA03EV9999", (55, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245), 3)

        _, was_inverted = normalize_plate_agnostic(green_plate)
        assert was_inverted is True, "Peripheral bright artifacts must not prevent EV plate inversion"

    def test_contrast_stretching_expands_dynamic_range(self):
        """
        Tests that 2nd–98th percentile contrast stretching expands a low-contrast
        input into the full [0, 255] dynamic range.
        """
        # Low-contrast image where pixel values only span [110, 135]
        low_contrast = np.full((100, 300, 3), 135, dtype=np.uint8)
        cv2.putText(low_contrast, "DL10AB5678", (50, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (110, 110, 110), 3)

        norm_bgr, _ = normalize_plate_agnostic(low_contrast)

        # Contrast should be significantly stretched
        assert norm_bgr.min() <= 5, f"Expected min near 0, got {norm_bgr.min()}"
        assert norm_bgr.max() >= 250, f"Expected max near 255, got {norm_bgr.max()}"

    def test_flat_uniform_image_safe(self):
        """
        Tests that flat/uniform inputs where p2 == p98 do not cause division by zero.
        """
        flat = np.full((80, 200, 3), 128, dtype=np.uint8)
        norm_bgr, was_inverted = normalize_plate_agnostic(flat)
        assert norm_bgr.shape == (80, 200, 3)
        assert not np.isnan(norm_bgr).any()

    def test_edge_cases_input_types(self):
        """
        Tests handling of None, empty array, 2D grayscale, and 4-channel BGRA images.
        """
        # None input
        res, inv = normalize_plate_agnostic(None)
        assert res is None and inv is False

        # Empty array
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        res, inv = normalize_plate_agnostic(empty)
        assert res.size == 0 and inv is False

        # 2D grayscale image
        gray = np.full((100, 300), 240, dtype=np.uint8)
        cv2.putText(gray, "DL01AB1234", (50, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 20, 3)
        res, inv = normalize_plate_agnostic(gray)
        assert res.shape == (100, 300, 3)
        assert inv is False

        # 4-channel BGRA image
        bgra = np.full((100, 300, 4), (25, 90, 25, 255), dtype=np.uint8)
        cv2.putText(bgra, "DL01EV1234", (50, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245, 255), 3)
        res, inv = normalize_plate_agnostic(bgra)
        assert res.shape == (100, 300, 3)
        assert inv is True
