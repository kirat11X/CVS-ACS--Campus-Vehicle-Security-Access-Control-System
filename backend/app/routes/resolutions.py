from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.observation import ObservationEvent
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.feed import ResolutionCreate, ResolutionCreated
from backend.app.services.identity_resolution_service import identity_resolution_service

router = APIRouter(prefix="/resolutions", tags=["Guard Resolutions"])

@router.post("", response_model=ResolutionCreated, status_code=status.HTTP_201_CREATED)
def record_resolution(
    payload: ResolutionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Records a guard's confirmation of which registered vehicle an observation shows,
    or that none of the candidates match ("none"). Append-only: every call adds a new
    event, the latest one is shown, and the observation row is never modified.
    """
    obs = db.get(ObservationEvent, payload.observation_id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{payload.observation_id}' not found.",
        )

    chosen = None
    if payload.chosen_vehicle_id != "none":
        chosen = db.get(Vehicle, payload.chosen_vehicle_id)
        if not chosen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle '{payload.chosen_vehicle_id}' not found in registry.",
            )

    resolution = identity_resolution_service.record_resolution(db, obs, chosen, payload.note, user.id)
    return ResolutionCreated(
        resolution=identity_resolution_service.resolution_summary(resolution),
        item=identity_resolution_service.resolve(db, obs),
    )
