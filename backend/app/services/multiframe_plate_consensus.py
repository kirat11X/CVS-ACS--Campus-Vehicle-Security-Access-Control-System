"""
Multi-Frame Plate Consensus & Statutory Indian Slot Verification.
-----------------------------------------------------------------
Aggregates 5-8 temporal candidate crops for each approaching vehicle,
decomposes OCR reads into statutory Indian plate slots (State, RTO, Series, Number),
applies position-wise alphanumeric confusion matrix repairs (O/0, I/1, B/8, S/5, Z/2),
and performs confidence-weighted voting across frames.

Implements all statutory constraints compiled in research_track/hitl_anpr/INDIAN_PLATE_FORMATS.md:
  1. State Code: 2 letters, strictly in 36 current + 4 retired state codes.
  2. RTO / Zone: 2 digits (not 00), except Delhi (DL) which allows 1 or 2 digits.
  3. Series: 1-3 letters, strictly excluding 'I' and 'O'. (Blank series permitted in KA only).
  4. Number: exactly 4 digits, 0001-9999 (leading zeros retained, 0000 prohibited).
  5. Bharat Series (BH): YY BH #### XX (YY >= 21, XX 1-2 letters excluding I and O).
"""

from __future__ import annotations

from collections import Counter
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.app.services.plate_normalizer import (
    ALL_VALID_STATES,
    CURRENT_STATES,
    FORMER_STATES,
    is_valid_indian_plate,
    normalize_plate,
    suggest_repairs,
)

logger = logging.getLogger("campus_security.multiframe_consensus")

# Bidirectional confusion pairs
CONFUSION_TO_ALPHA: Dict[str, str] = {
    "0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G", "4": "A"
}
CONFUSION_TO_NUM: Dict[str, str] = {
    "O": "0", "I": "1", "B": "8", "S": "5", "Z": "2", "G": "6", "A": "4", "D": "0", "Q": "0"
}


def decompose_indian_plate_slots(raw_text: str) -> Optional[Dict[str, str]]:
    """
    Decomposes raw or normalized plate text into statutory slots:
    - kind: 'standard' or 'bh'
    - state: 2-letter state code
    - rto: 1-2 digit zone code
    - series: 0-3 letter series
    - number: 4-digit number (0001-9999)
    """
    t = re.sub(r"[^A-Z0-9]", "", raw_text.upper())
    if t.startswith("IND") and len(t) > 5:
        t = t[3:]
    if t.endswith("IND") and len(t) > 5:
        t = t[:-3]
    if len(t) < 7:
        return None

    # 1. Bharat Series check: YY BH #### XX
    m_bh = re.match(r"^(\d{2})BH(\d{4})([A-Z]{1,2})$", t)
    if m_bh:
        yy, num, series = m_bh.groups()
        # Clean series: letters only, exclude I/O
        series_clean = "".join(CONFUSION_TO_ALPHA.get(c, c) for c in series if c.isalpha() and c not in "IO")
        return {
            "kind": "bh",
            "state": "BH",
            "yy": yy,
            "rto": "BH",
            "series": series_clean or "AA",
            "number": num,
        }

    # 2. Standard Indian plate format: State + RTO + Series + 4-digit Number
    # In standard plates, numbers are virtually always the last 4 digits (0001-9999)
    # Check if OCR emitted a phantom 5th trailing digit (e.g. GJ13UX35217)
    if len(t) >= 11 and t[-5:].isdigit():
        num_part = t[-5:-1]
        prefix = t[:-5]
    else:
        num_part = t[-4:]
        prefix = t[:-4]
    state_part = prefix[:2]
    rest = prefix[2:]

    # Clean State: must be 2 alphabetic characters in ALL_VALID_STATES
    state_c = "".join(CONFUSION_TO_ALPHA.get(c, c) for c in state_part)
    if state_c not in ALL_VALID_STATES:
        # Evaluate 1-character Hamming substitution to known valid state codes
        for valid_state in ALL_VALID_STATES:
            if len(state_c) == 2 and sum(a != b for a, b in zip(state_c, valid_state)) == 1:
                state_c = valid_state
                break

    # Extract RTO and Series from rest
    m_rto = re.match(r"^(\d{1,2})(.*)$", rest)
    if m_rto:
        rto_part = m_rto.group(1)
        series_part = m_rto.group(2)
    else:
        # RTO may have had alphanumeric confusion (e.g. 'O1' -> '01')
        rto_part = rest[:2]
        series_part = rest[2:]

    # Clean RTO: digits only
    rto_digits = "".join(CONFUSION_TO_NUM.get(c, c) for c in rto_part if c.isalnum())
    if state_c == "DL":
        rto_c = rto_digits[:2] if len(rto_digits) >= 2 else (rto_digits[:1] if len(rto_digits) == 1 else "01")
    else:
        rto_c = rto_digits[:2] if len(rto_digits) >= 2 else (f"0{rto_digits}" if len(rto_digits) == 1 else "01")

    # Clean Series: letters only, strictly no I or O
    series_letters = []
    for c in series_part:
        c = CONFUSION_TO_ALPHA.get(c, c)
        if c.isalpha() and c not in "IO":
            series_letters.append(c)
    series_c = "".join(series_letters[:3])

    # Clean Number: strictly 4 numeric digits, not 0000
    num_digits = "".join(CONFUSION_TO_NUM.get(c, c) for c in num_part if c.isalnum())
    if len(num_digits) > 4:
        num_digits = num_digits[:4]
    elif len(num_digits) < 4:
        num_digits = num_digits.zfill(4)
    if num_digits == "0000":
        num_digits = "0001"

    return {
        "kind": "standard",
        "state": state_c,
        "rto": rto_c,
        "series": series_c,
        "number": num_digits,
    }


