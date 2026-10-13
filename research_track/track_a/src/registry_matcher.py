"""
Track A: Registry-Constrained Fuzzy Matching Module.

Constrains candidate plate hypotheses against an authorized vehicle registry.
Enforces strict ambiguity rejection and safety margins:
- UNKNOWN over WRONG RECORD
- AMBIGUOUS over FALSE CERTAINTY
- Plate string match != Identity assertion

Does not connect to production databases or services.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Dict, List, Optional, Set, Tuple

# Standard optical OCR character confusion pairs with reduced edit penalties
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
    """Checks if two characters form a known optical OCR confusion pair."""
    return (c1.upper(), c2.upper()) in OCR_CONFUSION_PAIRS


def weighted_levenshtein(
    s1: str,
    s2: str,
    ocr_confusion_penalty: float = 0.25,
    normal_substitution_penalty: float = 1.0,
    insertion_penalty: float = 1.0,
    deletion_penalty: float = 1.0
) -> float:
    """
    Calculates weighted Levenshtein distance with reduced penalties for
    well-known optical character confusions (e.g., O vs 0, I vs 1).
    """
    s1 = s1.upper()
    s2 = s2.upper()
    m, n = len(s1), len(s2)

    dp = [[0.0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = float(i) * deletion_penalty
    for j in range(n + 1):
        dp[0][j] = float(j) * insertion_penalty

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                cost = 0.0
            elif is_ocr_confusion(s1[i - 1], s2[j - 1]):
                cost = ocr_confusion_penalty
            else:
                cost = normal_substitution_penalty

            dp[i][j] = min(
                dp[i - 1][j] + deletion_penalty,      # deletion
                dp[i][j - 1] + insertion_penalty,     # insertion
                dp[i - 1][j - 1] + cost               # substitution
            )

    return dp[m][n]


def compute_string_similarity(
    s1: str,
    s2: str,
    ocr_confusion_penalty: float = 0.25
) -> float:
    """
    Normalizes weighted Levenshtein distance into a similarity metric in [0.0, 1.0].
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


class MatchStatus(str, Enum):
    """Categorical resolution status of a registry match."""
    EXACT_MATCH = "EXACT_MATCH"
    FUZZY_CONFIDENT = "FUZZY_CONFIDENT"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True)
class RegistryRecord:
    """An authorized vehicle record in the campus registry."""
    registry_id: str
    plate: str
    raw_plate: str = ""
    vehicle_type: str = "CAR"
    owner_category: str = "UNKNOWN"
    status: str = "ACTIVE"


@dataclass(frozen=True)
class MatchCandidate:
    """A scored registry candidate evaluated during matching."""
    record: RegistryRecord
    similarity_score: float
    method: str
    details: str


@dataclass(frozen=True)
class RegistryMatchResult:
    """
    Full auditable output of the registry-constrained matcher.
    Adheres strictly to the architectural invariant that a registry match is
    an observation context, not a gate barrier decision or human identity claim.
    """
    status: MatchStatus
    matched_record: Optional[RegistryRecord]
    matched_plate: Optional[str]
    similarity_score: float
    score_margin: float
    qualifying_candidates: List[MatchCandidate]
    is_ambiguous: bool
    threshold_used: float
    ambiguity_margin_used: float
    algorithm_used: str
    explanation: str


