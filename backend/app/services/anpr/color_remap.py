"""
Soft CIE LAB Color Remapper for License Plates.

Adheres strictly to research/ANPR_INTERFACE_CONTRACT.md.
Transforms White Private and Green EV (white-on-green and yellow-on-green)
Indian license plates into standard commercial taxi yellow-background and
black-ink text in CIE LAB space, while preserving native yellow commercial plates
and softly blending the leftmost 14% HSRP blue 'IND' strip.
"""

from typing import Tuple
import cv2
import numpy as np

# Detected plate categories as defined in research/ANPR_INTERFACE_CONTRACT.md
PLATE_TYPE_GREEN_EV: str = "GREEN_EV"
PLATE_TYPE_WHITE_PRIVATE: str = "WHITE_PRIVATE"
PLATE_TYPE_YELLOW_COMMERCIAL: str = "YELLOW_COMMERCIAL"

# Target CIE LAB coordinates for Indian commercial taxi yellow background and black ink
TARGET_BG_L: float = 212.0
TARGET_BG_A: float = 134.0
TARGET_BG_B: float = 213.0

TARGET_FG_L: float = 18.0
TARGET_FG_A: float = 128.0
TARGET_FG_B: float = 128.0

# Central ROI bounds to skip peripheral noise and the leftmost blue HSRP 'IND' strip
HSRP_STRIP_WIDTH_FRACTION: float = 0.14
CENTRAL_ROI_X_MAX_FRACTION: float = 0.95


