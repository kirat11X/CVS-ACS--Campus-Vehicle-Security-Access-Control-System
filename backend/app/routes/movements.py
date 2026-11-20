from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.schemas.movement import MovementConfirm, MovementCorrection, MovementDetail, MovementPage
from backend.app.services.movement_service import MovementError, movement_service
from backend.app.services.visitor_service import check_and_trigger_visitor_overstay_alerts, get_active_campus_visitors

router = APIRouter(prefix="/logs", tags=["Movement Log"])

def _http(e: MovementError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.detail)

@router.get("", response_model=MovementPage)
def list_logs(
    plate: Optional[str] = Query(None, description="Plate as read, corrected, or of the linked vehicle"),
    gate_id: Optional[str] = Query(None),
    direction: Optional[Literal["ENTRY", "EXIT"]] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    linked: Optional[bool] = Query(None, description="true: attributed to a registered vehicle; false: unlinked"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Movement log across all gates (effective view: latest correction applied, newest first)."""
    return movement_service.logs(db, plate, gate_id, direction, date_from, date_to, linked, skip, limit)

@router.post("/confirm", response_model=MovementDetail, status_code=status.HTTP_201_CREATED)
def confirm_direction(payload: MovementConfirm, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """
    A guard confirms Entry/Exit for an observation whose direction is unknown. Creates a
    GUARD_CONFIRMED movement referencing the observation; the observation row is unchanged.
    """
    try:
        movement = movement_service.confirm_direction(db, payload.observation_id, payload.direction, payload.note, user.id)
    except MovementError as e:
        raise _http(e)
    return movement_service.detail(db, movement.id)

@router.get("/{log_id}", response_model=MovementDetail)
def get_log(log_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """A movement with every stored row (original first, then corrections)."""
    try:
        return movement_service.detail(db, log_id)
    except MovementError as e:
        raise _http(e)

@router.post("/{log_id}/corrections", response_model=MovementDetail, status_code=status.HTTP_201_CREATED)
def correct_log(log_id: UUID, payload: MovementCorrection, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """Records a correction (direction and/or guard-supplied plate) as a new row; the original stays."""
    try:
        movement = movement_service.correct(db, log_id, payload.direction, payload.plate, payload.note, user.id)
    except MovementError as e:
        raise _http(e)
    return movement_service.detail(db, movement.id)


@router.get("/visitors/active")
def get_active_visitors(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Returns current active visitors on campus and evaluates overstay status.
    Generates high-priority SecurityAlerts when a visitor overstays their allotted hours.
    """
    check_and_trigger_visitor_overstay_alerts(db)
    return get_active_campus_visitors(db)
