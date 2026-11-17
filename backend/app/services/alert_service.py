from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, selectinload

from backend.app.config import ALERTS_LOOKBACK_HOURS, UNLINKED_OVERSTAY_HOURS
from backend.app.models.enums import ScreeningVerdict
from backend.app.models.observation import ObservationEvent
from backend.app.schemas.delivery import AlertItem
from backend.app.schemas.feed import ResolvedObservation
from backend.app.services.delivery_policy import CATEGORY_LABELS
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.services.movement_service import movement_service

MAX_PLATE_OBSERVATIONS = 500

class AlertService:
    """
    Phase 7: one "needs attention" list for the guard console. Plates whose read needs a
    guard (several close registry plates, low confidence) or that are not in the registry,
    and delivery lines screened REVIEW / ALERT that no guard has decided on yet.
    An alert is a prompt to look, never a threat label and never an access decision.
    """

    @staticmethod
    def _plate_items(db: Session, since: datetime) -> List[Tuple[ObservationEvent, ResolvedObservation]]:
        observations = (
            db.query(ObservationEvent)
            .options(selectinload(ObservationEvent.gate), selectinload(ObservationEvent.created_by))
            .filter(
                ObservationEvent.observed_at >= since,
                ObservationEvent.normalized_plate.isnot(None),
                ObservationEvent.normalized_plate != "",
            )
            .order_by(ObservationEvent.observed_at.desc())
            .limit(MAX_PLATE_OBSERVATIONS)
            .all()
        )
        items = identity_resolution_service.resolve_many(db, observations, with_movement=False)
        latest, seen = [], set()
        for obs, item in zip(observations, items):
            if obs.normalized_plate in seen:
                continue  # newest sighting of a plate speaks for it
            seen.add(obs.normalized_plate)
            latest.append((obs, item))
        return latest

    def plate_alerts(self, db: Session, since: datetime) -> List[AlertItem]:
        alerts = []
        for obs, item in self._plate_items(db, since):
            match = item.registry_match
            if match is None or item.resolution is not None:
                continue  # a guard already resolved this read
            gate = obs.gate.name if obs.gate else obs.gate_id
            if match.outcome == "NEEDS_REVIEW":
                alerts.append(AlertItem(
                    kind="PLATE_REVIEW", severity="MEDIUM", title=f"{obs.normalized_plate} needs a guard to confirm",
                    detail=f"{match.explanation} · {gate}", ref=obs.normalized_plate, gate_id=obs.gate_id, at=obs.observed_at,
                ))
            elif match.outcome == "UNLINKED":
                alerts.append(AlertItem(
                    kind="PLATE_UNLINKED", severity="LOW", title=f"{obs.normalized_plate} is not in the registry",
                    detail=f"{match.explanation}; logged, link it or mark as visitor · {gate}", ref=obs.normalized_plate,
                    gate_id=obs.gate_id, at=obs.observed_at,
                ))
        return alerts

    def plate_counts(self, db: Session, since: datetime) -> Tuple[int, int]:
        """(unlinked plates, plates to review) in the window, one per plate, unresolved only."""
        unlinked = review = 0
        for _, item in self._plate_items(db, since):
            if item.registry_match is None or item.resolution is not None:
                continue
            if item.registry_match.outcome == "UNLINKED":
                unlinked += 1
            elif item.registry_match.outcome == "NEEDS_REVIEW":
                review += 1
        return unlinked, review

    @staticmethod
    def delivery_alerts(db: Session) -> List[AlertItem]:
        alerts = []
        for inv in delivery_screening_service.pending_invoices(db):
            order_id = inv.order.order_id
            gate_id = inv.gate_id or inv.order.gate_id
            for line in inv.items:
                if line.verdict not in (ScreeningVerdict.REVIEW, ScreeningVerdict.ALERT):
                    continue
                is_alert = line.verdict == ScreeningVerdict.ALERT
                label = CATEGORY_LABELS.get(line.category or "UNKNOWN", "Unknown")
                alerts.append(AlertItem(
                    kind="DELIVERY_ALERT" if is_alert else "DELIVERY_REVIEW",
                    severity="HIGH" if is_alert else "MEDIUM",
                    title=f"Order {order_id}: {line.item_name}",
                    detail=f"{label} · {line.reason_code} · {line.verdict.value}",
                    ref=order_id, gate_id=gate_id, at=inv.created_at,
                ))
            if inv.totals_match is False:
                alerts.append(AlertItem(
                    kind="DELIVERY_REVIEW", severity="MEDIUM", title=f"Order {order_id}: total does not add up",
                    detail=inv.reply_text or "Invoice total could not be confirmed", ref=order_id, gate_id=gate_id, at=inv.created_at,
                ))
            elif not inv.items:
                alerts.append(AlertItem(
                    kind="DELIVERY_REVIEW", severity="MEDIUM", title=f"Order {order_id}: invoice could not be read",
                    detail=inv.reply_text or "No item lines read", ref=order_id, gate_id=gate_id, at=inv.created_at,
                ))
        return alerts

    def unlinked_overstay_alerts(self, db: Session, threshold_hours: float = UNLINKED_OVERSTAY_HOURS) -> List[AlertItem]:
        """
        Flags unlinked vehicles, transient delivery cars, or unapproved visitors currently
        inside campus whose entry time exceeds the allowed threshold (default: 1.5 - 2.0 hours).
        Generates high-severity alerts for security officers to inspect or dispatch a patrol.
        """
        alerts = []
        now = datetime.now(timezone.utc)
        inside_resp = movement_service.inside(db)

        for item in inside_resp.items:
            # Check if vehicle is unlinked, has no student/faculty/resident owner, or is delivery/visitor
            is_unlinked = not item.linked or item.owner is None
            category = item.vehicle.category if item.vehicle else None
            is_transient = category in ("DELIVERY", "VISITOR", "RIDE_HAILING")

            if is_unlinked or is_transient:
                entry_time = item.inside_since
                if entry_time:
                    duration = now - entry_time
                    if duration >= timedelta(hours=threshold_hours):
                        hours_inside = duration.total_seconds() / 3600.0
                        plate_str = item.normalized_plate or item.subject
                        gate_id = None
                        if item.last_movement:
                            gate_obj = getattr(item.last_movement, "gate", None)
                            if gate_obj and hasattr(gate_obj, "id"):
                                gate_id = gate_obj.id
                            elif hasattr(item.last_movement, "gate_id"):
                                gate_id = getattr(item.last_movement, "gate_id")
                        
                        v_kind = "Delivery vehicle" if category == "DELIVERY" else ("Visitor car" if category == "VISITOR" else "Unlinked car")
                        alerts.append(AlertItem(
                            kind="OVERSTAY_UNLINKED",
                            severity="HIGH",
                            title=f"{v_kind} {plate_str} overstay ({hours_inside:.1f}h inside campus)",
                            detail=(
                                f"Entered via {gate_id or 'gate'} at {entry_time.strftime('%I:%M %p')}. "
                                f"Vehicle is not linked to any student or resident and has exceeded the {threshold_hours:.1f}h allowed stay window."
                            ),
                            ref=plate_str,
                            gate_id=gate_id,
                            at=entry_time,
                        ))
        return alerts

    def alerts(self, db: Session, limit: int = 50, since: Optional[datetime] = None) -> List[AlertItem]:
        since = since or datetime.now(timezone.utc) - timedelta(hours=ALERTS_LOOKBACK_HOURS)
        items = self.unlinked_overstay_alerts(db) + self.plate_alerts(db, since) + self.delivery_alerts(db)
        severity = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        items.sort(key=lambda a: (severity[a.severity], -a.at.timestamp()))
        return items[:limit]

alert_service = AlertService()
