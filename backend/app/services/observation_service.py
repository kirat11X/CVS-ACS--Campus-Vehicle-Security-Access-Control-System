from typing import Optional, List
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.app.models.gate import Gate
from backend.app.models.observation import ObservationEvent
from backend.app.models.base import utc_now
from backend.app.models.enums import ObservationSource, ObservedVehicleType, ObservationDirection, FeedEventKind
from backend.app.schemas.observation import ObservationCreate
from backend.app.schemas.feed import ManualObservationCreate
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.services.feed_events import record_feed_event
from backend.app.services.movement_service import movement_service

# Namespace for the per-event advisory lock (two-key form, so it cannot collide with the
# single-key feed cursor lock in feed_events.py).
SOURCE_EVENT_LOCK_NAMESPACE = 5_031_603

class ObservationService:
    @staticmethod
    def create_or_update_observation(db: Session, data: ObservationCreate) -> ObservationEvent:
        """
        Ingests an observation event with idempotency and deduplication.
        If a Frigate/sensor update arrives with an existing source_event_id,
        it updates/refines the observation rather than duplicating it.
        """
        gate = db.query(Gate).filter_by(id=data.gate_id).first()
        if not gate:
            raise ValueError(f"Gate '{data.gate_id}' not found in gate registry.")

        normalized_plate = normalize_plate(data.raw_plate) if data.raw_plate else None
        camera_id = data.camera_id or gate.camera_id
        observed_at = data.observed_at or utc_now()

        # Deduplication check via source_event_id
        if data.source_event_id:
            # Serialise writers of one event (two backend processes on the broker, or the worker and
            # POST /observations) until commit; otherwise both can miss the row and both insert it.
            db.execute(
                text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"),
                {"ns": SOURCE_EVENT_LOCK_NAMESPACE, "key": f"{data.source.value}:{data.source_event_id}"},
            )
            existing = db.query(ObservationEvent).filter_by(
                source=data.source,
                source_event_id=data.source_event_id
            ).first()

            if existing:
                # Refine existing observation with higher confidence or updated plate
                if data.plate_confidence is not None and (existing.plate_confidence is None or data.plate_confidence >= existing.plate_confidence):
                    existing.plate_confidence = data.plate_confidence
                    if data.raw_plate:
                        existing.raw_plate = data.raw_plate
                        existing.normalized_plate = normalized_plate
                elif not existing.raw_plate and data.raw_plate:
                    existing.raw_plate = data.raw_plate
                    existing.normalized_plate = normalized_plate
                    existing.plate_confidence = data.plate_confidence

                if data.vehicle_type != ObservedVehicleType.UNKNOWN:
                    existing.vehicle_type = data.vehicle_type
                    if data.vehicle_confidence is not None:
                        existing.vehicle_confidence = data.vehicle_confidence

                if data.direction != ObservationDirection.UNKNOWN:
                    existing.direction = data.direction

                # Track telemetry updates in metadata
                meta = dict(existing.metadata_payload or {})
                meta["update_count"] = meta.get("update_count", 0) + 1
                if data.metadata_payload:
                    meta["last_update"] = data.metadata_payload
                existing.metadata_payload = meta

                db.flush()
                movement_service.on_observation(db, existing)
                record_feed_event(db, existing.id, FeedEventKind.OBSERVATION_UPDATED)
                db.commit()
                db.refresh(existing)
                return existing

        obs = ObservationEvent(
            gate_id=data.gate_id,
            camera_id=camera_id,
            observed_at=observed_at,
            source=data.source,
            source_event_id=data.source_event_id,
            raw_plate=data.raw_plate,
            normalized_plate=normalized_plate,
            plate_confidence=data.plate_confidence,
            vehicle_type=data.vehicle_type,
            vehicle_confidence=data.vehicle_confidence,
            direction=data.direction,
            metadata_payload=data.metadata_payload
        )
        db.add(obs)
        db.flush()
        movement_service.on_observation(db, obs)
        record_feed_event(db, obs.id, FeedEventKind.OBSERVATION_CREATED)
        db.commit()
        db.refresh(obs)
        return obs

    @staticmethod
    def create_manual_observation(db: Session, data: ManualObservationCreate, created_by_id: UUID) -> ObservationEvent:
        """
        Records a guard's manual sighting as a new MANUAL observation. It is never
        merged into, and never modifies, a camera observation: there is no
        source_event_id, no camera attribution and no OCR confidence.
        """
        gate = db.query(Gate).filter_by(id=data.gate_id).first()
        if not gate:
            raise ValueError(f"Gate '{data.gate_id}' not found in gate registry.")

        raw_input = (data.plate or "").strip()
        if not raw_input:
            if data.vehicle_type == ObservedVehicleType.BICYCLE:
                raw_plate = "CYCLE"
                normalized_plate = "CYCLE"
            elif data.is_visitor and data.visitor_name:
                raw_plate = f"GUEST-{data.visitor_name[:6].upper().replace(' ', '')}"
                normalized_plate = raw_plate
            else:
                raise ValueError("Plate must contain at least one letter or digit (or choose Bicycle for cycle labor).")
        else:
            normalized_plate = normalize_plate(raw_input) or raw_input.upper()
            raw_plate = raw_input

        now_dt = utc_now()
        meta = {}
        if data.is_visitor or data.visitor_name:
            dur_hours = float(data.allowed_duration_hours) if data.allowed_duration_hours else 2.0
            from datetime import timedelta
            exp_exit = now_dt + timedelta(hours=dur_hours)
            meta["visitor_info"] = {
                "is_visitor": True,
                "visitor_name": data.visitor_name or "Visitor",
                "visitor_phone": data.visitor_phone or "",
                "place_of_visit": data.place_of_visit or "Campus",
                "reference_person": data.reference_person or "",
                "allowed_duration_hours": dur_hours,
                "entry_time": now_dt.isoformat(),
                "expected_exit_time": exp_exit.isoformat(),
                "overstay_alert": False,
            }

        obs = ObservationEvent(
            gate_id=gate.id,
            camera_id=None,
            observed_at=now_dt,
            source=ObservationSource.MANUAL,
            source_event_id=None,
            raw_plate=raw_plate,
            normalized_plate=normalized_plate,
            plate_confidence=None,
            vehicle_type=data.vehicle_type,
            vehicle_confidence=None,
            direction=data.direction,
            metadata_payload=meta or None,
            created_by_id=created_by_id,
            note=data.note
        )
        db.add(obs)
        db.flush()
        movement_service.on_observation(db, obs)
        record_feed_event(db, obs.id, FeedEventKind.OBSERVATION_CREATED)
        db.commit()
        db.refresh(obs)
        return obs

    @staticmethod
    def get_observation_by_id(db: Session, obs_id: UUID) -> Optional[ObservationEvent]:
        return db.query(ObservationEvent).filter_by(id=obs_id).first()

    @staticmethod
    def list_observations(
        db: Session,
        gate_id: Optional[str] = None,
        normalized_plate: Optional[str] = None,
        source: Optional[ObservationSource] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[ObservationEvent]:
        query = db.query(ObservationEvent)
        if gate_id:
            query = query.filter(ObservationEvent.gate_id == gate_id)
        if normalized_plate:
            query = query.filter(ObservationEvent.normalized_plate == normalized_plate)
        if source:
            query = query.filter(ObservationEvent.source == source)
        return query.order_by(ObservationEvent.observed_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def get_gate_observations(db: Session, gate_id: str, skip: int = 0, limit: int = 50) -> List[ObservationEvent]:
        gate = db.query(Gate).filter_by(id=gate_id).first()
        if not gate:
            raise ValueError(f"Gate '{gate_id}' not found in gate registry.")
        return db.query(ObservationEvent).filter_by(gate_id=gate_id).order_by(ObservationEvent.observed_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def get_plate_observations(db: Session, plate: str, skip: int = 0, limit: int = 50) -> List[ObservationEvent]:
        norm = normalize_plate(plate)
        return db.query(ObservationEvent).filter_by(normalized_plate=norm).order_by(ObservationEvent.observed_at.desc()).offset(skip).limit(limit).all()
