"""
Track A: Indian ANPR End-to-End Pipeline & Baseline Evaluation Harness.

Orchestrates normalization, multi-candidate ranking, and registry matching
across Baselines 0 through 3:
- Baseline 0: Normalized Exact Matching Only
- Baseline 1: Best OCR Candidate + Normalized Exact
- Baseline 2: Ranked Candidate + Constrained Fuzzy (No Ambiguity Rejection)
- Baseline 3: Full Track A Pipeline (Weighted Fuzzy with Ambiguity Margin Rejection)

Adheres to research-track invariants: offline execution, strict reproducibility,
and zero coupling to live production databases or services.
"""

import csv
from dataclasses import dataclass, field
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import yaml

from .normalization import PlateNormalizer, NormalizedPlate
from .candidate_ranking import OCRCandidate, RankedCandidate, OCRCandidateRanker
from .registry_matcher import (
    RegistryMatcher,
    RegistryRecord,
    RegistryMatchResult,
    MatchCandidate,
    MatchStatus,
    compute_string_similarity,
)
from .metrics import MetricCalculator, EvaluationSummary


@dataclass(frozen=True)
class PipelineResult:
    """End-to-end result of processing candidate plate hypotheses through a baseline."""
    baseline_id: str
    status: MatchStatus
    observed_plate: str
    matched_record: Optional[RegistryRecord]
    matched_plate: Optional[str]
    similarity_score: float
    score_margin: float
    ranked_candidates: List[RankedCandidate]
    qualifying_candidates: List[MatchCandidate]
    is_ambiguous: bool
    explanation: str
    latency_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "status": self.status.value,
            "observed_plate": self.observed_plate,
            "matched_record_id": self.matched_record.registry_id if self.matched_record else None,
            "matched_plate": self.matched_plate,
            "similarity_score": round(self.similarity_score, 4),
            "score_margin": round(self.score_margin, 4),
            "is_ambiguous": self.is_ambiguous,
            "candidate_count": len(self.ranked_candidates),
            "explanation": self.explanation,
            "latency_ms": round(self.latency_ms, 3),
        }


