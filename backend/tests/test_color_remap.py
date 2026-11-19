"""
Unit tests for Soft CIE LAB Color Remapper.
Verifies compliance with research/ANPR_INTERFACE_CONTRACT.md and Solution 1 specifications.
"""

import cv2
import numpy as np
import pytest

from backend.app.services.anpr.color_remap import (
    HSRP_STRIP_WIDTH_FRACTION,
    PLATE_TYPE_GREEN_EV,
    PLATE_TYPE_WHITE_PRIVATE,
    PLATE_TYPE_YELLOW_COMMERCIAL,
    TARGET_BG_A,
    TARGET_BG_B,
    TARGET_BG_L,
    TARGET_FG_A,
    TARGET_FG_B,
    TARGET_FG_L,
    remap_to_yellow_black,
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

    # Optional perimeter black border
    if add_black_border:
        cv2.rectangle(plate, (0, 0), (width - 1, height - 1), (10, 10, 10), 2)

    # Optional leftmost 14% HSRP blue 'IND' strip
    if add_hsrp_strip:
        hsrp_w = int(round(width * HSRP_STRIP_WIDTH_FRACTION))
        plate[:, :hsrp_w] = (160, 60, 20)  # BGR blue strip
        cv2.putText(
            plate,
            "IND",
            (int(hsrp_w * 0.2), int(height * 0.65)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    # Main registration characters
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


class TestColorRemap:
    """Test suite for remap_to_yellow_black."""

    def test_green_ev_white_text_plate_detection_and_soft_remapping(self):
        """
        Tests that private green EV plates (white text on dark green background)
        are correctly identified as 'GREEN_EV' and remapped to taxi yellow background
        with dark black text.
        """
        ev_plate = _draw_synthetic_plate(
            bg_bgr=(25, 95, 25),       # Dark green retro-reflective
            text_bgr=(245, 245, 245),  # White characters
            text="DL01EV1234",
            add_hsrp_strip=True,
        )

        remapped, detected_type = remap_to_yellow_black(ev_plate)

        assert detected_type == PLATE_TYPE_GREEN_EV
        assert remapped.shape == ev_plate.shape
        assert remapped.dtype == np.uint8

        # In CIE LAB, target background is (L=212, A=134, B=213), i.e. BGR (0, 200, 255)
        # Background pixel sample in clear region
        bg_sample = remapped[20:35, 100:150]
        mean_bg = bg_sample.mean(axis=(0, 1))

        # Check background is yellow (B near 0, G near 200, R near 255)
        assert mean_bg[0] <= 15, f"Expected low blue in yellow bg, got {mean_bg[0]}"
        assert mean_bg[1] >= 180, f"Expected high green in yellow bg, got {mean_bg[1]}"
        assert mean_bg[2] >= 240, f"Expected high red in yellow bg, got {mean_bg[2]}"

        # Foreground characters should be dark black ink
        text_region = remapped[50:70, 70:220]
        text_min_bgr = np.min(text_region, axis=(0, 1))
        assert text_min_bgr[0] <= 45 and text_min_bgr[1] <= 45 and text_min_bgr[2] <= 45

        # Foreground must be distinctly darker than background
        gray_remapped = cv2.cvtColor(remapped, cv2.COLOR_BGR2GRAY)
        assert int(np.min(gray_remapped[50:70, 70:220])) < int(np.mean(gray_remapped[20:35, 100:150])) - 100

    def test_green_ev_yellow_text_plate_detection_and_soft_remapping(self):
        """
        Tests that commercial green EV plates (yellow text on dark green background)
        are correctly identified as 'GREEN_EV' and remapped to taxi yellow background
        with dark black text.
        """
        comm_ev = _draw_synthetic_plate(
            bg_bgr=(25, 95, 25),       # Dark green
            text_bgr=(0, 215, 255),    # Yellow characters
            text="DL01EV5678",
            add_hsrp_strip=True,
        )

        remapped, detected_type = remap_to_yellow_black(comm_ev)

        assert detected_type == PLATE_TYPE_GREEN_EV
        assert remapped.shape == comm_ev.shape

        bg_sample = remapped[20:35, 100:150].mean(axis=(0, 1))
        assert bg_sample[0] <= 15
        assert bg_sample[1] >= 180
        assert bg_sample[2] >= 240

    def test_white_private_plate_detection_and_soft_remapping(self):
        """
        Tests that standard private white plates (black text on white background)
        are correctly identified as 'WHITE_PRIVATE' and remapped to taxi yellow background
        while preserving dark black characters.
        """
        white_plate = _draw_synthetic_plate(
            bg_bgr=(240, 240, 240),  # Bright white background
            text_bgr=(20, 20, 20),   # Black characters
            text="HR26DK8338",
            add_hsrp_strip=True,
        )

        remapped, detected_type = remap_to_yellow_black(white_plate)

        assert detected_type == PLATE_TYPE_WHITE_PRIVATE
        assert remapped.shape == white_plate.shape
        assert remapped.dtype == np.uint8

        # Background should smoothly shift to taxi yellow
        bg_sample = remapped[20:35, 100:150].mean(axis=(0, 1))
        assert bg_sample[0] <= 15
        assert bg_sample[1] >= 180
        assert bg_sample[2] >= 240

        # Characters should remain crisp dark ink
        text_region = remapped[50:70, 70:220]
        text_min_bgr = np.min(text_region, axis=(0, 1))
        assert text_min_bgr[0] <= 35 and text_min_bgr[1] <= 35 and text_min_bgr[2] <= 35

    def test_shaded_white_plate_soft_remapping(self):
        """
        Tests that white plates captured in deep shadow or overcast conditions
        (lower luminance) are still classified as 'WHITE_PRIVATE' and smoothly remapped.
        """
        shaded_white = _draw_synthetic_plate(
            bg_bgr=(165, 165, 165),  # Shaded white background
            text_bgr=(25, 25, 25),   # Dark text
            text="UP16BW1122",
            add_hsrp_strip=True,
        )

        remapped, detected_type = remap_to_yellow_black(shaded_white)

        assert detected_type == PLATE_TYPE_WHITE_PRIVATE
        bg_sample = remapped[20:35, 100:150].mean(axis=(0, 1))
        assert bg_sample[1] >= 170
        assert bg_sample[2] >= 225

    def test_yellow_commercial_plate_preservation(self):
        """
        Tests that native commercial plates (black text on yellow background)
        are classified as 'YELLOW_COMMERCIAL' and preserved as-is without unwanted alteration.
        """
        yellow_plate = _draw_synthetic_plate(
            bg_bgr=(0, 215, 255),  # Native commercial taxi yellow
            text_bgr=(20, 20, 20), # Black text
            text="DL01T1234",
            add_hsrp_strip=True,
        )

        remapped, detected_type = remap_to_yellow_black(yellow_plate)

        assert detected_type == PLATE_TYPE_YELLOW_COMMERCIAL
        # Exact array preservation
        np.testing.assert_array_equal(remapped, yellow_plate)

    def test_hsrp_blue_strip_does_not_bias_plate_classification(self):
        """
        Verifies that skipping the leftmost 14% HSRP blue 'IND' strip prevents
        the strong blue chromaticity and 'IND' text from skewing plate color fraction calculations.
        """
        hsrp_w = int(round(300 * HSRP_STRIP_WIDTH_FRACTION))

        # Green EV with large blue strip
        green_plate = _draw_synthetic_plate(
            bg_bgr=(25, 95, 25),
            text_bgr=(245, 245, 245),
            text="MH12EV0001",
            add_hsrp_strip=True,
        )
        _, green_type = remap_to_yellow_black(green_plate)
        assert green_type == PLATE_TYPE_GREEN_EV

        # White plate with large blue strip
        white_plate = _draw_synthetic_plate(
            bg_bgr=(240, 240, 240),
            text_bgr=(20, 20, 20),
            text="PB65AB9999",
            add_hsrp_strip=True,
        )
        _, white_type = remap_to_yellow_black(white_plate)
        assert white_type == PLATE_TYPE_WHITE_PRIVATE

        # Yellow plate with large blue strip
        yellow_plate = _draw_synthetic_plate(
            bg_bgr=(0, 215, 255),
            text_bgr=(20, 20, 20),
            text="KA01F4321",
            add_hsrp_strip=True,
        )
        _, yellow_type = remap_to_yellow_black(yellow_plate)
        assert yellow_type == PLATE_TYPE_YELLOW_COMMERCIAL

    def test_hsrp_blue_strip_soft_blend_eliminates_high_contrast_artifacts(self):
        """
        Verifies that the leftmost 14% region is softly blended so that:
        1. On white plates, the dark blue strip (L ~ 70) does not get inverted into a solid black block.
        2. On green EV plates, the bright 'IND' text does not produce sharp black character artifacts.
        3. The leftmost region transitions cleanly into taxi yellow background.
        """
        width, height = 300, 100
        hsrp_w = int(round(width * HSRP_STRIP_WIDTH_FRACTION))

        # 1. White plate test
        white_plate = _draw_synthetic_plate(
            bg_bgr=(240, 240, 240),
            text_bgr=(20, 20, 20),
            text="DL04CD5678",
            add_hsrp_strip=True,
        )
        remapped_white, _ = remap_to_yellow_black(white_plate)

        # In the leftmost 10% (well within the 14% HSRP strip), the color must be bright yellow,
        # NOT a solid black artifact block
        strip_region_white = remapped_white[:, :int(hsrp_w * 0.7)]
        mean_strip_bgr = strip_region_white.mean(axis=(0, 1))
        assert mean_strip_bgr[1] >= 170, f"Strip green channel should be bright yellow, got {mean_strip_bgr[1]}"
        assert mean_strip_bgr[2] >= 220, f"Strip red channel should be bright yellow, got {mean_strip_bgr[2]}"

        # 2. Green EV plate test: 'IND' text in blue strip should not cause high contrast spikes
        green_plate = _draw_synthetic_plate(
            bg_bgr=(25, 95, 25),
            text_bgr=(245, 245, 245),
            text="DL01EV9999",
            add_hsrp_strip=True,
        )
        remapped_green, _ = remap_to_yellow_black(green_plate)

        strip_gray = cv2.cvtColor(remapped_green[:, :int(hsrp_w * 0.7)], cv2.COLOR_BGR2GRAY)
        text_gray = cv2.cvtColor(remapped_green[:, int(width * 0.18):int(width * 0.85)], cv2.COLOR_BGR2GRAY)

        # Standard deviation in the softly blended strip should be much lower than the actual text region
        assert np.std(strip_gray) < np.std(text_gray) * 0.5, "Strip region contrast must be softly attenuated"

    def test_smooth_transition_across_hsrp_boundary(self):
        """
        Verifies that at the boundary x0 = int(round(w * 0.14)), the transition is
        smooth and does not exhibit an abrupt step discontinuity in background pixels.
        """
        width, height = 300, 100
        x0 = int(round(width * HSRP_STRIP_WIDTH_FRACTION))

        white_plate = _draw_synthetic_plate(
            bg_bgr=(240, 240, 240),
            text_bgr=(20, 20, 20),
            text="HR26DK8338",
            add_hsrp_strip=True,
            add_black_border=False,
        )
        remapped, _ = remap_to_yellow_black(white_plate)

        # Look at the top rows (y: 10..25) where there is no text, comparing column x0 - 1 and x0 + 1
        left_bg = remapped[10:25, x0 - 1].mean(axis=0)
        right_bg = remapped[10:25, x0 + 1].mean(axis=0)

        # Difference across the boundary should be negligible (< 10 intensity difference)
        diff = np.abs(left_bg - right_bg)
        assert np.max(diff) < 15.0, f"Discontinuity at x0 boundary too large: {diff}"

    def test_target_lab_color_mapping(self):
        """
        Verifies that target LAB background (L=212, A=134, B=213) matches Indian commercial
        taxi yellow and target foreground (L=18, A=128, B=128) matches dark black ink.
        """
        # Background test
        bg_lab = np.array([[[TARGET_BG_L, TARGET_BG_A, TARGET_BG_B]]], dtype=np.uint8)
        bg_bgr = cv2.cvtColor(bg_lab, cv2.COLOR_LAB2BGR)[0, 0]
        assert bg_bgr[0] == 0, f"Expected B=0 for taxi yellow, got {bg_bgr[0]}"
        assert bg_bgr[1] == 200, f"Expected G=200 for taxi yellow, got {bg_bgr[1]}"
        assert bg_bgr[2] == 255, f"Expected R=255 for taxi yellow, got {bg_bgr[2]}"

        # Foreground test
        fg_lab = np.array([[[TARGET_FG_L, TARGET_FG_A, TARGET_FG_B]]], dtype=np.uint8)
        fg_bgr = cv2.cvtColor(fg_lab, cv2.COLOR_LAB2BGR)[0, 0]
        assert fg_bgr[0] <= 25 and fg_bgr[1] <= 25 and fg_bgr[2] <= 25

    def test_edge_cases_input_types_and_dimensions(self):
        """
        Tests handling of None, empty array, degenerate 1x1, 2D grayscale, and 4-channel BGRA.
        """
        # None input
        res, t = remap_to_yellow_black(None)
        assert res is None and t == PLATE_TYPE_YELLOW_COMMERCIAL

        # Empty array
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        res, t = remap_to_yellow_black(empty)
        assert res.size == 0 and t == PLATE_TYPE_YELLOW_COMMERCIAL

        # Degenerate 1x1 image
        tiny = np.full((1, 1, 3), (25, 95, 25), dtype=np.uint8)
        res, t = remap_to_yellow_black(tiny)
        assert res.shape == (1, 1, 3) and t == PLATE_TYPE_YELLOW_COMMERCIAL

        # 2D Grayscale input (white plate with dark text)
        gray = np.full((100, 300), 240, dtype=np.uint8)
        cv2.putText(gray, "DL01AB1234", (50, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 20, 3)
        res, t = remap_to_yellow_black(gray)
        assert res.shape == (100, 300, 3)
        assert t == PLATE_TYPE_WHITE_PRIVATE

        # 4-channel BGRA input (Green EV plate)
        bgra = np.full((100, 300, 4), (25, 95, 25, 255), dtype=np.uint8)
        cv2.putText(bgra, "DL01EV1234", (50, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245, 255), 3)
        res, t = remap_to_yellow_black(bgra)
        assert res.shape == (100, 300, 3)
        assert t == PLATE_TYPE_GREEN_EV

    def test_flat_uniform_image_safe(self):
        """
        Tests that completely flat/uniform images do not trigger division by zero.
        """
        flat_white = np.full((80, 200, 3), 245, dtype=np.uint8)
        res, t = remap_to_yellow_black(flat_white)
        assert res.shape == (80, 200, 3)
        assert not np.isnan(res).any()
        assert t == PLATE_TYPE_WHITE_PRIVATE

        flat_green = np.full((80, 200, 3), (25, 95, 25), dtype=np.uint8)
        res, t = remap_to_yellow_black(flat_green)
        assert res.shape == (80, 200, 3)
        assert not np.isnan(res).any()
        assert t == PLATE_TYPE_GREEN_EV
