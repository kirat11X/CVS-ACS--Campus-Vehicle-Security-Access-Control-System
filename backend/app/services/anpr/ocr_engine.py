"""
Geometry Preprocessing, 2-Line Split & Dual-Pass ONNX OCR Engine.
----------------------------------------------------------------
Adheres strictly to research/ANPR_INTERFACE_CONTRACT.md.

Components:
1. pad_plate_bbox: Expands bounding box by +8% width and +5% height (clamped).
2. deskew_plate: Detects skew angle (minAreaRect & Hough lines) and straightens (3.0° - 25.0°).
3. split_two_line_plate: Horizontally splits 2-line plates (AR < 2.4) at minimum-ink projection valley.
4. is_plate_like_crop: Rejects flat walls (std < 22.0) and abnormal Canny edge density (< 0.04 or > 0.55).
5. run_dual_pass_ocr: Primary CRNN ONNX + Fallback RapidOCR (PP-OCRv4) cascade with 2-line handling.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, List, Optional, Tuple, Union

import cv2
import numpy as np

logger = logging.getLogger("campus_security.ocr_engine")

# Project root directory for weights resolution
_ROOT_DIR = Path(__file__).resolve().parents[4]
_WEIGHTS_DIR = _ROOT_DIR / "weights"

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHAR2IDX = {ch: i + 1 for i, ch in enumerate(ALPHABET)}
IDX2CHAR = {i + 1: ch for i, ch in enumerate(ALPHABET)}

_DEFAULT_CRNN_SESSION: Optional[Any] = None
_DEFAULT_RAPID_OCR: Optional[Any] = None


def get_default_ocr_session() -> Optional[Any]:
    """
    Lazily loads the default ONNX CRNN / CCT session from weights directory.
    Prefers indian_plate_crnn_best.onnx, falls back to track_a_ocr_cct.onnx.
    """
    global _DEFAULT_CRNN_SESSION
    if _DEFAULT_CRNN_SESSION is not None:
        return _DEFAULT_CRNN_SESSION

    candidates = [
        _WEIGHTS_DIR / "indian_plate_crnn_best.onnx",
        _WEIGHTS_DIR / "track_a_ocr_cct.onnx",
    ]
    for p in candidates:
        if p.exists():
            try:
                import onnxruntime as ort

                _DEFAULT_CRNN_SESSION = ort.InferenceSession(
                    str(p), providers=["CPUExecutionProvider"]
                )
                logger.info("Loaded default CRNN OCR session from %s", p)
                break
            except Exception as exc:
                logger.warning("Failed loading ONNX OCR session from %s: %s", p, exc)

    return _DEFAULT_CRNN_SESSION


def get_default_rapid_ocr() -> Optional[Any]:
    """Lazily loads the default RapidOCR instance if available."""
    global _DEFAULT_RAPID_OCR
    if _DEFAULT_RAPID_OCR is not None:
        return _DEFAULT_RAPID_OCR

    try:
        from rapidocr_onnxruntime import RapidOCR

        _DEFAULT_RAPID_OCR = RapidOCR()
        logger.info("Loaded default RapidOCR instance")
    except Exception as exc:
        logger.debug("RapidOCR unavailable: %s", exc)

    return _DEFAULT_RAPID_OCR


# =============================================================================
# 1. Bounding Box Padding
# =============================================================================


def pad_plate_bbox(
    bbox: Union[List[int], Tuple[int, int, int, int]],
    frame_shape: Tuple[int, ...],
    pad_w_pct: float = 0.08,
    pad_h_pct: float = 0.05,
) -> List[int]:
    """
    Expands bounding box by +8% width and +5% height, clamped to frame boundaries.

    Args:
        bbox: [x1, y1, x2, y2]
        frame_shape: (frame_h, frame_w, ...) as from frame.shape
        pad_w_pct: Horizontal expansion factor per side (default 0.08)
        pad_h_pct: Vertical expansion factor per side (default 0.05)

    Returns:
        [padded_x1, padded_y1, padded_x2, padded_y2] clamped to [0, frame_w] and [0, frame_h]
    """
    if len(bbox) != 4:
        raise ValueError(f"Expected bbox with 4 coordinates, got {bbox}")
    if len(frame_shape) < 2:
        raise ValueError(f"frame_shape must have at least 2 dimensions, got {frame_shape}")

    frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
    x1, y1, x2, y2 = bbox

    # Normalize coordinates if ordered backwards
    nx1, nx2 = min(x1, x2), max(x1, x2)
    ny1, ny2 = min(y1, y2), max(y1, y2)

    w = max(0, nx2 - nx1)
    h = max(0, ny2 - ny1)

    pad_w = int(round(w * pad_w_pct))
    pad_h = int(round(h * pad_h_pct))

    px1 = max(0, nx1 - pad_w)
    py1 = max(0, ny1 - pad_h)
    px2 = min(frame_w, nx2 + pad_w)
    py2 = min(frame_h, ny2 + pad_h)

    return [int(px1), int(py1), int(px2), int(py2)]


# =============================================================================
# 2. Deskewing
# =============================================================================


def estimate_skew_angle(crop_bgr: np.ndarray) -> float:
    """
    Estimates rotation tilt in degrees of a license plate crop.
    Uses Hough line transform on character/plate baselines, falling back
    to minimum area bounding box on thresholded text contours.

    Returns:
        Angle in degrees in [-45.0, 45.0] to rotate by for straightening.
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[0] < 8 or crop_bgr.shape[1] < 15:
        return 0.0

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if crop_bgr.ndim == 3 else crop_bgr
    h, w = gray.shape[:2]

    # Method 1: Hough Transform on Canny edges
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=15,
        minLineLength=15,
        maxLineGap=8,
    )
    if lines is not None and len(lines) >= 1:
        lines = lines.reshape(-1, 4)
        angles: List[float] = []
        for lx1, ly1, lx2, ly2 in lines:
            deg = float(np.degrees(np.arctan2(ly2 - ly1, lx2 - lx1)))
            if deg > 45.0:
                deg -= 90.0
            elif deg < -45.0:
                deg += 90.0
            if abs(deg) <= 35.0:
                angles.append(deg)
        if len(angles) >= 1:
            return float(np.median(angles))

    # Method 2: Fallback to minAreaRect on Otsu foreground
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if np.mean(thresh == 255) > 0.5:
        thresh = cv2.bitwise_not(thresh)

    pts = cv2.findNonZero(thresh)
    if pts is not None and len(pts) >= 20:
        rect = cv2.minAreaRect(pts)
        (cx, cy), (rw, rh), angle = rect
        if rw < rh:
            angle = angle + 90.0
        while angle > 45.0:
            angle -= 90.0
        while angle < -45.0:
            angle += 90.0
        return float(angle)

    return 0.0


