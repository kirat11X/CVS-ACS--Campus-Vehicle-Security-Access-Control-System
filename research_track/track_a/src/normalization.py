"""
Track A: Indian License Plate Normalization Module.

Provides non-destructive canonical formatting, positional syntax validation,
and auditable confusion variant generation for Indian vehicle registration plates.

Key Invariant:
- Raw input is immutable and permanently preserved.
- Canonical cleaning preserves characters (no destructive in-place character swaps).
- Ambiguous OCR confusions (e.g., O/0, I/1, B/8) are emitted as alternative candidates
  with explicit provenance and penalty metrics rather than silently overwritten.
"""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple

# Recognized 2-letter state & union territory codes under Motor Vehicles Act, 1988
INDIAN_STATE_CODES: Set[str] = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UP", "WB"
}

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


@dataclass(frozen=True)
class NormalizedPlate:
    """Immutable representation of a normalized plate with full audit metadata."""
    raw_text: str
    clean_text: str
    is_valid_format: bool
    format_type: str
    state_code: Optional[str] = None
    district_code: Optional[str] = None
    series_code: Optional[str] = None
    number_code: Optional[str] = None
    confusion_variants: List[Tuple[str, float, str]] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)


class PlateNormalizer:
    """
    Configurable normalizer for Indian vehicle license plates.

    Rule 1 (Cleaning): Strips non-alphanumeric punctuation and whitespace; converts to uppercase.
    Rule 2 (Audit): Original string is stored unmodified in raw_text.
    Rule 3 (Syntax): Validates against standard, BH (Bharat), vintage, and special series.
    Rule 4 (Variant Generation): Position-aware substitution generator produces alternative candidates
                       with explicit penalty costs, without altering clean_text.
    """

    def __init__(
        self,
        strip_separators: bool = True,
        to_uppercase: bool = True,
        min_length: int = 6,
        max_length: int = 12,
        validate_indian_format: bool = True,
        enable_variant_generation: bool = True,
        max_variants: int = 4,
        penalty_per_substitution: float = 0.05
    ):
        self.strip_separators = strip_separators
        self.to_uppercase = to_uppercase
        self.min_length = min_length
        self.max_length = max_length
        self.validate_indian_format = validate_indian_format
        self.enable_variant_generation = enable_variant_generation
        self.max_variants = max_variants
        self.penalty_per_substitution = penalty_per_substitution

        # Regular expressions for Indian plate patterns:
        # Standard: 2 letters (state) + 1-2 digits (RTO) + 0-3 letters (series) + 4 digits (unique number)
        # e.g., PB65AB0902, CH01AA1111, DL1C1234, HR261234
        self._standard_pattern = re.compile(
            r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$"
        )
        # Bharat (BH) Series (introduced 2021): YY BH #### XX (e.g. 22BH1234AA)
        self._bh_pattern = re.compile(
            r"^([0-9]{2})(BH)([0-9]{4})([A-Z]{1,2})$"
        )
        # Military Vehicle: upward arrow or digits + letter + digits + letter (e.g. 21D123456A)
        self._military_pattern = re.compile(
            r"^([0-9]{2})([A-Z])([0-9]{5,6})([A-Z])$"
        )
        # Diplomatic: e.g., 22CD1234 or 19CC5678
        self._diplomatic_pattern = re.compile(
            r"^([0-9]{1,3})(CD|CC)([0-9]{1,4})$"
        )

    def clean_string(self, text: str) -> str:
        """Removes spaces, hyphens, dots, and non-alphanumerics; converts to uppercase."""
        if not text:
            return ""
        s = text
        if self.strip_separators:
            s = re.sub(r"[^A-Za-z0-9]", "", s)
        if self.to_uppercase:
            s = s.upper()
        return s.strip()

    def normalize(self, raw_text: Optional[str]) -> NormalizedPlate:
        """
        Executes full non-destructive normalization and validation pipeline.
        """
        if raw_text is None or not str(raw_text).strip():
            return NormalizedPlate(
                raw_text="" if raw_text is None else str(raw_text),
                clean_text="",
                is_valid_format=False,
                format_type="EMPTY",
                validation_notes=["Input text is null or empty whitespace"]
            )

        raw_str = str(raw_text)
        clean = self.clean_string(raw_str)
        notes: List[str] = []

        if len(clean) < self.min_length:
            notes.append(f"Length {len(clean)} below minimum threshold {self.min_length}")
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text=clean,
                is_valid_format=False,
                format_type="MALFORMED_TOO_SHORT",
                validation_notes=notes
            )

        if len(clean) > self.max_length:
            notes.append(f"Length {len(clean)} exceeds maximum threshold {self.max_length}")
            return NormalizedPlate(
                raw_text=raw_str,
                clean_text=clean,
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

        if m_std:
            st, dist, ser, num = m_std.groups()
            state = st
            district = dist
            series = ser if ser else ""
            number = num
            format_type = "STANDARD_INDIAN"
            if st in INDIAN_STATE_CODES:
                is_valid = True
                notes.append(f"Recognized state code: {st}")
            else:
                notes.append(f"Prefix '{st}' matches format but is not in recognized state code registry")
        elif m_bh:
            year, code, num, letters = m_bh.groups()
            state = code
            district = year
            series = letters
            number = num
            format_type = "BH_SERIES"
            is_valid = True
            notes.append(f"Bharat Series plate detected (Registration year: 20{year})")
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
        else:
            notes.append("Does not match strict Indian registration regular expression patterns")

        # Position-Aware Confusion Alternative Generation
        variants: List[Tuple[str, float, str]] = []
        if self.enable_variant_generation:
            variants = self._generate_confusion_variants(clean, format_type, state)

        return NormalizedPlate(
            raw_text=raw_str,
            clean_text=clean,
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
        - Positions 0-1 (State): should be letters; digit '0' -> 'O', '1' -> 'I'
        - Positions 2-3 (District): should be digits; letter 'O' -> '0', 'I' -> '1', 'B' -> '8'
        - Final 4 positions (Number): should be digits; letter 'O' -> '0', 'B' -> '8', 'S' -> '5'
        """
        variants: List[Tuple[str, float, str]] = []
        chars = list(clean_text)
        n = len(chars)

        for i, ch in enumerate(chars):
            # Check state code position (indices 0 and 1)
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

            # Check trailing 4 numeric positions (indices n-4 to n)
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

            # Check district code positions (indices 2 and 3)
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
