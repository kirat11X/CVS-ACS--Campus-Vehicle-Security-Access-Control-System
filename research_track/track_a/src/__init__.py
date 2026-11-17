"""
Track A: Indian ANPR Research & Evaluation Prototype.
Provides non-destructive plate normalization, multi-OCR candidate ranking,
registry-constrained fuzzy matching, optical plate matching, and offline evaluation metrics.
"""

from .plate_normalizer import (
    PlateNormalizer,
    NormalizedPlate,
    normalize_plate,
    is_valid_indian_plate,
    CURRENT_STATES,
    FORMER_STATES,
    ALL_VALID_STATES,
    INDIAN_STATE_CODES,
    OCR_CONFUSION_MAP,
    OCR_CONFUSION_PAIRS,
)
from .candidate_ranking import OCRCandidate, RankedCandidate, OCRCandidateRanker
from .registry_matcher import (
    RegistryMatcher,
    OpticalPlateMatcher,
    RegistryRecord,
    MatchCandidate,
    RegistryMatchResult,
    MatchStatus,
    compute_string_similarity,
    weighted_levenshtein,
)
from .resolver_adapter import Phase5AResolverAdapter
from .metrics import MetricCalculator, EvaluationSummary
from .pipeline import ANPRPipeline, PipelineResult

__all__ = [
    "PlateNormalizer",
    "NormalizedPlate",
    "normalize_plate",
    "is_valid_indian_plate",
    "CURRENT_STATES",
    "FORMER_STATES",
    "ALL_VALID_STATES",
    "INDIAN_STATE_CODES",
    "OCR_CONFUSION_MAP",
    "OCR_CONFUSION_PAIRS",
    "OCRCandidate",
    "RankedCandidate",
    "OCRCandidateRanker",
    "RegistryMatcher",
    "OpticalPlateMatcher",
    "RegistryRecord",
    "MatchCandidate",
    "RegistryMatchResult",
    "MatchStatus",
    "compute_string_similarity",
    "weighted_levenshtein",
    "Phase5AResolverAdapter",
    "MetricCalculator",
    "EvaluationSummary",
    "ANPRPipeline",
    "PipelineResult",
]