def deskew_plate(
    crop_bgr: np.ndarray,
    min_angle: float = 3.0,
    max_angle: float = 25.0,
) -> np.ndarray:
    """
    Detects skew angle using Hough transform / minimum area bounding box.
    If angle magnitude is between min_angle and max_angle, rotates to straighten
    using bicubic interpolation with neutral border reflection.
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[0] < 8 or crop_bgr.shape[1] < 15:
        return crop_bgr

    angle = estimate_skew_angle(crop_bgr)
    if min_angle <= abs(angle) <= max_angle:
        h, w = crop_bgr.shape[:2]
        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(
            crop_bgr,
            M,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REFLECT,
        )

    return crop_bgr


# =============================================================================
# 3. 2-Line Plate Splitting
# =============================================================================


def split_two_line_plate(
    crop_bgr: np.ndarray,
    ar_threshold: float = 2.4,
) -> List[np.ndarray]:
    """
    Computes aspect ratio w / max(1, h).
    If w / h < ar_threshold (standard square/two-wheeler plate format):
      Calculates horizontal projection (sum of dark pixel intensities per row)
      across the middle band between 38% and 62% height.
      Finds the minimum-ink row (valley between top and bottom text lines),
      and splits into [top_crop, bottom_crop].
    If w / h >= ar_threshold:
      Returns single-element list [crop_bgr].
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return [crop_bgr]

    h, w = crop_bgr.shape[:2]
    ar = float(w) / max(1.0, float(h))

    if ar >= ar_threshold or h < 10:
        return [crop_bgr]

    # Convert to grayscale to compute horizontal ink projection
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if crop_bgr.ndim == 3 else crop_bgr
    mean_val = float(np.mean(gray))

    # Ink map: text pixels have high value, background pixels have low value
    if mean_val > 127.0:
        # Light background (white/yellow), dark text
        ink = 255.0 - gray.astype(np.float32)
    else:
        # Dark background (green EV), light text
        ink = gray.astype(np.float32)

    # Middle band: 38% to 62% height
    y_start = int(round(h * 0.38))
    y_end = int(round(h * 0.62))
    if y_end <= y_start:
        y_end = min(h, y_start + 1)

    proj = np.sum(ink[y_start:y_end], axis=1)
    if proj.size == 0:
        return [crop_bgr]

    min_val = np.min(proj)
    min_indices = np.where(proj == min_val)[0]
    # Pick midpoint of minimum-ink valley
    mid_idx = min_indices[len(min_indices) // 2]
    split_y = y_start + int(mid_idx)

    # Clamp split_y so neither slice is empty
    split_y = max(1, min(h - 1, split_y))

    top_crop = crop_bgr[:split_y, :]
    bottom_crop = crop_bgr[split_y:, :]

    return [top_crop, bottom_crop]


# =============================================================================
# 4. Plate-likeness Gate
# =============================================================================


def is_plate_like_crop(crop: np.ndarray) -> bool:
    """
    Filters out flat walls/shadows (contrast std < 22.0) and abnormal
    Canny edge density (< 0.04 or > 0.55). Minimum dimensions 12x30.
    """
    if crop is None or crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 30:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    std = float(np.std(gray))
    if std < 22.0:
        return False

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)
    if edge_density < 0.04 or edge_density > 0.55:
        return False

    return True


