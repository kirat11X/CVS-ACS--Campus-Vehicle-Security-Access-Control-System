from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from sqlalchemy.orm import Session

from backend.app.models.enums import DirectionMethod, LaneRole, ObservationDirection, ObservationSource
from backend.app.models.movement import CameraLane
from backend.app.models.observation import ObservationEvent

@dataclass(frozen=True)
class DirectionResult:
    direction: ObservationDirection
    method: DirectionMethod
    confidence: Optional[float] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_known(self) -> bool:
        return self.direction in (ObservationDirection.ENTRY, ObservationDirection.EXIT)

    @property
    def is_provisional(self) -> bool:
        """Provisional until lane role (CAMERA_ROLE / ZONE_ORDER) or guard confirmation (GUARD_CONFIRMED) is established."""
        return (not self.is_known) or (self.method == DirectionMethod.NONE)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction.value,
            "method": self.method.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "is_provisional": self.is_provisional,
        }

def _unknown(reason: str, **evidence) -> DirectionResult:
    return DirectionResult(ObservationDirection.UNKNOWN, DirectionMethod.NONE, None, {"reason": reason, **evidence})

class DirectionResolver:
    """
    Phase 6: derives an observation's direction from declared configuration only.

      * MANUAL observation with ENTRY/EXIT chosen by the guard -> GUARD_CONFIRMED
      * camera declared ENTRY_LANE / EXIT_LANE                  -> CAMERA_ROLE
      * camera declared BIDIRECTIONAL with outside/inside zones,
        and Frigate entered_zones shows the order               -> ZONE_ORDER
      * anything else                                           -> UNKNOWN (method NONE)

    A declared lane role is site configuration entered by an administrator, not
    an inference. Camera and gate names are never interpreted. The observation's
    own `direction` column (what the sensor reported) is never modified.
    """

    @staticmethod
    def load_lanes(db: Session, camera_ids: Iterable[Optional[str]]) -> Dict[str, CameraLane]:
        ids = {c for c in camera_ids if c}
        if not ids:
            return {}
        lanes = db.query(CameraLane).filter(CameraLane.camera_id.in_(ids), CameraLane.is_active.is_(True)).all()
        return {lane.camera_id: lane for lane in lanes}

    @staticmethod
    def entered_zones(obs: ObservationEvent) -> List[str]:
        """Zones Frigate reports the tracked object entered, in order (latest payload wins)."""
        meta = obs.metadata_payload if isinstance(obs.metadata_payload, dict) else {}
        for payload in (meta.get("last_update"), meta):
            if not isinstance(payload, dict):
                continue
            after = payload.get("after") if isinstance(payload.get("after"), dict) else payload
            zones = after.get("entered_zones")
            if isinstance(zones, list):
                return [str(z) for z in zones]
        return []

    def resolve(self, db: Session, obs: ObservationEvent, lanes: Optional[Dict[str, CameraLane]] = None) -> DirectionResult:
        if obs.source == ObservationSource.MANUAL:
            if obs.direction in (ObservationDirection.ENTRY, ObservationDirection.EXIT):
                return DirectionResult(
                    obs.direction, DirectionMethod.GUARD_CONFIRMED, None,
                    {"reported_by_id": str(obs.created_by_id) if obs.created_by_id else None, "source": "MANUAL"},
                )
            return _unknown("GUARD_REPORTED_UNKNOWN")

        if obs.source != ObservationSource.FRIGATE:
            return _unknown("UNSUPPORTED_SOURCE", source=obs.source.value)
        if not obs.camera_id:
            return _unknown("NO_CAMERA")

        if lanes is None:
            lanes = self.load_lanes(db, [obs.camera_id])
        lane = lanes.get(obs.camera_id)
        if lane is None:
            return _unknown("NO_LANE_CONFIG", camera_id=obs.camera_id)
        if lane.gate_id != obs.gate_id:
            return _unknown("LANE_GATE_MISMATCH", camera_id=obs.camera_id, lane_gate_id=lane.gate_id, gate_id=obs.gate_id)

        base = {"camera_id": lane.camera_id, "lane_role": lane.lane_role.value}
        if lane.lane_role == LaneRole.ENTRY_LANE:
            return DirectionResult(ObservationDirection.ENTRY, DirectionMethod.CAMERA_ROLE, None, base)
        if lane.lane_role == LaneRole.EXIT_LANE:
            return DirectionResult(ObservationDirection.EXIT, DirectionMethod.CAMERA_ROLE, None, base)

        # BIDIRECTIONAL: only declared zone order can establish direction
        if not lane.outside_zone or not lane.inside_zone:
            return _unknown("BIDIRECTIONAL_WITHOUT_ZONES", **base)
        zones = self.entered_zones(obs)
        evidence = {**base, "outside_zone": lane.outside_zone, "inside_zone": lane.inside_zone, "entered_zones": zones}
        if lane.outside_zone not in zones or lane.inside_zone not in zones:
            return _unknown("INSUFFICIENT_ZONE_EVIDENCE", **evidence)
        if zones.index(lane.outside_zone) < zones.index(lane.inside_zone):
            return DirectionResult(ObservationDirection.ENTRY, DirectionMethod.ZONE_ORDER, None, evidence)
        return DirectionResult(ObservationDirection.EXIT, DirectionMethod.ZONE_ORDER, None, evidence)

direction_resolver = DirectionResolver()
