"""
Track A: Multi-Reader OCR Candidate Ranking Module.

Provides a model-independent interface that aggregates, normalizes, and ranks
competing license plate hypotheses produced by one or more OCR readers (e.g.,
primary edge detector, secondary vision-language OCR, synthetic generators).

Key Invariants:
- Missing OCR confidence is explicitly handled (never silently defaulted to 0.0 or 1.0).
- OCR confidence, candidate ranking scores, and registry similarity scores remain separate.
- Scores are transparent and traceable; no synthetic 'pseudo-probabilities' are claimed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .normalization import NormalizedPlate, PlateNormalizer


@dataclass(frozen=True)
class OCRCandidate:
    """A raw candidate hypothesis emitted by an OCR engine or upstream perception worker."""
    raw_text: str
    source: str
    confidence: Optional[float] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    normalized: Optional[NormalizedPlate] = None


@dataclass(frozen=True)
class RankedCandidate:
    """An OCR candidate ranked with transparent component scores and an auditable explanation."""
    candidate: OCRCandidate
    rank: int
    ranking_score: float
    has_confidence: bool
    component_scores: Dict[str, float]
    explanation: str


class OCRCandidateRanker:
    """
    Ranks multiple OCR candidates using a transparent, rule-based scoring methodology.
    """

    def __init__(
        self,
        normalizer: Optional[PlateNormalizer] = None,
        default_confidence: float = 0.50,
        weight_confidence: float = 0.50,
        weight_format: float = 0.35,
        weight_length: float = 0.15,
        source_reliability: Optional[Dict[str, float]] = None
    ):
        self.normalizer = normalizer or PlateNormalizer()
        self.default_confidence = default_confidence
        self.weight_confidence = weight_confidence
        self.weight_format = weight_format
        self.weight_length = weight_length
        self.source_reliability = source_reliability or {
            "camera_primary": 1.00,
            "paddleocr_vl": 1.05,
            "fast_plate_ocr": 0.95,
            "synthetic_oracle": 1.00,
            "fallback": 0.80
        }

    def score_single(self, cand: OCRCandidate) -> RankedCandidate:
        """Computes transparent ranking score and audit explanation for a single candidate."""
        # 1. Normalize if not already present
        norm = cand.normalized or self.normalizer.normalize(cand.raw_text)

        # 2. Confidence Evaluation
        has_conf = cand.confidence is not None
        if has_conf:
            raw_conf = float(cand.confidence)
            # Clip between 0.0 and 1.0
            conf_val = max(0.0, min(1.0, raw_conf))
            conf_note = f"Reported OCR confidence: {conf_val:.2f}"
        else:
            conf_val = self.default_confidence
            conf_note = f"Missing confidence; defaulted to neutral {self.default_confidence:.2f}"

        # 3. Format Validity Scoring
        if norm.is_valid_format:
            format_score = 1.00
            format_note = f"Valid Indian format ({norm.format_type})"
        elif norm.format_type == "NON_STANDARD" and len(norm.clean_text) >= 8:
            format_score = 0.50
            format_note = "Plausible length but non-standard syntax"
        elif norm.format_type.startswith("MALFORMED"):
            format_score = 0.10
            format_note = f"Syntax invalid ({norm.format_type})"
        else:
            format_score = 0.20
            format_note = f"Unrecognized pattern ({norm.format_type})"

        # 4. Length Plausibility Scoring (Standard Indian plates are 9-10 chars, occasionally 8 or 11)
        length = len(norm.clean_text)
        if length in (9, 10):
            length_score = 1.00
        elif length in (8, 11):
            length_score = 0.80
        elif 6 <= length <= 12:
            length_score = 0.50
        else:
            length_score = 0.00

        # 5. Source Multiplier
        source_mult = self.source_reliability.get(cand.source, self.source_reliability.get("fallback", 0.80))

        # Composite Ranking Score calculation (Linear combination)
        base_score = (
            self.weight_confidence * conf_val +
            self.weight_format * format_score +
            self.weight_length * length_score
        )
        total_score = round(base_score * source_mult, 4)

        explanation = (
            f"Score {total_score:.4f} [Source '{cand.source}' (x{source_mult:.2f}) | "
            f"{conf_note} | {format_note} | Length {length} (score {length_score:.2f})]"
        )

        scores_dict = {
            "source_multiplier": source_mult,
            "confidence_score": conf_val,
            "format_score": format_score,
            "length_score": length_score,
            "unweighted_composite": round(base_score, 4),
            "final_ranking_score": total_score
        }

        # Update candidate with normalized plate if needed
        enriched_cand = OCRCandidate(
            raw_text=cand.raw_text,
            source=cand.source,
            confidence=cand.confidence,
            provenance=cand.provenance,
            normalized=norm
        )

        return RankedCandidate(
            candidate=enriched_cand,
            rank=-1,  # Assigned in rank_candidates
            ranking_score=total_score,
            has_confidence=has_conf,
            component_scores=scores_dict,
            explanation=explanation
        )

    def rank_candidates(self, candidates: List[OCRCandidate]) -> List[RankedCandidate]:
        """Ranks a list of candidate OCR strings in descending order of ranking score."""
        if not candidates:
            return []

        scored = [self.score_single(c) for c in candidates]
        # Sort descending by ranking score
        scored.sort(key=lambda x: x.ranking_score, reverse=True)

        ranked: List[RankedCandidate] = []
        for rank_idx, s in enumerate(scored, start=1):
            ranked.append(RankedCandidate(
                candidate=s.candidate,
                rank=rank_idx,
                ranking_score=s.ranking_score,
                has_confidence=s.has_confidence,
                component_scores=s.component_scores,
                explanation=f"Rank #{rank_idx}: {s.explanation}"
            ))

        return ranked
