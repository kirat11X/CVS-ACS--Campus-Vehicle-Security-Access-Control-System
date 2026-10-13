"""
Track A: Offline Evaluation Metrics & Error Taxonomy Module.

Provides comprehensive, mathematically rigorous offline evaluation metrics for
license plate OCR and registry matching pipelines, including:
- Exact-Plate Recognition Accuracy
- Character Error Rate (CER) via Levenshtein distance
- Registry Match Accuracy
- False-Match Rate (FMR) with explicit dual denominators (matched vs total)
- No-Match Rate (NMR) & Ambiguity Rate (AR)
- Coverage
- Latency Percentiles (P50, P90, P95, Mean)
- Granular Error Taxonomy Categorization

Adheres to research-track invariants: offline evaluation only, transparent reporting.
"""

from dataclasses import dataclass, field
import json
import math
from typing import Any, Dict, List, Optional, Tuple


def standard_levenshtein(s1: str, s2: str) -> int:
    """Computes standard unit-cost Levenshtein edit distance between two strings."""
    s1, s2 = s1.upper(), s2.upper()
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]


def calculate_cer(prediction: str, ground_truth: str) -> float:
    """
    Calculates Character Error Rate (CER):
    CER = LevenshteinDistance(prediction, ground_truth) / max(len(ground_truth), 1)
    """
    pred_clean = prediction.strip().upper() if prediction else ""
    gt_clean = ground_truth.strip().upper() if ground_truth else ""
    if not gt_clean:
        return 0.0 if not pred_clean else 1.0
    dist = standard_levenshtein(pred_clean, gt_clean)
    return round(dist / len(gt_clean), 4)


@dataclass(frozen=True)
class ErrorBreakdown:
    """Granular error taxonomy breakdown for audit and failure analysis."""
    substitution_errors: int = 0
    optical_confusion_substitutions: int = 0
    non_optical_substitutions: int = 0
    insertion_errors: int = 0
    deletion_errors: int = 0
    state_code_errors: int = 0
    district_series_errors: int = 0
    number_sequence_errors: int = 0
    incorrect_record_accepted: int = 0  # Critical: False Positive match to wrong vehicle
    ambiguous_rejections: int = 0       # Expected safe rejection
    unmatched_out_of_registry: int = 0  # Expected correct non-match

    def to_dict(self) -> Dict[str, int]:
        return {
            "substitution_errors": self.substitution_errors,
            "optical_confusion_substitutions": self.optical_confusion_substitutions,
            "non_optical_substitutions": self.non_optical_substitutions,
            "insertion_errors": self.insertion_errors,
            "deletion_errors": self.deletion_errors,
            "state_code_errors": self.state_code_errors,
            "district_series_errors": self.district_series_errors,
            "number_sequence_errors": self.number_sequence_errors,
            "incorrect_record_accepted": self.incorrect_record_accepted,
            "ambiguous_rejections": self.ambiguous_rejections,
            "unmatched_out_of_registry": self.unmatched_out_of_registry,
        }


@dataclass(frozen=True)
class EvaluationSummary:
    """Complete summary of offline ANPR evaluation across a test dataset."""
    baseline_id: str
    total_samples: int
    exact_plate_accuracy: float          # OCR predicted plate matches GT plate exactly
    mean_cer: float                      # Mean Character Error Rate
    registry_match_accuracy: float       # Predicted registry_id matches expected_registry_id
    false_match_rate_matched: float      # False matches / Total samples with resolved match
    false_match_rate_total: float        # False matches / Total samples overall
    no_match_rate: float                 # NO_MATCH decisions / Total samples
    ambiguity_rate: float                # AMBIGUOUS decisions / Total samples
    coverage: float                      # Resolved matches (EXACT + FUZZY) / Total samples
    error_breakdown: ErrorBreakdown
    latency_p50_ms: Optional[float] = None
    latency_p90_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    latency_mean_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "total_samples": self.total_samples,
            "exact_plate_accuracy": round(self.exact_plate_accuracy, 4),
            "mean_cer": round(self.mean_cer, 4),
            "registry_match_accuracy": round(self.registry_match_accuracy, 4),
            "false_match_rate_matched": round(self.false_match_rate_matched, 4),
            "false_match_rate_total": round(self.false_match_rate_total, 4),
            "no_match_rate": round(self.no_match_rate, 4),
            "ambiguity_rate": round(self.ambiguity_rate, 4),
            "coverage": round(self.coverage, 4),
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p90_ms": self.latency_p90_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_mean_ms": self.latency_mean_ms,
            "error_breakdown": self.error_breakdown.to_dict(),
            "metadata": self.metadata,
        }

    def format_markdown_table(self) -> str:
        """Generates a clean markdown summary table for reports."""
        lines = [
            f"### Baseline `{self.baseline_id}` Performance Summary",
            "",
            "| Metric | Value | Interpretation |",
            "| :--- | :--- | :--- |",
            f"| **Total Evaluated** | {self.total_samples} | Sample count |",
            f"| **Exact-Plate Accuracy** | {self.exact_plate_accuracy * 100:.2f}% | OCR candidate matches GT string exactly |",
            f"| **Mean CER** | {self.mean_cer:.4f} | Normalized Levenshtein distance per plate |",
            f"| **Registry Match Accuracy** | {self.registry_match_accuracy * 100:.2f}% | Correct registry record or correct rejection |",
            f"| **False-Match Rate (of Matched)** | {self.false_match_rate_matched * 100:.2f}% | False matches / total matched predictions |",
            f"| **False-Match Rate (of Total)** | {self.false_match_rate_total * 100:.2f}% | False matches / total test dataset |",
            f"| **Coverage** | {self.coverage * 100:.2f}% | Proportion of plates matched to a registry record |",
            f"| **No-Match Rate** | {self.no_match_rate * 100:.2f}% | Safely declared not in registry |",
            f"| **Ambiguity Rate** | {self.ambiguity_rate * 100:.2f}% | Safely flagged as ambiguous near-tie |",
        ]
        if self.latency_mean_ms is not None:
            lines.extend([
                f"| **Mean Latency** | {self.latency_mean_ms:.2f} ms | Average pipeline decision latency |",
                f"| **Latency P50 / P95** | {self.latency_p50_ms:.2f} / {self.latency_p95_ms:.2f} ms | Median and 95th percentile |",
            ])
        lines.append("")
        return "\n".join(lines)


