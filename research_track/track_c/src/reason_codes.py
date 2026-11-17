"""
Track C: Stable Reason Codes & Audit Metadata Module.

Provides machine-readable standardized audit reason codes and descriptive metadata
explaining deterministic screening outcomes.

Invariants:
- Reason codes are immutable, stable uppercase identifiers.
- Descriptions and escalation severity remain separate from machine-readable codes.
- Never embeds PII or confidential payload text into reason code identifiers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class ReasonCode(str, Enum):
    """Stable, standardized audit reason codes emitted by the deterministic policy engine."""
    CATEGORY_RULE_ALERT = "CATEGORY_RULE_ALERT"
    CATEGORY_RULE_REVIEW = "CATEGORY_RULE_REVIEW"
    CATEGORY_RULE_ALLOW = "CATEGORY_RULE_ALLOW"

    # Standardized domain outcome reason codes
    ALLOW_PERMITTED_FOOD = "ALLOW_PERMITTED_FOOD"
    ALLOW_PERMITTED_GOODS = "ALLOW_PERMITTED_GOODS"
    REVIEW_UNCERTAIN_CLASSIFICATION = "REVIEW_UNCERTAIN_CLASSIFICATION"
    REVIEW_CONTROLLED_ITEM = "REVIEW_CONTROLLED_ITEM"
    REVIEW_HAZARDOUS_QUANTITY = "REVIEW_HAZARDOUS_QUANTITY"
    ALERT_PROHIBITED_CHEMICAL = "ALERT_PROHIBITED_CHEMICAL"
    ALERT_PROHIBITED_TOBACCO = "ALERT_PROHIBITED_TOBACCO"
    ALERT_PROHIBITED_ALCOHOL = "ALERT_PROHIBITED_ALCOHOL"
    ALERT_PROHIBITED_DRUG = "ALERT_PROHIBITED_DRUG"
    ALERT_PROHIBITED_WEAPON = "ALERT_PROHIBITED_WEAPON"

    UNKNOWN_CATEGORY = "UNKNOWN_CATEGORY"
    LOW_CLASSIFIER_CONFIDENCE = "LOW_CLASSIFIER_CONFIDENCE"
    MISSING_CLASSIFIER_CONFIDENCE = "MISSING_CLASSIFIER_CONFIDENCE"
    INVALID_CLASSIFICATION = "INVALID_CLASSIFICATION"
    MISSING_QUANTITY = "MISSING_QUANTITY"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    UNSUPPORTED_QUANTITY_UNIT = "UNSUPPORTED_QUANTITY_UNIT"
    NO_MATCHING_POLICY_RULE = "NO_MATCHING_POLICY_RULE"
    POLICY_RULE_CONFLICT = "POLICY_RULE_CONFLICT"
    POLICY_VERSION_INVALID = "POLICY_VERSION_INVALID"
    POLICY_RULE_INACTIVE = "POLICY_RULE_INACTIVE"
    POLICY_RULE_EXPIRED = "POLICY_RULE_EXPIRED"
    MISSING_REQUIRED_PLATFORM = "MISSING_REQUIRED_PLATFORM"
    MULTIPLE_RULES_MATCHED = "MULTIPLE_RULES_MATCHED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    HAZARDOUS_THRESHOLD_MET = "HAZARDOUS_THRESHOLD_MET"
    HAZARDOUS_THRESHOLD_NOT_MET = "HAZARDOUS_THRESHOLD_NOT_MET"


class CodeCategory(str, Enum):
    """Functional category of the reason code."""
    RULE_MATCH = "RULE_MATCH"
    PERCEPTION_UNCERTAINTY = "PERCEPTION_UNCERTAINTY"
    INPUT_ANOMALY = "INPUT_ANOMALY"
    POLICY_ANOMALY = "POLICY_ANOMALY"
    THRESHOLD_CONDITION = "THRESHOLD_CONDITION"


@dataclass(frozen=True)
class ReasonCodeDetail:
    """Human-readable metadata and operational guidance for a reason code."""
    code: ReasonCode
    category: CodeCategory
    summary: str
    description: str
    requires_human_escalation: bool


REASON_CODE_REGISTRY: Dict[ReasonCode, ReasonCodeDetail] = {
    ReasonCode.CATEGORY_RULE_ALERT: ReasonCodeDetail(
        code=ReasonCode.CATEGORY_RULE_ALERT,
        category=CodeCategory.RULE_MATCH,
        summary="High-risk category matched alert rule",
        description="A policy rule for an elevated category (e.g. alcohol, tobacco, rx drug) triggered an ALERT.",
        requires_human_escalation=True,
    ),
    ReasonCode.CATEGORY_RULE_REVIEW: ReasonCodeDetail(
        code=ReasonCode.CATEGORY_RULE_REVIEW,
        category=CodeCategory.RULE_MATCH,
        summary="Policy rule mandated manual guard review",
        description="A policy rule for a controlled category (e.g. sharp object, hazardous chemical) triggered a REVIEW.",
        requires_human_escalation=True,
    ),
    ReasonCode.CATEGORY_RULE_ALLOW: ReasonCodeDetail(
        code=ReasonCode.CATEGORY_RULE_ALLOW,
        category=CodeCategory.RULE_MATCH,
        summary="Policy rule permitted item entry",
        description="The item category satisfied all policy criteria for standard gate entry (ALLOW).",
        requires_human_escalation=False,
    ),
    ReasonCode.ALLOW_PERMITTED_FOOD: ReasonCodeDetail(
        code=ReasonCode.ALLOW_PERMITTED_FOOD,
        category=CodeCategory.RULE_MATCH,
        summary="Permitted food or beverage delivery allowed",
        description="Standard permitted groceries, meals, and non-sensitive food items cleared for gate entry.",
        requires_human_escalation=False,
    ),
    ReasonCode.ALLOW_PERMITTED_GOODS: ReasonCodeDetail(
        code=ReasonCode.ALLOW_PERMITTED_GOODS,
        category=CodeCategory.RULE_MATCH,
        summary="Permitted campus goods or stationery allowed",
        description="Ordinary household sundries, books, and authorized goods cleared for entry.",
        requires_human_escalation=False,
    ),
    ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION: ReasonCodeDetail(
        code=ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION,
        category=CodeCategory.PERCEPTION_UNCERTAINTY,
        summary="Uncertain classification requires guard review",
        description="Classification is uncertain or confidence below safety threshold; degraded ALLOW to REVIEW.",
        requires_human_escalation=True,
    ),
    ReasonCode.REVIEW_CONTROLLED_ITEM: ReasonCodeDetail(
        code=ReasonCode.REVIEW_CONTROLLED_ITEM,
        category=CodeCategory.RULE_MATCH,
        summary="Controlled item requires physical verification",
        description="Regulated or sharp item requires physical inspection by gate personnel.",
        requires_human_escalation=True,
    ),
    ReasonCode.REVIEW_HAZARDOUS_QUANTITY: ReasonCodeDetail(
        code=ReasonCode.REVIEW_HAZARDOUS_QUANTITY,
        category=CodeCategory.THRESHOLD_CONDITION,
        summary="Hazardous chemical quantity requires inspection",
        description="Hazardous chemical package count or volume exceeds domestic threshold.",
        requires_human_escalation=True,
    ),
    ReasonCode.ALERT_PROHIBITED_CHEMICAL: ReasonCodeDetail(
        code=ReasonCode.ALERT_PROHIBITED_CHEMICAL,
        category=CodeCategory.RULE_MATCH,
        summary="Prohibited hazardous chemical detected",
        description="Item identified as a prohibited toxic or explosive substance.",
        requires_human_escalation=True,
    ),
    ReasonCode.ALERT_PROHIBITED_TOBACCO: ReasonCodeDetail(
        code=ReasonCode.ALERT_PROHIBITED_TOBACCO,
        category=CodeCategory.RULE_MATCH,
        summary="Prohibited tobacco or nicotine product detected",
        description="Cigarettes, vapes, or tobacco products are strictly barred from campus.",
        requires_human_escalation=True,
    ),
    ReasonCode.ALERT_PROHIBITED_ALCOHOL: ReasonCodeDetail(
        code=ReasonCode.ALERT_PROHIBITED_ALCOHOL,
        category=CodeCategory.RULE_MATCH,
        summary="Prohibited alcohol product detected",
        description="Alcoholic beverages are strictly prohibited on campus premises.",
        requires_human_escalation=True,
    ),
    ReasonCode.ALERT_PROHIBITED_DRUG: ReasonCodeDetail(
        code=ReasonCode.ALERT_PROHIBITED_DRUG,
        category=CodeCategory.RULE_MATCH,
        summary="Prohibited prescription or scheduled drug detected",
        description="Controlled substances or prescription narcotics without permit detected.",
        requires_human_escalation=True,
    ),
    ReasonCode.ALERT_PROHIBITED_WEAPON: ReasonCodeDetail(
        code=ReasonCode.ALERT_PROHIBITED_WEAPON,
        category=CodeCategory.RULE_MATCH,
        summary="Prohibited weapon or tactical blade detected",
        description="Weapon, firearm, or unauthorized sharp implement triggered high-priority alert.",
        requires_human_escalation=True,
    ),
    ReasonCode.UNKNOWN_CATEGORY: ReasonCodeDetail(
        code=ReasonCode.UNKNOWN_CATEGORY,
        category=CodeCategory.PERCEPTION_UNCERTAINTY,
        summary="Unrecognized or unclassified product description",
        description="The product description could not be mapped to any recognized screening category.",
        requires_human_escalation=True,
    ),
    ReasonCode.LOW_CLASSIFIER_CONFIDENCE: ReasonCodeDetail(
        code=ReasonCode.LOW_CLASSIFIER_CONFIDENCE,
        category=CodeCategory.PERCEPTION_UNCERTAINTY,
        summary="Classifier confidence below review threshold",
        description="The proposed category confidence is below the configured safety threshold.",
        requires_human_escalation=True,
    ),
    ReasonCode.MISSING_CLASSIFIER_CONFIDENCE: ReasonCodeDetail(
        code=ReasonCode.MISSING_CLASSIFIER_CONFIDENCE,
        category=CodeCategory.PERCEPTION_UNCERTAINTY,
        summary="Classifier emitted null confidence",
        description="The classifier model did not provide a confidence score for its prediction.",
        requires_human_escalation=True,
    ),
    ReasonCode.INVALID_CLASSIFICATION: ReasonCodeDetail(
        code=ReasonCode.INVALID_CLASSIFICATION,
        category=CodeCategory.PERCEPTION_UNCERTAINTY,
        summary="Classifier output payload malformed or invalid",
        description="The classifier returned an invalid category string, empty payload, or schema error.",
        requires_human_escalation=True,
    ),
    ReasonCode.MISSING_QUANTITY: ReasonCodeDetail(
        code=ReasonCode.MISSING_QUANTITY,
        category=CodeCategory.INPUT_ANOMALY,
        summary="Quantity is missing for a quantity-dependent rule",
        description="A quantity-dependent policy threshold could not be evaluated because quantity is null.",
        requires_human_escalation=True,
    ),
    ReasonCode.INVALID_QUANTITY: ReasonCodeDetail(
        code=ReasonCode.INVALID_QUANTITY,
        category=CodeCategory.INPUT_ANOMALY,
        summary="Quantity value is negative or non-numeric",
        description="The provided item quantity was invalid or less than zero.",
        requires_human_escalation=True,
    ),
    ReasonCode.UNSUPPORTED_QUANTITY_UNIT: ReasonCodeDetail(
        code=ReasonCode.UNSUPPORTED_QUANTITY_UNIT,
        category=CodeCategory.INPUT_ANOMALY,
        summary="Quantity unit is incompatible with rule threshold",
        description="The unit of measure cannot be safely converted or compared against the rule threshold unit.",
        requires_human_escalation=True,
    ),
    ReasonCode.NO_MATCHING_POLICY_RULE: ReasonCodeDetail(
        code=ReasonCode.NO_MATCHING_POLICY_RULE,
        category=CodeCategory.POLICY_ANOMALY,
        summary="No active policy rule matched the item category",
        description="No rule in the active policy version matched this category; applied safe category fallback.",
        requires_human_escalation=True,
    ),
    ReasonCode.POLICY_RULE_CONFLICT: ReasonCodeDetail(
        code=ReasonCode.POLICY_RULE_CONFLICT,
        category=CodeCategory.POLICY_ANOMALY,
        summary="Contradictory rules matched at equal priority",
        description="Two or more policy rules at identical priority specified conflicting actions; defaulted to REVIEW.",
        requires_human_escalation=True,
    ),
    ReasonCode.POLICY_VERSION_INVALID: ReasonCodeDetail(
        code=ReasonCode.POLICY_VERSION_INVALID,
        category=CodeCategory.POLICY_ANOMALY,
        summary="Requested policy version is unrecognized or invalid",
        description="The supplied policy version string did not match any loaded ruleset.",
        requires_human_escalation=True,
    ),
    ReasonCode.POLICY_RULE_INACTIVE: ReasonCodeDetail(
        code=ReasonCode.POLICY_RULE_INACTIVE,
        category=CodeCategory.POLICY_ANOMALY,
        summary="Matching policy rule is soft-deactivated",
        description="A rule matching the category was ignored because active=false.",
        requires_human_escalation=False,
    ),
    ReasonCode.POLICY_RULE_EXPIRED: ReasonCodeDetail(
        code=ReasonCode.POLICY_RULE_EXPIRED,
        category=CodeCategory.POLICY_ANOMALY,
        summary="Matching policy rule is expired or not yet effective",
        description="A rule matching the category was ignored because evaluation time falls outside its effective window.",
        requires_human_escalation=False,
    ),
    ReasonCode.MISSING_REQUIRED_PLATFORM: ReasonCodeDetail(
        code=ReasonCode.MISSING_REQUIRED_PLATFORM,
        category=CodeCategory.INPUT_ANOMALY,
        summary="Platform-specific rule could not match without platform",
        description="A rule required a specific delivery platform, but input platform was null.",
        requires_human_escalation=False,
    ),
    ReasonCode.MULTIPLE_RULES_MATCHED: ReasonCodeDetail(
        code=ReasonCode.MULTIPLE_RULES_MATCHED,
        category=CodeCategory.RULE_MATCH,
        summary="Multiple rules matched; resolved by priority",
        description="More than one rule matched the criteria; the rule with lowest priority integer was selected.",
        requires_human_escalation=False,
    ),
    ReasonCode.MANUAL_REVIEW_REQUIRED: ReasonCodeDetail(
        code=ReasonCode.MANUAL_REVIEW_REQUIRED,
        category=CodeCategory.RULE_MATCH,
        summary="Human auditor sign-off required",
        description="The item requires physical guard verification before entry clearance.",
        requires_human_escalation=True,
    ),
    ReasonCode.HAZARDOUS_THRESHOLD_MET: ReasonCodeDetail(
        code=ReasonCode.HAZARDOUS_THRESHOLD_MET,
        category=CodeCategory.THRESHOLD_CONDITION,
        summary="Hazardous chemical quantity met or exceeded threshold",
        description="Hazardous chemical quantity is >= 3 units, triggering mandatory review.",
        requires_human_escalation=True,
    ),
    ReasonCode.HAZARDOUS_THRESHOLD_NOT_MET: ReasonCodeDetail(
        code=ReasonCode.HAZARDOUS_THRESHOLD_NOT_MET,
        category=CodeCategory.THRESHOLD_CONDITION,
        summary="Hazardous chemical quantity below review threshold",
        description="Small household quantity of hazardous chemical (< 3 units) permitted with audit log.",
        requires_human_escalation=False,
    ),
}


def get_reason_code_detail(code: ReasonCode) -> ReasonCodeDetail:
    """Returns descriptive details for a reason code."""
    return REASON_CODE_REGISTRY.get(code, ReasonCodeDetail(
        code=code,
        category=CodeCategory.RULE_MATCH,
        summary=str(code),
        description=str(code),
        requires_human_escalation=True,
    ))
