"""
Track C: Core Domain Types, Enums, and Dataclasses.

Defines the fundamental data representations for item classification, category taxonomy,
policy rules, deterministic outcomes, and audit traces.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ScreeningOutcome(str, Enum):
    """Deterministic campus security outcome produced exclusively by the policy engine."""
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    ALERT = "ALERT"


class ItemCategoryCode(str, Enum):
    """Standardized campus screening item categories."""
    TOBACCO_NICOTINE = "TOBACCO_NICOTINE"
    ALCOHOL = "ALCOHOL"
    RX_SCHEDULED_DRUG = "RX_SCHEDULED_DRUG"
    OTC_MEDICINE = "OTC_MEDICINE"
    HAZARDOUS_CHEMICAL = "HAZARDOUS_CHEMICAL"
    SHARP_OBJECT = "SHARP_OBJECT"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"


class CategorySeverity(str, Enum):
    """Categorical severity for administrative escalation."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass(frozen=True)
class CategoryDefinition:
    """Metadata describing a recognized item category in the screening taxonomy."""
    code: ItemCategoryCode
    display_name: str
    description: str
    default_action: ScreeningOutcome
    severity: CategorySeverity = CategorySeverity.NONE
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "display_name": self.display_name,
            "description": self.description,
            "default_action": self.default_action.value,
            "severity": self.severity.value,
            "active": self.active,
        }


@dataclass(frozen=True)
class ClassificationInput:
    """Input provided to an item classifier."""
    line_item_id: str
    raw_item_description: str
    normalized_description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    platform: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_item_id": self.line_item_id,
            "raw_item_description": self.raw_item_description,
            "normalized_description": self.normalized_description,
            "quantity": self.quantity,
            "unit": self.unit,
            "platform": self.platform,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AlternativeCategory:
    """Candidate category with model confidence."""
    category: ItemCategoryCode
    confidence: float


@dataclass(frozen=True)
class ClassificationOutput:
    """Observational output proposed by a classifier. Does not determine the screening outcome."""
    line_item_id: str
    predicted_category: ItemCategoryCode
    confidence: Optional[float]
    classifier_name: str
    classifier_version: str
    is_uncertain: bool
    alternative_categories: List[AlternativeCategory] = field(default_factory=list)
    prediction_timestamp: Optional[str] = None
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_item_id": self.line_item_id,
            "predicted_category": self.predicted_category.value,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "classifier_name": self.classifier_name,
            "classifier_version": self.classifier_version,
            "is_uncertain": self.is_uncertain,
            "alternative_categories": [
                {"category": alt.category.value, "confidence": round(alt.confidence, 4)}
                for alt in self.alternative_categories
            ],
            "prediction_timestamp": self.prediction_timestamp,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class PolicyRule:
    """A deterministic campus security policy rule."""
    rule_id: str
    category_code: ItemCategoryCode
    action: ScreeningOutcome
    priority: int  # Lower integer = higher precedence
    policy_version: str
    min_quantity: Optional[float] = None
    max_quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    platform: Optional[str] = None
    effective_from: Optional[str] = None  # ISO 8601
    effective_to: Optional[str] = None    # ISO 8601
    active: bool = True
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category_code": self.category_code.value,
            "action": self.action.value,
            "priority": self.priority,
            "policy_version": self.policy_version,
            "min_quantity": self.min_quantity,
            "max_quantity": self.max_quantity,
            "quantity_unit": self.quantity_unit,
            "platform": self.platform,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "active": self.active,
            "description": self.description,
        }


@dataclass(frozen=True)
class RuleEvaluationTrace:
    """Detailed audit trace of the deterministic evaluation process."""
    rules_considered: int
    matching_candidates: List[str]
    rejected_rules: Dict[str, str]
    conflicts_detected: List[str]
    applied_rule_id: Optional[str]
    resolution_method: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rules_considered": self.rules_considered,
            "matching_candidates": self.matching_candidates,
            "rejected_rules": self.rejected_rules,
            "conflicts_detected": self.conflicts_detected,
            "applied_rule_id": self.applied_rule_id,
            "resolution_method": self.resolution_method,
        }


@dataclass(frozen=True)
class ScreeningResult:
    """Final explainable outcome emitted by the deterministic policy engine."""
    screening_event_id: str
    line_item_id: str
    outcome: ScreeningOutcome
    reason_codes: List[str]
    matched_rule_ids: List[str]
    policy_version: str
    evaluation_timestamp: str
    explanation: str
    requires_human_review: bool
    classification_summary: Dict[str, Any]
    audit_trace: RuleEvaluationTrace

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screening_event_id": self.screening_event_id,
            "line_item_id": self.line_item_id,
            "outcome": self.outcome.value,
            "reason_codes": self.reason_codes,
            "matched_rule_ids": self.matched_rule_ids,
            "policy_version": self.policy_version,
            "evaluation_timestamp": self.evaluation_timestamp,
            "explanation": self.explanation,
            "requires_human_review": self.requires_human_review,
            "classification_summary": self.classification_summary,
            "audit_trace": self.audit_trace.to_dict(),
        }
