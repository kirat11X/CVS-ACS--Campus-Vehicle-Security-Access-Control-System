"""Indian registration-plate text checks. A read is flagged for review, never rewritten.

Formats (per the pipeline spec, after removing spaces and punctuation):
  standard  SS NN [A-Z]{1,3} NNNN   e.g. PB65AB1234, CH01A0001
  BH series NN BH NNNN AA           e.g. 22BH1234AA
The O/0, I/1, B/8, S/5 confusion table only produces *suggestions* for the reviewer.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

STANDARD_PLATE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$")
BH_PLATE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{2}$")

# States and UTs, including codes still seen on older plates (OR, UA, DN, DD, TS).
STATE_CODES = frozenset(
    "AN AP AR AS BR CG CH DD DL DN GA GJ HP HR JH JK KA KL LA LD MH ML MN MP MZ NL OD OR PB PY "
    "RJ SK TG TN TR TS UA UK UP WB".split()
)

CONFUSION_PAIRS = {"O": "0", "0": "O", "I": "1", "1": "I", "B": "8", "8": "B", "S": "5", "5": "S"}
MAX_CONFUSABLE_POSITIONS = 8  # cap on the swap search (2^8 variants)


def normalize_plate(text: str | None) -> str:
    """Uppercase ASCII letters and digits only; spaces, hyphens, dots and non-Latin script are dropped."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def plate_format(text: str) -> str | None:
    if STANDARD_PLATE.match(text):
        return "standard"
    if BH_PLATE.match(text):
        return "bh"
    return None


@dataclass(frozen=True)
class PlateCheck:
    raw: str
    text: str  # normalized read, exactly as read
    format: str | None
    regex_valid: bool
    state_code_known: bool
    confusion_suggestions: tuple[str, ...] = ()
    low_conf_positions: tuple[int, ...] = ()
    flags: tuple[str, ...] = field(default=())

    @property
    def state(self) -> str | None:
        return self.text[:2] if self.format == "standard" else ("BH" if self.format == "bh" else None)


def _confusion_variants(text: str, positions: list[int]) -> list[tuple[int, str]]:
    """(number of swaps, variant) for every non-empty subset of confusable positions."""
    out = []
    for k in range(1, len(positions) + 1):
        for subset in itertools.combinations(positions, k):
            chars = list(text)
            for i in subset:
                chars[i] = CONFUSION_PAIRS[chars[i]]
            out.append((k, "".join(chars)))
    return out


def check_plate(raw: str | None, char_confs: list[float] | None = None, low_char_conf: float = 0.5) -> PlateCheck:
    """Validate a read. `char_confs` aligns with the normalized text (one score per character)."""
    text = normalize_plate(raw)
    fmt = plate_format(text)
    flags: list[str] = []
    if not text:
        flags.append("empty")
    if fmt is None and text:
        flags.append("regex_invalid")
    state_known = fmt == "bh" or (fmt == "standard" and text[:2] in STATE_CODES)
    if fmt == "standard" and not state_known:
        flags.append("unknown_state")

    positions = [i for i, ch in enumerate(text) if ch in CONFUSION_PAIRS]
    if len(positions) > MAX_CONFUSABLE_POSITIONS:
        if char_confs and len(char_confs) == len(text):
            positions = sorted(positions, key=lambda i: char_confs[i])[:MAX_CONFUSABLE_POSITIONS]
        else:
            positions = positions[:MAX_CONFUSABLE_POSITIONS]
    suggestions = sorted(
        {(k, v) for k, v in _confusion_variants(text, sorted(positions)) if plate_format(v) and v != text}
    )
    suggestion_texts = tuple(v for _, v in suggestions)
    if suggestion_texts:
        flags.append("confusion_suggestion" if fmt is None else "ambiguous_confusion")

    low = ()
    if char_confs is not None:
        if len(char_confs) != len(text):
            flags.append("char_conf_misaligned")
        else:
            low = tuple(i for i, c in enumerate(char_confs) if c < low_char_conf)
            if low:
                flags.append("low_char_conf")
    return PlateCheck(
        raw=raw or "", text=text, format=fmt, regex_valid=fmt is not None, state_code_known=state_known,
        confusion_suggestions=suggestion_texts, low_conf_positions=low, flags=tuple(flags),
    )
