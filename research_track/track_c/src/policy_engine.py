"""
Track C: Deterministic Screening Policy Engine.

A pure, standalone evaluation engine that evaluates classifier hypotheses against
an explicit, versioned policy rule table to produce explainable security outcomes.

Invariants:
- Pure deterministic function of inputs, rules, timestamp, and policy version.
- Zero network, database, model, or file I/O calls during evaluation.
- Identical inputs and rules yield identical results regardless of rule ordering.
- Ambiguous rule conflicts at equal priority never silently resolve to ALLOW.
- Low or missing confidence never silently produces ALLOW.
"""

from datetime import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .category_normalization import CategoryNormalizer
from .reason_codes import ReasonCode
from .types import (
    ClassificationOutput,
    ItemCategoryCode,
    PolicyRule,
    RuleEvaluationTrace,
    ScreeningOutcome,
    ScreeningResult,
)


class DeterministicPolicyEngine:
    """
    Evaluates item classifications against versioned security rules deterministically.
    """

    def __init__(
        self,
        rules: Optional[List[PolicyRule]] = None,
        default_policy_version: str = "v1.0",
        confidence_review_threshold: float = 0.70,
        treat_missing_confidence_as_review: bool = True,
        fallback_action_on_conflict: ScreeningOutcome = ScreeningOutcome.REVIEW,
        fallback_action_on_unmatched: ScreeningOutcome = ScreeningOutcome.REVIEW,
    ):
        self.rules = rules or []
        self.default_policy_version = default_policy_version
        self.confidence_review_threshold = confidence_review_threshold
        self.treat_missing_confidence_as_review = treat_missing_confidence_as_review
        self.fallback_action_on_conflict = fallback_action_on_conflict
        self.fallback_action_on_unmatched = fallback_action_on_unmatched

    def evaluate(
        self,
        classification: ClassificationOutput,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        platform: Optional[str] = None,
        policy_version: Optional[str] = None,
        evaluation_timestamp: Optional[str] = None,
    ) -> ScreeningResult:
        """
        Executes pure deterministic policy evaluation for a line item classification.
        """
        active_version = policy_version or self.default_policy_version
        if evaluation_timestamp is None:
            raise ValueError("evaluation_timestamp is required for deterministic evaluation")
        eval_time_str = evaluation_timestamp
        event_payload = {
            "classification": classification.to_dict(),
            "quantity": quantity,
            "unit": unit,
            "platform": platform,
            "policy_version": active_version,
            "evaluation_timestamp": eval_time_str,
            "rules": [
                rule.to_dict()
                for rule in sorted(self.rules, key=lambda candidate: candidate.rule_id)
            ],
        }
        event_digest = hashlib.sha256(
            json.dumps(event_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        event_id = f"scr-{classification.line_item_id}-{event_digest}"

        reason_codes: List[str] = []
        rejected_rules: Dict[str, str] = {}
        conflicts: List[str] = []

        # Parse evaluation timestamp for effective window checks
        eval_dt = self._parse_iso(eval_time_str)

        # 1. Filter rules relevant to policy version
        version_rules = [r for r in self.rules if r.policy_version == active_version]
        if not version_rules and self.rules:
            # Active policy version not found in loaded rules
            reason_codes.append(ReasonCode.POLICY_VERSION_INVALID.value)
            reason_codes.append(ReasonCode.MANUAL_REVIEW_REQUIRED.value)
            trace = RuleEvaluationTrace(
                rules_considered=len(self.rules),
                matching_candidates=[],
                rejected_rules={"all": f"No rules found matching policy_version '{active_version}'"},
                conflicts_detected=[],
                applied_rule_id=None,
                resolution_method="policy_version_invalid_fallback",
            )
            return ScreeningResult(
                screening_event_id=event_id,
                line_item_id=classification.line_item_id,
                outcome=ScreeningOutcome.REVIEW,
                reason_codes=reason_codes,
                matched_rule_ids=[],
                policy_version=active_version,
                evaluation_timestamp=eval_time_str,
                explanation=f"Policy version '{active_version}' is invalid or has no configured rules. Mandating manual review.",
                requires_human_review=True,
                classification_summary=classification.to_dict(),
                audit_trace=trace,
            )

        # 2. Check for UNKNOWN category upfront
        cat = classification.predicted_category
        if cat == ItemCategoryCode.UNKNOWN or classification.is_uncertain and cat == ItemCategoryCode.UNKNOWN:
            reason_codes.append(ReasonCode.UNKNOWN_CATEGORY.value)
            reason_codes.append(ReasonCode.MANUAL_REVIEW_REQUIRED.value)

        # 3. Filter matching rules based on category, validity, platform, and quantity
        matched_candidates: List[PolicyRule] = []

        for rule in version_rules:
            # A. Active check
            if not rule.active:
                rejected_rules[rule.rule_id] = "Rule is inactive (active=false)"
                continue

            # B. Temporal validity window check
            if rule.effective_from:
                from_dt = self._parse_iso(rule.effective_from)
                if eval_dt and from_dt and eval_dt < from_dt:
                    rejected_rules[rule.rule_id] = "Rule not yet effective"
                    continue

            if rule.effective_to:
                to_dt = self._parse_iso(rule.effective_to)
                if eval_dt and to_dt and eval_dt > to_dt:
                    rejected_rules[rule.rule_id] = "Rule has expired"
                    continue

            # C. Category match check
            if rule.category_code != cat:
                rejected_rules[rule.rule_id] = f"Category mismatch ({rule.category_code.value} != {cat.value})"
                continue

            # D. Platform match check
            if rule.platform:
                if not platform:
                    rejected_rules[rule.rule_id] = f"Platform required ({rule.platform}) but input was null"
                    if ReasonCode.MISSING_REQUIRED_PLATFORM.value not in reason_codes:
                        reason_codes.append(ReasonCode.MISSING_REQUIRED_PLATFORM.value)
                    continue
                if rule.platform.strip().upper() != platform.strip().upper():
                    rejected_rules[rule.rule_id] = f"Platform mismatch ({rule.platform} != {platform})"
                    continue

            # E. Quantity threshold checks
            if rule.min_quantity is not None or rule.max_quantity is not None:
                if quantity is None:
                    rejected_rules[rule.rule_id] = "Rule requires quantity, but input quantity was null"
                    if ReasonCode.MISSING_QUANTITY.value not in reason_codes:
                        reason_codes.append(ReasonCode.MISSING_QUANTITY.value)
                    continue

                if quantity < 0:
                    rejected_rules[rule.rule_id] = "Quantity is negative"
                    if ReasonCode.INVALID_QUANTITY.value not in reason_codes:
                        reason_codes.append(ReasonCode.INVALID_QUANTITY.value)
                    continue

                # Check unit compatibility if specified
                if rule.quantity_unit:
                    if not unit or rule.quantity_unit.strip().upper() != unit.strip().upper():
                        rejected_rules[rule.rule_id] = f"Unit mismatch ({rule.quantity_unit} != {unit})"
                        if ReasonCode.UNSUPPORTED_QUANTITY_UNIT.value not in reason_codes:
                            reason_codes.append(ReasonCode.UNSUPPORTED_QUANTITY_UNIT.value)
                        continue

                # Check numerical interval
                if rule.min_quantity is not None and quantity < rule.min_quantity:
                    rejected_rules[rule.rule_id] = f"Quantity {quantity} < min {rule.min_quantity}"
                    continue

                if rule.max_quantity is not None and quantity > rule.max_quantity:
                    rejected_rules[rule.rule_id] = f"Quantity {quantity} > max {rule.max_quantity}"
                    continue

            # All criteria satisfied!
            matched_candidates.append(rule)

        # 4. Resolve Best Rule by Deterministic Precedence
        applied_rule: Optional[PolicyRule] = None
        outcome: ScreeningOutcome
        resolution_method: str

        if not matched_candidates:
            # Case: No matching rule
            cat_def = CategoryNormalizer.get_definition(cat)
            outcome = cat_def.default_action
            applied_rule = None
            resolution_method = "category_default_fallback"
            if cat != ItemCategoryCode.UNKNOWN:
                reason_codes.append(ReasonCode.NO_MATCHING_POLICY_RULE.value)

            # Special case for hazardous chemicals below threshold when no threshold rule matched
            if cat == ItemCategoryCode.HAZARDOUS_CHEMICAL:
                if quantity is not None and quantity < 3.0:
                    outcome = ScreeningOutcome.ALLOW
                    reason_codes.append(ReasonCode.HAZARDOUS_THRESHOLD_NOT_MET.value)
                elif quantity is None:
                    outcome = ScreeningOutcome.REVIEW
                    reason_codes.append(ReasonCode.MISSING_QUANTITY.value)
        else:
            # Sort candidates strictly by priority (lower int = higher priority)
            # Secondarily sort deterministically by rule_id string to be order-independent
            matched_candidates.sort(key=lambda r: (r.priority, r.rule_id))

            # Find all candidates at top priority
            best_priority = matched_candidates[0].priority
            top_priority_rules = [r for r in matched_candidates if r.priority == best_priority]

            # Check for conflict among rules at equal highest priority
            distinct_actions = {r.action for r in top_priority_rules}
            if len(distinct_actions) > 1:
                # Critical Priority Conflict: two rules at same priority mandate different actions!
                conflicts = [r.rule_id for r in top_priority_rules]
                reason_codes.append(ReasonCode.POLICY_RULE_CONFLICT.value)
                reason_codes.append(ReasonCode.MANUAL_REVIEW_REQUIRED.value)
                outcome = self.fallback_action_on_conflict
                applied_rule = None
                resolution_method = "priority_tie_conflict_fallback"
            else:
                # Unambiguous match!
                applied_rule = top_priority_rules[0]
                outcome = applied_rule.action
                resolution_method = f"rule_match_priority_{applied_rule.priority}"

                if len(matched_candidates) > 1:
                    reason_codes.append(ReasonCode.MULTIPLE_RULES_MATCHED.value)

                # Attach matching reason code
                if outcome == ScreeningOutcome.ALERT:
                    reason_codes.append(ReasonCode.CATEGORY_RULE_ALERT.value)
                elif outcome == ScreeningOutcome.REVIEW:
                    reason_codes.append(ReasonCode.CATEGORY_RULE_REVIEW.value)
                elif outcome == ScreeningOutcome.ALLOW:
                    reason_codes.append(ReasonCode.CATEGORY_RULE_ALLOW.value)

                # Hazardous threshold indicator
                if cat == ItemCategoryCode.HAZARDOUS_CHEMICAL:
                    if applied_rule.min_quantity is not None and quantity is not None and quantity >= applied_rule.min_quantity:
                        reason_codes.append(ReasonCode.HAZARDOUS_THRESHOLD_MET.value)

        # 5. Apply Confidence Safety Invariants
        # A low confidence or missing confidence MUST NOT allow items through without review
        conf = classification.confidence
        if conf is None:
            if self.treat_missing_confidence_as_review:
                if ReasonCode.MISSING_CLASSIFIER_CONFIDENCE.value not in reason_codes:
                    reason_codes.append(ReasonCode.MISSING_CLASSIFIER_CONFIDENCE.value)
                # If outcome was ALLOW, downgrade to REVIEW! (Never downgrade ALERT)
                if outcome == ScreeningOutcome.ALLOW:
                    outcome = ScreeningOutcome.REVIEW
                    resolution_method += "_downgraded_due_to_missing_confidence"
        elif conf < self.confidence_review_threshold:
            if ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value not in reason_codes:
                reason_codes.append(ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value)
            # If outcome was ALLOW, downgrade to REVIEW!
            if outcome == ScreeningOutcome.ALLOW:
                outcome = ScreeningOutcome.REVIEW
                resolution_method += "_downgraded_due_to_low_confidence"

        if classification.is_uncertain and outcome == ScreeningOutcome.ALLOW:
            if ReasonCode.MANUAL_REVIEW_REQUIRED.value not in reason_codes:
                reason_codes.append(ReasonCode.MANUAL_REVIEW_REQUIRED.value)
            outcome = ScreeningOutcome.REVIEW
            resolution_method += "_downgraded_due_to_uncertain_classification"

        # 6. Final Review Flag & Plain English Explanation
        requires_review = (outcome != ScreeningOutcome.ALLOW) or (ReasonCode.MANUAL_REVIEW_REQUIRED.value in reason_codes)
        matched_rule_ids = [applied_rule.rule_id] if applied_rule else []

        explanation = self._build_explanation(
            classification=classification,
            outcome=outcome,
            applied_rule=applied_rule,
            quantity=quantity,
            unit=unit,
            platform=platform,
            reason_codes=reason_codes,
        )

        trace = RuleEvaluationTrace(
            rules_considered=len(version_rules),
            matching_candidates=[r.rule_id for r in matched_candidates],
            rejected_rules=rejected_rules,
            conflicts_detected=conflicts,
            applied_rule_id=applied_rule.rule_id if applied_rule else None,
            resolution_method=resolution_method,
        )

        return ScreeningResult(
            screening_event_id=event_id,
            line_item_id=classification.line_item_id,
            outcome=outcome,
            reason_codes=reason_codes,
            matched_rule_ids=matched_rule_ids,
            policy_version=active_version,
            evaluation_timestamp=eval_time_str,
            explanation=explanation,
            requires_human_review=requires_review,
            classification_summary=classification.to_dict(),
            audit_trace=trace,
        )

    @staticmethod
    def _parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
        """Safely parses ISO 8601 string to datetime."""
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _build_explanation(
        classification: ClassificationOutput,
        outcome: ScreeningOutcome,
        applied_rule: Optional[PolicyRule],
        quantity: Optional[float],
        unit: Optional[str],
        platform: Optional[str],
        reason_codes: List[str],
    ) -> str:
        """Constructs auditable explanation sentence for security log."""
        cat_name = classification.predicted_category.value
        parts = [f"Outcome [{outcome.value}] for item '{classification.line_item_id}' ({cat_name})."]

        if applied_rule:
            parts.append(f"Matched rule '{applied_rule.rule_id}' (priority {applied_rule.priority}).")
        else:
            parts.append("No specific rule applied; evaluated under category default / safety fallback.")

        if quantity is not None:
            parts.append(f"Quantity: {quantity} {unit or ''}.".strip())

        if platform:
            parts.append(f"Platform: {platform}.")

        if ReasonCode.LOW_CLASSIFIER_CONFIDENCE.value in reason_codes:
            parts.append(f"Caution: Model confidence ({classification.confidence}) was below safety threshold.")
        elif ReasonCode.MISSING_CLASSIFIER_CONFIDENCE.value in reason_codes:
            parts.append("Caution: Model confidence was unstated/null.")

        if ReasonCode.POLICY_RULE_CONFLICT.value in reason_codes:
            parts.append("Warning: Priority conflict detected between applicable rules.")

        return " ".join(parts)
