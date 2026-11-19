"""
Unit and Regression Tests for ANPR Pipeline Fixes:
---------------------------------------------------
1. Crop-level plate-likeness gate and empty-wall / low-contrast rejection.
2. Positional syntax-constrained Indian plate repair (Bharat Series and Standard State).
3. 2-line plate OCR bounding box sorting (top-to-bottom, left-to-right).
4. Aspect-preserving bicubic upscale and LAB CLAHE preprocessing.
"""

from pathlib import Path
import cv2
import numpy as np
import pytest

from backend.app.services.plate_normalizer import (
    is_valid_indian_plate,
    normalize_plate,
    repair_plate_positional,
    suggest_repairs,
)
from backend.app.workers.camera_stream_runner import (
    is_plate_like_crop,
    preprocess_plate_crop,
    sort_multiline_boxes,
)


# =============================================================================
# (a) Empty-Wall and Low-Contrast Crop Rejection Tests
# =============================================================================

def test_empty_wall_rejection_flat_surface():
    """Flat uniform crops (e.g., plaster wall, clear sky) must be rejected."""
    # Completely flat 50x150 gray wall (std = 0.0)
    flat_wall = np.full((50, 150, 3), 160, dtype=np.uint8)
    assert not is_plate_like_crop(flat_wall)


def test_empty_wall_rejection_smooth_gradient_shadow():
    """Smooth shadows or gentle lighting gradients across flat walls must be rejected."""
    # Subtle gradient from 100 to 118 across 150 pixels (std ~ 5.2 < 22.0, edge density = 0.0)
    gradient = np.tile(np.linspace(100, 118, 150, dtype=np.uint8), (50, 1))
    gradient_bgr = cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR)
    assert not is_plate_like_crop(gradient_bgr)


def test_empty_wall_rejection_high_frequency_noise():
    """Unstructured high-frequency noise (e.g. gravel, dense wire mesh) must be rejected."""
    # Pure noise with extreme edge density (> 0.55)
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 256, (50, 150, 3), dtype=np.uint8)
    # Binary checkerboard texture causing Canny saturation
    checker = np.zeros((60, 160), dtype=np.uint8)
    checker[::2, ::2] = 255
    checker[1::2, 1::2] = 255
    checker_bgr = cv2.cvtColor(checker, cv2.COLOR_GRAY2BGR)
    assert not is_plate_like_crop(checker_bgr)


def test_plate_likeness_accepts_valid_plate():
    """Real license plate crops must pass the contrast and edge texture gate."""
    test_plate_path = Path("media/test_plate.png")
    if test_plate_path.exists():
        plate_img = cv2.imread(str(test_plate_path))
        assert is_plate_like_crop(plate_img)
    else:
        # Synthetic high-contrast plate crop: white plate with black bold text
        synth = np.full((60, 200, 3), 240, dtype=np.uint8)
        cv2.putText(synth, "DL01AB1234", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (10, 10, 10), 3)
        assert is_plate_like_crop(synth)


def test_plate_likeness_rejects_undersized_crops():
    """Crops smaller than minimum physical dimensions (12x30) must be rejected."""
    tiny = np.ones((10, 25, 3), dtype=np.uint8)
    assert not is_plate_like_crop(tiny)
    assert not is_plate_like_crop(None)
    assert not is_plate_like_crop(np.array([]))


# =============================================================================
# (b) Positional Alphabet Repair Tests
# =============================================================================

def test_positional_repair_standard_state_p810a81234():
    """P810A81234 has 8 in letter positions 1 and 5 -> must repair to PB10AB1234."""
    raw = "P810A81234"
    repaired = repair_plate_positional(raw)
    assert repaired == "PB10AB1234"
    assert is_valid_indian_plate(repaired)

    suggestions = suggest_repairs(raw)
    assert len(suggestions) > 0
    assert suggestions[0] == "PB10AB1234"


def test_positional_repair_delhi_state_0l01ab1234():
    """0L01AB1234 has 0 in state slot -> must resolve to DL (Delhi) as OL is not a valid state."""
    raw = "0L01AB1234"
    repaired = repair_plate_positional(raw)
    assert repaired == "DL01AB1234"
    assert is_valid_indian_plate(repaired)

    suggestions = suggest_repairs(raw)
    assert len(suggestions) > 0
    assert suggestions[0] == "DL01AB1234"


