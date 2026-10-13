from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.enums import PresenceStatus
from backend.app.schemas.movement import InsideResponse, PresencePage
from backend.app.services.movement_service import movement_service

router = APIRouter(prefix="/presence", tags=["Presence"])

@router.get("", response_model=PresencePage)
def get_presence(
    status: Optional[PresenceStatus] = Query(None),
    linked: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, max_length=100, description="Plate fragment or owner name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Derived on read from the latest effective movement per vehicle: INSIDE (last ENTRY),
    OUTSIDE (last EXIT) or UNKNOWN (registered, no movement). Unlinked plates are included.
    Flags (EXIT_WITHOUT_ENTRY, ENTRY_WHILE_INSIDE, LONG_STAY) are neutral context only.
    """
    return movement_service.presence(db, status, linked, q, skip, limit)

@router.get("/inside", response_model=InsideResponse)
def get_inside(
    linked: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Vehicles whose latest effective movement is an entry, linked and unlinked, plus recent entries without a plate."""
    return movement_service.inside(db, linked)
