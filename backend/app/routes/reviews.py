import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.base import utc_now
from backend.app.models.delivery import DeliveryDecision, Invoice
from backend.app.models.enums import (
    AccessState,
    AlertSeverity,
    AlertStatus,
    GuardDecision,
    ReasonCode,
    ResolutionOutcome,
    ScreeningVerdict,
)
from backend.app.models.gate import AccessDecision, EntryExitLog, Gate, SecurityAlert
from backend.app.models.identity import User
from backend.app.models.observation import ObservationEvent, ObservationResolution
from backend.app.services.alert_service import alert_service
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.services.policy_engine import evaluate_access_policy

logger = logging.getLogger("campus_security.reviews")

router = APIRouter(prefix="/security/reviews", tags=["Security Review Queue"])


# ---- Schemas ----

class ReviewType(str, Enum):
    ACCESS_EVENT = "ACCESS_EVENT"
    CARGO_SCREENING = "CARGO_SCREENING"


class TriageAction(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"
    OVERRIDE = "OVERRIDE"


class ReviewItem(BaseModel):
    review_id: str
    review_type: ReviewType
    gate_id: Optional[str] = None
    plate: Optional[str] = None
    order_id: Optional[str] = None
    confidence: Optional[float] = None
    reason_code: Optional[str] = None
    severity: str = "MEDIUM"
    status: str = "PENDING"
    created_at: datetime
    details: Dict[str, Any] = {}


class ReviewQueueResponse(BaseModel):
    total: int
    items: List[ReviewItem]


class TriageRequest(BaseModel):
    action: TriageAction
    guard_id: UUID = Field(..., description="Mandatory ID of the guard performing triage")
    reason_notes: str = Field(..., min_length=3, max_length=1000, description="Mandatory operational notes")
    gate_override: Optional[str] = Field(None, max_length=30, description="Optional gate identifier override")


class TriageResponse(BaseModel):
    status: str = "SUCCESS"
    review_id: str
    action: str
    audit_id: UUID
    timestamp: datetime
    message: str


# ---- Endpoints ----

@router.get("", response_model=ReviewQueueResponse)
def get_security_reviews(
    review_type: Optional[ReviewType] = Query(None, alias="type", description="Filter by review type"),
    gate_id: Optional[str] = Query(None, description="Filter by gate ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Returns pending access events and cargo items requiring guard review (Phase 11-12).
    """
    items: List[ReviewItem] = []
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    # 1. Access Events requiring review
    if review_type in (None, ReviewType.ACCESS_EVENT):
        # A. Pending SecurityAlert rows
        alert_query = (
            db.query(SecurityAlert)
            .filter(SecurityAlert.status == AlertStatus.PENDING)
            .order_by(SecurityAlert.created_at.desc())
        )
        if gate_id:
            alert_query = alert_query.filter(SecurityAlert.gate_id == gate_id)

        for alert in alert_query.limit(limit).all():
            items.append(
                ReviewItem(
                    review_id=f"alert_{alert.id}",
                    review_type=ReviewType.ACCESS_EVENT,
                    gate_id=alert.gate_id,
                    plate=alert.log.plate if alert.log else None,
                    confidence=alert.log.confidence if alert.log else None,
                    reason_code=ReasonCode.MANUAL_REVIEW.value,
                    severity=alert.severity.value,
                    status=alert.status.value,
                    created_at=alert.created_at,
                    details={"title": alert.title, "description": alert.description, "alert_id": str(alert.id)},
                )
            )

        # B. Unresolved Observations needing review or unlinked
        obs_query = (
            db.query(ObservationEvent)
            .options(selectinload(ObservationEvent.gate))
            .filter(ObservationEvent.observed_at >= lookback)
            .order_by(ObservationEvent.observed_at.desc())
        )
        if gate_id:
            obs_query = obs_query.filter(ObservationEvent.gate_id == gate_id)

        observations = obs_query.limit(limit).all()
        # Find which observations already have resolutions or access decisions
        resolved_obs_ids = {
            r[0]
            for r in db.query(ObservationResolution.observation_id)
            .filter(ObservationResolution.observation_id.in_([o.id for o in observations]))
            .all()
        }

        for obs in observations:
            if obs.id in resolved_obs_ids:
                continue

            # Check if this observation needs review
            is_low_conf = obs.plate_confidence is not None and obs.plate_confidence < 0.70
            is_unreadable = not obs.normalized_plate

            if is_low_conf or is_unreadable:
                reason = (
                    ReasonCode.REVIEW_UNREADABLE_PLATE.value
                    if is_unreadable
                    else ReasonCode.REVIEW_LOW_CONFIDENCE_PLATE.value
                )
                items.append(
                    ReviewItem(
                        review_id=f"obs_{obs.id}",
                        review_type=ReviewType.ACCESS_EVENT,
                        gate_id=obs.gate_id,
                        plate=obs.raw_plate or obs.normalized_plate,
                        confidence=obs.plate_confidence,
                        reason_code=reason,
                        severity="MEDIUM",
                        status="PENDING",
                        created_at=obs.observed_at,
                        details={
                            "observation_id": str(obs.id),
                            "vehicle_type": obs.vehicle_type.value,
                            "direction": obs.direction.value,
                        },
                    )
                )

    # 2. Cargo / Delivery Items requiring review
    if review_type in (None, ReviewType.CARGO_SCREENING):
        try:
            pending_invoices = delivery_screening_service.pending_invoices(db)
        except Exception as e:
            logger.warning(f"Error calling pending_invoices: {e}")
            pending_invoices = []

        # Ensure all unscreened/undecided invoices with ALERT/REVIEW are surfaced
        if not pending_invoices:
            from sqlalchemy.sql import exists
            pending_invoices = (
                db.query(Invoice)
                .options(selectinload(Invoice.items), selectinload(Invoice.order))
                .filter(
                    Invoice.overall_verdict.in_([ScreeningVerdict.REVIEW, ScreeningVerdict.ALERT]),
                    ~exists().where(DeliveryDecision.invoice_id == Invoice.id),
                )
                .order_by(Invoice.created_at.desc())
                .limit(limit)
                .all()
            )

        for inv in pending_invoices:
            inv_gate = inv.gate_id or (inv.order.gate_id if inv.order else None)
            if gate_id and inv_gate != gate_id:
                continue

            order_id = inv.order.order_id if inv.order else "UNKNOWN"
            # Check if any line was ALERT or REVIEW
            has_alert = any(item.verdict == ScreeningVerdict.ALERT for item in inv.items) or (inv.overall_verdict == ScreeningVerdict.ALERT)
            has_review = any(item.verdict == ScreeningVerdict.REVIEW for item in inv.items) or (inv.totals_match is False) or (inv.overall_verdict == ScreeningVerdict.REVIEW)

            if has_alert or has_review or not inv.items:
                reason = (
                    ReasonCode.ALERT_RESTRICTED_ITEM.value
                    if has_alert
                    else ReasonCode.REVIEW_CARGO_SCREENING_UNCERTAIN.value
                )
                severity = "HIGH" if has_alert else "MEDIUM"
                items.append(
                    ReviewItem(
                        review_id=f"cargo_{inv.id}",
                        review_type=ReviewType.CARGO_SCREENING,
                        gate_id=inv_gate,
                        order_id=order_id,
                        confidence=inv.confidence,
                        reason_code=reason,
                        severity=severity,
                        status="PENDING",
                        created_at=inv.created_at,
                        details={
                            "invoice_id": str(inv.id),
                            "vendor": inv.vendor,
                            "total_amount": float(inv.total_amount) if inv.total_amount else None,
                            "item_count": len(inv.items),
                            "totals_match": inv.totals_match,
                        },
                    )
                )

    # Sort items by timestamp descending
    items.sort(key=lambda x: x.created_at, reverse=True)
    total = len(items)
    paged_items = items[skip : skip + limit]

    return ReviewQueueResponse(total=total, items=paged_items)


@router.post("/{review_id}/triage", response_model=TriageResponse)
def triage_security_review(
    review_id: str,
    payload: TriageRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Guard action (ALLOW, REJECT, OVERRIDE) on a pending review item (Phase 11-12).
    Mandatory guard_id and reason_notes.
    Persists immutable audit records into the database.
    """
    # 1. Verify guard exists
    guard = db.get(User, payload.guard_id)
    if not guard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guard user with ID '{payload.guard_id}' not found.",
        )

    # 2. Verify optional gate override
    effective_gate = payload.gate_override
    if effective_gate:
        gate_obj = db.get(Gate, effective_gate)
        if not gate_obj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Gate override '{effective_gate}' does not exist.",
            )

    # 3. Determine target entity from review_id
    raw_id = review_id.strip()
    clean_uuid_str = raw_id
    for prefix in ("alert_", "obs_", "cargo_", "delivery_"):
        if raw_id.startswith(prefix):
            clean_uuid_str = raw_id[len(prefix):]
            break

    target_uuid: Optional[UUID] = None
    try:
        target_uuid = UUID(clean_uuid_str)
    except (ValueError, TypeError):
        pass

    audit_decision_id = uuid.uuid4()
    now = utc_now()

    # Case A: Cargo / Invoice review
    invoice: Optional[Invoice] = None
    if raw_id.startswith(("cargo_", "delivery_")) and target_uuid:
        invoice = db.get(Invoice, target_uuid)
    elif target_uuid:
        invoice = db.get(Invoice, target_uuid)

    if invoice and invoice.order_id:
        # Determine guard decision
        if payload.action in (TriageAction.ALLOW, TriageAction.OVERRIDE):
            g_decision = GuardDecision.CLEARED
            access_state = AccessState.ALLOWED
        else:
            g_decision = GuardDecision.HELD
            access_state = AccessState.DENIED

        # Persist append-only DeliveryDecision
        delivery_decision = DeliveryDecision(
            id=uuid.uuid4(),
            order_id=invoice.order_id,
            invoice_id=invoice.id,
            decision=g_decision,
            note=f"[{payload.action.value}] {payload.reason_notes}"
            + (f" (Gate override: {payload.gate_override})" if payload.gate_override else ""),
            decided_by_id=payload.guard_id,
            decided_at=now,
        )
        db.add(delivery_decision)

        # Persist immutable AccessDecision audit record
        plate_str = invoice.order.delivery_vehicle_plate if invoice.order else "DELIVERY"
        gate_id_val = effective_gate or invoice.gate_id or (invoice.order.gate_id if invoice.order else "GATE_1")
        access_audit = AccessDecision(
            id=audit_decision_id,
            plate=plate_str or "DELIVERY",
            normalized_plate=plate_str or "DELIVERY",
            gate_id=gate_id_val,
            decision=access_state,
            reason_code=f"GUARD_CARGO_{payload.action.value}",
            reason=payload.reason_notes,
            confidence=1.0,
            context_data={
                "review_id": review_id,
                "action": payload.action.value,
                "guard_id": str(payload.guard_id),
                "guard_username": guard.username,
                "gate_override": payload.gate_override,
                "order_id": invoice.order.order_id if invoice.order else None,
                "invoice_id": str(invoice.id),
                "policy_version": "1.0",
            },
            timestamp=now,
        )
        db.add(access_audit)
        db.commit()

        return TriageResponse(
            status="SUCCESS",
            review_id=review_id,
            action=payload.action.value,
            audit_id=audit_decision_id,
            timestamp=now,
            message=f"Cargo review '{review_id}' successfully triaged with action '{payload.action.value}'.",
        )

    # Case B: Observation / Access Event review
    obs: Optional[ObservationEvent] = None
    if target_uuid:
        obs = db.get(ObservationEvent, target_uuid)

    alert: Optional[SecurityAlert] = None
    if raw_id.startswith("alert_") and target_uuid:
        alert = db.get(SecurityAlert, target_uuid)
        if alert and alert.log and alert.log.observation_id:
            obs = db.get(ObservationEvent, alert.log.observation_id)

    gate_val = effective_gate or (obs.gate_id if obs else (alert.gate_id if alert else "GATE_1"))
    plate_val = (obs.normalized_plate or obs.raw_plate) if obs else (alert.log.plate if alert and alert.log else "UNKNOWN")

    access_state = (
        AccessState.ALLOWED
        if payload.action in (TriageAction.ALLOW, TriageAction.OVERRIDE)
        else AccessState.DENIED
    )

    # Persist immutable AccessDecision audit record
    access_audit = AccessDecision(
        id=audit_decision_id,
        plate=plate_val or "UNKNOWN",
        normalized_plate=plate_val or "UNKNOWN",
        gate_id=gate_val,
        decision=access_state,
        reason_code=f"GUARD_{payload.action.value}",
        reason=payload.reason_notes,
        confidence=1.0,
        context_data={
            "review_id": review_id,
            "action": payload.action.value,
            "guard_id": str(payload.guard_id),
            "guard_username": guard.username,
            "gate_override": payload.gate_override,
            "observation_id": str(obs.id) if obs else None,
            "alert_id": str(alert.id) if alert else None,
            "policy_version": "1.0",
        },
        timestamp=now,
    )
    db.add(access_audit)

    # If linked to an observation, record append-only ObservationResolution
    if obs:
        resolution = ObservationResolution(
            id=uuid.uuid4(),
            observation_id=obs.id,
            outcome=ResolutionOutcome.NONE_OF_THESE,
            note=f"[{payload.action.value}] {payload.reason_notes}",
            created_by_id=payload.guard_id,
            created_at=now,
        )
        db.add(resolution)

    # If linked to a SecurityAlert, resolve the alert
    if alert:
        alert.status = AlertStatus.RESOLVED
        alert.reviewed_by_id = payload.guard_id
        alert.resolution_notes = f"[{payload.action.value}] {payload.reason_notes}"
        alert.resolved_at = now

    db.commit()

    return TriageResponse(
        status="SUCCESS",
        review_id=review_id,
        action=payload.action.value,
        audit_id=audit_decision_id,
        timestamp=now,
        message=f"Access review '{review_id}' successfully triaged with action '{payload.action.value}'.",
    )
