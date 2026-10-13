import uuid
from datetime import timedelta, timezone
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.config import GUARD_REGISTRATION_MAX_VALIDITY_HOURS
from backend.app.dependencies import CurrentUser
from backend.app.models.base import utc_now
from backend.app.models.enums import VehicleCategory, VehicleStatus, UserRole
from backend.app.models.identity import VehicleOwner
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.vehicle import VehicleCreate
from backend.app.services.feed_events import record_registry_update
from backend.app.services.plate_normalizer import normalize_plate

def resolve_owner(owner_id_str: str, db: Session) -> Optional[VehicleOwner]:
    if not owner_id_str:
        return None
    # Try by UUID first
    try:
        val_uuid = uuid.UUID(owner_id_str)
        owner = db.query(VehicleOwner).filter(VehicleOwner.id == val_uuid).first()
        if owner:
            return owner
    except ValueError:
        pass
    # Fallback to institutional identifier (e.g. STUDENT-2026-123)
    return db.query(VehicleOwner).filter(VehicleOwner.identifier == owner_id_str).first()

# Categories a GUARD / SUPERVISOR may register, and only with a bounded validity window.
# Every other category (STUDENT, FACULTY, STAFF, RESIDENT, ...) is a permanent
# institutional registration and requires ADMIN.
TEMPORARY_CATEGORIES = {VehicleCategory.VISITOR, VehicleCategory.DELIVERY}

def _as_utc(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

def enforce_registration_policy(payload: VehicleCreate, user: CurrentUser) -> Tuple:
    """Returns the (valid_from, valid_until) to store, or raises 403/400."""
    valid_from, valid_until = _as_utc(payload.valid_from), _as_utc(payload.valid_until)
    if user.role == UserRole.ADMIN:
        return valid_from, valid_until

    if payload.vehicle_category not in TEMPORARY_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Registering {payload.vehicle_category.value} vehicles requires the ADMIN role. "
                f"{user.role.value} users may register VISITOR or DELIVERY vehicles with a validity window."
            )
        )
    if valid_until is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{payload.vehicle_category.value} registrations by {user.role.value} require valid_until (a validity window)."
        )
    now = utc_now()
    valid_from = valid_from or now
    if valid_until <= valid_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="valid_until must be after valid_from.")
    if valid_until <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="valid_until must be in the future.")
    if valid_until - valid_from > timedelta(hours=GUARD_REGISTRATION_MAX_VALIDITY_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validity window may not exceed {GUARD_REGISTRATION_MAX_VALIDITY_HOURS} hours for {user.role.value} registrations."
        )
    return valid_from, valid_until

def create_vehicle(db: Session, payload: VehicleCreate, user: CurrentUser, owner_uuid: Optional[uuid.UUID] = None) -> Vehicle:
    """
    Shared by POST /vehicles and POST /vehicles/{plate}/link: applies the role
    policy, rejects duplicate plates (409), resolves payload.owner_id (404) unless
    owner_uuid is given, adds the vehicle and queues feed re-emission. Flushes; the
    caller commits.
    """
    valid_from, valid_until = enforce_registration_policy(payload, user)
    norm_plate = normalize_plate(payload.plate)
    if not norm_plate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid license plate number."
        )

    # Check unique constraint on normalized plate
    existing = db.query(Vehicle).filter(Vehicle.normalized_plate == norm_plate).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vehicle with plate '{payload.plate}' (normalized: '{norm_plate}') is already registered."
        )

    # Resolve owner if provided
    if owner_uuid is None and payload.owner_id:
        owner = resolve_owner(payload.owner_id, db)
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle owner not found with identifier '{payload.owner_id}'."
            )
        owner_uuid = owner.id

    vehicle = Vehicle(
        raw_plate=payload.plate,
        normalized_plate=norm_plate,
        vehicle_category=payload.vehicle_category,
        status=VehicleStatus.ACTIVE,
        owner_id=owner_uuid,
        make_model=payload.make_model,
        color=payload.color,
        valid_from=valid_from,
        valid_until=valid_until,
        notes=payload.notes,
        created_by_id=user.id
    )
    db.add(vehicle)
    record_registry_update(db, norm_plate)
    db.flush()
    return vehicle
