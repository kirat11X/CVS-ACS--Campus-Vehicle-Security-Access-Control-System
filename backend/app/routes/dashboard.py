import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.enums import ObservationSource, VehicleCategory, VehicleStatus
from backend.app.models.identity import VehicleOwner
from backend.app.models.observation import ObservationEvent, ObservationResolution
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.dashboard import (
    ActivityBucket,
    DashboardSummary,
    MovementCounts,
    ObservationCounts,
    PresenceCounts,
    RegistryCounts,
)
from backend.app.services.alert_service import alert_service
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.services.movement_service import movement_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

MAX_WINDOW = timedelta(days=7)

def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

@router.get("/summary", response_model=DashboardSummary)
def get_summary(
    since: Optional[datetime] = Query(None, description="Start of the window, e.g. local midnight (default: 24 h ago, at most 7 days)"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Counts for the console overview: observations and movements in the window, current presence
    and registry totals. Movements use the effective view of the movement log, so these numbers
    match /logs and /presence/inside. Context for guards only; no access decision is made here.
    """
    now = datetime.now(timezone.utc)
    start = _as_utc(since) if since else now - timedelta(hours=24)
    start = min(max(start, now - MAX_WINDOW), now)

    # Hourly buckets for windows up to 48 h, daily beyond. Buckets start at `since`, so a client
    # that passes its local midnight gets local-hour boundaries whatever the server time zone.
    bucket = timedelta(hours=1) if now - start <= timedelta(hours=48) else timedelta(days=1)
    buckets = [ActivityBucket(start=start + i * bucket) for i in range(max(1, math.ceil((now - start) / bucket)))]

    def bucket_of(t: datetime) -> Optional[ActivityBucket]:
        i = int((t - start) / bucket)
        return buckets[i] if 0 <= i < len(buckets) else None

    in_window = ObservationEvent.observed_at >= start
    observed = db.query(ObservationEvent.observed_at, ObservationEvent.source, ObservationEvent.normalized_plate).filter(in_window).all()
    for observed_at, _, _ in observed:
        b = bucket_of(observed_at)
        if b:
            b.observations += 1

    # Same rule as IdentityResolutionService.is_low_confidence, minus reads a guard has already resolved.
    low_confidence_unresolved = db.query(func.count(ObservationEvent.id)).filter(
        in_window,
        ObservationEvent.source != ObservationSource.MANUAL,
        ObservationEvent.normalized_plate.isnot(None),
        ObservationEvent.normalized_plate != "",
        or_(
            ObservationEvent.plate_confidence.is_(None),
            ObservationEvent.plate_confidence < identity_resolution_service.confidence_threshold,
        ),
        ~exists().where(ObservationResolution.observation_id == ObservationEvent.id),
    ).scalar()

    activity = movement_service.activity_summary(db, start)
    for timestamp, direction in activity["movement_times"]:
        b = bucket_of(timestamp)
        if b:
            if direction == "ENTRY":
                b.entries += 1
            else:
                b.exits += 1

    by_status = {s.value: n for s, n in db.query(Vehicle.status, func.count(Vehicle.id)).group_by(Vehicle.status).all()}
    by_category = {
        c.value: n for c, n in db.query(Vehicle.vehicle_category, func.count(Vehicle.id)).group_by(Vehicle.vehicle_category).all()
    }
    temporary_active = db.query(func.count(Vehicle.id)).filter(
        Vehicle.vehicle_category.in_([VehicleCategory.VISITOR, VehicleCategory.DELIVERY]),
        Vehicle.status == VehicleStatus.ACTIVE,
        or_(Vehicle.valid_from.is_(None), Vehicle.valid_from <= now),
        or_(Vehicle.valid_until.is_(None), Vehicle.valid_until > now),
    ).scalar()

    unlinked_plates, plates_to_review = alert_service.plate_counts(db, start)

    return DashboardSummary(
        delivery_flags=delivery_screening_service.pending_flag_count(db),
        unlinked_plates=unlinked_plates,
        plates_to_review=plates_to_review,
        since=start,
        generated_at=now,
        bucket_minutes=int(bucket.total_seconds() // 60),
        observations=ObservationCounts(
            total=len(observed),
            camera=sum(1 for _, source, _ in observed if source == ObservationSource.FRIGATE),
            manual=sum(1 for _, source, _ in observed if source == ObservationSource.MANUAL),
            without_plate=sum(1 for _, _, plate in observed if not plate),
            low_confidence_unresolved=low_confidence_unresolved,
        ),
        movements=MovementCounts(entries=activity["entries"], exits=activity["exits"]),
        presence=PresenceCounts(
            inside=activity["inside"],
            inside_linked=activity["inside_linked"],
            inside_unlinked=activity["inside"] - activity["inside_linked"],
            long_stay=activity["long_stay"],
            unattributed_entries=activity["unattributed_entries"],
        ),
        registry=RegistryCounts(
            vehicles=sum(by_status.values()),
            vehicles_by_status=by_status,
            vehicles_by_category=by_category,
            temporary_active=temporary_active,
            owners=db.query(func.count(VehicleOwner.id)).scalar(),
        ),
        activity=buckets,
    )
