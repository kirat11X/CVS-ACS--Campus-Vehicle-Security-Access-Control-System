"""
Track C: Deterministic Policy Engine & Campus Safety Rules Verification Tests.

Validates:
1. 21 Deterministic Campus Safety Policy Rules enforcement.
2. CRITICAL UNCERTAINTY ESCALATION:
   - If is_uncertain=True or confidence < 0.70, any tentative ALLOW MUST degrade to REVIEW.
   - Any ALERT decision NEVER degrades—hazardous/prohibited items remain ALERT.
3. Priority tie conflict safety (falls back to REVIEW, never ALLOW).
4. Hazardous chemical bulk vs domestic thresholds and input anomaly handling.
5. Rule-order invariance and bit-exact reproducibility.
6. 100% agreement on all 115 synthetic test cases with 0.0% False-Allow Rate.
"""

from datetime import datetime
import json
from pathlib import Path
import random
import pytest

from research_track.track_c.src.policy import (
    CONFIDENCE_REVIEW_THRESHOLD,
    DEFAULT_POLICY_VERSION,
    CategoryNormalizer,
    DeterministicPolicyEngine,
    ItemCategoryCode,
    PolicyRule,
    ReasonCode,
    ScreeningOutcome,
    ScreeningResult,
    create_policy_engine,
    evaluate_screening_policy,
    load_policy_rules,
)
from research_track.track_c.src.types import ClassificationOutput
from research_track.track_c.src.evaluation import MetricCalculator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RULES_FIXTURE_PATH = REPO_ROOT / "research_track/track_c/fixtures/policy_rules.json"
CASES_FIXTURE_PATH = REPO_ROOT / "research_track/track_c/fixtures/synthetic_screening_cases.json"
GT_FIXTURE_PATH = REPO_ROOT / "research_track/track_c/fixtures/synthetic_ground_truth.json"

_TIMESTAMP = "2026-01-01T00:00:00Z"


@pytest.fixture
def policy_rules():
    """Loads canonical 21-rule Track C policy fixture."""
    return load_policy_rules(RULES_FIXTURE_PATH)


@pytest.fixture
def policy_engine(policy_rules):
    """Instantiates a DeterministicPolicyEngine loaded with the 21 rules."""
    return DeterministicPolicyEngine(rules=policy_rules)


def _make_classification(
    category: ItemCategoryCode,
    confidence: float | None = 0.99,
    uncertain: bool = False,
    line_id: str = "line-item-test",
) -> ClassificationOutput:
    return ClassificationOutput(
        line_item_id=line_id,
        predicted_category=category,
        confidence=confidence,
        classifier_name="test_classifier",
        classifier_version="1.0.0",
        is_uncertain=uncertain,
    )


# --------------------------------------------------------------------------
# 1. 21 Deterministic Campus Safety Policy Rules Enforcement
# --------------------------------------------------------------------------

def test_loads_exactly_21_policy_rules(policy_rules):
    """Fixture must contain exactly 21 deterministic campus safety policy rules."""
    assert len(policy_rules) == 21


def test_prohibited_tobacco_alert(policy_engine):
    """Tobacco & nicotine products mandate immediate ALERT."""
    cl = _make_classification(ItemCategoryCode.TOBACCO_NICOTINE, confidence=0.98)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes
    assert ReasonCode.ALERT_PROHIBITED_TOBACCO.value in res.reason_codes


def test_prohibited_alcohol_alert(policy_engine):
    """Alcoholic beverages mandate immediate ALERT."""
    cl = _make_classification(ItemCategoryCode.ALCOHOL, confidence=0.95)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes
    assert ReasonCode.ALERT_PROHIBITED_ALCOHOL.value in res.reason_codes


def test_prohibited_rx_drugs_alert(policy_engine):
    """Prescription scheduled drugs/narcotics mandate immediate ALERT."""
    cl = _make_classification(ItemCategoryCode.RX_SCHEDULED_DRUG, confidence=0.96)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes
    assert ReasonCode.ALERT_PROHIBITED_DRUG.value in res.reason_codes


