from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.enums import LaneRole
from backend.app.models.gate import Gate
from backend.app.models.movement import CameraLane
from backend.app.schemas.movement import LaneResponse, LaneUpsert

router = APIRouter(prefix="/lanes", tags=["Camera Lanes"])

def _response(lane: CameraLane) -> LaneResponse:
    return LaneResponse(
        camera_id=lane.camera_id, gate_id=lane.gate_id, lane_role=lane.lane_role,
        outside_zone=lane.outside_zone, inside_zone=lane.inside_zone, is_active=lane.is_active,
        notes=lane.notes, updated_at=lane.updated_at,
    )

@router.get("", response_model=List[LaneResponse])
def list_lanes(db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """Declared camera lane roles used to derive movement direction."""
    return [_response(l) for l in db.query(CameraLane).order_by(CameraLane.gate_id, CameraLane.camera_id).all()]

@router.put("/{camera_id}", response_model=LaneResponse)
def upsert_lane(
    camera_id: str,
    payload: LaneUpsert,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Declares (ADMIN) which way traffic passes a camera. ENTRY_LANE / EXIT_LANE give a
    direction directly; BIDIRECTIONAL needs both Frigate zone names, otherwise its
    sightings stay UNKNOWN. Set is_active=false to retire a lane (no deletion).
    """
    camera_id = camera_id.strip()
    if not camera_id or len(camera_id) > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="camera_id must be 1-50 characters.")
    if not db.get(Gate, payload.gate_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Gate '{payload.gate_id}' not found.")
    other = db.query(Gate).filter(Gate.camera_id == camera_id, Gate.id != payload.gate_id).first()
    if other:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Camera '{camera_id}' is the registered camera of gate '{other.id}'.")

    zones = (payload.outside_zone, payload.inside_zone)
    if payload.lane_role == LaneRole.BIDIRECTIONAL:
        if (zones[0] is None) != (zones[1] is None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Give both outside_zone and inside_zone, or neither.")
        if zones[0] is not None and zones[0] == zones[1]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="outside_zone and inside_zone must differ.")
    elif any(zones):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Zones apply only to BIDIRECTIONAL lanes.")

    lane = db.get(CameraLane, camera_id)
    if lane is None:
        lane = CameraLane(camera_id=camera_id)
        db.add(lane)
    lane.gate_id = payload.gate_id
    lane.lane_role = payload.lane_role
    lane.outside_zone, lane.inside_zone = zones
    lane.is_active = payload.is_active
    lane.notes = payload.notes
    lane.updated_by_id = user.id
    db.commit()
    db.refresh(lane)
    return _response(lane)
