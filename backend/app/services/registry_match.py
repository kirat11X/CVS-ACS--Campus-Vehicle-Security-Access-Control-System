from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.app.config import REGISTRY_MATCH_MAX_EDITS

# Slide 6 "plate reading": OCR read -> registry match by edit distance.
#   one registry plate within one edit  -> LINKED (proposed; the guard can still correct it)
#   two or more within one edit         -> NEEDS_REVIEW (the guard picks)
#   none                                -> UNLINKED (logged, never treated as a threat)
# This is a display classification. It writes nothing, and the Phase 5C link_status
# (exact match on a confident read, or a guard confirmation) is unchanged.

_NUMBER_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}

def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]

def _deletions(s: str) -> Set[str]:
    return {s[:i] + s[i + 1:] for i in range(len(s))}

def describe_edit(read: str, plate: str) -> str:
    """Plain-language reason for a one-edit match, as on the slide's plate detail panel."""
    if len(read) == len(plate) + 1:
        return f"Matched {plate} after removing 1 extra character"
    if len(read) + 1 == len(plate):
        return f"Matched {plate} after adding 1 missing character"
    for r, p in zip(read, plate):
        if r != p:
            return f"Matched {plate} after correcting 1 misread character ({r} read for {p})"
    return f"Matched {plate}"

@dataclass(frozen=True)
class PlateMatch:
    outcome: str  # LINKED | NEEDS_REVIEW | UNLINKED
    basis: str  # EXACT | ONE_EDIT | CLOSE_MATCHES | NO_MATCH
    edits: Optional[int]
    plates: Tuple[str, ...]
    explanation: str

class RegistryIndex:
    """Symmetric-deletion index: finds every registry plate within one edit without a full scan."""

    def __init__(self, plates: Iterable[str], max_edits: int = REGISTRY_MATCH_MAX_EDITS):
        self.plates = sorted({p for p in plates if p})
        self.max_edits = max_edits
        self._by_key: Dict[str, Set[str]] = defaultdict(set)
        if max_edits == 1:
            for p in self.plates:
                self._by_key[p].add(p)
                for d in _deletions(p):
                    self._by_key[d].add(p)

    def close_plates(self, read: str) -> List[Tuple[str, int]]:
        if self.max_edits == 1:
            found = set()
            for key in {read} | _deletions(read):
                found |= self._by_key.get(key, set())
            pairs = [(p, levenshtein(read, p)) for p in found]
        else:
            pairs = [(p, levenshtein(read, p)) for p in self.plates if abs(len(p) - len(read)) <= self.max_edits]
        return sorted(((p, d) for p, d in pairs if d <= self.max_edits), key=lambda pd: (pd[1], pd[0]))

    def classify(self, read: Optional[str]) -> PlateMatch:
        read = (read or "").upper()
        close = self.close_plates(read) if read else []
        if any(d == 0 for _, d in close):
            return PlateMatch("LINKED", "EXACT", 0, (read,), f"Exact registry match {read}")
        if len(close) == 1:
            plate, edits = close[0]
            return PlateMatch("LINKED", "ONE_EDIT", edits, (plate,), describe_edit(read, plate))
        if close:
            plates = tuple(p for p, _ in close)
            count = _NUMBER_WORDS.get(len(plates), str(len(plates)))
            return PlateMatch("NEEDS_REVIEW", "CLOSE_MATCHES", 1, plates, f"{count} close matches: {', '.join(plates)}")
        word = "one edit" if self.max_edits == 1 else f"{self.max_edits} edits"
        return PlateMatch("UNLINKED", "NO_MATCH", None, (), f"No registry plate within {word}")

def classify_plate(read: str, registry_plates: Sequence[str]) -> PlateMatch:
    return RegistryIndex(registry_plates).classify(read)