def test_permitted_otc_medicine_allow(policy_engine):
    """Over-the-counter medicine evaluates to ALLOW."""
    cl = _make_classification(ItemCategoryCode.OTC_MEDICINE, confidence=0.95)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
    assert ReasonCode.CATEGORY_RULE_ALLOW.value in res.reason_codes


def test_permitted_normal_grocery_allow(policy_engine):
    """Normal grocery / food items evaluate to ALLOW."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.95)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
    assert ReasonCode.CATEGORY_RULE_ALLOW.value in res.reason_codes
    assert ReasonCode.ALLOW_PERMITTED_FOOD.value in res.reason_codes


def test_controlled_sharp_objects_review(policy_engine):
    """Sharp objects (cutlery, box cutters) require guard REVIEW."""
    cl = _make_classification(ItemCategoryCode.SHARP_OBJECT, confidence=0.95)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.CATEGORY_RULE_REVIEW.value in res.reason_codes
    assert ReasonCode.REVIEW_CONTROLLED_ITEM.value in res.reason_codes


def test_platform_override_instamart_sharp_escalates_to_alert(policy_engine):
    """Sharp objects via Instamart platform override escalate from REVIEW to ALERT."""
    cl = _make_classification(ItemCategoryCode.SHARP_OBJECT, confidence=0.95)
    res = policy_engine.evaluate(cl, platform="INSTAMART", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes


def test_platform_override_blinkit_normal_expedited(policy_engine):
    """Regular groceries on Blinkit match expedited priority 50 rule."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.99)
    res = policy_engine.evaluate(cl, platform="BLINKIT", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
    assert res.matched_rule_ids == ["RULE-OVERRIDE-BLINKIT-NORMAL"]


# --------------------------------------------------------------------------
# 2. Hazardous Chemical Quantity Thresholds & Anomaly Safeguards
# --------------------------------------------------------------------------

@pytest.mark.parametrize("unit", ["PACK", "PCS", "BOTTLE"])
def test_hazardous_chemical_bulk_threshold_review(policy_engine, unit):
    """Hazardous chemicals in bulk (>= 3 units) mandate guard REVIEW."""
    cl = _make_classification(ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95)
    res = policy_engine.evaluate(cl, quantity=3.0, unit=unit, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.HAZARDOUS_THRESHOLD_MET.value in res.reason_codes


@pytest.mark.parametrize("unit", ["PACK", "PCS", "BOTTLE"])
def test_hazardous_chemical_household_threshold_allow(policy_engine, unit):
    """Hazardous chemicals under 3 units allowed with audit trail."""
    cl = _make_classification(ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95)
    res = policy_engine.evaluate(cl, quantity=1.0, unit=unit, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
    assert ReasonCode.HAZARDOUS_THRESHOLD_NOT_MET.value in res.reason_codes


def test_hazardous_chemical_negative_quantity_review(policy_engine):
    """Negative quantity on hazardous chemicals must safely route to REVIEW."""
    cl = _make_classification(ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95)
    res = policy_engine.evaluate(cl, quantity=-2.0, unit="BOTTLE", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.INVALID_QUANTITY.value in res.reason_codes


def test_hazardous_chemical_missing_quantity_review(policy_engine):
    """Missing quantity on hazardous chemicals must safely route to REVIEW."""
    cl = _make_classification(ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95)
    res = policy_engine.evaluate(cl, quantity=None, unit=None, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.MISSING_QUANTITY.value in res.reason_codes


def test_hazardous_chemical_unsupported_unit_review(policy_engine):
    """Unsupported unit on hazardous chemicals must safely route to REVIEW."""
    cl = _make_classification(ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95)
    res = policy_engine.evaluate(cl, quantity=1.0, unit="INVALID_XYZ", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.UNSUPPORTED_QUANTITY_UNIT.value in res.reason_codes


# --------------------------------------------------------------------------
# 3. CRITICAL UNCERTAINTY ESCALATION (ALLOW -> REVIEW)
# --------------------------------------------------------------------------

def test_uncertainty_escalation_low_confidence_downgrades_allow_to_review(policy_engine):
    """Low confidence (< 0.70) must degrade tentative ALLOW to REVIEW."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.65, uncertain=False)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value in res.reason_codes
    assert ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION.value in res.reason_codes
    assert res.requires_human_review is True


def test_uncertainty_escalation_missing_confidence_downgrades_allow_to_review(policy_engine):
    """Missing confidence (None) must degrade tentative ALLOW to REVIEW."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=None, uncertain=False)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.MISSING_CLASSIFIER_CONFIDENCE.value in res.reason_codes
    assert ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION.value in res.reason_codes
    assert res.requires_human_review is True


def test_uncertainty_escalation_is_uncertain_downgrades_allow_to_review(policy_engine):
    """is_uncertain=True must degrade tentative ALLOW to REVIEW for human guard inspection."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.95, uncertain=True)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.MANUAL_REVIEW_REQUIRED.value in res.reason_codes
    assert ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION.value in res.reason_codes
    assert res.requires_human_review is True


def test_uncertainty_escalation_both_low_conf_and_uncertain(policy_engine):
    """Both confidence < 0.70 and is_uncertain=True must degrade ALLOW to REVIEW with all reason codes."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.45, uncertain=True)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value in res.reason_codes
    assert ReasonCode.MANUAL_REVIEW_REQUIRED.value in res.reason_codes
    assert ReasonCode.REVIEW_UNCERTAIN_CLASSIFICATION.value in res.reason_codes


# --------------------------------------------------------------------------
# 4. CRITICAL INVARIANT: ALERT DECISIONS NEVER DEGRADE
# --------------------------------------------------------------------------

@pytest.mark.parametrize("category", [
    ItemCategoryCode.TOBACCO_NICOTINE,
    ItemCategoryCode.ALCOHOL,
    ItemCategoryCode.RX_SCHEDULED_DRUG,
])
def test_alert_never_degrades_on_low_confidence(policy_engine, category):
    """Any ALERT decision NEVER degrades even with low confidence (< 0.70)."""
    cl = _make_classification(category, confidence=0.15, uncertain=False)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes


@pytest.mark.parametrize("category", [
    ItemCategoryCode.TOBACCO_NICOTINE,
    ItemCategoryCode.ALCOHOL,
    ItemCategoryCode.RX_SCHEDULED_DRUG,
])
def test_alert_never_degrades_on_missing_confidence(policy_engine, category):
    """Any ALERT decision NEVER degrades even when confidence is None."""
    cl = _make_classification(category, confidence=None, uncertain=False)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes


@pytest.mark.parametrize("category", [
    ItemCategoryCode.TOBACCO_NICOTINE,
    ItemCategoryCode.ALCOHOL,
    ItemCategoryCode.RX_SCHEDULED_DRUG,
])
def test_alert_never_degrades_on_is_uncertain(policy_engine, category):
    """Any ALERT decision NEVER degrades even when is_uncertain=True."""
    cl = _make_classification(category, confidence=0.20, uncertain=True)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT
    assert ReasonCode.CATEGORY_RULE_ALERT.value in res.reason_codes


def test_platform_override_alert_never_degrades(policy_engine):
    """Instamart sharp objects ALERT override never degrades even under uncertainty."""
    cl = _make_classification(ItemCategoryCode.SHARP_OBJECT, confidence=0.25, uncertain=True)
    res = policy_engine.evaluate(cl, platform="INSTAMART", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALERT


# --------------------------------------------------------------------------
# 5. Deterministic Conflict Resolution & Rule Temporal Filters
# --------------------------------------------------------------------------

def test_priority_tie_conflict_safely_falls_back_to_review(policy_engine):
    """Contradictory rules matching at equal highest priority must NEVER allow; routes to REVIEW."""
    cl = _make_classification(ItemCategoryCode.OTC_MEDICINE, confidence=0.99)
    res = policy_engine.evaluate(cl, platform="TEST_CONFLICT", evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.POLICY_RULE_CONFLICT.value in res.reason_codes
    assert ReasonCode.MANUAL_REVIEW_REQUIRED.value in res.reason_codes


def test_inactive_and_expired_rules_are_filtered_out(policy_engine):
    """Inactive (RULE-TEST-INACTIVE) and expired (RULE-TEST-EXPIRED) rules must not trigger."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.99)
    res = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
    assert "RULE-TEST-INACTIVE" not in res.matched_rule_ids
    assert "RULE-TEST-EXPIRED" not in res.matched_rule_ids


def test_rule_order_invariance(policy_rules):
    """Shuffling the loaded rule array yields 100% bit-exact identical evaluation outcomes."""
    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.95)
    first = DeterministicPolicyEngine(rules=policy_rules).evaluate(cl, evaluation_timestamp=_TIMESTAMP)

    shuffled_rules = list(policy_rules)
    random.seed(42)
    random.shuffle(shuffled_rules)

    second = DeterministicPolicyEngine(rules=shuffled_rules).evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    assert first.to_dict() == second.to_dict()


def test_repeated_evaluation_determinism(policy_engine):
    """Re-evaluating identical inputs yields 100% bit-exact results."""
    cl = _make_classification(ItemCategoryCode.TOBACCO_NICOTINE, confidence=0.98)
    first = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
    for _ in range(25):
        nxt = policy_engine.evaluate(cl, evaluation_timestamp=_TIMESTAMP)
        assert first.to_dict() == nxt.to_dict()


# --------------------------------------------------------------------------
# 6. Evaluation Matrix: All 115 Synthetic Screening Test Cases
# --------------------------------------------------------------------------

def test_full_synthetic_suite_115_cases_match_ground_truth(policy_engine):
    """All 115 synthetic test cases must match ground truth with 0.0% False-Allow Rate."""
    with open(CASES_FIXTURE_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    with open(GT_FIXTURE_PATH, "r", encoding="utf-8") as f:
        gt = json.load(f)

    assert len(cases) == 115
    assert len(gt) == 115

    results: list[ScreeningResult] = []
    for c in cases:
        sim = c["simulated_classification"]
        cl = ClassificationOutput(
            line_item_id=c["line_item_id"],
            predicted_category=ItemCategoryCode(sim["predicted_category"]),
            confidence=sim["confidence"],
            classifier_name=sim["classifier_name"],
            classifier_version=sim["classifier_version"],
            is_uncertain=sim["is_uncertain"],
        )
        res = policy_engine.evaluate(
            classification=cl,
            quantity=c.get("quantity"),
            unit=c.get("unit"),
            platform=c.get("platform"),
            evaluation_timestamp=_TIMESTAMP,
        )
        results.append(res)

    summary = MetricCalculator.evaluate_policy(results, gt)

    assert summary.outcome_accuracy == 1.0, f"Outcome accuracy is {summary.outcome_accuracy}, expected 1.0"
    assert summary.false_allow_rate == 0.0, f"False-Allow Rate is {summary.false_allow_rate}, expected 0.0"
    assert summary.reason_code_correctness == 1.0, f"Reason code correctness is {summary.reason_code_correctness}"


# --------------------------------------------------------------------------
# 7. Facade Module Helpers Verification
# --------------------------------------------------------------------------

def test_policy_facade_helpers():
    """policy.py module convenience functions operate correctly."""
    engine = create_policy_engine()
    assert isinstance(engine, DeterministicPolicyEngine)

    cl = _make_classification(ItemCategoryCode.NORMAL, confidence=0.99)
    res = evaluate_screening_policy(cl, engine=engine, evaluation_timestamp=_TIMESTAMP)
    assert res.outcome == ScreeningOutcome.ALLOW
