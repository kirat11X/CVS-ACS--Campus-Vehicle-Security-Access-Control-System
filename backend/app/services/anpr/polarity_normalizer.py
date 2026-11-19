"""
Color-Agnostic CLAHE + Otsu Polarity Normalizer for License Plates.

Adheres strictly to research/ANPR_INTERFACE_CONTRACT.md.
Normalizes Indian license plates (white private, yellow commercial, green EV,
temporary, etc.) into high-contrast dark-text-on-light-background 3-channel BGR
images optimized for downstream OCR engines (CRNN, PP-OCRv4).
"""

from typing import Tuple
import cv2
import numpy as np


# Central ROI sampling percentages to avoid plate borders, mounting screws,
# and the leftmost blue HSRP 'IND' strip.
CENTRAL_ROI_Y_MIN_PCT: float = 0.15
CENTRAL_ROI_Y_MAX_PCT: float = 0.85
CENTRAL_ROI_X_MIN_PCT: float = 0.15
CENTRAL_ROI_X_MAX_PCT: float = 0.92

# Inversion decision threshold: plates with white pixel ratio < 0.45 under Otsu
# have light characters on a dark background (e.g. Green EV plates) and must be inverted.
INVERSION_WHITE_RATIO_THRESHOLD: float = 0.45


def get_central_roi_bounds(height: int, width: int) -> Tuple[int, int, int, int]:
    """
    Computes (y1, y2, x1, x2) pixel coordinates for the central ROI
    (y: 15%-85%, x: 15%-92%) of a plate image.
    """
    y1 = int(round(height * CENTRAL_ROI_Y_MIN_PCT))
    y2 = int(round(height * CENTRAL_ROI_Y_MAX_PCT))
    x1 = int(round(width * CENTRAL_ROI_X_MIN_PCT))
    x2 = int(round(width * CENTRAL_ROI_X_MAX_PCT))

    # Fallback to full image if dimensions are too small or invalid
    if y2 <= y1 or x2 <= x1:
        return 0, max(height, 1), 0, max(width, 1)

    return y1, y2, x1, x2


def normalize_plate_agnostic(
    crop_bgr: np.ndarray,
    clip_limit: float = 2.5,
    tile_grid_size: Tuple[int, int] = (8, 4),
    white_ratio_threshold: float = INVERSION_WHITE_RATIO_THRESHOLD,
) -> Tuple[np.ndarray, bool]:
    """
    Color-agnostic CLAHE + Otsu polarity normalizer.

    1. Extracts L* channel from CIE LAB.
    2. Applies CLAHE (clipLimit=2.5, tileGridSize=(8, 4)).
    3. Computes Otsu threshold on central ROI (y: 15%-85%, x: 15%-92%).
    4. Auto-inverts (255 - L_eq) when white_ratio < 0.45 (green EV plates with light text on dark green bg).
    5. Applies 2nd–98th percentile stretching for optimal OCR contrast.
    6. Converts back to 3-channel BGR image.

    Args:
        crop_bgr: Input cropped license plate image in BGR format.
        clip_limit: Threshold for contrast limiting in CLAHE (default 2.5).
        tile_grid_size: Grid size for CLAHE histogram equalization (default (8, 4)).
        white_ratio_threshold: Threshold below which polarity is inverted (default 0.45).

    Returns:
        tuple[np.ndarray, bool]: (normalized_plate_bgr, was_inverted)
            - normalized_plate_bgr: 3-channel BGR image with dark text on light background.
            - was_inverted: True if polarity was inverted (e.g. green EV plate), False otherwise.
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.ndim < 2:
        return crop_bgr, False

    # Standardize input image channels to 3-channel BGR uint8
    if crop_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_GRAY2BGR)
    elif crop_bgr.shape[2] == 4:
        img_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_BGRA2BGR)
    elif crop_bgr.shape[2] == 1:
        img_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_GRAY2BGR)
    else:
        img_bgr = crop_bgr

    if img_bgr.dtype != np.uint8:
        img_bgr = np.clip(img_bgr, 0, 255).astype(np.uint8)

    # 1. Extract L* channel from CIE LAB
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_chan = lab[:, :, 0]

    # 2. Apply CLAHE (clipLimit=2.5, tileGridSize=(8, 4))
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    l_eq = clahe.apply(l_chan)

    # 3. Sample central ROI for Otsu thresholding: y: 15%-85%, x: 15%-92%
    h, w = l_eq.shape[:2]
    y1, y2, x1, x2 = get_central_roi_bounds(h, w)
    roi = l_eq[y1:y2, x1:x2]

    # 4. Compute Otsu threshold and white pixel ratio on central ROI
    if roi.size == 0:
        roi = l_eq

    _, thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    white_ratio = float(np.mean(thresh == 255))

    # Polarity inversion:
    # If white_ratio < 0.45 (indicates light characters on dark background, such as green EV plates with white text):
    #   Auto-invert using 255 - L_eq (Ensure correct '-' arithmetic operator!).
    #   was_inverted = True
    # Else:
    #   was_inverted = False
    if white_ratio < white_ratio_threshold:
        l_out = (255 - l_eq).astype(np.uint8)
        was_inverted = True
    else:
        l_out = l_eq.copy()
        was_inverted = False

    # 5. Apply 2nd–98th percentile contrast stretching on the resulting L channel:
    #   p2, p98 = np.percentile(L_out, (2, 98))
    #   Stretch [p2, p98] to [0, 255].
    p2, p98 = np.percentile(l_out, (2, 98))
    if p98 > p2:
        stretched = np.clip(
            (l_out.astype(np.float32) - p2) * (255.0 / (p98 - p2)),
            0,
            255,
        ).astype(np.uint8)
    else:
        stretched = l_out.astype(np.uint8)

    # 6. Convert back to 3-channel BGR image so downstream OCR engines can consume it directly
    normalized_plate_bgr = cv2.cvtColor(stretched, cv2.COLOR_GRAY2BGR)

    return normalized_plate_bgr, was_inverted
