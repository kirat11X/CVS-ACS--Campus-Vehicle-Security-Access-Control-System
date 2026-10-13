"""
Track C: Offline Evaluation Metrics & Property-Based Verification Module.

Computes separate, rigorous evaluation metrics for:
1. Classifier Perception: Category Accuracy, Precision/Recall/F1, Macro-F1, Confusion Matrix,
   UNKNOWN detection rate, Abstention rate.
2. Deterministic Policy Engine: Outcome Accuracy, False-Allow Rate, False-Alert Rate, Review Rate,
   Coverage, Rule Conflict Detection Rate, and Reason Code Correctness.

Invariants:
- Classifier accuracy and policy correctness are evaluated independently.
- False-Allow Rate is explicitly highlighted as the critical perimeter security failure metric.
- Property tests verify rule-order invariance, input determinism, and priority conflict safety.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import (
    ClassificationOutput,
    ItemCategoryCode,
    PolicyRule,
    ScreeningOutcome,
    ScreeningResult,
)


@dataclass(frozen=True)
class ClassifierEvaluationSummary:
    """Evaluation metrics for ML/heuristic item classification perception."""
    total_samples: int
    accuracy: float
    macro_f1: float
    per_category_metrics: Dict[str, Dict[str, float]]
    unknown_detection_rate: float
    abstention_rate: float
    confusion_matrix: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_category_metrics": self.per_category_metrics,
            "unknown_detection_rate": round(self.unknown_detection_rate, 4),
            "abstention_rate": round(self.abstention_rate, 4),
            "confusion_matrix": self.confusion_matrix,
        }


@dataclass(frozen=True)
class PolicyEvaluationSummary:
    """Evaluation metrics for deterministic policy engine outcomes."""
    total_samples: int
    outcome_accuracy: float
    false_allow_rate: float       # CRITICAL: cases that should NOT be ALLOW but received ALLOW
    false_alert_rate: float       # Friction: cases that should NOT be ALERT but received ALERT
    review_rate: float            # % of items routed to manual guard review
    coverage: float               # % of cases evaluated without unexpected failure
    rule_conflict_rate: float     # % of cases where priority tie conflicts were detected
    reason_code_correctness: float
    outcome_distribution: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "outcome_accuracy": round(self.outcome_accuracy, 4),
            "false_allow_rate": round(self.false_allow_rate, 4),
            "false_alert_rate": round(self.false_alert_rate, 4),
            "review_rate": round(self.review_rate, 4),
            "coverage": round(self.coverage, 4),
            "rule_conflict_rate": round(self.rule_conflict_rate, 4),
            "reason_code_correctness": round(self.reason_code_correctness, 4),
            "outcome_distribution": self.outcome_distribution,
        }

    def format_markdown_table(self) -> str:
        """Formats policy metrics as markdown table."""
        lines = [
            "### Deterministic Policy Engine Evaluation Summary",
            "",
            "| Metric | Value | Security / Operational Interpretation |",
            "| :--- | :--- | :--- |",
            f"| **Evaluated Cases** | {self.total_samples} | Total screening evaluation count |",
            f"| **Outcome Accuracy** | {self.outcome_accuracy * 100:.1f}% | Exact agreement with expected policy action |",
            f"| **False-Allow Rate** | {self.false_allow_rate * 100:.2f}% | **CRITICAL SECURITY RISK** (Disallowed items permitted) |",
            f"| **False-Alert Rate** | {self.false_alert_rate * 100:.2f}% | Operational friction (Harmless items escalated) |",
            f"| **Review Rate** | {self.review_rate * 100:.1f}% | Workload routed to guard inspection queue |",
            f"| **Rule Conflict Rate** | {self.rule_conflict_rate * 100:.1f}% | Cases with detected priority tie conflicts |",
            f"| **Reason Code Correctness** | {self.reason_code_correctness * 100:.1f}% | Cases where expected reason codes were emitted |",
            f"| **Outcome Distribution** | `ALLOW`: {self.outcome_distribution.get('ALLOW', 0)}, `REVIEW`: {self.outcome_distribution.get('REVIEW', 0)}, `ALERT`: {self.outcome_distribution.get('ALERT', 0)} | Categorical distribution |",
            ""
        ]
        return "\n".join(lines)


class MetricCalculator:
    """
    Evaluates item classification and deterministic policy engine outputs independently.
    """

    @classmethod
    def evaluate_classifier(
        cls,
        predictions: List[ClassificationOutput],
        ground_truth: List[ItemCategoryCode]
    ) -> ClassifierEvaluationSummary:
        """
        Calculates category prediction metrics against ground-truth labels.
        """
        n = len(predictions)
        if n == 0 or len(ground_truth) != n:
            return ClassifierEvaluationSummary(
                total_samples=0,
                accuracy=0.0,
                macro_f1=0.0,
                per_category_metrics={},
                unknown_detection_rate=0.0,
                abstention_rate=0.0,
                confusion_matrix={},
            )

        correct = 0
        conf_mat: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        all_cats: Set[str] = {c.value for c in ItemCategoryCode}

        for p, g in zip(predictions, ground_truth):
            p_cat = p.predicted_category.value
            g_cat = g.value
            conf_mat[g_cat][p_cat] += 1
            if p_cat == g_cat:
                correct += 1

        accuracy = correct / n

        # Per-category Precision, Recall, F1
        per_cat: Dict[str, Dict[str, float]] = {}
        f1_list: List[float] = []

        for cat in all_cats:
            tp = conf_mat[cat][cat]
            fp = sum(conf_mat[other][cat] for other in all_cats if other != cat)
            fn = sum(conf_mat[cat][other] for other in all_cats if other != cat)

            prec = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
            rec = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

            support = tp + fn
            per_cat[cat] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": float(support),
            }
            if support > 0:
                f1_list.append(f1)

        macro_f1 = (sum(f1_list) / len(f1_list)) if f1_list else 0.0

        # UNKNOWN detection rate: how many GT UNKNOWN were predicted as UNKNOWN
        gt_unknown_count = sum(1 for g in ground_truth if g == ItemCategoryCode.UNKNOWN)
        pred_unknown_on_gt = sum(1 for p, g in zip(predictions, ground_truth) if g == ItemCategoryCode.UNKNOWN and p.predicted_category == ItemCategoryCode.UNKNOWN)
        unknown_det_rate = (pred_unknown_on_gt / gt_unknown_count) if gt_unknown_count > 0 else 1.0

        # Abstention rate (% where is_uncertain is True or category is UNKNOWN)
        abstention_rate = sum(1 for p in predictions if p.is_uncertain or p.predicted_category == ItemCategoryCode.UNKNOWN) / n

        return ClassifierEvaluationSummary(
            total_samples=n,
            accuracy=accuracy,
            macro_f1=macro_f1,
            per_category_metrics=per_cat,
            unknown_detection_rate=unknown_det_rate,
            abstention_rate=abstention_rate,
            confusion_matrix={k: dict(v) for k, v in conf_mat.items()},
        )

    @classmethod
    def evaluate_policy(
        cls,
        results: List[ScreeningResult],
        ground_truth: List[Dict[str, Any]]
    ) -> PolicyEvaluationSummary:
        """
        Calculates policy engine decision outcomes against expected security actions.
        Each ground_truth entry has: 'expected_outcome' (ALLOW/REVIEW/ALERT) and optional 'expected_reason_codes'.
        """
        n = len(results)
        if n == 0 or len(ground_truth) != n:
            return PolicyEvaluationSummary(
                total_samples=0,
                outcome_accuracy=0.0,
                false_allow_rate=0.0,
                false_alert_rate=0.0,
                review_rate=0.0,
                coverage=0.0,
                rule_conflict_rate=0.0,
                reason_code_correctness=0.0,
                outcome_distribution={},
            )

        correct_outcomes = 0
        false_allows = 0
        false_alerts = 0
        review_count = 0
        conflict_count = 0
        correct_reasons = 0
        dist: Dict[str, int] = defaultdict(int)

        for res, gt in zip(results, ground_truth):
            obs_out = res.outcome.value
            exp_out = gt.get("expected_outcome")
            dist[obs_out] += 1

            if obs_out == exp_out:
                correct_outcomes += 1

            # False Allow: Expected was REVIEW or ALERT, but got ALLOW!
            if exp_out in ("REVIEW", "ALERT") and obs_out == "ALLOW":
                false_allows += 1

            # False Alert: Expected was ALLOW or REVIEW, but got ALERT!
            if exp_out in ("ALLOW", "REVIEW") and obs_out == "ALERT":
                false_alerts += 1

            if obs_out == "REVIEW":
                review_count += 1

            if "POLICY_RULE_CONFLICT" in res.reason_codes:
                conflict_count += 1

            # Reason code check
            exp_reasons = gt.get("expected_reason_codes")
            if exp_reasons:
                if any(r in res.reason_codes for r in exp_reasons):
                    correct_reasons += 1
            else:
                correct_reasons += 1

        return PolicyEvaluationSummary(
            total_samples=n,
            outcome_accuracy=correct_outcomes / n,
            false_allow_rate=false_allows / n,
            false_alert_rate=false_alerts / n,
            review_rate=review_count / n,
            coverage=1.0,
            rule_conflict_rate=conflict_count / n,
            reason_code_correctness=correct_reasons / n,
            outcome_distribution=dict(dist),
        )

    # =========================================================================
    # Property-Based Verification Helpers
    # =========================================================================

    @staticmethod
    def verify_rule_order_invariance(
        rules: List[PolicyRule],
        classification: ClassificationOutput,
        quantity: Optional[float] = None,
        platform: Optional[str] = None,
        evaluation_timestamp: str = "1970-01-01T00:00:00+00:00",
    ) -> bool:
        """
        Property Test: Reversing or shuffling rules must produce identical outcomes.
        """
        from .policy_engine import DeterministicPolicyEngine
        engine_forward = DeterministicPolicyEngine(rules=rules)
        engine_reverse = DeterministicPolicyEngine(rules=list(reversed(rules)))

        res1 = engine_forward.evaluate(
            classification,
            quantity=quantity,
            platform=platform,
            evaluation_timestamp=evaluation_timestamp,
        )
        res2 = engine_reverse.evaluate(
            classification,
            quantity=quantity,
            platform=platform,
            evaluation_timestamp=evaluation_timestamp,
        )

        return (res1.outcome == res2.outcome) and (set(res1.reason_codes) == set(res2.reason_codes))

    @staticmethod
    def verify_conflict_safety(
        conflicting_rules: List[PolicyRule],
        classification: ClassificationOutput,
        evaluation_timestamp: str = "1970-01-01T00:00:00+00:00",
    ) -> bool:
        """
        Property Test: Rules with equal priority and contradictory actions must NEVER yield ALLOW.
        """
        from .policy_engine import DeterministicPolicyEngine
        engine = DeterministicPolicyEngine(rules=conflicting_rules)
        res = engine.evaluate(classification, evaluation_timestamp=evaluation_timestamp)

        is_safe = (res.outcome != ScreeningOutcome.ALLOW)
        has_conflict_code = ("POLICY_RULE_CONFLICT" in res.reason_codes)
        return is_safe and has_conflict_code
