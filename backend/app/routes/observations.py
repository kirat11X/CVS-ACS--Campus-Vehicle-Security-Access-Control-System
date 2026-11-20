from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from backend.app.db import SessionLocal
from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.enums import ObservationSource
from backend.app.models.observation import ObservationEvent
from backend.app.models.gate import EntryExitLog
from backend.app.schemas.observation import ObservationCreate, ObservationResponse, ObservationPlateUpdate
from backend.app.schemas.feed import ManualObservationCreate, ResolvedObservation
from backend.app.services.observation_service import ObservationService
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.services.movement_service import movement_service
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.services.anpr.rl_dataset_logger import log_human_plate_correction

router = APIRouter(prefix="/observations", tags=["Observations"])


@router.post("", response_model=ObservationResponse, status_code=status.HTTP_201_CREATED)
def record_observation(payload: ObservationCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Ingest a vehicle observation from a camera/sensor (ADMIN only; Frigate itself arrives over MQTT).
    Idempotent: updates existing record if same source and source_event_id is received.
    Guard-entered sightings must use POST /observations/manual so they carry created_by.
    """
    if payload.source == ObservationSource.MANUAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MANUAL observations must be recorded via POST /observations/manual."
        )
    try:
        obs = ObservationService.create_or_update_observation(db, payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    return ObservationResponse.from_orm_model(obs)

@router.post("/manual", response_model=ResolvedObservation, status_code=status.HTTP_201_CREATED)
def record_manual_observation(
    payload: ManualObservationCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    Logs a guard's manual sighting (source=MANUAL, created_by=current user,
    direction as chosen by the guard). Always a new row; camera observations are
    never edited. Returns the observation with its registry linkage.
    """
    try:
        obs = ObservationService.create_manual_observation(db, payload, created_by_id=user.id)
    except ValueError as e:
        detail = str(e)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)
    return identity_resolution_service.resolve(db, obs)

@router.get("", response_model=List[ObservationResponse])
def list_observations(
    gate_id: Optional[str] = Query(None, description="Filter by gate ID"),
    plate: Optional[str] = Query(None, description="Filter by license plate (raw or normalized)"),
    source: Optional[ObservationSource] = Query(None, description="Filter by sensor source"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff)
):
    """
    List historical observations with optional filtering.
    """
    norm_plate = normalize_plate(plate) if plate else None
    observations = ObservationService.list_observations(
        db,
        gate_id=gate_id,
        normalized_plate=norm_plate,
        source=source,
        skip=skip,
        limit=limit
    )
    return [ObservationResponse.from_orm_model(obs) for obs in observations]

@router.get("/{id}", response_model=ObservationResponse)
def get_observation(id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """
    Retrieve single observation by its unique identifier.
    """
    obs = ObservationService.get_observation_by_id(db, id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation with ID '{id}' not found."
        )
    return ObservationResponse.from_orm_model(obs)


@router.patch("/{id}/plate", response_model=ResolvedObservation)
def update_observation_plate(
    id: UUID,
    payload: ObservationPlateUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Directly edit/correct an observed license plate in the feed & large window.
    Immediately re-resolves registry linkage, corrects associated movements,
    and logs ground-truth labels for offline Reinforcement Learning.
    """
    obs = db.get(ObservationEvent, id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation with ID '{id}' not found.",
        )

    clean_raw = payload.plate.strip().upper()
    clean_norm = normalize_plate(clean_raw) or clean_raw
    old_plate = obs.normalized_plate or obs.raw_plate or ""

    obs.raw_plate = clean_raw
    obs.normalized_plate = clean_norm
    obs.plate_confidence = 1.0  # human verified

    curr_meta = dict(obs.metadata_payload or {})
    curr_meta["manual_plate_edit"] = {
        "original_plate": old_plate,
        "corrected_plate": clean_norm,
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "edited_by_id": str(user.id),
        "note": payload.note,
    }
    obs.metadata_payload = curr_meta

    # Correct associated entry/exit movement log if one exists
    try:
        log_entry = (
            db.query(EntryExitLog)
            .filter(EntryExitLog.observation_id == obs.id)
            .first()
        )
        if log_entry:
            movement_service.correct(
                db,
                log_id=log_entry.id,
                direction=None,
                plate=clean_norm,
                note=f"Manual plate edit by {user.full_name}: {payload.note or 'Plate corrected'}",
                user_id=user.id,
            )
    except Exception as mov_err:
        # Don't fail plate edit if movement correction hits minor constraint
        pass

    # Log to permanent RL dataset storage
    log_human_plate_correction(
        observation_id=str(obs.id),
        original_plate=old_plate,
        corrected_plate=clean_norm,
        guard_user_id=str(user.id),
        note=payload.note,
    )

    db.commit()
    db.refresh(obs)

    # Re-run identity resolution and return updated card
    return identity_resolution_service.resolve(db, obs)
