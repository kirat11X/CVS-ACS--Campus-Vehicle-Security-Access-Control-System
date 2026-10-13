import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from backend.app.models.gate import Gate
from backend.app.models.movement import CameraLane
from backend.app.models.enums import GateStatus, ObservationSource, ObservedVehicleType, ObservationDirection
from backend.app.schemas.observation import ObservationCreate
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.models.base import utc_now

logger = logging.getLogger("campus_security.frigate_parser")

LABEL_TO_VEHICLE_TYPE = {
    "car": ObservedVehicleType.CAR,
    "automobile": ObservedVehicleType.CAR,
    "vehicle": ObservedVehicleType.CAR,
    "motorcycle": ObservedVehicleType.MOTORCYCLE,
    "motorbike": ObservedVehicleType.MOTORCYCLE,
    "scooter": ObservedVehicleType.MOTORCYCLE,
    "bus": ObservedVehicleType.BUS,
    "truck": ObservedVehicleType.TRUCK,
    "bicycle": ObservedVehicleType.BICYCLE,
}

class FrigateEventParser:
    @staticmethod
    def resolve_camera_to_gate(camera_id: str, db: Session) -> Optional[Gate]:
        """
        Resolves a Frigate camera identifier to a registered Gate record via
        Gate.camera_id, or an active declared camera lane. If the camera is not
        mapped in the database, returns None.
        Never falls back to a default gate. A gate that is not INACTIVE wins over
        retired gates that once used the same camera.
        """
        if not camera_id:
            return None
        gate = db.query(Gate).filter(
            (Gate.camera_id == camera_id) | (Gate.id == camera_id)
        ).order_by((Gate.status == GateStatus.INACTIVE).asc(), Gate.id.asc()).first()
        if gate:
            return gate
        # Additional cameras at a gate are declared in camera_lanes (Phase 6)
        lane = db.query(CameraLane).filter(CameraLane.camera_id == camera_id, CameraLane.is_active.is_(True)).first()
        return lane.gate if lane else None

    @classmethod
    def parse_event(cls, payload: Dict[str, Any], db: Session) -> Optional[ObservationCreate]:
        """
        Translates a raw Frigate MQTT event dictionary into an ObservationCreate schema.
        Handles both full envelope events (type, before, after) and flat object updates.
        Returns None if the payload is invalid or unmapped.
        """
        if not isinstance(payload, dict):
            logger.warning(f"Rejected non-dict Frigate payload: {type(payload)}")
            return None

        # Frigate /events topic wraps tracked-object state in 'after'
        data = payload.get("after")
        if not isinstance(data, dict):
            data = payload

        # Extract event ID (source_event_id)
        source_event_id = data.get("id") or payload.get("id") or data.get("event_id")
        if not source_event_id:
            logger.warning("Frigate payload missing 'id' or 'source_event_id'. Skipping event.")
            return None

        # Extract camera identifier
        camera_id = data.get("camera") or payload.get("camera")
        if not camera_id:
            logger.warning(f"Frigate event '{source_event_id}' missing 'camera'. Skipping event.")
            return None

        # Resolve Camera -> Gate
        gate = cls.resolve_camera_to_gate(camera_id, db)
        if not gate:
            logger.warning(
                f"Unmapped camera '{camera_id}' for event '{source_event_id}'. "
                f"No matching gate registered. Quarantine/skipping observation."
            )
            return None

        # Physical vehicle type mapping
        label = str(data.get("label") or "").lower().strip()
        vehicle_type = LABEL_TO_VEHICLE_TYPE.get(label, ObservedVehicleType.UNKNOWN)

        # Vehicle detection confidence
        vehicle_confidence = None
        raw_vc = data.get("top_score") if data.get("top_score") is not None else data.get("score")
        if raw_vc is not None:
            try:
                vehicle_confidence = round(float(raw_vc), 4)
            except (ValueError, TypeError):
                vehicle_confidence = None

        # Extract License Plate (LPR) and confidence
        raw_plate = None
        plate_confidence = None

        sub_label = data.get("sub_label")
        if "recognized_license_plate" in data:
            # Frigate >= 0.16 always sends recognized_license_plate as (plate, score), or None when
            # nothing was read, and uses sub_label for a known_plates *name* or another enrichment
            # label - never the plate text - so sub_label is not read as a plate here.
            sub_label = None
            rec = data.get("recognized_license_plate")
            if isinstance(rec, (list, tuple)) and len(rec) > 0:
                raw_plate = str(rec[0]).strip() if rec[0] else None
                if len(rec) > 1 and rec[1] is not None:
                    try:
                        plate_confidence = round(float(rec[1]), 4)
                    except (ValueError, TypeError):
                        pass

        # Check sub_label (plate destination before Frigate 0.16 and for third-party LPR)
        if isinstance(sub_label, str) and sub_label.strip():
            raw_plate = sub_label.strip()
        elif isinstance(sub_label, dict):
            raw_plate = sub_label.get("text") or sub_label.get("plate")
            if sub_label.get("score") is not None:
                try:
                    plate_confidence = round(float(sub_label["score"]), 4)
                except (ValueError, TypeError):
                    pass
        elif isinstance(sub_label, (list, tuple)) and len(sub_label) > 0:
            raw_plate = str(sub_label[0]).strip() if sub_label[0] else None
            if len(sub_label) > 1 and plate_confidence is None and sub_label[1] is not None:
                try:
                    plate_confidence = round(float(sub_label[1]), 4)
                except (ValueError, TypeError):
                    pass

        # Check license_plate field
        if not raw_plate:
            lp = data.get("license_plate")
            if isinstance(lp, str) and lp.strip():
                raw_plate = lp.strip()
            elif isinstance(lp, dict):
                raw_plate = lp.get("plate") or lp.get("text")
                if plate_confidence is None and lp.get("score") is not None:
                    try:
                        plate_confidence = round(float(lp["score"]), 4)
                    except (ValueError, TypeError):
                        pass

        # Check fallback plate keys
        if not raw_plate:
            rec = data.get("recognized_license_plate") or data.get("plate")
            if isinstance(rec, str) and rec.strip():
                raw_plate = rec.strip()

        # Check plate confidence fallback keys
        if plate_confidence is None:
            raw_pc = (
                data.get("sub_label_score")
                or data.get("recognized_license_plate_score")
                or data.get("plate_confidence")
            )
            if raw_pc is not None:
                try:
                    plate_confidence = round(float(raw_pc), 4)
                except (ValueError, TypeError):
                    pass

        # A plate without an OCR score keeps plate_confidence None (LOW_CONFIDENCE downstream). The
        # detector's top_score says the object is a car, not that the characters were read correctly.

        # Clamp plate confidence between 0.0 and 1.0 if set
        if plate_confidence is not None:
            plate_confidence = max(0.0, min(1.0, plate_confidence))

        # Clamp vehicle confidence between 0.0 and 1.0 if set
        if vehicle_confidence is not None:
            vehicle_confidence = max(0.0, min(1.0, vehicle_confidence))

        # Extract timestamp
        observed_at = None
        ts = data.get("frame_time") or data.get("start_time") or data.get("timestamp")
        if ts is not None:
            try:
                if isinstance(ts, (int, float)):
                    observed_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                elif isinstance(ts, str):
                    observed_at = datetime.fromisoformat(ts)
            except Exception:
                observed_at = utc_now()
        if not observed_at:
            observed_at = utc_now()

        # Direction is strictly UNKNOWN (Section 4 mandate)
        direction = ObservationDirection.UNKNOWN

        return ObservationCreate(
            gate_id=gate.id,
            camera_id=camera_id,
            observed_at=observed_at,
            source=ObservationSource.FRIGATE,
            source_event_id=str(source_event_id),
            raw_plate=raw_plate,
            plate_confidence=plate_confidence,
            vehicle_type=vehicle_type,
            vehicle_confidence=vehicle_confidence,
            direction=direction,
            metadata_payload=payload
        )