class ANPRPipeline:
    """
    Offline ANPR Pipeline supporting comparative evaluation across Baselines 0 to 3.
    """

    def __init__(
        self,
        registry: List[RegistryRecord],
        normalizer: Optional[PlateNormalizer] = None,
        ranker: Optional[OCRCandidateRanker] = None,
        min_similarity_threshold: float = 0.82,
        ambiguity_margin: float = 0.07,
        ocr_confusion_penalty: float = 0.25,
    ):
        self.registry = registry
        self.normalizer = normalizer or PlateNormalizer()
        self.ranker = ranker or OCRCandidateRanker(normalizer=self.normalizer)
        self.min_similarity_threshold = min_similarity_threshold
        self.ambiguity_margin = ambiguity_margin
        self.ocr_confusion_penalty = ocr_confusion_penalty

        # Full registry matcher for Baseline 3
        self.matcher = RegistryMatcher(
            registry=self.registry,
            min_similarity_threshold=self.min_similarity_threshold,
            ambiguity_margin=self.ambiguity_margin,
            ocr_confusion_penalty=self.ocr_confusion_penalty,
        )

        # Fast exact lookup index for Baselines 0 and 1
        self._exact_index: Dict[str, RegistryRecord] = {
            rec.plate.upper(): rec for rec in self.registry
        }

    @classmethod
    def from_config(cls, config_path: str, registry_csv_path: Optional[str] = None) -> "ANPRPipeline":
        """Factory constructor instantiating the pipeline from Track A's config.yaml."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        base_dir = os.path.dirname(config_path)
        reg_path = registry_csv_path or os.path.join(base_dir, cfg.get("evaluation", {}).get("registry_path", "fixtures/synthetic_registry.csv"))
        registry = cls.load_registry_from_csv(reg_path)

        norm_cfg = cfg.get("normalization", {})
        conf_cfg = norm_cfg.get("confusion_generation", {})
        normalizer = PlateNormalizer(
            strip_separators=norm_cfg.get("strip_separators", True),
            to_uppercase=norm_cfg.get("to_uppercase", True),
            min_length=norm_cfg.get("min_length", 6),
            max_length=norm_cfg.get("max_length", 12),
            validate_indian_format=norm_cfg.get("validate_indian_format", True),
            enable_variant_generation=conf_cfg.get("enabled", True),
            max_variants=conf_cfg.get("max_variants", 4),
            penalty_per_substitution=conf_cfg.get("penalty_per_substitution", 0.05),
        )

        rank_cfg = cfg.get("candidate_ranking", {})
        weights = rank_cfg.get("weights", {})
        ranker = OCRCandidateRanker(
            normalizer=normalizer,
            default_confidence=rank_cfg.get("default_confidence", 0.50),
            weight_confidence=weights.get("ocr_confidence", 0.50),
            weight_format=weights.get("format_validity", 0.35),
            weight_length=weights.get("length_plausibility", 0.15),
            source_reliability=rank_cfg.get("source_reliability"),
        )

        match_cfg = cfg.get("registry_matcher", {})
        return cls(
            registry=registry,
            normalizer=normalizer,
            ranker=ranker,
            min_similarity_threshold=match_cfg.get("min_similarity_threshold", 0.82),
            ambiguity_margin=match_cfg.get("ambiguity_margin", 0.07),
            ocr_confusion_penalty=match_cfg.get("ocr_confusion_penalty", 0.25),
        )

    @staticmethod
    def load_registry_from_csv(csv_path: str) -> List[RegistryRecord]:
        """Loads authorized campus vehicles from synthetic registry CSV."""
        records: List[RegistryRecord] = []
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(RegistryRecord(
                    registry_id=row["registry_id"].strip(),
                    plate=row["plate"].strip().upper(),
                    raw_plate=row.get("raw_plate", "").strip(),
                    vehicle_type=row.get("vehicle_type", "CAR").strip(),
                    owner_category=row.get("owner_category", "UNKNOWN").strip(),
                    status=row.get("status", "ACTIVE").strip(),
                ))
        return records

    @staticmethod
    def load_examples_from_csv(csv_path: str) -> List[Dict[str, Any]]:
        """
        Loads labeled test examples from CSV and parses candidates, confidences,
        and ground truth into structured dictionaries.
        """
        examples: List[Dict[str, Any]] = []
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_cands = [c.strip() for c in row["raw_ocr_candidates"].split("|") if c.strip()]
                conf_strs = [c.strip() for c in row["candidate_confidences"].split("|")] if row.get("candidate_confidences") else []
                sources = [s.strip() for s in row["candidate_sources"].split("|")] if row.get("candidate_sources") else []

                candidates: List[OCRCandidate] = []
                for i, text in enumerate(raw_cands):
                    conf = None
                    if i < len(conf_strs) and conf_strs[i] != "":
                        try:
                            conf = float(conf_strs[i])
                        except ValueError:
                            conf = None
                    src = sources[i] if i < len(sources) else "camera_primary"
                    candidates.append(OCRCandidate(raw_text=text, source=src, confidence=conf))

                examples.append({
                    "example_id": row["example_id"].strip(),
                    "case_type": row.get("case_type", "").strip(),
                    "candidates": candidates,
                    "ground_truth_plate": row["ground_truth_plate"].strip().upper(),
                    "expected_registry_id": row["expected_registry_id"].strip() if row.get("expected_registry_id") else None,
                    "expected_status": row.get("expected_status", "").strip(),
                })
        return examples

    def process(
        self,
        candidates: List[OCRCandidate],
        baseline_id: str = "baseline_3"
    ) -> PipelineResult:
        """
        Processes candidate plate hypotheses using the requested baseline configuration.
        """
        start_time = time.perf_counter()

        if baseline_id == "baseline_0":
            res = self._process_baseline_0(candidates)
        elif baseline_id == "baseline_1":
            res = self._process_baseline_1(candidates)
        elif baseline_id == "baseline_2":
            res = self._process_baseline_2(candidates)
        elif baseline_id == "baseline_3":
            res = self._process_baseline_3(candidates)
        else:
            raise ValueError(f"Unknown baseline_id: '{baseline_id}'. Must be one of baseline_0..baseline_3")

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return PipelineResult(
            baseline_id=baseline_id,
            status=res["status"],
            observed_plate=res["observed_plate"],
            matched_record=res["matched_record"],
            matched_plate=res["matched_plate"],
            similarity_score=res["similarity_score"],
            score_margin=res["score_margin"],
            ranked_candidates=res["ranked_candidates"],
            qualifying_candidates=res["qualifying_candidates"],
            is_ambiguous=res["is_ambiguous"],
            explanation=res["explanation"],
            latency_ms=latency_ms,
        )

    def _process_baseline_0(self, candidates: List[OCRCandidate]) -> Dict[str, Any]:
        """
        Baseline 0: First Candidate Normalized Exact Match Only.
        Does not rank candidates. Does not perform fuzzy matching.
        """
        if not candidates:
            return {
                "status": MatchStatus.INVALID_INPUT,
                "observed_plate": "",
                "matched_record": None,
                "matched_plate": None,
                "similarity_score": 0.0,
                "score_margin": 0.0,
                "ranked_candidates": [],
                "qualifying_candidates": [],
                "is_ambiguous": False,
                "explanation": "No OCR candidates provided.",
            }

        first_cand = candidates[0]
        norm = self.normalizer.normalize(first_cand.raw_text)
        ranked = [RankedCandidate(
            candidate=first_cand,
            rank=1,
            ranking_score=1.0,
            has_confidence=first_cand.confidence is not None,
            component_scores={"exact": 1.0},
            explanation="Unranked first-arrival candidate"
        )]

        clean_text = norm.clean_text
        if clean_text in self._exact_index:
            rec = self._exact_index[clean_text]
            cand = MatchCandidate(record=rec, similarity_score=1.0, method="EXACT", details="Exact string hit")
            return {
                "status": MatchStatus.EXACT_MATCH,
                "observed_plate": clean_text,
                "matched_record": rec,
                "matched_plate": rec.plate,
                "similarity_score": 1.0,
                "score_margin": 1.0,
                "ranked_candidates": ranked,
                "qualifying_candidates": [cand],
                "is_ambiguous": False,
                "explanation": f"Baseline 0 exact match found for {rec.registry_id}",
            }

        return {
            "status": MatchStatus.NO_MATCH,
            "observed_plate": clean_text,
            "matched_record": None,
            "matched_plate": None,
            "similarity_score": 0.0,
            "score_margin": 0.0,
            "ranked_candidates": ranked,
            "qualifying_candidates": [],
            "is_ambiguous": False,
            "explanation": "Baseline 0: No exact match found in registry.",
        }

    def _process_baseline_1(self, candidates: List[OCRCandidate]) -> Dict[str, Any]:
        """
        Baseline 1: Best OCR Candidate + Normalized Exact Match.
        Ranks candidates by confidence/format validity, then attempts exact match on top-1.
        """
        if not candidates:
            return self._process_baseline_0(candidates)

        ranked = self.ranker.rank_candidates(candidates)
        top = ranked[0]
        clean_text = top.candidate.normalized.clean_text if top.candidate.normalized else top.candidate.raw_text

        if clean_text in self._exact_index:
            rec = self._exact_index[clean_text]
            cand = MatchCandidate(record=rec, similarity_score=1.0, method="EXACT", details="Exact string hit")
            return {
                "status": MatchStatus.EXACT_MATCH,
                "observed_plate": clean_text,
                "matched_record": rec,
                "matched_plate": rec.plate,
                "similarity_score": 1.0,
                "score_margin": 1.0,
                "ranked_candidates": ranked,
                "qualifying_candidates": [cand],
                "is_ambiguous": False,
                "explanation": f"Baseline 1: Exact match on top-ranked candidate for {rec.registry_id}",
            }

        return {
            "status": MatchStatus.NO_MATCH,
            "observed_plate": clean_text,
            "matched_record": None,
            "matched_plate": None,
            "similarity_score": 0.0,
            "score_margin": 0.0,
            "ranked_candidates": ranked,
            "qualifying_candidates": [],
            "is_ambiguous": False,
            "explanation": "Baseline 1: Top-ranked candidate has no exact match in registry.",
        }

    def _process_baseline_2(self, candidates: List[OCRCandidate]) -> Dict[str, Any]:
        """
        Baseline 2: Ranked Candidate + Constrained Fuzzy (WITHOUT Ambiguity Rejection).
        Computes fuzzy similarity; if score >= threshold, accepts top hit blindly even if tied.
        """
        if not candidates:
            return self._process_baseline_0(candidates)

        ranked = self.ranker.rank_candidates(candidates)
        top = ranked[0]
        clean_text = top.candidate.normalized.clean_text if top.candidate.normalized else top.candidate.raw_text

        # Exact match fast path
        if clean_text in self._exact_index:
            rec = self._exact_index[clean_text]
            cand = MatchCandidate(record=rec, similarity_score=1.0, method="EXACT", details="Exact string hit")
            return {
                "status": MatchStatus.EXACT_MATCH,
                "observed_plate": clean_text,
                "matched_record": rec,
                "matched_plate": rec.plate,
                "similarity_score": 1.0,
                "score_margin": 1.0,
                "ranked_candidates": ranked,
                "qualifying_candidates": [cand],
                "is_ambiguous": False,
                "explanation": f"Baseline 2: Exact match found for {rec.registry_id}",
            }

        # Fuzzy matching without ambiguity rejection
        scored: List[Tuple[RegistryRecord, float]] = []
        for rec in self.registry:
            sim = compute_string_similarity(clean_text, rec.plate, ocr_confusion_penalty=self.ocr_confusion_penalty)
            scored.append((rec, sim))
        scored.sort(key=lambda x: x[1], reverse=True)

        qualifying = [c for c in scored if c[1] >= self.min_similarity_threshold]
        if not qualifying:
            top_sim = scored[0][1] if scored else 0.0
            return {
                "status": MatchStatus.NO_MATCH,
                "observed_plate": clean_text,
                "matched_record": None,
                "matched_plate": None,
                "similarity_score": top_sim,
                "score_margin": 0.0,
                "ranked_candidates": ranked,
                "qualifying_candidates": [],
                "is_ambiguous": False,
                "explanation": f"Baseline 2: No candidate reached threshold {self.min_similarity_threshold:.2f}",
            }

        best_rec, best_score = qualifying[0]
        margin = (best_score - qualifying[1][1]) if len(qualifying) > 1 else 1.0
        match_cands = [MatchCandidate(r, s, "FUZZY_NAIVE", f"Score {s:.4f}") for r, s in qualifying[:5]]

        # Blindly accept top candidate without ambiguity rejection!
        return {
            "status": MatchStatus.FUZZY_CONFIDENT,
            "observed_plate": clean_text,
            "matched_record": best_rec,
            "matched_plate": best_rec.plate,
            "similarity_score": best_score,
            "score_margin": margin,
            "ranked_candidates": ranked,
            "qualifying_candidates": match_cands,
            "is_ambiguous": False,
            "explanation": f"Baseline 2: Blind fuzzy match accepted '{best_rec.plate}' without checking ambiguity margin.",
        }

    def _process_baseline_3(self, candidates: List[OCRCandidate]) -> Dict[str, Any]:
        """
        Baseline 3: Full Track A Pipeline.
        Multi-candidate ranking, weighted Levenshtein matching, and strict ambiguity margin rejection.
        """
        if not candidates:
            return self._process_baseline_0(candidates)

        ranked = self.ranker.rank_candidates(candidates)
        top = ranked[0]
        clean_text = top.candidate.normalized.clean_text if top.candidate.normalized else top.candidate.raw_text

        # Evaluate through RegistryMatcher
        match_result = self.matcher.match(clean_text)

        # If top candidate yielded NO_MATCH or AMBIGUOUS, and top candidate has confusion variants,
        # or if secondary candidates exist, check if an unambiguous match can be confirmed.
        if match_result.status == MatchStatus.NO_MATCH and len(ranked) > 1:
            # Check runner-up candidate
            runner_up = ranked[1]
            runner_clean = runner_up.candidate.normalized.clean_text if runner_up.candidate.normalized else runner_up.candidate.raw_text
            secondary_result = self.matcher.match(runner_clean)
            if secondary_result.status in (MatchStatus.EXACT_MATCH, MatchStatus.FUZZY_CONFIDENT):
                match_result = secondary_result
                clean_text = runner_clean

        return {
            "status": match_result.status,
            "observed_plate": clean_text,
            "matched_record": match_result.matched_record,
            "matched_plate": match_result.matched_plate,
            "similarity_score": match_result.similarity_score,
            "score_margin": match_result.score_margin,
            "ranked_candidates": ranked,
            "qualifying_candidates": match_result.qualifying_candidates,
            "is_ambiguous": match_result.is_ambiguous,
            "explanation": match_result.explanation,
        }

    def evaluate_dataset(
        self,
        examples: List[Dict[str, Any]],
        baseline_id: str = "baseline_3",
        metadata: Optional[Dict[str, Any]] = None
    ) -> EvaluationSummary:
        """
        Evaluates a labeled dataset through the specified baseline and computes
        all evaluation metrics.
        """
        eval_records: List[Dict[str, Any]] = []

        for ex in examples:
            result = self.process(ex["candidates"], baseline_id=baseline_id)
            eval_records.append({
                "example_id": ex.get("example_id"),
                "case_type": ex.get("case_type"),
                "observed_plate": result.observed_plate,
                "ground_truth_plate": ex["ground_truth_plate"],
                "status": result.status.value,
                "matched_registry_id": result.matched_record.registry_id if result.matched_record else None,
                "expected_registry_id": ex.get("expected_registry_id"),
                "expected_status": ex.get("expected_status"),
                "latency_ms": result.latency_ms,
                "similarity_score": result.similarity_score,
                "score_margin": result.score_margin,
            })

        meta = dict(metadata or {})
        meta["baseline_id"] = baseline_id
        meta["example_count"] = len(examples)
        return MetricCalculator.compute_metrics(eval_records, baseline_id=baseline_id, metadata=meta)
