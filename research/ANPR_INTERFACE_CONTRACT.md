# Campus Gate White & Green-EV ANPR Interface Contract

This contract defines the shared function signatures, data structures, and invariants for the 5 ANPR solutions.
All sub-agents in Wave 1 and Wave 2 MUST adhere to these exact signatures to guarantee zero integration friction.

---

## 1. Color Remapper (`backend/app/services/anpr/color_remap.py`)

```python
import numpy as np

def remap_to_yellow_black(crop_bgr: np.ndarray) -> tuple[np.ndarray, str]:
    """
    Remaps green EV (light on dark) or white private (dark on light) plates into standard
    yellow-background / black-text in CIE LAB space.
    
    1. Skips the leftmost 14% HSRP blue 'IND' strip (x0 = int(w * 0.14)).
    2. Measures color fractions:
       - green_fraction > 0.30 -> 'GREEN_EV'
       - yellow_fraction < 0.25 -> 'WHITE_PRIVATE'
       - otherwise -> 'YELLOW_COMMERCIAL'
    3. Soft alpha-blends foreground and background:
       L = 212.0 * (1.0 - fg_score) + 18.0 * fg_score
       Target A = 134, Target B = 213 (Indian commercial taxi yellow)
    
    Returns:
        (remapped_bgr, detected_type)
        where detected_type in ('GREEN_EV', 'WHITE_PRIVATE', 'YELLOW_COMMERCIAL')
    """
```

---

## 2. Polarity Normalizer (`backend/app/services/anpr/polarity_normalizer.py`)

```python
import numpy as np

def normalize_plate_agnostic(crop_bgr: np.ndarray) -> tuple[np.ndarray, bool]:
    """
    Color-agnostic CLAHE + Otsu polarity normalizer.
    
    1. Extracts L* channel from CIE LAB.
    2. Applies CLAHE (clipLimit=2.5, tileGridSize=(8, 4)).
    3. Computes Otsu threshold on central ROI (y: 15%-85%, x: 15%-92%).
    4. Auto-inverts (255 - L_eq) when white_ratio < 0.45 (green EV plates with light text on dark green bg).
    5. Applies 2nd–98th percentile stretching for optimal OCR contrast.
    
    Returns:
        (normalized_plate_bgr, was_inverted: bool)
    """
```

---

## 3. Geometry, 2-Line Split & ONNX OCR Engine (`backend/app/services/anpr/ocr_engine.py`)

```python
from typing import Any, List, Optional, Tuple
import numpy as np

def pad_plate_bbox(
    bbox: List[int] | Tuple[int, int, int, int],
    frame_shape: Tuple[int, int],
    pad_w_pct: float = 0.08,
    pad_h_pct: float = 0.05,
) -> List[int]:
    """
    Expands bounding box by +8% width and +5% height (clamped to frame boundaries).
    Returns: [x1, y1, x2, y2]
    """

def deskew_plate(
    crop_bgr: np.ndarray,
    min_angle: float = 3.0,
    max_angle: float = 25.0,
) -> np.ndarray:
    """
    Detects skew angle using minimum area rectangle or Hough lines.
    Rotates to deskew if angle is between min_angle and max_angle.
    """

def split_two_line_plate(
    crop_bgr: np.ndarray,
    ar_threshold: float = 2.4,
) -> List[np.ndarray]:
    """
    If aspect ratio (w/h) < 2.4:
      Finds horizontal minimum-ink projection split line between 38% and 62% height.
      Returns [top_crop, bottom_crop].
    Otherwise:
      Returns [crop_bgr].
    """

def is_plate_like_crop(crop: np.ndarray) -> bool:
    """
    Rejects crops with grayscale contrast std < 22.0 or abnormal Canny edge density (< 0.04 or > 0.55).
    """

def run_dual_pass_ocr(
    crop_bgr: np.ndarray,
    ocr_session: Optional[Any] = None,
    rapid_ocr: Optional[Any] = None,
) -> Tuple[str, float, str]:
    """
    Dual-pass OCR engine:
    1. Primary: CRNN ONNX (indian_plate_crnn_best.onnx / track_a_ocr_cct.onnx).
    2. Fallback: RapidOCR PP-OCRv4 top-to-bottom on low confidence (< 0.55) or 2-line split plates.
    Returns: (recognized_text, confidence, engine_name)
    """
```

---

## 4. Positional Grammar & Track Voting (`plate_normalizer.py` & `track_voter.py`)

```python
from typing import Any, Dict, List, Optional, Tuple

def correct_indian_plate(raw_text: str) -> Tuple[str, float, str]:
    """
    CMVR Rule 50 statutory positional syntax repair:
    - Strips leading 'IND' and non-alphanumeric noise.
    - Evaluates Bharat Series (YYBH####XX) and Standard State (SS DD [L{1,3}] NNNN).
    - Applies positional confusion mappings:
      Slots 0-1: State letters (ALL_VALID_STATES)
      Slots 2-3: RTO digits
      Middle: Series letters (no I/O)
      Tail: 4 digits (not 0000)
    Returns: (canonical_plate, confidence_score, format_category)
    where format_category in ('STANDARD', 'BHARAT_SERIES', 'VINTAGE', 'DIPLOMATIC', 'MILITARY', 'INVALID')
    """

class TrackVoter:
    """
    Accumulates multi-frame plate hypotheses for a given vehicle track_id.
    Performs confidence-weighted positional voting across 5-8 frames.
    Routes non-standard statutory formats (military/diplomatic/temp) to 'MANUAL_CHECK'.
    """
    def __init__(self, min_consensus_frames: int = 5, max_track_frames: int = 8): ...
    def add_observation(
        self,
        track_id: str,
        plate_text: str,
        confidence: float,
        bbox: List[int],
        frame_ts: float,
        frame_bgr: Optional[np.ndarray] = None,
    ) -> None: ...
    def get_consensus(self, track_id: str) -> Optional[Dict[str, Any]]: ...
    def clear_track(self, track_id: str) -> None: ...
```

---

## 5. Pipeline Integration (`backend/app/workers/camera_stream_runner.py`)

- Relax plate bbox aspect ratio: `0.9 <= w/h <= 6.0` and `bw >= 32, bh >= 16`.
- Vehicle-box containment check: Plate bbox must be geometrically inside or intersecting a detected vehicle bbox (`car`, `two_wheeler`, `auto_rickshaw`, `bus`, `truck`).
- Dual-pass pipeline:
  1. Pass 1: `normalize_plate_agnostic(crop)` -> ONNX OCR -> `correct_indian_plate`.
  2. Pass 2 (fallback): If Pass 1 confidence < 0.55 or invalid plate, run `remap_to_yellow_black(crop)` -> ONNX OCR.
  3. Feed candidate into `TrackVoter(track_id)`.