# =============================================================================
# 5. Dual-Pass ONNX OCR Engine
# =============================================================================


def decode_crnn_logits(logits: np.ndarray) -> Tuple[str, float]:
    """
    Decodes CTC greedy output from CRNN logits array and calculates mean character confidence.
    Supports (batch, seq_len, num_classes) or (seq_len, num_classes).
    Returns:
        (decoded_text, mean_char_confidence)
    """
    if logits is None:
        return "", 0.0

    if hasattr(logits, "detach"):
        logits = logits.detach().cpu().numpy()
    logits = np.asarray(logits)

    if logits.size == 0:
        return "", 0.0

    pred_logits = logits[0] if logits.ndim == 3 else logits
    if pred_logits.ndim != 2:
        return "", 0.0

    # Softmax across class axis
    exp_logits = np.exp(pred_logits - np.max(pred_logits, axis=-1, keepdims=True))
    probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

    preds = np.argmax(pred_logits, axis=-1)
    chars: List[str] = []
    confs: List[float] = []
    prev = 0
    for t, idx in enumerate(preds):
        if idx != prev and idx != 0 and idx in IDX2CHAR:
            chars.append(IDX2CHAR[idx])
            confs.append(float(probs[t, idx]))
        prev = idx

    decoded = "".join(chars)
    mean_conf = float(np.mean(confs)) if confs else 0.0
    return decoded, mean_conf


def sort_multiline_boxes(
    lines_with_boxes: List[Any],
    crop_height: int,
) -> List[Any]:
    """
    When RapidOCR returns multiple boxes on multi-line plates, sorts boxes
    top-to-bottom (vertical clustering) then left-to-right.
    """
    if not lines_with_boxes or len(lines_with_boxes) <= 1:
        return lines_with_boxes

    parsed = []
    for item in lines_with_boxes:
        if isinstance(item, (list, tuple)) and len(item) >= 1 and isinstance(item[0], (list, tuple, np.ndarray)):
            box = item[0]
            pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            y_center = float(np.mean(pts[:, 1]))
            x_center = float(np.mean(pts[:, 0]))
            parsed.append({"item": item, "y_center": y_center, "x_center": x_center})
        else:
            parsed.append({"item": item, "y_center": 0.0, "x_center": 0.0})

    parsed.sort(key=lambda d: d["y_center"])

    line_threshold = max(10.0, 0.25 * float(crop_height))
    lines: List[List[dict]] = []

    for entry in parsed:
        placed = False
        for line in lines:
            avg_y = sum(d["y_center"] for d in line) / len(line)
            if abs(entry["y_center"] - avg_y) <= line_threshold:
                line.append(entry)
                placed = True
                break
        if not placed:
            lines.append([entry])

    sorted_items = []
    for line in lines:
        line.sort(key=lambda d: d["x_center"])
        for d in line:
            sorted_items.append(d["item"])

    return sorted_items


