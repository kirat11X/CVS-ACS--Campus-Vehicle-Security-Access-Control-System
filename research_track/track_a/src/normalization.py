"""
Track A: Indian License Plate Normalization Module (Facade / Backward Compatibility).

Provides canonical plate formatting, syntax validation, and confusion variant generation.
Delegates to `research_track.track_a.src.plate_normalizer`.
"""

from __future__ import annotations

from .plate_normalizer import (
    CURRENT_STATES,
    FORMER_STATES,
    ALL_VALID_STATES,
    INDIAN_STATE_CODES,
    OCR_CONFUSION_MAP,
    OCR_CONFUSION_PAIRS,
    DELHI_VEHICLE_CATEGORIES,
    NormalizedPlate,
    PlateNormalizer,
    normalize_plate,
    is_valid_indian_plate,
)

__all__ = [
    "CURRENT_STATES",
    "FORMER_STATES",
    "ALL_VALID_STATES",
    "INDIAN_STATE_CODES",
    "OCR_CONFUSION_MAP",
    "OCR_CONFUSION_PAIRS",
    "DELHI_VEHICLE_CATEGORIES",
    "NormalizedPlate",
    "PlateNormalizer",
    "normalize_plate",
    "is_valid_indian_plate",
]