def remap_to_yellow_black(crop_bgr: np.ndarray) -> Tuple[np.ndarray, str]:
    """
    Remaps green EV (light on dark) or white private (dark on light) plates into standard
    yellow-background / black-text in CIE LAB space.

    1. Skips the leftmost 14% HSRP blue 'IND' strip (x0 = int(w * 0.14)).
    2. Measures color fractions:
       - green_fraction > 0.30 -> 'GREEN_EV'
       - yellow_fraction < 0.25 and high luminance -> 'WHITE_PRIVATE'
       - otherwise -> 'YELLOW_COMMERCIAL'
    3. Soft alpha-blends foreground and background into taxi yellow-black:
       - Foreground detection (characters): dark for white/yellow plates, light for green EV plates.
       - Alpha-blend L: L = 212.0 * (1.0 - fg_score) + 18.0 * fg_score
       - Target background in LAB: L=212, A=134, B=213 (Indian commercial taxi yellow). Target foreground: L=18.
       - Softly blends the leftmost 14% region so HSRP blue strip does not produce high-contrast visual artifacts.

    Args:
        crop_bgr: Input cropped license plate image in BGR format.

    Returns:
        tuple[np.ndarray, str]: (remapped_bgr, detected_type)
            where detected_type in ('GREEN_EV', 'WHITE_PRIVATE', 'YELLOW_COMMERCIAL')
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.ndim < 2:
        return crop_bgr, PLATE_TYPE_YELLOW_COMMERCIAL

    # Standardize input image to 3-channel BGR uint8
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

    h, w = img_bgr.shape[:2]
    if h < 2 or w < 2:
        return img_bgr.copy(), PLATE_TYPE_YELLOW_COMMERCIAL

    # Convert to CIE LAB and HSV color spaces
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    L, A, B = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]

    # 1. Skip the leftmost 14% HSRP blue 'IND' strip (x0 = int(w * 0.14))
    x0 = int(round(w * HSRP_STRIP_WIDTH_FRACTION))
    x1 = max(x0 + 1, int(round(w * CENTRAL_ROI_X_MAX_FRACTION)))
    if x0 >= w:
        x0 = 0
        x1 = w

    roi_A = A[:, x0:x1]
    roi_B = B[:, x0:x1]
    roi_H = hsv[:, x0:x1, 0]
    roi_S = hsv[:, x0:x1, 1]
    roi_L = L[:, x0:x1]

    # 2. Measure color fractions in the central ROI
    # Green EV plate detection:
    # Green features negative a* (A < 118), saturated green hue in HSV [35, 95]
    green_mask = ((roi_A < 118) & (roi_S > 40) & (roi_H >= 35) & (roi_H <= 95)) | ((roi_A < 110) & (roi_B > 115))
    green_fraction = float(np.mean(green_mask))

    # Yellow commercial plate detection:
    # Yellow features strong positive b* (B > 155), warm a* (A >= 115), yellow hue in HSV [10, 38]
    yellow_mask = (roi_B > 155) & (roi_A >= 115) & (roi_S > 60) & (roi_H >= 10) & (roi_H <= 38)
    yellow_fraction = float(np.mean(yellow_mask))

    # Luminance metrics to identify bright white backgrounds
    p75_L = float(np.percentile(roi_L, 75))
    mean_L = float(np.mean(roi_L))
    high_luminance = (p75_L > 130.0) or (mean_L > 105.0)

    # Classify plate category
    if green_fraction > 0.30:
        detected_type = PLATE_TYPE_GREEN_EV
    elif yellow_fraction < 0.25 and high_luminance:
        detected_type = PLATE_TYPE_WHITE_PRIVATE
    else:
        detected_type = PLATE_TYPE_YELLOW_COMMERCIAL

    # Native yellow commercial plates are preserved as-is without alteration
    if detected_type == PLATE_TYPE_YELLOW_COMMERCIAL:
        return img_bgr.copy(), PLATE_TYPE_YELLOW_COMMERCIAL

    # 3. Soft alpha-blend foreground and background into taxi yellow-black
    if detected_type == PLATE_TYPE_GREEN_EV:
        # Green EV plates: characters are LIGHT (white or yellow) on dark green background
        p35 = float(np.percentile(roi_L, 35))
        p95 = float(np.percentile(roi_L, 95))
        fg_score = np.clip((L - p35) / max(15.0, p95 - p35), 0.0, 1.0)
    else:
        # White private plates: characters are DARK (black ink) on bright white background
        p15 = float(np.percentile(roi_L, 15))
        p85 = float(np.percentile(roi_L, 85))
        if p85 - p15 > 25.0:
            fg_score = np.clip((p85 - L) / max(1.0, p85 - p15), 0.0, 1.0)
        else:
            bg_weight = np.clip((L - 90.0) / 110.0, 0.0, 1.0)
            fg_score = 1.0 - bg_weight

    # 4. Softly blend the leftmost 14% region so HSRP blue strip does not produce high-contrast visual artifacts
    # The blue strip contains no registration characters; suppressing foreground in x < x0
    # smoothly maps the strip into the target taxi yellow background, with a soft feather across x0
    # to eliminate edge artifacts and border discontinuities.
    if x0 > 0:
        fg_score[:, :x0] = 0.0
        if x0 + 2 <= w:
            transition = np.clip((np.arange(w, dtype=np.float32) - x0) / 2.0, 0.0, 1.0)
            fg_score[:, x0:x0 + 2] *= transition[np.newaxis, x0:x0 + 2]

    # Continuous alpha-blend in CIE LAB space:
    # L = 212.0 * (1.0 - fg_score) + 18.0 * fg_score
    out_L = np.clip(TARGET_BG_L * (1.0 - fg_score) + TARGET_FG_L * fg_score, 0.0, 255.0)
    out_A = np.clip(TARGET_BG_A * (1.0 - fg_score) + TARGET_FG_A * fg_score, 0.0, 255.0)
    out_B = np.clip(TARGET_BG_B * (1.0 - fg_score) + TARGET_FG_B * fg_score, 0.0, 255.0)

    out_lab = cv2.merge([out_L, out_A, out_B]).astype(np.uint8)
    remapped_bgr = cv2.cvtColor(out_lab, cv2.COLOR_LAB2BGR)

    return remapped_bgr, detected_type