def _clean_ocr_text(text: str) -> str:
    """Strips non-alphanumeric noise and extraneous leading/trailing HSRP 'IND' strings."""
    if not text:
        return ""
    norm = re.sub(r"[^A-Za-z0-9]", "", str(text)).upper().strip()
    if norm == "IND":
        return ""
    if norm.startswith("IND") and len(norm) > 4:
        norm = norm[3:]
    if norm.endswith("IND") and len(norm) > 4:
        norm = norm[:-3]
    return norm


def _infer_crnn(crop_bgr: np.ndarray, session: Any) -> Tuple[str, float]:
    """Runs CRNN inference on a single horizontal line crop."""
    if crop_bgr is None or crop_bgr.size == 0 or session is None:
        return "", 0.0

    if crop_bgr.ndim == 2:
        c_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_GRAY2BGR)
    elif crop_bgr.ndim == 3 and crop_bgr.shape[2] == 1:
        c_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_GRAY2BGR)
    else:
        c_bgr = crop_bgr

    c_rgb = cv2.cvtColor(c_bgr, cv2.COLOR_BGR2RGB)
    c_res = cv2.resize(c_rgb, (128, 32), interpolation=cv2.INTER_LINEAR)
    inp = c_res.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 127.5 - 1.0

    # Support ONNX InferenceSession or Mock session
    if hasattr(session, "run"):
        input_name = "input"
        if hasattr(session, "get_inputs") and session.get_inputs():
            try:
                input_name = session.get_inputs()[0].name
            except Exception:
                pass
        out = session.run(None, {input_name: inp})
    elif callable(session):
        out = session(inp)
    else:
        return "", 0.0

    # In case a mock or helper returned (text, conf) directly
    if isinstance(out, (tuple, list)) and len(out) == 2 and isinstance(out[0], str):
        return out[0], float(out[1])

    logits = out[0] if isinstance(out, (list, tuple)) else out
    if isinstance(logits, (tuple, list)) and len(logits) == 2 and isinstance(logits[0], str):
        return logits[0], float(logits[1])

    return decode_crnn_logits(logits)


def _infer_rapid_ocr(crop_bgr: np.ndarray, engine: Any) -> Tuple[str, float]:
    """Runs RapidOCR on plate crop, sorting multiline boxes top-to-bottom then left-to-right."""
    if crop_bgr is None or crop_bgr.size == 0 or engine is None:
        return "", 0.0

    try:
        out = engine(crop_bgr)
    except Exception as exc:
        logger.debug("RapidOCR invocation failed: %s", exc)
        return "", 0.0

    if out is None:
        return "", 0.0

    res = (
        out[0]
        if isinstance(out, (tuple, list))
        and len(out) == 2
        and isinstance(out[1], (float, int, str))
        else out
    )
    if not res or not isinstance(res, list):
        return "", 0.0

    h = crop_bgr.shape[0]
    sorted_items = sort_multiline_boxes(res, crop_height=h)

    lines: List[str] = []
    confs: List[float] = []
    for item in sorted_items:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            txt = item[1]
            try:
                score = float(item[2]) if len(item) >= 3 else 1.0
            except (ValueError, TypeError):
                score = 0.5
            cleaned = _clean_ocr_text(str(txt))
            if cleaned:
                lines.append(cleaned)
                confs.append(score)
        elif isinstance(item, str):
            cleaned = _clean_ocr_text(item)
            if cleaned:
                lines.append(cleaned)
                confs.append(1.0)

    if not lines:
        return "", 0.0

    full_text = "".join(lines)
    mean_conf = float(np.mean(confs)) if confs else 0.0
    return full_text, mean_conf