class RegistryMatcher:
    """
    Performs constrained search against an offline vehicle registry.
    """

    def __init__(
        self,
        registry: List[RegistryRecord],
        min_similarity_threshold: float = 0.82,
        ambiguity_margin: float = 0.07,
        ocr_confusion_penalty: float = 0.25,
        algorithm: str = "weighted_levenshtein",
        max_qualifying_candidates: int = 5
    ):
        self.registry = registry
        self.min_similarity_threshold = min_similarity_threshold
        self.ambiguity_margin = ambiguity_margin
        self.ocr_confusion_penalty = ocr_confusion_penalty
        self.algorithm = algorithm
        self.max_qualifying_candidates = max_qualifying_candidates

        # Fast exact lookup index: normalized plate -> RegistryRecord
        self._plate_index: Dict[str, RegistryRecord] = {
            rec.plate.upper(): rec for rec in self.registry
        }

    def match(self, observed_plate: str) -> RegistryMatchResult:
        """
        Matches a normalized observed plate string against the vehicle registry.
        """
        if not observed_plate or not observed_plate.strip():
            return RegistryMatchResult(
                status=MatchStatus.INVALID_INPUT,
                matched_record=None,
                matched_plate=None,
                similarity_score=0.0,
                score_margin=0.0,
                qualifying_candidates=[],
                is_ambiguous=False,
                threshold_used=self.min_similarity_threshold,
                ambiguity_margin_used=self.ambiguity_margin,
                algorithm_used=self.algorithm,
                explanation="Observed plate string is empty or null"
            )

        norm_obs = observed_plate.strip().upper()

        # Step 1: Exact Match Fast Path
        if norm_obs in self._plate_index:
            matched_rec = self._plate_index[norm_obs]
            cand = MatchCandidate(
                record=matched_rec,
                similarity_score=1.0000,
                method="EXACT",
                details="Exact normalized alphanumeric string match in registry"
            )
            return RegistryMatchResult(
                status=MatchStatus.EXACT_MATCH,
                matched_record=matched_rec,
                matched_plate=matched_rec.plate,
                similarity_score=1.0000,
                score_margin=1.0000,
                qualifying_candidates=[cand],
                is_ambiguous=False,
                threshold_used=self.min_similarity_threshold,
                ambiguity_margin_used=self.ambiguity_margin,
                algorithm_used="exact_hash",
                explanation=f"Exact match confirmed for registry record {matched_rec.registry_id}"
            )

        # Step 2: Constrained Fuzzy Match Evaluation
        scored: List[Tuple[RegistryRecord, float]] = []
        for rec in self.registry:
            sim = compute_string_similarity(
                norm_obs,
                rec.plate,
                ocr_confusion_penalty=self.ocr_confusion_penalty
            )
            scored.append((rec, sim))

        # Sort descending by similarity
        scored.sort(key=lambda x: x[1], reverse=True)

        # Filter qualifying candidates exceeding minimum similarity
        qualifying = [c for c in scored if c[1] >= self.min_similarity_threshold]

        # Case: No candidate meets the threshold -> NO_MATCH
        if not qualifying:
            top_score = scored[0][1] if scored else 0.0
            return RegistryMatchResult(
                status=MatchStatus.NO_MATCH,
                matched_record=None,
                matched_plate=None,
                similarity_score=top_score,
                score_margin=0.0,
                qualifying_candidates=[],
                is_ambiguous=False,
                threshold_used=self.min_similarity_threshold,
                ambiguity_margin_used=self.ambiguity_margin,
                algorithm_used=self.algorithm,
                explanation=f"No registry plate reached similarity threshold {self.min_similarity_threshold:.2f} (Best was {top_score:.4f})"
            )

        # Prepare candidates for review
        match_candidates: List[MatchCandidate] = [
            MatchCandidate(
                record=r,
                similarity_score=s,
                method="FUZZY",
                details=f"Weighted similarity {s:.4f}"
            )
            for r, s in qualifying[:self.max_qualifying_candidates]
        ]

        best_rec, best_score = qualifying[0]

        # Case: Ambiguity Check
        # If second candidate is within ambiguity margin, do not guess
        is_ambiguous = False
        margin = 1.0000
        if len(qualifying) > 1:
            second_rec, second_score = qualifying[1]
            margin = round(best_score - second_score, 4)
            if margin < self.ambiguity_margin:
                is_ambiguous = True

        if is_ambiguous:
            second_rec, second_score = qualifying[1]
            return RegistryMatchResult(
                status=MatchStatus.AMBIGUOUS,
                matched_record=None,  # NEVER resolve ambiguous match to a record!
                matched_plate=None,
                similarity_score=best_score,
                score_margin=margin,
                qualifying_candidates=match_candidates,
                is_ambiguous=True,
                threshold_used=self.min_similarity_threshold,
                ambiguity_margin_used=self.ambiguity_margin,
                algorithm_used=self.algorithm,
                explanation=(
                    f"Ambiguous candidates detected: '{best_rec.plate}' ({best_score:.4f}) and "
                    f"'{second_rec.plate}' ({second_score:.4f}) within margin {self.ambiguity_margin:.2f} "
                    f"(actual delta: {margin:.4f}). Resolution rejected to avoid false match."
                )
            )

        # Case: Confident Fuzzy Match
        return RegistryMatchResult(
            status=MatchStatus.FUZZY_CONFIDENT,
            matched_record=best_rec,
            matched_plate=best_rec.plate,
            similarity_score=best_score,
            score_margin=margin,
            qualifying_candidates=match_candidates,
            is_ambiguous=False,
            threshold_used=self.min_similarity_threshold,
            ambiguity_margin_used=self.ambiguity_margin,
            algorithm_used=self.algorithm,
            explanation=(
                f"Confident fuzzy match resolved to '{best_rec.plate}' "
                f"(score: {best_score:.4f}, margin: {margin:.4f} > {self.ambiguity_margin:.2f})"
            )
        )
