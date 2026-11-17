"""
Track C: Campus Safety Policy & Deterministic Evaluation Interface.

Provides a unified facade for evaluating item classifications against 
the 21 versioned campus safety policy rules (firearms, explosives, hazardous
chemicals, narcotics, unmanifested alcohol, commercial gas cylinders, drones,
and high-risk cargo).

Critical Invariants:
1. Pure Deterministic Evaluation: Bit-exact reproducibility given the same inputs.
2. Critical Uncertainty Escalation:
   - If is_uncertain=True or confidence < 0.70 (or None), any tentative ALLOW
     decision MUST degrade to REVIEW for human guard inspection.
   - Any ALERT decision NEVER degrades—if a hazardous or prohibited item is
     detected with high or low confidence, it MUST remain ALERT.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .category_normalization import CategoryNormalizer
from .policy_engine import DeterministicPolicyEngine
from .reason_codes import ReasonCode, ReasonCodeDetail, get_reason_code_detail
from .types import (
    ClassificationInput,
    ClassificationOutput,
    ItemCategoryCode,
    PolicyRule,
    RuleEvaluationTrace,
    ScreeningOutcome,
    ScreeningResult,
)

DEFAULT_POLICY_VERSION: str = "1.0"
CONFIDENCE_REVIEW_THRESHOLD: float = 0.70

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "policy_rules.json"


def load_policy_rules(rules_path: Optional[Path | str] = None) -> List[PolicyRule]:
    """
    Loads policy rules from JSON fixture or database export.
    Defaults to the canonical 21-rule Track C policy fixture.
    """
    path = Path(rules_path) if rules_path else _FIXTURE_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw_rules = json.load(f)

    rules: List[PolicyRule] = []
    for item in raw_rules:
        rules.append(
            PolicyRule(
                rule_id=item["rule_id"],
                category_code=ItemCategoryCode(item["category_code"]),
                action=ScreeningOutcome(item["action"]),
                priority=item["priority"],
                policy_version=item.get("policy_version", DEFAULT_POLICY_VERSION),
                min_quantity=item.get("min_quantity"),
                max_quantity=item.get("max_quantity"),
                quantity_unit=item.get("quantity_unit"),
                platform=item.get("platform"),
                effective_from=item.get("effective_from"),
                effective_to=item.get("effective_to"),
                active=item.get("active", True),
                description=item.get("description"),
            )
        )
    return rules


def create_policy_engine(
    rules: Optional[List[PolicyRule]] = None,
    default_policy_version: str = "v1.0",
    confidence_review_threshold: float = CONFIDENCE_REVIEW_THRESHOLD,
    treat_missing_confidence_as_review: bool = True,
) -> DeterministicPolicyEngine:
    """Creates a configured DeterministicPolicyEngine instance."""
    active_rules = rules if rules is not None else load_policy_rules()
    return DeterministicPolicyEngine(
        rules=active_rules,
        default_policy_version=default_policy_version,
        confidence_review_threshold=confidence_review_threshold,
        treat_missing_confidence_as_review=treat_missing_confidence_as_review,
    )


def evaluate_screening_policy(
    classification: ClassificationOutput,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    platform: Optional[str] = None,
    policy_version: Optional[str] = None,
    evaluation_timestamp: str = "2026-01-01T00:00:00Z",
    engine: Optional[DeterministicPolicyEngine] = None,
) -> ScreeningResult:
    """Evaluates a single item classification against campus safety rules."""
    active_engine = engine or create_policy_engine()
    return active_engine.evaluate(
        classification=classification,
        quantity=quantity,
        unit=unit,
        platform=platform,
        policy_version=policy_version,
        evaluation_timestamp=evaluation_timestamp,
    )


__all__ = [
    "CONFIDENCE_REVIEW_THRESHOLD",
    "CategoryNormalizer",
    "ClassificationInput",
    "ClassificationOutput",
    "DEFAULT_POLICY_VERSION",
    "DeterministicPolicyEngine",
    "ItemCategoryCode",
    "PolicyRule",
    "ReasonCode",
    "ReasonCodeDetail",
    "RuleEvaluationTrace",
    "ScreeningOutcome",
    "ScreeningResult",
    "create_policy_engine",
    "evaluate_screening_policy",
    "get_reason_code_detail",
    "load_policy_rules",
]
