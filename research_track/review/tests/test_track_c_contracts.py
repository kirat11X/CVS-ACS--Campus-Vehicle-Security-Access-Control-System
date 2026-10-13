import json

from research_track.track_c.src.policy_engine import DeterministicPolicyEngine
from research_track.track_c.src.types import (
    ClassificationOutput,
    ItemCategoryCode,
    PolicyRule,
    ScreeningOutcome,
)


_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _classification(uncertain=False):
    return ClassificationOutput(
        line_item_id="line-1",
        predicted_category=ItemCategoryCode.NORMAL,
        confidence=0.99,
        classifier_name="review",
        classifier_version="1",
        is_uncertain=uncertain,
        prediction_timestamp=None,
    )


def _rules():
    raw = json.loads(open("research_track/track_c/fixtures/policy_rules.json", encoding="utf-8").read())
    return [
        PolicyRule(
            rule_id=item["rule_id"],
            category_code=ItemCategoryCode(item["category_code"]),
            action=ScreeningOutcome(item["action"]),
            priority=item["priority"],
            policy_version=item["policy_version"],
            min_quantity=item["min_quantity"],
            max_quantity=item["max_quantity"],
            quantity_unit=item["quantity_unit"],
            platform=item["platform"],
            effective_from=item["effective_from"],
            effective_to=item["effective_to"],
            active=item["active"],
            description=item["description"],
        )
        for item in raw
    ]


def test_track_c_repeated_evaluation_is_identical():
    engine = DeterministicPolicyEngine(rules=_rules())
    first = engine.evaluate(_classification(), evaluation_timestamp=_TIMESTAMP)
    second = engine.evaluate(_classification(), evaluation_timestamp=_TIMESTAMP)
    assert first.to_dict() == second.to_dict()


def test_track_c_uncertain_classification_never_allows():
    engine = DeterministicPolicyEngine(rules=_rules())
    result = engine.evaluate(_classification(uncertain=True), evaluation_timestamp=_TIMESTAMP)
    assert result.outcome != ScreeningOutcome.ALLOW
    assert "MANUAL_REVIEW_REQUIRED" in result.reason_codes


def test_track_c_rule_order_does_not_change_result():
    classification = ClassificationOutput(
        line_item_id="line-2",
        predicted_category=ItemCategoryCode.TOBACCO_NICOTINE,
        confidence=0.99,
        classifier_name="review",
        classifier_version="1",
        is_uncertain=False,
    )
    first = DeterministicPolicyEngine(rules=_rules()).evaluate(
        classification, evaluation_timestamp=_TIMESTAMP
    )
    second = DeterministicPolicyEngine(rules=list(reversed(_rules()))).evaluate(
        classification, evaluation_timestamp=_TIMESTAMP
    )
    assert first.to_dict() == second.to_dict()
