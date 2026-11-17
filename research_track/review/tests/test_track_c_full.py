"""
Comprehensive Review Tests for Track C:
- Category Normalization & Synonyms
- Lexical Mapping Classifier
- Deterministic Policy Engine (Temporal windows, platform, quantity intervals, priority ties, confidence degradation)
- Audit Records & Append-Only Ledger
- Evaluation Metrics (Classifier and Policy metrics)
"""

import json
import pytest

from research_track.track_c.src.types import (
    ClassificationInput,
    ClassificationOutput,
    ItemCategoryCode,
    PolicyRule,
    ScreeningOutcome,
    ScreeningResult,
    RuleEvaluationTrace,
)
from research_track.track_c.src.category_normalization import (
    CategoryNormalizer,
    STANDARD_CATEGORY_DEFINITIONS,
)
from research_track.track_c.src.classifier_interface import (
    LexicalMappingClassifier,
)
from research_track.track_c.src.policy_engine import (
    DeterministicPolicyEngine,
)
from research_track.track_c.src.reason_codes import ReasonCode
from research_track.track_c.src.audit_records import (
    HumanReviewAction,
    HumanReviewEvent,
    ScreeningAuditEvent,
    AuditLogLedger,
)
from research_track.track_c.src.evaluation import (
    MetricCalculator,
    ClassifierEvaluationSummary,
    PolicyEvaluationSummary,
)

_TIMESTAMP = "2026-06-01T12:00:00+00:00"


# ==============================================================================
# 1. Category Normalizer & Taxonomy Tests
# ==============================================================================

def test_category_normalizer():
    # Direct enum match
    assert CategoryNormalizer.normalize("TOBACCO_NICOTINE") == ItemCategoryCode.TOBACCO_NICOTINE
    assert CategoryNormalizer.normalize("alcohol") == ItemCategoryCode.ALCOHOL

    # Synonyms
    assert CategoryNormalizer.normalize("BEER") == ItemCategoryCode.ALCOHOL
    assert CategoryNormalizer.normalize("CIGARETTES") == ItemCategoryCode.TOBACCO_NICOTINE
    assert CategoryNormalizer.normalize("VAPE") == ItemCategoryCode.TOBACCO_NICOTINE
    assert CategoryNormalizer.normalize("PRESCRIPTION_DRUG") == ItemCategoryCode.RX_SCHEDULED_DRUG
    assert CategoryNormalizer.normalize("KNIFE") == ItemCategoryCode.SHARP_OBJECT
    assert CategoryNormalizer.normalize("FOOD") == ItemCategoryCode.NORMAL

    # Blank / Unknown
    assert CategoryNormalizer.normalize(None) == ItemCategoryCode.UNKNOWN
    assert CategoryNormalizer.normalize("   ") == ItemCategoryCode.UNKNOWN
    assert CategoryNormalizer.normalize("completely_random_unknown_token") == ItemCategoryCode.UNKNOWN

    # Definitions
    defn = CategoryNormalizer.get_definition(ItemCategoryCode.ALCOHOL)
    assert defn.code == ItemCategoryCode.ALCOHOL
    assert defn.default_action == ScreeningOutcome.ALERT

    all_defns = CategoryNormalizer.list_all_definitions()
    assert len(all_defns) == len(STANDARD_CATEGORY_DEFINITIONS)


# ==============================================================================
# 2. Lexical Classifier Tests
# ==============================================================================

def test_lexical_mapping_classifier():
    kw_map = {
        "beer bottle": ItemCategoryCode.ALCOHOL,
        "paracetamol 500mg": ItemCategoryCode.OTC_MEDICINE,
    }
    classifier = LexicalMappingClassifier(keyword_map=kw_map, default_confidence=0.95)

    # Blank item
    res_blank = classifier.classify(ClassificationInput(line_item_id="L0", raw_item_description="   "))
    assert res_blank.predicted_category == ItemCategoryCode.UNKNOWN
    assert res_blank.is_uncertain is True
    assert res_blank.confidence is None

    # Exact match
    res_exact = classifier.classify(ClassificationInput(line_item_id="L1", raw_item_description="Beer Bottle"))
    assert res_exact.predicted_category == ItemCategoryCode.ALCOHOL
    assert res_exact.confidence == 0.95
    assert res_exact.is_uncertain is False

    # Factory from CSV
    csv_classifier = LexicalMappingClassifier.from_csv(
        "research_track/track_c/fixtures/item_taxonomy_seed.csv",
        default_confidence=0.90,
    )
    assert len(csv_classifier.keyword_map) > 0


# ==============================================================================
# 3. Deterministic Policy Engine Tests
# ==============================================================================

