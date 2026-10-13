"""
Track C: Append-Only Audit Records & Review Event Ledger.

Defines in-memory data structures for screening audit events and human review actions.

Invariants:
- All audit events are append-only; historical decisions are never mutated or deleted.
- Human review decisions are stored as separate events referencing prior screening IDs.
- Prefers opaque references over raw sensitive text to protect privacy.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class HumanReviewAction(str, Enum):
    """Categorical action taken by human security guard or supervisor."""
    CONFIRM_ALLOW = "CONFIRM_ALLOW"
    CONFIRM_ALERT = "CONFIRM_ALERT"
    OVERRIDE_TO_ALLOW = "OVERRIDE_TO_ALLOW"
    OVERRIDE_TO_ALERT = "OVERRIDE_TO_ALERT"
    ESCALATE_TO_SUPERVISOR = "ESCALATE_TO_SUPERVISOR"
    REJECT_VEHICLE_ENTRY = "REJECT_VEHICLE_ENTRY"


@dataclass(frozen=True)
class ScreeningAuditEvent:
    """An immutable, append-only event recording an automated policy evaluation."""
    screening_event_id: str
    line_item_ref: str
    invoice_ref: Optional[str]
    classifier_name: str
    classifier_version: str
    predicted_category: str
    confidence: Optional[float]
    policy_version: str
    outcome: str
    matched_rule_ids: List[str]
    reason_codes: List[str]
    requires_human_review: bool
    evaluation_timestamp: str
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "AUTOMATED_SCREENING",
            "screening_event_id": self.screening_event_id,
            "line_item_ref": self.line_item_ref,
            "invoice_ref": self.invoice_ref,
            "classifier_name": self.classifier_name,
            "classifier_version": self.classifier_version,
            "predicted_category": self.predicted_category,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "policy_version": self.policy_version,
            "outcome": self.outcome,
            "matched_rule_ids": self.matched_rule_ids,
            "reason_codes": self.reason_codes,
            "requires_human_review": self.requires_human_review,
            "evaluation_timestamp": self.evaluation_timestamp,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class HumanReviewEvent:
    """An immutable review event recording a guard's operational determination."""
    review_event_id: str
    prior_screening_event_id: str
    reviewer_badge_id: str
    action: HumanReviewAction
    review_timestamp: str
    justification_notes: str
    corrected_category: Optional[str] = None
    override_reason_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "HUMAN_REVIEW",
            "review_event_id": self.review_event_id,
            "prior_screening_event_id": self.prior_screening_event_id,
            "reviewer_badge_id": self.reviewer_badge_id,
            "action": self.action.value,
            "review_timestamp": self.review_timestamp,
            "justification_notes": self.justification_notes,
            "corrected_category": self.corrected_category,
            "override_reason_code": self.override_reason_code,
        }


class AuditLogLedger:
    """
    Append-only in-memory ledger recording security events without mutation.
    """

    def __init__(self):
        self._screening_events: List[ScreeningAuditEvent] = []
        self._review_events: List[HumanReviewEvent] = []

    def record_screening(self, event: ScreeningAuditEvent) -> None:
        """Appends a new screening audit event."""
        self._screening_events.append(event)

    def record_human_review(self, event: HumanReviewEvent) -> None:
        """Appends a new human review event referencing a past screening."""
        self._review_events.append(event)

    def get_screening_event(self, screening_event_id: str) -> Optional[ScreeningAuditEvent]:
        """Finds a screening event by ID."""
        for ev in self._screening_events:
            if ev.screening_event_id == screening_event_id:
                return ev
        return None

    def get_reviews_for_screening(self, screening_event_id: str) -> List[HumanReviewEvent]:
        """Returns all review events attached to a specific screening event."""
        return [r for r in self._review_events if r.prior_screening_event_id == screening_event_id]

    @property
    def total_events_count(self) -> int:
        return len(self._screening_events) + len(self._review_events)
