"""
Track A: Indian ANPR Research & Evaluation Prototype.
Provides non-destructive plate normalization, multi-OCR candidate ranking,
registry-constrained fuzzy matching, and offline evaluation metrics.
"""

from .normalization import PlateNormalizer, NormalizedPlate
from .candidate_ranking import OCRCandidate, RankedCandidate, OCRCandidateRanker
from .registry_matcher import RegistryMatcher, RegistryRecord, RegistryMatchResult, MatchStatus
from .resolver_adapter import Phase5AResolverAdapter
from .metrics import MetricCalculator, EvaluationSummary
from .pipeline import ANPRPipeline, PipelineResult

__all__ = [
    "PlateNormalizer",
    "NormalizedPlate",
    "OCRCandidate",
    "RankedCandidate",
    "OCRCandidateRanker",
    "RegistryMatcher",
    "RegistryRecord",
    "RegistryMatchResult",
    "MatchStatus",
    "Phase5AResolverAdapter",
    "MetricCalculator",
    "EvaluationSummary",
    "ANPRPipeline",
    "PipelineResult",
]