def compute_iou(box1: List[int], box2: List[int]) -> float:
    """Computes Intersection over Union between two [x1, y1, x2, y2] boxes."""
    if not box1 or not box2 or len(box1) != 4 or len(box2) != 4:
        return 0.0
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = float(a1 + a2 - inter)
    return inter / union if union > 0 else 0.0


def fuse_multiframe_plate_reads(
    candidates: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Fuses 5 to 8 candidate frame reads for a vehicle.
    Each candidate item contains:
      - raw_plate: str
      - conf: float
      - bbox: List[int]
      - frame: np.ndarray
      - sharpness: float

    Returns dict with:
      - fused_plate: str
      - confidence: float
      - best_frame: np.ndarray (clearest snapshot for evidence)
      - best_bbox: List[int]
      - best_sharpness: float
      - slot_breakdown: Dict[str, str]
      - frame_count: int
      - agreement_rate: float
    """
    if not candidates:
        return None

    parsed_slots: List[Tuple[Dict[str, str], float]] = []
    best_candidate_frame = None
    best_candidate_bbox = None
    max_visual_quality = -1.0
    total_conf = 0.0

    for cand in candidates:
        raw = cand.get("raw_plate", "")
        conf = float(cand.get("conf", 0.5))
        sharpness = float(cand.get("sharpness", 50.0))
        frame = cand.get("frame")
        bbox = cand.get("bbox", [])

        # Track clearest frame based on sharpness * detection score
        quality = sharpness * conf
        if quality > max_visual_quality and frame is not None and frame.size > 0:
            max_visual_quality = quality
            best_candidate_frame = frame
            best_candidate_bbox = bbox

        slots = decompose_indian_plate_slots(raw)
        if slots:
            parsed_slots.append((slots, conf))
            total_conf += conf

    if not parsed_slots:
        return None

    # Confidence-weighted per-slot voting
    state_votes: Counter = Counter()
    rto_votes: Counter = Counter()
    series_votes: Counter = Counter()
    number_votes: Counter = Counter()
    kind_votes: Counter = Counter()

    for slots, w in parsed_slots:
        kind = slots.get("kind", "standard")
        kind_votes[kind] += w
        state_votes[slots.get("state", "")] += w
        rto_votes[slots.get("rto", "")] += w
        series_votes[slots.get("series", "")] += w
        number_votes[slots.get("number", "")] += w

    best_kind = kind_votes.most_common(1)[0][0]

    if best_kind == "bh":
        best_yy = [s.get("yy", "22") for s, _ in parsed_slots if s.get("kind") == "bh"][0]
        best_num = number_votes.most_common(1)[0][0]
        best_series = series_votes.most_common(1)[0][0]
        fused_plate = f"{best_yy}BH{best_num}{best_series}"
        slots_dict = {"kind": "bh", "yy": best_yy, "number": best_num, "series": best_series}
    else:
        best_state = state_votes.most_common(1)[0][0]
        best_rto = rto_votes.most_common(1)[0][0]
        best_series = series_votes.most_common(1)[0][0]
        best_num = number_votes.most_common(1)[0][0]

        # Outside Karnataka, series cannot be blank: pick highest-confidence non-empty series
        if not best_series and best_state != "KA":
            non_empty_series = [s for s in series_votes if s]
            if non_empty_series:
                best_series = max(non_empty_series, key=lambda s: series_votes[s])

        fused_plate = f"{best_state}{best_rto}{best_series}{best_num}"
        slots_dict = {
            "kind": "standard",
            "state": best_state,
            "rto": best_rto,
            "series": best_series,
            "number": best_num,
        }

    # Validate against statutory rules
    if not is_valid_indian_plate(fused_plate):
        repairs = suggest_repairs(fused_plate)
        if repairs:
            fused_plate = repairs[0]

    # Calculate agreement rate: percentage of frames agreeing with fused number
    num_agreed = sum(1 for s, _ in parsed_slots if s.get("number") == slots_dict.get("number"))
    agreement_rate = round(num_agreed / max(1, len(parsed_slots)), 3)
    avg_confidence = round(total_conf / max(1, len(parsed_slots)), 3)

    return {
        "fused_plate": fused_plate,
        "confidence": avg_confidence,
        "best_frame": best_candidate_frame,
        "best_bbox": best_candidate_bbox,
        "slot_breakdown": slots_dict,
        "frame_count": len(candidates),
        "agreement_rate": agreement_rate,
        "is_valid": is_valid_indian_plate(fused_plate),
    }
