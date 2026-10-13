from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser
from backend.app.models.enums import LinkMethod, UserRole
from backend.app.models.identity import VehicleOwner
from backend.app.models.movement import VehicleLinkEvent
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.movement import RetroactiveCounts, VehicleLinkRequest, VehicleLinkResponse
from backend.app.schemas.vehicle import VehicleCreate
from backend.app.services.movement_service import link_event_response, movement_service
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.services.vehicle_identity_service import vehicle_identity_service
from backend.app.services.vehicle_registration_service import create_vehicle, enforce_registration_policy, resolve_owner

def link_vehicle(db: Session, plate: str, req: VehicleLinkRequest, user: CurrentUser) -> VehicleLinkResponse:
    """
    Registers a previously unknown plate and links it to an owner in one transaction,
    recording an append-only VehicleLinkEvent. Reuses the POST /vehicles path (role
    policy, 409 on duplicate plate). Past movements and sightings of the plate are not
    rewritten; they resolve to the owner on read through the plate join.
    """
    payload = VehicleCreate(
        plate=plate,
        vehicle_category=req.vehicle_category,
        make_model=req.make_model,
        color=req.color,
        valid_from=req.valid_from,
        valid_until=req.valid_until,
    )
    # Validate everything before creating any row
    enforce_registration_policy(payload, user)
    norm = normalize_plate(plate)
    if not norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid license plate number.")
    if db.query(Vehicle.id).filter(Vehicle.normalized_plate == norm).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vehicle with plate '{plate}' (normalized: '{norm}') is already registered.",
        )

    if req.owner_id:
        owner = resolve_owner(req.owner_id, db)
        if owner is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle owner not found with identifier '{req.owner_id}'.")
    else:
        new = req.new_owner
        identifier = new.identifier.strip()
        if db.query(VehicleOwner.id).filter(VehicleOwner.identifier == identifier).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An owner with identifier '{identifier}' already exists; link to that owner instead.",
            )
        owner = VehicleOwner(
            identifier=identifier,
            full_name=new.full_name.strip(),
            person_type=new.person_type,
            residence_type=new.residence_type,
            residence=new.residence,
            department=new.department,
            status="ACTIVE",
            created_by_id=user.id,
        )
        db.add(owner)
        db.flush()

    vehicle = create_vehicle(db, payload, user, owner_uuid=owner.id)
    event = VehicleLinkEvent(
        vehicle_id=vehicle.id,
        owner_id=owner.id,
        method=LinkMethod.ADMIN if user.role == UserRole.ADMIN else LinkMethod.GUARD_VERIFIED_ID,
        evidence_note=req.evidence_note.strip(),
        linked_by_id=user.id,
        expires_at=vehicle.valid_until,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return VehicleLinkResponse(
        vehicle=vehicle_identity_service.resolve(norm, db),
        link_event=link_event_response(event),
        retroactive=RetroactiveCounts(**movement_service.count_for_plate(db, norm)),
    )
