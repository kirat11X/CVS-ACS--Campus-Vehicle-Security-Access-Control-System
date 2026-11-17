"""
Track A: Indian License Plate Normalizer Module.

Provides comprehensive, non-destructive canonical plate formatting,
positional syntax validation, HSRP prefix stripping, multi-format classification
(Standard State, Bharat BH, EV, Commercial, Military Arrow, Diplomatic, Vintage, Temporary),
and auditable positional OCR character confusion variants (O/0, I/1, Z/2, B/8, S/5, G/6).

Contract Invariants:
- Raw input is immutable and permanently preserved in raw_text.
- Empty or whitespace input returns status='UNREADABLE' and clean_text=''.
- Str representation of NormalizedPlate returns clean_text.
- Character swaps are never silently forced into clean_text: plausible OCR confusions
  are generated as auditable alternative variants with explicit penalty scores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union

# Recognized 36 Current Indian States & Union Territories
CURRENT_STATES: Set[str] = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "GA", "GJ", "HP", "HR", "JH",
    "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY",
    "RJ", "SK", "TG", "TN", "TR", "UK", "UP", "WB"
}

# Former State codes still legally present on older vehicles
FORMER_STATES: Set[str] = {"UA", "OR", "DN", "TS"}

# Unified valid state codes
ALL_VALID_STATES: Set[str] = CURRENT_STATES | FORMER_STATES
INDIAN_STATE_CODES: Set[str] = ALL_VALID_STATES

# Optical OCR confusion pairs: character -> possible alternative
OCR_CONFUSION_MAP: Dict[str, List[str]] = {
    "O": ["0", "D", "Q"],
    "0": ["O", "D", "Q"],
    "I": ["1", "L", "T"],
    "1": ["I", "L", "T"],
    "B": ["8"],
    "8": ["B"],
    "S": ["5"],
    "5": ["S"],
    "Z": ["2"],
    "2": ["Z"],
    "G": ["6"],
    "6": ["G"],
    "D": ["0", "O"],
    "Q": ["0", "O"],
}

OCR_CONFUSION_PAIRS: Set[Tuple[str, str]] = {
    ("O", "0"), ("0", "O"),
    ("I", "1"), ("1", "I"),
    ("B", "8"), ("8", "B"),
    ("S", "5"), ("5", "S"),
    ("Z", "2"), ("2", "Z"),
    ("D", "0"), ("0", "D"),
    ("Q", "0"), ("0", "Q"),
    ("G", "6"), ("6", "G"),
}

# Delhi commercial vehicle series classifications
DELHI_VEHICLE_CATEGORIES: Dict[str, str] = {
    "A": "ambulance",
    "B": "mini bus",
    "C": "car",
    "E": "electric / commercial",
    "F": "private (number on demand)",
    "G": "truck",
    "K": "school vehicle",
    "L": "truck",
    "M": "commercial",
    "N": "self-drive",
    "P": "bus",
    "Q": "three-wheeler",
    "R": "autorickshaw / radio taxi",
    "S": "two-wheeler",
    "T": "city taxi",
    "U": "commercial",
    "V": "commercial",
    "W": "commercial",
    "Y": "private taxi",
    "Z": "commercial",
}


@dataclass(frozen=True)
class NormalizedPlate:
    """Immutable representation of a normalized plate with full audit metadata."""
    raw_text: str
    clean_text: str
    status: str  # "VALID", "UNREADABLE", "INVALID_FORMAT", "AMBIGUOUS_REPAIR"
    is_valid_format: bool
    format_type: str  # "STANDARD_INDIAN", "BH_SERIES", "MILITARY", "DIPLOMATIC", "VINTAGE", "TEMPORARY", "COMMERCIAL_TRADE", "NON_STANDARD", "UNREADABLE"
    state_code: Optional[str] = None
    district_code: Optional[str] = None
    series_code: Optional[str] = None
    number_code: Optional[str] = None
    confusion_variants: List[Tuple[str, float, str]] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.clean_text


class PlateNormalizer:
    """
    Configurable normalizer and statutory syntax validator for Indian vehicle license plates.
    """

    def __init__(
        self,
        strip_separators: bool = True,
        to_uppercase: bool = True,
        strip_hsrp_ind: bool = True,
        min_length: int = 5,
        max_length: int = 12,
        validate_indian_format: bool = True,
        enable_variant_generation: bool = True,
        max_variants: int = 5,
        penalty_per_substitution: float = 0.05,
    ):
        self.strip_separators = strip_separators
        self.to_uppercase = to_uppercase
        self.strip_hsrp_ind = strip_hsrp_ind
        self.min_length = min_length
        self.max_length = max_length
        self.validate_indian_format = validate_indian_format
        self.enable_variant_generation = enable_variant_generation
        self.max_variants = max_variants
        self.penalty_per_substitution = penalty_per_substitution

        # Standard Indian Format:
        # State (2 letters) + District (1-2 digits) + Series (0-3 letters) + Number (4 digits)
        self._standard_pattern = re.compile(
            r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$"
        )
        # Bharat (BH) Series (introduced 2021): YY BH #### XX (e.g. 22BH1234AA)
        self._bh_pattern = re.compile(
            r"^([0-9]{2})(BH)([0-9]{4})([A-Z]{1,2})$"
        )
        # Military Vehicle: upward arrow (↑ / ^) or digits + letter + 5-6 digits + letter (e.g. 21D123456A)
        self._military_pattern = re.compile(
            r"^([0-9]{2})([A-Z])([0-9]{5,6})([A-Z])$"
        )
        # Diplomatic: 1-3 digits + (CD|CC|UN|IOD) + 1-4 digits (+ optional letter)
        self._diplomatic_pattern = re.compile(
            r"^([0-9]{1,3})(CD|CC|UN|IOD)([0-9]{1,4}[A-Z]?)$"
        )
        # Vintage: State (2 letters) + VA + optional RTO/Series + Number (4 digits)
        self._vintage_pattern = re.compile(
            r"^([A-Z]{2})(VA)([A-Z0-9]{1,4})([0-9]{4})$"
        )
        # Temporary: optional T + Month (2 digits) + Year (2 digits) + State (2 letters) + Number (4 digits) + Series (1-2 letters)
        self._temporary_pattern = re.compile(
            r"^T?([0-9]{2})([0-9]{2})([A-Z]{2})([0-9]{4})([A-Z]{1,2})$"
        )
        # Trade Certificate: State (2 letters) + District (1-2 digits) + optional category + TC + Number
        self._trade_pattern = re.compile(
            r"^([A-Z]{2})([0-9]{1,2})([A-Z]?)TC([0-9]{1,6})$"
        )

    def clean_string(self, text: Optional[str]) -> Tuple[str, List[str]]:
        """
        Cleans raw input text: strips whitespace, punctuation, military arrows,
        and High Security Registration Plate (HSRP) 'IND' prefix.
        Returns (clean_text, notes).
        """
        if not text:
            return "", []

        s = str(text).strip()
        notes: List[str] = []

        # Handle Military Arrow prefix (↑ or ^)
        if s.startswith("↑") or s.startswith("^"):
            notes.append("Military upward arrow prefix removed")
            s = s[1:].strip()

        # Remove non-alphanumeric separators (spaces, dots, hyphens, colons, slashes)
        if self.strip_separators:
            s = re.sub(r"[^A-Za-z0-9]", "", s)

        if self.to_uppercase:
            s = s.upper()

        # Handle HSRP 'IND' prefix stripping
        if self.strip_hsrp_ind and s.startswith("IND"):
            remainder = s[3:]
            # Only strip IND if remainder looks like an Indian plate (at least 5 chars)
            # and is not an intrinsic part of a valid plate (no state code begins with IN)
            if len(remainder) >= self.min_length:
                s = remainder
                notes.append("HSRP 'IND' country prefix stripped")

        return s.strip(), notes

    def normalize(self, raw_text: Optional[str]) -> NormalizedPlate:
        """
        Executes full non-destructive normalization and validation pipeline.
        Empty or whitespace strings return status='UNREADABLE'.
        """
        raw_str = "" if raw_text is None else str(raw_text)

        # Invariant: Empty or whitespace-only OCR is UNREADABLE
        if not raw_str or not raw_str.strip():
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text="",
                status="UNREADABLE",
                is_valid_format=False,
                format_type="UNREADABLE",
                validation_notes=["Input text is null or empty whitespace"]
            )

        clean, notes = self.clean_string(raw_str)

        # Invariant: If after removing noise nothing remains -> UNREADABLE
        if not clean:
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text="",
                status="UNREADABLE",
                is_valid_format=False,
                format_type="UNREADABLE",
                validation_notes=["Input contained no alphanumeric characters"]
            )

        # Length validation
        if len(clean) < self.min_length:
            notes.append(f"Length {len(clean)} below minimum threshold {self.min_length}")
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text=clean,
                status="INVALID_FORMAT",
                is_valid_format=False,
                format_type="MALFORMED_TOO_SHORT",
                validation_notes=notes
            )

        if len(clean) > self.max_length:
            notes.append(f"Length {len(clean)} exceeds maximum threshold {self.max_length}")
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text=clean,
                status="INVALID_FORMAT",
                is_valid_format=False,
                format_type="MALFORMED_TOO_LONG",
                validation_notes=notes
            )

        # Syntax Pattern Matching
        state = None
        district = None
        series = None
        number = None
        format_type = "NON_STANDARD"
        is_valid = False

        m_std = self._standard_pattern.match(clean)
        m_bh = self._bh_pattern.match(clean)
        m_mil = self._military_pattern.match(clean)
        m_dip = self._diplomatic_pattern.match(clean)
        m_vin = self._vintage_pattern.match(clean)
        m_tmp = self._temporary_pattern.match(clean)
        m_trd = self._trade_pattern.match(clean)

        if m_bh:
            year, code, num, letters = m_bh.groups()
            state = "BH"
            district = year
            series = letters
            number = num
            format_type = "BH_SERIES"

            # BH series validation: year >= 21, series letters no I or O, num != 0000
            year_int = int(year)
            num_ok = num != "0000"
            ser_ok = not any(c in letters for c in "IO")
            if year_int >= 21 and num_ok and ser_ok:
                is_valid = True
                notes.append(f"Bharat Series plate detected (Year: 20{year})")
            else:
                notes.append(f"BH series pattern matched but invalid: year=20{year}, series={letters}")

        elif m_mil:
            year, branch, num, suffix = m_mil.groups()
            state = "MILITARY"
            district = year
            series = branch
            number = num
            format_type = "MILITARY"
            is_valid = True
            notes.append("Military defense vehicle format detected")

        elif m_dip:
            mission, corps, num = m_dip.groups()
            state = corps
            district = mission
            series = ""
            number = num
            format_type = "DIPLOMATIC"
            is_valid = True
            notes.append(f"Diplomatic corps plate detected: {corps}")

        elif m_vin:
            st, va, ser, num = m_vin.groups()
            state = st
            district = va
            series = ser
            number = num
            format_type = "VINTAGE"
            if st in ALL_VALID_STATES and not any(c in ser for c in "IO") and num != "0000":
                is_valid = True
                notes.append(f"Vintage vehicle plate detected for state {st}")

        elif m_tmp:
            month, year, st, num, ser = m_tmp.groups()
            state = st
            district = f"{month}/{year}"
            series = ser
            number = num
            format_type = "TEMPORARY"
            if st in ALL_VALID_STATES:
                is_valid = True
                notes.append(f"Temporary registration plate detected ({month}/{year})")

        elif m_trd:
            st, dist, cat, num = m_trd.groups()
            state = st
            district = dist
            series = f"{cat}TC" if cat else "TC"
            number = num
            format_type = "COMMERCIAL_TRADE"
            if st in ALL_VALID_STATES:
                is_valid = True
                notes.append(f"Trade certificate plate detected for state {st}")

        elif m_std:
            st, dist, ser, num = m_std.groups()
            state = st
            district = dist
            series = ser if ser else ""
            number = num
            format_type = "STANDARD_INDIAN"

            if st in ALL_VALID_STATES:
                # Validation checks:
                # 1. Outside Delhi, single-digit RTO is non-standard
                rto_ok = not (len(dist) == 1 and st != "DL")
                # 2. Number cannot be 0000
                num_ok = num != "0000"
                # 3. Series letters must not contain I or O
                ser_ok = not any(c in series for c in "IO")

                if rto_ok and num_ok and ser_ok:
                    is_valid = True
                    if st in FORMER_STATES:
                        notes.append(f"Former state/UT code '{st}' detected (valid on legacy registrations)")
                    else:
                        notes.append(f"Recognized state code: {st}")

                    # EV detection: Series starts with 'E' or 'EV'
                    if series.startswith("EV") or (st == "DL" and series.startswith("E")):
                        notes.append("Electric vehicle series indicator detected")

                    # Commercial vehicle detection in Delhi
                    if st == "DL" and series and series[0] in DELHI_VEHICLE_CATEGORIES:
                        cat_desc = DELHI_VEHICLE_CATEGORIES[series[0]]
                        notes.append(f"Delhi vehicle category: {cat_desc}")
                else:
                    reasons = []
                    if not rto_ok:
                        reasons.append("Single-digit RTO outside Delhi")
                    if not num_ok:
                        reasons.append("Registration number is 0000")
                    if not ser_ok:
                        reasons.append("Series contains disallowed letter 'I' or 'O'")
                    notes.append("Standard pattern matched with statutory violations: " + ", ".join(reasons))
            else:
                notes.append(f"Prefix '{st}' matches standard syntax but is not a recognized Indian state code")

        else:
            notes.append("Does not match strict Indian registration regular expression patterns")

        # Position-Aware Confusion Alternative Generation
        variants: List[Tuple[str, float, str]] = []
        if self.enable_variant_generation:
            variants = self._generate_confusion_variants(clean, format_type, state)

        status_str = "VALID" if is_valid else "INVALID_FORMAT"

        return NormalizedPlate(
            raw_text=raw_str,
            clean_text=clean,
            status=status_str,
            is_valid_format=is_valid,
            format_type=format_type,
            state_code=state,
            district_code=district,
            series_code=series,
            number_code=number,
            confusion_variants=variants,
            validation_notes=notes
        )

    def _generate_confusion_variants(
        self,
        clean_text: str,
        format_type: str,
        state_code: Optional[str]
    ) -> List[Tuple[str, float, str]]:
        """
        Emits plausible alternative candidate strings without mutating clean_text.
        Prioritizes known position confusions:
        - Positions 0-1 (State prefix): should be letters; digit '0' -> 'O', '1' -> 'I', '8' -> 'B', etc.
        - Positions 2-3 (District): should be digits; letter 'O' -> '0', 'I' -> '1', 'B' -> '8', 'S' -> '5', 'Z' -> '2'
        - Final 4 positions (Number): should be digits; letter 'O' -> '0', 'B' -> '8', 'S' -> '5', 'Z' -> '2'
        """
        variants: List[Tuple[str, float, str]] = []
        chars = list(clean_text)
        n = len(chars)

        for i, ch in enumerate(chars):
            # Check state code position (indices 0 and 1) - must be letters
            if i < 2 and ch.isdigit() and ch in OCR_CONFUSION_MAP:
                for replacement in OCR_CONFUSION_MAP[ch]:
                    if replacement.isalpha():
                        new_chars = list(chars)
                        new_chars[i] = replacement
                        candidate_str = "".join(new_chars)
                        reason = f"Position {i}: Replaced digit '{ch}' with letter '{replacement}' in state prefix"
                        variants.append((candidate_str, self.penalty_per_substitution, reason))
                        if len(variants) >= self.max_variants:
                            return variants

            # Check trailing 4 numeric positions (indices n-4 to n) - must be digits
            if i >= max(0, n - 4) and ch.isalpha() and ch in OCR_CONFUSION_MAP:
                for replacement in OCR_CONFUSION_MAP[ch]:
                    if replacement.isdigit():
                        new_chars = list(chars)
                        new_chars[i] = replacement
                        candidate_str = "".join(new_chars)
                        reason = f"Position {i}: Replaced letter '{ch}' with digit '{replacement}' in number block"
                        variants.append((candidate_str, self.penalty_per_substitution, reason))
                        if len(variants) >= self.max_variants:
                            return variants

            # Check district code positions (indices 2 and 3) - must be digits
            if 2 <= i <= 3 and ch.isalpha() and ch in OCR_CONFUSION_MAP:
                for replacement in OCR_CONFUSION_MAP[ch]:
                    if replacement.isdigit():
                        new_chars = list(chars)
                        new_chars[i] = replacement
                        candidate_str = "".join(new_chars)
                        reason = f"Position {i}: Replaced letter '{ch}' with digit '{replacement}' in district code"
                        variants.append((candidate_str, self.penalty_per_substitution, reason))
                        if len(variants) >= self.max_variants:
                            return variants

        return variants


def normalize_plate(raw_text: Optional[str]) -> NormalizedPlate:
    """Convenience functional interface for plate normalization."""
    return PlateNormalizer().normalize(raw_text)


def is_valid_indian_plate(raw_text: Optional[str]) -> bool:
    """Convenience functional interface for checking if text is a valid Indian plate."""
    return PlateNormalizer().normalize(raw_text).is_valid_format
