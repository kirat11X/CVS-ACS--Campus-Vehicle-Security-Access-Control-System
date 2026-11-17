from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session, selectinload

from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.enums import PersonType, ResidenceType
from backend.app.models.identity import VehicleOwner, Visitor
from backend.app.models.movement import VehicleLinkEvent
from backend.app.models.delivery import DeliveryOrder
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.owner import OwnerCreate, OwnerDetailResponse, OwnerUpdate
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.feed_events import record_registry_update
from backend.app.services.vehicle_identity_service import vehicle_identity_service
from backend.app.services.vehicle_registration_service import resolve_owner

router = APIRouter(prefix="/owners", tags=["Owners"])

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def _owner_or_404(owner_id: str, db: Session) -> VehicleOwner:
    owner = resolve_owner(owner_id, db)
    if not owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Owner '{owner_id}' not found.")
    return owner

@router.get("", response_model=List[OwnerContextResponse])
def search_owners(
    q: Optional[str] = Query(None, min_length=1, max_length=100, description="Name, institutional ID, email or phone fragment"),
    person_type: Optional[PersonType] = Query(None),
    residence_type: Optional[ResidenceType] = Query(None),
    department: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Searches registered vehicle owners (for linking a registration, or browsing the directory)."""
    query = db.query(VehicleOwner).options(selectinload(VehicleOwner.vehicles))
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.filter(or_(
            VehicleOwner.full_name.ilike(pattern, escape="\\"),
            VehicleOwner.identifier.ilike(pattern, escape="\\"),
            VehicleOwner.email.ilike(pattern, escape="\\"),
            VehicleOwner.phone.ilike(pattern, escape="\\"),
            VehicleOwner.residence.ilike(pattern, escape="\\"),
            VehicleOwner.department.ilike(pattern, escape="\\"),
        ))
    if person_type:
        query = query.filter(VehicleOwner.person_type == person_type)
    if residence_type:
        query = query.filter(VehicleOwner.residence_type == residence_type)
    if department:
        query = query.filter(VehicleOwner.department.ilike(f"%{_escape_like(department.strip())}%", escape="\\"))
    owners = query.order_by(VehicleOwner.full_name.asc(), VehicleOwner.identifier.asc()).offset(skip).limit(limit).all()
    return [vehicle_identity_service.build_owner_context(o) for o in owners]

@router.post("", response_model=OwnerContextResponse, status_code=status.HTTP_201_CREATED)
def create_owner(
    payload: OwnerCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Creates an institutional vehicle owner (ADMIN only). Residence context is
    stored on the person, never on a vehicle.
    """
    identifier = payload.identifier.strip()
    if db.query(VehicleOwner).filter(VehicleOwner.identifier == identifier).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Owner with identifier '{identifier}' already exists.",
        )
    owner = VehicleOwner(
        identifier=identifier,
        full_name=payload.full_name.strip(),
        email=payload.email,
        phone=payload.phone,
        person_type=payload.person_type,
        residence_type=payload.residence_type,
        residence=payload.residence,
        department=payload.department,
        status="ACTIVE",
        created_by_id=user.id,
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return vehicle_identity_service.build_owner_context(owner)

@router.get("/{owner_id}", response_model=OwnerDetailResponse)
def get_owner(owner_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """An owner (by UUID or institutional ID) with every vehicle registered to them."""
    owner = _owner_or_404(owner_id, db)
    vehicles = (
        db.query(Vehicle).options(selectinload(Vehicle.owner), selectinload(Vehicle.visitor))
        .filter(Vehicle.owner_id == owner.id)
        .order_by(Vehicle.created_at.desc())
        .all()
    )
    return OwnerDetailResponse(
        owner=vehicle_identity_service.build_owner_context(owner),
        vehicles=[vehicle_identity_service.build_context(v) for v in vehicles],
    )

@router.put("/{owner_id}", response_model=OwnerDetailResponse)
def update_owner(owner_id: str, payload: OwnerUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Updates an owner's details (ADMIN only). The institutional identifier cannot change.
    Residence belongs to the person, so one edit applies to all of their vehicles; their recent
    observations are re-emitted on the live feed. Omitted fields are kept; null clears an optional field.
    """
    owner = _owner_or_404(owner_id, db)
    changes = payload.model_dump(exclude_unset=True)
    for required in ("full_name", "person_type", "residence_type"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{required} cannot be cleared.")
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip() or None
            if field == "full_name" and value is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name cannot be blank.")
        setattr(owner, field, value)
    for vehicle in owner.vehicles:
        record_registry_update(db, vehicle.normalized_plate)
    db.commit()
    return get_owner(str(owner.id), db, user)

@router.delete("/{owner_id}", status_code=status.HTTP_200_OK)
def delete_owner(
    owner_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Deletes an institutional owner from PostgreSQL (ADMIN only).
    Safely dissociates linked orders/visitors, removes vehicle links, and purges the owner record.
    """
    owner = _owner_or_404(owner_id, db)
    owner_id_val = owner.id
    owner_name = owner.full_name
    owner_ident = owner.identifier

    # Use replica session role locally to bypass append-only triggers during administrative deletion
    db.execute(text("SET LOCAL session_replication_role = 'replica';"))

    # 1. Clean up or dissociate references
    db.query(VehicleLinkEvent).filter(VehicleLinkEvent.owner_id == owner_id_val).delete(synchronize_session=False)
    db.query(DeliveryOrder).filter(DeliveryOrder.customer_id == owner_id_val).update({"customer_id": None}, synchronize_session=False)
    db.query(Visitor).filter(Visitor.host_owner_id == owner_id_val).update({"host_owner_id": None}, synchronize_session=False)

    # 2. De-link vehicles
    for vehicle in owner.vehicles:
        vehicle.owner_id = None
        record_registry_update(db, vehicle.normalized_plate)

    # 3. Delete owner record
    db.delete(owner)
    db.commit()

    return {
        "status": "success",
        "message": f"Owner '{owner_name}' ({owner_ident}) deleted successfully from PostgreSQL.",
        "deleted_id": str(owner_id_val),
    }