class MetricCalculator:
    """
    Evaluator that aggregates test predictions against ground truth labels
    and computes standard metrics, safety rates, and error taxonomy breakdowns.
    """

    @staticmethod
    def classify_plate_errors(predicted_plate: str, ground_truth: str) -> Dict[str, int]:
        """
        Decomposes discrepancies between predicted plate and ground truth
        into specific character-level and structural error categories.
        """
        p = predicted_plate.upper().strip() if predicted_plate else ""
        g = ground_truth.upper().strip() if ground_truth else ""

        errors = {
            "substitutions": 0,
            "optical_confusions": 0,
            "non_optical_substitutions": 0,
            "insertions": 0,
            "deletions": 0,
            "state_code_errors": 0,
            "district_series_errors": 0,
            "number_errors": 0,
        }

        if p == g:
            return errors

        # Structural segment checks (if GT is standard Indian format)
        if len(g) >= 8:
            gt_state = g[:2]
            p_state = p[:2] if len(p) >= 2 else ""
            if gt_state != p_state:
                errors["state_code_errors"] += 1

            gt_num = g[-4:] if len(g) >= 4 else ""
            p_num = p[-4:] if len(p) >= 4 else ""
            if gt_num != p_num:
                errors["number_errors"] += 1

        # Alignment and edit categorization
        len_diff = len(p) - len(g)
        if len_diff > 0:
            errors["insertions"] += len_diff
        elif len_diff < 0:
            errors["deletions"] += abs(len_diff)

        # Character comparison up to common length
        common_len = min(len(p), len(g))
        from .registry_matcher import is_ocr_confusion

        for i in range(common_len):
            cp, cg = p[i], g[i]
            if cp != cg:
                errors["substitutions"] += 1
                if is_ocr_confusion(cp, cg):
                    errors["optical_confusions"] += 1
                else:
                    errors["non_optical_substitutions"] += 1

        return errors

    @classmethod
    def compute_metrics(
        cls,
        evaluations: List[Dict[str, Any]],
        baseline_id: str = "baseline_3",
        metadata: Optional[Dict[str, Any]] = None
    ) -> EvaluationSummary:
        """
        Computes evaluation summary across a list of test sample evaluation records.

        Each record in `evaluations` is expected to contain:
        - `observed_plate`: Optional[str] (top OCR candidate text)
        - `ground_truth_plate`: str
        - `status`: str (EXACT_MATCH, FUZZY_CONFIDENT, AMBIGUOUS, NO_MATCH, INVALID_INPUT)
        - `matched_registry_id`: Optional[str]
        - `expected_registry_id`: Optional[str] (None if out-of-registry or expected ambiguous)
        - `expected_status`: Optional[str]
        - `latency_ms`: Optional[float]
        """
        total = len(evaluations)
        if total == 0:
            return EvaluationSummary(
                baseline_id=baseline_id,
                total_samples=0,
                exact_plate_accuracy=0.0,
                mean_cer=0.0,
                registry_match_accuracy=0.0,
                false_match_rate_matched=0.0,
                false_match_rate_total=0.0,
                no_match_rate=0.0,
                ambiguity_rate=0.0,
                coverage=0.0,
                error_breakdown=ErrorBreakdown(),
                metadata=metadata or {},
            )

        exact_plate_correct = 0
        cer_sum = 0.0
        registry_correct = 0
        false_matches = 0
        total_matched = 0
        no_matches = 0
        ambiguous_count = 0
        latencies: List[float] = []

        sub_errs = 0
        opt_conf_errs = 0
        non_opt_errs = 0
        ins_errs = 0
        del_errs = 0
        state_errs = 0
        dist_series_errs = 0
        num_errs = 0
        incorrect_records = 0
        ambiguous_rejections = 0
        unmatched_out_of_reg = 0

        for item in evaluations:
            obs = item.get("observed_plate") or ""
            gt = item.get("ground_truth_plate") or ""
            status = item.get("status") or "NO_MATCH"
            matched_id = item.get("matched_registry_id")
            expected_id = item.get("expected_registry_id")
            expected_stat = item.get("expected_status")

            if "latency_ms" in item and item["latency_ms"] is not None:
                latencies.append(float(item["latency_ms"]))

            # 1. Exact-Plate Accuracy
            obs_clean = obs.strip().upper().replace(" ", "").replace("-", "")
            gt_clean = gt.strip().upper().replace(" ", "").replace("-", "")
            if obs_clean == gt_clean:
                exact_plate_correct += 1

            # 2. CER
            cer = calculate_cer(obs_clean, gt_clean)
            cer_sum += cer

            # 3. Status categorization
            is_matched = status in ("EXACT_MATCH", "FUZZY_CONFIDENT", "FUZZY_MATCH")
            if is_matched:
                total_matched += 1

            if status == "AMBIGUOUS":
                ambiguous_count += 1
                ambiguous_rejections += 1
            elif status == "NO_MATCH":
                no_matches += 1
                if not expected_id:
                    unmatched_out_of_reg += 1

            # 4. Registry Match Accuracy & False-Match Rate
            # A prediction is registry-correct if:
            # - It matched the exact expected registry ID, OR
            # - It correctly returned NO_MATCH when expected is None/NO_MATCH, OR
            # - It correctly returned AMBIGUOUS when expected is AMBIGUOUS
            if expected_stat == "AMBIGUOUS":
                if status == "AMBIGUOUS":
                    registry_correct += 1
                elif is_matched:
                    # Premature match on ambiguous case -> false match
                    false_matches += 1
                    incorrect_records += 1
            elif expected_id is None or expected_stat == "NO_MATCH":
                if status == "NO_MATCH":
                    registry_correct += 1
                elif is_matched:
                    # Matched an out-of-registry vehicle -> false match / hallucination
                    false_matches += 1
                    incorrect_records += 1
            else:
                # Expected a specific registry ID
                if is_matched and matched_id == expected_id:
                    registry_correct += 1
                elif is_matched and matched_id != expected_id:
                    # Matched the WRONG vehicle -> false match
                    false_matches += 1
                    incorrect_records += 1

            # 5. Granular plate character error decomposition
            errs = cls.classify_plate_errors(obs_clean, gt_clean)
            sub_errs += errs["substitutions"]
            opt_conf_errs += errs["optical_confusions"]
            non_opt_errs += errs["non_optical_substitutions"]
            ins_errs += errs["insertions"]
            del_errs += errs["deletions"]
            state_errs += errs["state_code_errors"]
            dist_series_errs += errs["district_series_errors"]
            num_errs += errs["number_errors"]

        # Latency calculations
        p50 = None
        p90 = None
        p95 = None
        mean_lat = None
        if latencies:
            latencies.sort()
            n = len(latencies)
            p50 = latencies[int(n * 0.50)]
            p90 = latencies[min(int(n * 0.90), n - 1)]
            p95 = latencies[min(int(n * 0.95), n - 1)]
            mean_lat = round(sum(latencies) / n, 2)

        # Dual denominator FMR
        fmr_matched = (false_matches / total_matched) if total_matched > 0 else 0.0
        fmr_total = false_matches / total

        breakdown = ErrorBreakdown(
            substitution_errors=sub_errs,
            optical_confusion_substitutions=opt_conf_errs,
            non_optical_substitutions=non_opt_errs,
            insertion_errors=ins_errs,
            deletion_errors=del_errs,
            state_code_errors=state_errs,
            district_series_errors=dist_series_errs,
            number_sequence_errors=num_errs,
            incorrect_record_accepted=incorrect_records,
            ambiguous_rejections=ambiguous_rejections,
            unmatched_out_of_registry=unmatched_out_of_reg,
        )

        return EvaluationSummary(
            baseline_id=baseline_id,
            total_samples=total,
            exact_plate_accuracy=exact_plate_correct / total,
            mean_cer=cer_sum / total,
            registry_match_accuracy=registry_correct / total,
            false_match_rate_matched=fmr_matched,
            false_match_rate_total=fmr_total,
            no_match_rate=no_matches / total,
            ambiguity_rate=ambiguous_count / total,
            coverage=total_matched / total,
            error_breakdown=breakdown,
            latency_p50_ms=p50,
            latency_p90_ms=p90,
            latency_p95_ms=p95,
            latency_mean_ms=mean_lat,
            metadata=metadata or {},
        )
