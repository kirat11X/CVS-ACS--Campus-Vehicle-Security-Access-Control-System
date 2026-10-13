from typing import FrozenSet, Tuple

# Ported from the Phase 5A prototype (scripts/prototypes/phase5_identity_resolution/fuzzy_matcher.py).
# Production code must not import from scripts/, so the scoring lives here.

OCR_CONFUSION_PAIRS: FrozenSet[Tuple[str, str]] = frozenset({
    ("O", "0"), ("0", "O"),
    ("I", "1"), ("1", "I"),
    ("B", "8"), ("8", "B"),
    ("S", "5"), ("5", "S"),
    ("Z", "2"), ("2", "Z"),
    ("D", "0"), ("0", "D"),
    ("Q", "0"), ("0", "Q"),
    ("G", "6"), ("6", "G"),
})

def weighted_levenshtein(s1: str, s2: str, ocr_confusion_penalty: float = 0.25) -> float:
    """
    Levenshtein distance where substituting a known OCR confusion pair
    (e.g. O/0, B/8) costs ocr_confusion_penalty instead of 1.
    """
    s1 = s1.upper()
    s2 = s2.upper()
    m, n = len(s1), len(s2)
    prev = [float(j) for j in range(n + 1)]
    for i in range(1, m + 1):
        curr = [float(i)] + [0.0] * n
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                cost = 0.0
            elif (s1[i - 1], s2[j - 1]) in OCR_CONFUSION_PAIRS:
                cost = ocr_confusion_penalty
            else:
                cost = 1.0
            curr[j] = min(prev[j] + 1.0, curr[j - 1] + 1.0, prev[j - 1] + cost)
        prev = curr
    return prev[n]

def plate_similarity(s1: str, s2: str, ocr_confusion_penalty: float = 0.25) -> float:
    """Similarity in [0.0, 1.0] derived from the weighted Levenshtein distance."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1.upper() == s2.upper():
        return 1.0
    dist = weighted_levenshtein(s1, s2, ocr_confusion_penalty=ocr_confusion_penalty)
    return round(max(0.0, min(1.0, 1.0 - dist / max(len(s1), len(s2)))), 4)
