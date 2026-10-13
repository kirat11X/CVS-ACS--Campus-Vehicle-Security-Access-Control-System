from typing import List, Tuple, Set, Optional

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

def is_ocr_confusion(c1: str, c2: str) -> bool:
    return (c1.upper(), c2.upper()) in OCR_CONFUSION_PAIRS

def weighted_levenshtein(s1: str, s2: str, ocr_confusion_penalty: float = 0.25) -> float:
    """
    Computes weighted Levenshtein distance between two strings with reduced
    substitution penalties for well-known optical OCR confusion pairs.
    """
    s1 = s1.upper()
    s2 = s2.upper()
    m, n = len(s1), len(s2)

    dp = [[0.0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = float(i)
    for j in range(n + 1):
        dp[0][j] = float(j)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                cost = 0.0
            elif is_ocr_confusion(s1[i - 1], s2[j - 1]):
                cost = ocr_confusion_penalty
            else:
                cost = 1.0

            dp[i][j] = min(
                dp[i - 1][j] + 1.0,         # deletion
                dp[i][j - 1] + 1.0,         # insertion
                dp[i - 1][j - 1] + cost     # substitution
            )

    return dp[m][n]

def compute_similarity(s1: str, s2: str, ocr_confusion_penalty: float = 0.25) -> float:
    """
    Normalizes weighted Levenshtein distance into a similarity score in [0.0, 1.0].
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1.upper() == s2.upper():
        return 1.0

    max_len = max(len(s1), len(s2))
    dist = weighted_levenshtein(s1, s2, ocr_confusion_penalty=ocr_confusion_penalty)
    sim = 1.0 - (dist / max_len)
    return round(max(0.0, min(1.0, sim)), 4)

class FuzzyMatcher:
    """
    Deterministic OCR-aware candidate generator and scoring engine.
    Does not use LLMs, GPT, or external APIs.
    """
    def __init__(
        self,
        min_similarity: float = 0.85,
        ambiguity_margin: float = 0.08,
        ocr_confusion_penalty: float = 0.25
    ):
        self.min_similarity = min_similarity
        self.ambiguity_margin = ambiguity_margin
        self.ocr_confusion_penalty = ocr_confusion_penalty

    def score_candidates(
        self,
        observed_plate: str,
        candidate_plates: List[str]
    ) -> List[Tuple[str, float]]:
        """
        Calculates similarity for each candidate plate against the observed plate,
        returning candidates sorted by descending similarity.
        """
        scored = []
        for cand in candidate_plates:
            sim = compute_similarity(
                observed_plate,
                cand,
                ocr_confusion_penalty=self.ocr_confusion_penalty
            )
            scored.append((cand, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def evaluate_match(
        self,
        observed_plate: str,
        candidate_plates: List[str]
    ) -> Tuple[Optional[str], float, List[Tuple[str, float]], bool]:
        """
        Evaluates candidates against minimum similarity and ambiguity thresholds.
        Returns:
            (best_plate, best_score, qualifying_candidates, is_ambiguous)
        """
        scored = self.score_candidates(observed_plate, candidate_plates)
        qualifying = [c for c in scored if c[1] >= self.min_similarity]

        if not qualifying:
            top_score = scored[0][1] if scored else 0.0
            return (None, top_score, [], False)

        best_plate, best_score = qualifying[0]

        # Check for ambiguity: if second candidate is within ambiguity_margin
        is_ambiguous = False
        if len(qualifying) > 1:
            second_plate, second_score = qualifying[1]
            margin = best_score - second_score
            if margin < self.ambiguity_margin:
                is_ambiguous = True

        return (best_plate if not is_ambiguous else None, best_score, qualifying, is_ambiguous)
