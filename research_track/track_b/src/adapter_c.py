"""
Track B Exposure of Track B -> Track C Cross-Track Adapter.

Re-exports pure decoupled adapter transforming extracted invoice line items into
Track C security screening input payloads.
"""

from research_track.adapters.track_b_to_c import (
    CANONICAL_UNIT_MAP,
    CANONICAL_UNIT_MAP_LOWER,
    CANONICAL_UNIT_MAP_UPPER,
    ScreeningInputPayload,
    ScreeningItemInput,
    TrackBToCAdapter,
    convert_invoice_to_screening_payloads,
    convert_line_item_to_screening_input,
    infer_platform_from_vendor,
    normalize_screening_unit,
    parse_exact_decimal_quantity,
)

__all__ = [
    "CANONICAL_UNIT_MAP",
    "CANONICAL_UNIT_MAP_LOWER",
    "CANONICAL_UNIT_MAP_UPPER",
    "ScreeningInputPayload",
    "ScreeningItemInput",
    "TrackBToCAdapter",
    "convert_invoice_to_screening_payloads",
    "convert_line_item_to_screening_input",
    "infer_platform_from_vendor",
    "normalize_screening_unit",
    "parse_exact_decimal_quantity",
]
