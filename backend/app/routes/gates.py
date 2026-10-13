from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from backend.app.db import SessionLocal
from backend.app.dependencies import CurrentUser, require_admin, require_staff
from backend.app.models.gate import Gate
from backend.app.models.enums import GateStatus
from backend.app.schemas.gate import GateCreate, GateUpdate, GateResponse
from backend.app.schemas.observation import ObservationResponse
from backend.app.services.observation_service import ObservationService

router = APIRouter(prefix="/gates", tags=["Gates"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_model=List[GateResponse])
def list_gates(
    status: Optional[GateStatus] = Query(None, description="Filter gates by operational status"),
    db: Session = Depends(get_db)
):
    """
    Retrieve all configured campus gates, with optional status filtering.
    """
    query = db.query(Gate)
    if status:
        query = query.filter(Gate.status == status)
    return query.order_by(Gate.id.asc()).all()

@router.get("/{gate_id}", response_model=GateResponse)
def get_gate(gate_id: str, db: Session = Depends(get_db)):
    """
    Retrieve gate configuration and operational metadata by ID.
    """
    gate = db.query(Gate).filter_by(id=gate_id).first()
    if not gate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate with ID '{gate_id}' not found."
        )
    return gate

@router.post("", response_model=GateResponse, status_code=status.HTTP_201_CREATED)
def create_gate(payload: GateCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Register a new campus access gate (ADMIN only).
    """
    existing = db.query(Gate).filter_by(id=payload.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Gate with ID '{payload.id}' already exists."
        )

    gate = Gate(
        id=payload.id,
        name=payload.name,
        location=payload.location,
        status=payload.status,
        camera_id=payload.camera_id,
        direction_capability=payload.direction_capability
    )
    db.add(gate)
    db.commit()
    db.refresh(gate)
    return gate

@router.put("/{gate_id}", response_model=GateResponse)
def update_gate(gate_id: str, payload: GateUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Update gate operational status, camera mapping, or description (ADMIN only).
    """
    gate = db.query(Gate).filter_by(id=gate_id).first()
    if not gate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate with ID '{gate_id}' not found."
        )

    if payload.name is not None:
        gate.name = payload.name
    if payload.location is not None:
        gate.location = payload.location
    if payload.status is not None:
        gate.status = payload.status
    if payload.camera_id is not None:
        gate.camera_id = payload.camera_id
    if payload.direction_capability is not None:
        gate.direction_capability = payload.direction_capability

    db.commit()
    db.refresh(gate)
    return gate

@router.delete("/{gate_id}")
def deactivate_gate(gate_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Safe soft-deactivation of a gate (ADMIN only).
    Physical records are never deleted to preserve historical observation and entry logs.
    """
    gate = db.query(Gate).filter_by(id=gate_id).first()
    if not gate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gate with ID '{gate_id}' not found."
        )

    gate.status = GateStatus.INACTIVE
    db.commit()
    return {"message": f"Gate '{gate_id}' soft-deactivated successfully (status=INACTIVE)."}

@router.get("/{gate_id}/observations", response_model=List[ObservationResponse])
def get_gate_observations(
    gate_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Retrieve sensory observation events captured at this specific gate.
    """
    try:
        observations = ObservationService.get_gate_observations(db, gate_id=gate_id, skip=skip, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return [ObservationResponse.from_orm_model(obs) for obs in observations]
