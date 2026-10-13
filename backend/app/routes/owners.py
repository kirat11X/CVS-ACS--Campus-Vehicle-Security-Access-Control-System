from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.identity import VehicleOwner
from backend.app.schemas.owner import OwnerCreate
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.vehicle_identity_service import vehicle_identity_service

router = APIRouter(prefix="/owners", tags=["Owners"])

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

@router.get("", response_model=List[OwnerContextResponse])
def search_owners(
    q: str = Query(..., min_length=2, max_length=100, description="Name, institutional ID, email or phone fragment"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Searches registered vehicle owners for linking a vehicle registration."""
    pattern = f"%{_escape_like(q.strip())}%"
    owners = (
        db.query(VehicleOwner)
        .filter(or_(
            VehicleOwner.full_name.ilike(pattern, escape="\\"),
            VehicleOwner.identifier.ilike(pattern, escape="\\"),
            VehicleOwner.email.ilike(pattern, escape="\\"),
            VehicleOwner.phone.ilike(pattern, escape="\\"),
        ))
        .order_by(VehicleOwner.full_name.asc())
        .limit(limit)
        .all()
    )
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