def test_positional_repair_preserves_valid_bharat_series():
    """Already valid Bharat Series plates (22BH1234AA) must be strictly preserved without modification."""
    raw = "22BH1234AA"
    assert is_valid_indian_plate(raw)
    repaired = repair_plate_positional(raw)
    assert repaired == "22BH1234AA"

    # suggest_repairs returns empty list for plates that are already valid
    assert suggest_repairs(raw) == []


def test_positional_repair_bharat_series_confusions():
    """228H1234AA and 22B41234AA must repair to 22BH1234AA."""
    assert repair_plate_positional("228H1234AA") == "22BH1234AA"
    assert repair_plate_positional("22B41234AA") == "22BH1234AA"
    assert suggest_repairs("228H1234AA")[0] == "22BH1234AA"
    assert suggest_repairs("22B41234AA")[0] == "22BH1234AA"


def test_positional_repair_rejects_unrepairable_noise():
    """Unrepairable non-Indian or gibberish strings must produce None and empty suggestions."""
    assert repair_plate_positional("XX99ZZ9999") is None
    assert suggest_repairs("XX99ZZ9999") == []

    assert repair_plate_positional("EMPTYWALL") is None
    assert suggest_repairs("EMPTYWALL") == []


# =============================================================================
# (c) 2-Line Box Sorting Tests
# =============================================================================

def test_two_line_box_sorting_inverted_order():
    """When OCR returns the bottom line before the top line, sort_multiline_boxes must fix reading order."""
    crop_h = 80
    # Bottom line box: y in [45, 75], center y = 60
    box_bottom = [[10, 45], [190, 45], [190, 75], [10, 75]]
    item_bottom = (box_bottom, "AB1234", 0.94)

    # Top line box: y in [10, 40], center y = 25
    box_top = [[10, 10], [130, 10], [130, 40], [10, 40]]
    item_top = (box_top, "MH12", 0.96)

    # Feed in inverted order
    inverted = [item_bottom, item_top]
    sorted_res = sort_multiline_boxes(inverted, crop_h)

    assert len(sorted_res) == 2
    assert sorted_res[0][1] == "MH12"
    assert sorted_res[1][1] == "AB1234"
    joined = "".join([item[1] for item in sorted_res])
    assert joined == "MH12AB1234"


def test_two_line_box_sorting_multi_word_per_line():
    """Words on the same line must be sorted left-to-right before proceeding to next line."""
    crop_h = 100
    # Line 1: 'MH' at x=10..60, '12' at x=80..130 (y center = 25)
    box_l1_w1 = [[10, 10], [60, 10], [60, 40], [10, 40]]
    box_l1_w2 = [[80, 10], [130, 10], [130, 40], [80, 40]]

    # Line 2: 'AB' at x=10..60, '1234' at x=80..180 (y center = 75)
    box_l2_w1 = [[10, 60], [60, 60], [60, 90], [10, 90]]
    box_l2_w2 = [[80, 60], [180, 60], [180, 90], [80, 90]]

    # Scrambled order
    scrambled = [
        (box_l2_w2, "1234", 0.95),
        (box_l1_w2, "12", 0.93),
        (box_l2_w1, "AB", 0.92),
        (box_l1_w1, "MH", 0.97),
    ]

    sorted_res = sort_multiline_boxes(scrambled, crop_h)
    words = [item[1] for item in sorted_res]
    assert words == ["MH", "12", "AB", "1234"]
    assert "".join(words) == "MH12AB1234"


# =============================================================================
# (d) Preprocessing Tests: Upscale & CLAHE
# =============================================================================

def test_preprocess_upscales_small_crops():
    """Crops with height < 48px must be bicubic-upscaled to 48px while maintaining aspect ratio."""
    small_crop = np.full((24, 120, 3), 150, dtype=np.uint8)
    enhanced = preprocess_plate_crop(small_crop)
    assert enhanced.shape[0] == 48
    assert enhanced.shape[1] == 240


def test_preprocess_clahe_on_dark_crops():
    """Dark or low-contrast crops must receive LAB CLAHE enhancement."""
    # Dark crop with mean brightness ~ 40 < 90
    dark_crop = np.full((50, 150, 3), 40, dtype=np.uint8)
    # Add a slightly brighter patch to represent characters
    dark_crop[20:30, 30:70] = 70

    enhanced = preprocess_plate_crop(dark_crop)
    assert enhanced.shape == dark_crop.shape
    # LAB CLAHE increases dynamic range
    gray_orig = cv2.cvtColor(dark_crop, cv2.COLOR_BGR2GRAY)
    gray_enh = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    assert np.std(gray_enh) >= np.std(gray_orig)