def run_dual_pass_ocr(
    crop_bgr: np.ndarray,
    ocr_session: Optional[Any] = None,
    rapid_ocr: Optional[Any] = None,
) -> Tuple[str, float, str]:
    """
    Dual-pass OCR architecture:
    1. Handles 2-line plates by splitting, running OCR on top and bottom crops, and joining them.
    2. Primary engine: CRNN ONNX session (indian_plate_crnn_best.onnx or track_a_ocr_cct.onnx).
    3. Fallback engine: RapidOCR (PP-OCRv4) when CRNN confidence < 0.55 or on 2-line plates.
    Returns: (recognized_text, confidence, engine_used)
    """
    if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[0] < 5 or crop_bgr.shape[1] < 5:
        return "", 0.0, "none"

    # If neither session provided, attempt lazy load of default models
    if ocr_session is None and rapid_ocr is None:
        ocr_session = get_default_ocr_session()
        rapid_ocr = get_default_rapid_ocr()

    splits = split_two_line_plate(crop_bgr, ar_threshold=2.4)
    is_2line = len(splits) == 2

    # --- Primary Pass: CRNN ONNX ---
    crnn_text = ""
    crnn_conf = 0.0
    if ocr_session is not None:
        try:
            if is_2line:
                top_txt, top_conf = _infer_crnn(splits[0], ocr_session)
                bot_txt, bot_conf = _infer_crnn(splits[1], ocr_session)
                top_clean = _clean_ocr_text(top_txt)
                bot_clean = _clean_ocr_text(bot_txt)
                crnn_text = top_clean + bot_clean
                if top_conf > 0.0 and bot_conf > 0.0:
                    crnn_conf = (top_conf + bot_conf) / 2.0
                else:
                    crnn_conf = max(top_conf, bot_conf)
            else:
                txt, conf = _infer_crnn(crop_bgr, ocr_session)
                crnn_text = _clean_ocr_text(txt)
                crnn_conf = conf
        except Exception as exc:
            logger.debug("CRNN primary pass failed: %s", exc)

    # --- Fallback Pass: RapidOCR ---
    need_fallback = (
        rapid_ocr is not None
        and (crnn_conf < 0.55 or not crnn_text or is_2line or ocr_session is None)
    )

    rapid_text = ""
    rapid_conf = 0.0
    if need_fallback:
        try:
            if is_2line:
                # RapidOCR processes crop_bgr directly with multiline sorting,
                # falling back to explicit split lines if needed.
                r_txt, r_conf = _infer_rapid_ocr(crop_bgr, rapid_ocr)
                if not r_txt:
                    top_txt, top_conf = _infer_rapid_ocr(splits[0], rapid_ocr)
                    bot_txt, bot_conf = _infer_rapid_ocr(splits[1], rapid_ocr)
                    r_txt = top_txt + bot_txt
                    r_conf = (top_conf + bot_conf) / 2.0 if (top_conf and bot_conf) else max(top_conf, bot_conf)
                rapid_text = r_txt
                rapid_conf = r_conf
            else:
                rapid_text, rapid_conf = _infer_rapid_ocr(crop_bgr, rapid_ocr)
        except Exception as exc:
            logger.debug("RapidOCR fallback pass failed: %s", exc)

    # --- Engine Arbitration ---
    if crnn_text and not rapid_text:
        return crnn_text, crnn_conf, "CRNN"
    if rapid_text and not crnn_text:
        return rapid_text, rapid_conf, "RapidOCR"
    if crnn_text and rapid_text:
        if is_2line:
            # On 2-line plates, RapidOCR is prioritized if confidence >= 0.55 or higher than CRNN
            if rapid_conf >= 0.55 or rapid_conf >= crnn_conf:
                return rapid_text, rapid_conf, "RapidOCR"
            return crnn_text, crnn_conf, "CRNN"

        # On 1-line plates: CRNN is primary if confidence >= 0.55
        if crnn_conf >= 0.55:
            return crnn_text, crnn_conf, "CRNN"
        if rapid_conf >= crnn_conf:
            return rapid_text, rapid_conf, "RapidOCR"
        return crnn_text, crnn_conf, "CRNN"

    return "", 0.0, "none"