def _make_rule(
    rule_id: str,
    cat: ItemCategoryCode,
    action: ScreeningOutcome,
    priority: int = 1,
    platform: str = None,
    min_qty: float = None,
    max_qty: float = None,
    unit: str = None,
    effective_from: str = None,
    effective_to: str = None,
    active: bool = True,
    policy_version: str = "v1.0",
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        category_code=cat,
        action=action,
        priority=priority,
        policy_version=policy_version,
        min_quantity=min_qty,
        max_quantity=max_qty,
        quantity_unit=unit,
        platform=platform,
        effective_from=effective_from,
        effective_to=effective_to,
        active=active,
        description=f"Rule {rule_id}",
    )


def test_policy_engine_temporal_and_platform_filters():
    rules = [
        # Active rule
        _make_rule("R1", ItemCategoryCode.ALCOHOL, ScreeningOutcome.ALERT, priority=1),
        # Inactive rule
        _make_rule("R_INACTIVE", ItemCategoryCode.ALCOHOL, ScreeningOutcome.ALLOW, priority=0, active=False),
        # Expired rule
        _make_rule("R_EXPIRED", ItemCategoryCode.ALCOHOL, ScreeningOutcome.ALLOW, priority=0, effective_to="2025-01-01T00:00:00+00:00"),
        # Future rule
        _make_rule("R_FUTURE", ItemCategoryCode.ALCOHOL, ScreeningOutcome.ALLOW, priority=0, effective_from="2027-01-01T00:00:00+00:00"),
        # Platform-specific rule
        _make_rule("R_AMZN", ItemCategoryCode.NORMAL, ScreeningOutcome.ALLOW, priority=1, platform="AMAZON"),
    ]
    engine = DeterministicPolicyEngine(rules=rules)

    # Missing evaluation_timestamp raises ValueError
    with pytest.raises(ValueError):
        engine.evaluate(ClassificationOutput(line_item_id="L1", predicted_category=ItemCategoryCode.ALCOHOL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False))

    # Inactive/expired rules ignored, active R1 ALERT applies
    res_alcohol = engine.evaluate(
        ClassificationOutput(line_item_id="L1", predicted_category=ItemCategoryCode.ALCOHOL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_alcohol.outcome == ScreeningOutcome.ALERT
    assert "R1" in res_alcohol.matched_rule_ids

    # Platform match check
    res_amzn = engine.evaluate(
        ClassificationOutput(line_item_id="L2", predicted_category=ItemCategoryCode.NORMAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        platform="AMAZON",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_amzn.outcome == ScreeningOutcome.ALLOW

    # Platform mismatch check
    res_amzn_mismatch = engine.evaluate(
        ClassificationOutput(line_item_id="L2", predicted_category=ItemCategoryCode.NORMAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        platform="SWIGGY",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_amzn_mismatch.outcome in (ScreeningOutcome.ALLOW, ScreeningOutcome.REVIEW)


def test_policy_engine_quantity_and_priority_conflicts():
    rules = [
        # Quantity threshold rule
        _make_rule("R_QTY", ItemCategoryCode.HAZARDOUS_CHEMICAL, ScreeningOutcome.ALERT, priority=1, min_qty=5.0, unit="LTR"),
        # Conflicting rules at same priority
        _make_rule("R_TIE_1", ItemCategoryCode.TOBACCO_NICOTINE, ScreeningOutcome.ALERT, priority=1),
        _make_rule("R_TIE_2", ItemCategoryCode.TOBACCO_NICOTINE, ScreeningOutcome.ALLOW, priority=1),
    ]
    engine = DeterministicPolicyEngine(rules=rules)

    # Hazardous chemical: qty 10 >= min 5 -> ALERT
    res_haz_alert = engine.evaluate(
        ClassificationOutput(line_item_id="L1", predicted_category=ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        quantity=10.0,
        unit="LTR",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_haz_alert.outcome == ScreeningOutcome.ALERT

    # Hazardous chemical below default threshold (< 3.0) with no matching rule -> ALLOW
    res_haz_allow = engine.evaluate(
        ClassificationOutput(line_item_id="L2", predicted_category=ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        quantity=1.0,
        unit="LTR",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_haz_allow.outcome == ScreeningOutcome.ALLOW

    # Priority tie conflict -> REVIEW
    res_tie = engine.evaluate(
        ClassificationOutput(line_item_id="L3", predicted_category=ItemCategoryCode.TOBACCO_NICOTINE, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_tie.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.POLICY_RULE_CONFLICT.value in res_tie.reason_codes

    # Invalid policy version
    res_bad_ver = engine.evaluate(
        ClassificationOutput(line_item_id="L4", predicted_category=ItemCategoryCode.NORMAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        policy_version="v999.0",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_bad_ver.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.POLICY_VERSION_INVALID.value in res_bad_ver.reason_codes

    # UNKNOWN category upfront
    res_unk = engine.evaluate(
        ClassificationOutput(line_item_id="L5", predicted_category=ItemCategoryCode.UNKNOWN, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_unk.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.UNKNOWN_CATEGORY.value in res_unk.reason_codes

    # Missing quantity when rule requires quantity
    res_no_qty = engine.evaluate(
        ClassificationOutput(line_item_id="L6", predicted_category=ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        quantity=None,
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_no_qty.outcome == ScreeningOutcome.REVIEW

    # Negative quantity
    res_neg_qty = engine.evaluate(
        ClassificationOutput(line_item_id="L7", predicted_category=ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        quantity=-2.0,
        unit="LTR",
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_neg_qty.outcome in (ScreeningOutcome.REVIEW, ScreeningOutcome.ALERT)

    # Unit mismatch
    res_unit_mismatch = engine.evaluate(
        ClassificationOutput(line_item_id="L8", predicted_category=ItemCategoryCode.HAZARDOUS_CHEMICAL, confidence=0.95, classifier_name="c", classifier_version="1", is_uncertain=False),
        quantity=10.0,
        unit="KG",  # Rule requires LTR
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_unit_mismatch.outcome in (ScreeningOutcome.REVIEW, ScreeningOutcome.ALERT)


def test_policy_engine_confidence_safety_invariants():
    rules = [
        _make_rule("R_ALLOW", ItemCategoryCode.NORMAL, ScreeningOutcome.ALLOW, priority=1),
        _make_rule("R_ALERT", ItemCategoryCode.ALCOHOL, ScreeningOutcome.ALERT, priority=1),
    ]
    engine = DeterministicPolicyEngine(rules=rules, confidence_review_threshold=0.70)

    # 1. Missing confidence downgrades ALLOW to REVIEW
    res_no_conf = engine.evaluate(
        ClassificationOutput(line_item_id="L1", predicted_category=ItemCategoryCode.NORMAL, confidence=None, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_no_conf.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.MISSING_CLASSIFIER_CONFIDENCE.value in res_no_conf.reason_codes

    # 2. Low confidence (< 0.70) downgrades ALLOW to REVIEW
    res_low_conf = engine.evaluate(
        ClassificationOutput(line_item_id="L2", predicted_category=ItemCategoryCode.NORMAL, confidence=0.55, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_low_conf.outcome == ScreeningOutcome.REVIEW
    assert ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value in res_low_conf.reason_codes

    # 3. is_uncertain flag downgrades ALLOW to REVIEW
    res_uncertain = engine.evaluate(
        ClassificationOutput(line_item_id="L3", predicted_category=ItemCategoryCode.NORMAL, confidence=0.95, is_uncertain=True, classifier_name="c", classifier_version="1"),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_uncertain.outcome == ScreeningOutcome.REVIEW

    # 4. Low confidence NEVER downgrades ALERT to REVIEW! Security perimeter stays firm!
    res_alert_low = engine.evaluate(
        ClassificationOutput(line_item_id="L4", predicted_category=ItemCategoryCode.ALCOHOL, confidence=0.30, classifier_name="c", classifier_version="1", is_uncertain=False),
        evaluation_timestamp=_TIMESTAMP,
    )
    assert res_alert_low.outcome == ScreeningOutcome.ALERT


# ==============================================================================
# 4. Audit Log Ledger Tests
# ==============================================================================

def test_audit_log_ledger():
    ledger = AuditLogLedger()

    screening_ev = ScreeningAuditEvent(
        screening_event_id="scr-001",
        line_item_ref="item-1",
        invoice_ref="inv-1",
        classifier_name="model_v1",
        classifier_version="1.0",
        predicted_category="ALCOHOL",
        confidence=0.95,
        policy_version="v1.0",
        outcome="ALERT",
        matched_rule_ids=["R1"],
        reason_codes=["CATEGORY_RULE_ALERT"],
        requires_human_review=True,
        evaluation_timestamp=_TIMESTAMP,
    )
    ledger.record_screening(screening_ev)

    review_ev = HumanReviewEvent(
        review_event_id="rev-001",
        prior_screening_event_id="scr-001",
        reviewer_badge_id="GUARD-42",
        action=HumanReviewAction.OVERRIDE_TO_ALLOW,
        review_timestamp=_TIMESTAMP,
        justification_notes="Item inspected: certified non-alcoholic malt drink.",
        corrected_category="NORMAL",
    )
    ledger.record_human_review(review_ev)

    assert ledger.total_events_count == 2
    assert ledger.get_screening_event("scr-001") == screening_ev
    assert len(ledger.get_reviews_for_screening("scr-001")) == 1

    ev_dict = screening_ev.to_dict()
    assert ev_dict["event_type"] == "AUTOMATED_SCREENING"
    assert review_ev.to_dict()["event_type"] == "HUMAN_REVIEW"


# ==============================================================================
# 5. Evaluation Metrics Tests
# ==============================================================================

def test_track_c_evaluation_metrics():
    # evaluate_classifier
    preds = [
        ClassificationOutput(line_item_id="L1", predicted_category=ItemCategoryCode.ALCOHOL, confidence=0.90, classifier_name="c", classifier_version="1", is_uncertain=False),
        ClassificationOutput(line_item_id="L2", predicted_category=ItemCategoryCode.NORMAL, confidence=0.85, classifier_name="c", classifier_version="1", is_uncertain=False),
    ]
    gt_cats = [ItemCategoryCode.ALCOHOL, ItemCategoryCode.NORMAL]

    cls_summary = MetricCalculator.evaluate_classifier(preds, gt_cats)
    assert cls_summary.total_samples == 2
    assert cls_summary.accuracy == 1.0
    assert cls_summary.to_dict()["accuracy"] == 1.0

    # evaluate_policy
    scr_results = [
        ScreeningResult(
            screening_event_id="ev1",
            line_item_id="L1",
            outcome=ScreeningOutcome.ALERT,
            reason_codes=["CATEGORY_RULE_ALERT"],
            matched_rule_ids=["R1"],
            policy_version="v1.0",
            evaluation_timestamp=_TIMESTAMP,
            explanation="Alert",
            requires_human_review=True,
            classification_summary={},
            audit_trace=RuleEvaluationTrace(1, [], {}, [], "R1", "rule"),
        )
    ]
    gt_policy = [{"expected_outcome": "ALERT", "expected_reason_codes": ["CATEGORY_RULE_ALERT"]}]

    pol_summary = MetricCalculator.evaluate_policy(scr_results, gt_policy)
    assert pol_summary.total_samples == 1
    assert pol_summary.outcome_accuracy == 1.0
    assert pol_summary.false_allow_rate == 0.0
    assert pol_summary.to_dict()["outcome_accuracy"] == 1.0
    md = pol_summary.format_markdown_table()
    assert "Deterministic Policy Engine Evaluation Summary" in md


def test_track_c_policy_facade():
    from research_track.track_c.src.policy import (
        load_policy_rules,
        create_policy_engine,
        evaluate_screening_policy,
    )
    rules = load_policy_rules()
    assert len(rules) >= 20

    engine = create_policy_engine(rules=rules)
    assert engine is not None

    # Normal grocery -> ALLOW
    clf_normal = ClassificationOutput(
        line_item_id="L-GROCERY",
        predicted_category=ItemCategoryCode.NORMAL,
        confidence=0.99,
        classifier_name="test",
        classifier_version="1.0",
        is_uncertain=False,
    )
    res = evaluate_screening_policy(clf_normal, engine=engine)
    assert res.outcome == ScreeningOutcome.ALLOW

    # Prohibited alcohol -> ALERT
    clf_alcohol = ClassificationOutput(
        line_item_id="L-BEER",
        predicted_category=ItemCategoryCode.ALCOHOL,
        confidence=0.99,
        classifier_name="test",
        classifier_version="1.0",
        is_uncertain=False,
    )
    res_alc = evaluate_screening_policy(clf_alcohol, engine=engine)
    assert res_alc.outcome == ScreeningOutcome.ALERT


def test_track_c_invariance_and_conflict_properties():
    from research_track.track_c.src.evaluation import MetricCalculator
    rules = [
        _make_rule("R1", ItemCategoryCode.NORMAL, ScreeningOutcome.ALLOW, priority=2),
        _make_rule("R2", ItemCategoryCode.NORMAL, ScreeningOutcome.REVIEW, priority=1),
    ]
    clf = ClassificationOutput(
        line_item_id="L-INV",
        predicted_category=ItemCategoryCode.NORMAL,
        confidence=0.95,
        classifier_name="test",
        classifier_version="1.0",
        is_uncertain=False,
    )

    # Invariance check
    inv_ok = MetricCalculator.verify_rule_order_invariance(rules, clf, evaluation_timestamp=_TIMESTAMP)
    assert inv_ok is True

    # Conflict check
    conflict_rules = [
        _make_rule("RC1", ItemCategoryCode.NORMAL, ScreeningOutcome.ALLOW, priority=1),
        _make_rule("RC2", ItemCategoryCode.NORMAL, ScreeningOutcome.ALERT, priority=1),
    ]
    safe = MetricCalculator.verify_conflict_safety(conflict_rules, clf, evaluation_timestamp=_TIMESTAMP)
    assert safe is True

