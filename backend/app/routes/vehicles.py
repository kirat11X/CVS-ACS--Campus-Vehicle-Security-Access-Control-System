from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.db import SessionLocal
from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.vehicle import Vehicle
from backend.app.models.identity import VehicleOwner
from backend.app.models.enums import VehicleCategory, VehicleStatus, ResidenceType
from backend.app.services.feed_events import record_registry_update
from backend.app.services.vehicle_registration_service import create_vehicle, resolve_owner
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.services.vehicle_identity_service import vehicle_identity_service
from backend.app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleDetailResponse
)
from backend.app.schemas.observation import ObservationResponse
from backend.app.schemas.movement import VehicleHistory, VehicleLinkRequest, VehicleLinkResponse
from backend.app.services.observation_service import ObservationService
from backend.app.services.movement_service import MovementError, movement_service
from backend.app.services.vehicle_link_service import link_vehicle

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.post("", response_model=VehicleDetailResponse, status_code=status.HTTP_201_CREATED)
def register_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Registers a new vehicle and associates it with an institutional identity.
    Automatically normalizes the plate (e.g. 'PB65 AB 1234' -> 'PB65AB1234').
    STUDENT/FACULTY/STAFF (and other permanent) registrations require ADMIN;
    GUARD/SUPERVISOR may register VISITOR/DELIVERY vehicles with a validity window.
    """
    vehicle = create_vehicle(db, payload, user)
    db.commit()
    norm_plate = vehicle.normalized_plate

    resolved = vehicle_identity_service.resolve(norm_plate, db)
    return resolved

@router.get("/{plate}", response_model=VehicleDetailResponse)
def get_vehicle_by_plate(plate: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """
    Retrieves vehicle record and its authoritative identity and residence context.
    Executes PLATE -> VEHICLE -> PERSON -> RESIDENCE CONTEXT lookup.
    """
    norm_plate = normalize_plate(plate)
    resolved = vehicle_identity_service.resolve(norm_plate, db)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with plate '{plate}' (normalized: '{norm_plate}') not found in campus registry."
        )
    return resolved

@router.get("", response_model=List[VehicleDetailResponse])
def list_vehicles(
    category: Optional[VehicleCategory] = Query(None, description="Filter by vehicle category"),
    status_filter: Optional[VehicleStatus] = Query(None, alias="status", description="Filter by vehicle status"),
    owner_id: Optional[str] = Query(None, description="Filter by owner UUID or institutional ID"),
    plate: Optional[str] = Query(None, description="Filter by plate (raw or normalized)"),
    q: Optional[str] = Query(None, max_length=30, description="Plate fragment, format-tolerant (e.g. 'pb 65')"),
    residence_type: Optional[ResidenceType] = Query(None, description="Filter by owner residence type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Lists registered vehicles (newest first) with optional filters for category, status, owner,
    exact plate, plate fragment, or residence type.
    """
    query = db.query(Vehicle)

    if category:
        query = query.filter(Vehicle.vehicle_category == category)
    if status_filter:
        query = query.filter(Vehicle.status == status_filter)
    if plate:
        query = query.filter(Vehicle.normalized_plate == normalize_plate(plate))
    if q and normalize_plate(q):
        # normalize_plate keeps only [A-Z0-9], so the fragment carries no LIKE wildcards
        query = query.filter(Vehicle.normalized_plate.contains(normalize_plate(q)))
    if owner_id:
        owner = resolve_owner(owner_id, db)
        if owner:
            query = query.filter(Vehicle.owner_id == owner.id)
        else:
            return []
    if residence_type:
        query = query.join(VehicleOwner, Vehicle.owner_id == VehicleOwner.id).filter(
            VehicleOwner.residence_type == residence_type
        )

    vehicles = query.order_by(Vehicle.created_at.desc(), Vehicle.id.asc()).offset(skip).limit(limit).all()
    return [vehicle_identity_service.build_context(v) for v in vehicles]

@router.put("/{plate}", response_model=VehicleDetailResponse)
def update_vehicle(
    plate: str,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin)
):
    """
    Updates vehicle information (ADMIN only). Rejects any attempt to mutate the license plate itself.
    """
    norm_plate = normalize_plate(plate)
    vehicle = db.query(Vehicle).filter(Vehicle.normalized_plate == norm_plate).first()
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with plate '{plate}' (normalized: '{norm_plate}') not found."
        )

    # Inviolable rule: License plate cannot be silently mutated
    if payload.plate:
        new_norm = normalize_plate(payload.plate)
        if new_norm != vehicle.normalized_plate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="License plate cannot be mutated. To update a plate, deactivate the old vehicle registration and register a new vehicle record."
            )

    if payload.owner_id is not None:
        owner = resolve_owner(payload.owner_id, db)
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle owner not found with identifier '{payload.owner_id}'."
            )
        vehicle.owner_id = owner.id

    if payload.vehicle_category is not None:
        vehicle.vehicle_category = payload.vehicle_category
    if payload.status is not None:
        vehicle.status = payload.status
    if payload.make_model is not None:
        vehicle.make_model = payload.make_model
    if payload.color is not None:
        vehicle.color = payload.color
    if payload.valid_from is not None:
        vehicle.valid_from = payload.valid_from
    if payload.valid_until is not None:
        vehicle.valid_until = payload.valid_until
    if payload.notes is not None:
        vehicle.notes = payload.notes

    record_registry_update(db, vehicle.normalized_plate)
    db.commit()
    db.refresh(vehicle)

    resolved = vehicle_identity_service.resolve(vehicle.normalized_plate, db)
    return resolved

@router.delete("/{plate}")
def deactivate_vehicle(
    plate: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin)
):
    """
    Soft-deactivates a vehicle registration (status = INACTIVE). ADMIN only.
    Preserves historical logs, crossing audits, and database foreign keys.
    """
    norm_plate = normalize_plate(plate)
    vehicle = db.query(Vehicle).filter(Vehicle.normalized_plate == norm_plate).first()
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle with plate '{plate}' (normalized: '{norm_plate}') not found."
        )

    vehicle.status = VehicleStatus.INACTIVE
    record_registry_update(db, vehicle.normalized_plate)
    db.commit()

    return {
        "status": "success",
        "message": f"Vehicle '{vehicle.normalized_plate}' soft-deactivated successfully.",
        "vehicle_status": vehicle.status.value
    }

@router.get("/{plate}/observations", response_model=List[ObservationResponse])
def get_vehicle_observations(
    plate: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Retrieve all sensory observation events captured for a specific license plate (format-tolerant).
    """
    observations = ObservationService.get_plate_observations(db, plate=plate, skip=skip, limit=limit)
    return [ObservationResponse.from_orm_model(obs) for obs in observations]

@router.post("/{plate}/link", response_model=VehicleLinkResponse, status_code=status.HTTP_201_CREATED)
def link_vehicle_to_owner(
    plate: Annotated[str, Path(max_length=30)],
    payload: VehicleLinkRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Registers an unknown plate and links it to an existing or new owner, with an
    append-only link event (a human assertion, not proof of identity). Same role
    policy as POST /vehicles: permanent categories need ADMIN; GUARD/SUPERVISOR may
    create VISITOR/DELIVERY links with an expiry. 409 if the plate is registered.
    Past movements and sightings resolve to the owner on read; none are rewritten.
    """
    return link_vehicle(db, plate, payload, user)

@router.get("/{plate}/history", response_model=VehicleHistory)
def get_vehicle_history(
    plate: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """One timeline across all gates: movements (effective view, flagged) and unlogged sightings."""
    try:
        return movement_service.history(db, plate)
    except MovementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
