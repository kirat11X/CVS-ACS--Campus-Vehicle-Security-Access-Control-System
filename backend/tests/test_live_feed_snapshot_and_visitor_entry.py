"""
Unit and integration tests for:
1. Live feed snapshot capture and permanent RL dataset storage
2. Direct plate editing on observation cards and larger detail windows
3. Guest/Visitor manual entry with visitor hours and automated overstay alerts
4. Bicycle/Cycle labor handling with optional license plate
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
import numpy as np
import pytest
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.db import SessionLocal
from backend.app.models.enums import (
    AlertSeverity,
    AlertStatus,
    GateDirection,
    ObservationDirection,
    ObservationSource,
    ObservedVehicleType,
    UserRole,
)
from backend.app.models.gate import Gate, SecurityAlert
from backend.app.models.identity import User
from backend.app.models.observation import ObservationEvent
from backend.app.routes.observations import update_observation_plate
from backend.app.schemas.feed import ManualObservationCreate
from backend.app.schemas.observation import ObservationPlateUpdate
from backend.app.services.anpr.rl_dataset_logger import (
    RL_MANIFEST_PATH,
    get_rl_dataset_stats,
    log_anpr_observation_sample,
    log_human_plate_correction,
)
from backend.app.services.observation_service import ObservationService
from backend.app.services.visitor_service import (
    check_and_trigger_visitor_overstay_alerts,
    get_active_campus_visitors,
)


@pytest.fixture
def db_session():
    with SessionLocal() as db:
        yield db


@pytest.fixture
def test_gate(db_session: Session):
    gate = db_session.get(Gate, "GATE_1")
    if not gate:
        gate = Gate(id="GATE_1", name="Main Gate 1", status="ACTIVE")
        db_session.add(gate)
        db_session.commit()
    return gate


@pytest.fixture
def test_guard(db_session: Session):
    user = db_session.query(User).filter_by(role=UserRole.GUARD).first()
    if not user:
        user = User(
            username=f"guard_{uuid.uuid4().hex[:6]}",
            full_name="Gate Officer Sharma",
            role=UserRole.GUARD,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
    return user


def test_rl_dataset_sample_and_correction_logging():
    """Verifies that anpr samples and human plate corrections are saved permanently."""
    obs_id = str(uuid.uuid4())
    fake_frame = np.full((100, 200, 3), 128, dtype=np.uint8)
    fake_crop = np.full((30, 80, 3), 200, dtype=np.uint8)

    sample = log_anpr_observation_sample(
        observation_id=obs_id,
        gate_id="GATE_1",
        raw_text="DL3CQD3885",
        normalized_plate="DL3CQD3885",
        confidence=0.92,
        vehicle_class="car",
        full_frame=fake_frame,
        plate_crop=fake_crop,
        vehicle_bbox=[10, 10, 190, 90],
        plate_bbox=[40, 30, 120, 60],
    )
    assert sample is not None
    assert Path(sample["full_frame_path"]).exists()
    assert Path(sample["plate_crop_path"]).exists()

    corr_logged = log_human_plate_correction(
        observation_id=obs_id,
        original_plate="DL3CQ03885",
        corrected_plate="DL3CQD3885",
        guard_user_id="test_guard_1",
        note="Replaced 0 with letter D in series",
    )
    assert corr_logged is True

    stats = get_rl_dataset_stats()
    assert stats["total_records"] >= 2
    assert stats["corrections"] >= 1


def test_direct_plate_editing(db_session: Session, test_gate, test_guard):
    """Verifies PATCH /observations/{id}/plate directly updates the plate and logs correction."""
    obs = ObservationEvent(
        gate_id=test_gate.id,
        observed_at=datetime.now(timezone.utc),
        source=ObservationSource.FRIGATE,
        raw_plate="HR26DK8338",
        normalized_plate="HR26DK8338",
        plate_confidence=0.75,
        vehicle_type=ObservedVehicleType.CAR,
        direction=ObservationDirection.ENTRY,
    )
    db_session.add(obs)
    db_session.commit()

    payload = ObservationPlateUpdate(plate="HR26DK8339", note="Guard noticed last digit 9 not 8")
    resolved = update_observation_plate(id=obs.id, payload=payload, db=db_session, user=test_guard)

    assert resolved.observation.plate.normalized == "HR26DK8339"
    assert resolved.observation.plate.confidence == 1.0

    refreshed_obs = db_session.get(ObservationEvent, obs.id)
    assert refreshed_obs.normalized_plate == "HR26DK8339"
    assert refreshed_obs.metadata_payload.get("manual_plate_edit") is not None


def test_bicycle_cycle_labor_optional_plate(db_session: Session, test_gate, test_guard):
    """Verifies that cycle labor entries do not require a standard license plate."""
    data = ManualObservationCreate(
        gate_id=test_gate.id,
        plate="",  # blank plate
        direction=ObservationDirection.ENTRY,
        vehicle_type=ObservedVehicleType.BICYCLE,
        note="Campus construction worker on bicycle",
    )
    obs = ObservationService.create_manual_observation(db_session, data, created_by_id=test_guard.id)
    assert obs.normalized_plate == "CYCLE"
    assert obs.vehicle_type == ObservedVehicleType.BICYCLE


def test_visitor_manual_entry_and_overstay_alert(db_session: Session, test_gate, test_guard):
    """Verifies visitor entry with allotted hours and automatic generation of overstay alerts."""
    now_past = datetime.now(timezone.utc) - timedelta(hours=3)
    unique_plate = f"CH01AB{uuid.uuid4().hex[:4].upper()}"
    data = ManualObservationCreate(
        gate_id=test_gate.id,
        plate=unique_plate,
        direction=ObservationDirection.ENTRY,
        vehicle_type=ObservedVehicleType.CAR,
        is_visitor=True,
        visitor_name="Vikramaditya Verma",
        visitor_phone="9876543210",
        place_of_visit="Directorate / Admin Block",
        reference_person="Prof. Singla",
        allowed_duration_hours=2.0,  # Allotted 2 hours, but entered 3 hours ago
    )

    obs = ObservationService.create_manual_observation(db_session, data, created_by_id=test_guard.id)
    # Simulate past entry
    obs.observed_at = now_past
    obs.metadata_payload = {
        "visitor_info": {
            "is_visitor": True,
            "visitor_name": "Vikramaditya Verma",
            "visitor_phone": "9876543210",
            "place_of_visit": "Directorate / Admin Block",
            "reference_person": "Prof. Singla",
            "allowed_duration_hours": 2.0,
            "entry_time": now_past.isoformat(),
            "expected_exit_time": (now_past + timedelta(hours=2)).isoformat(),
            "overstay_alert": False,
        }
    }
    flag_modified(obs, "metadata_payload")
    db_session.commit()

    # Trigger overstay detection
    alerts = check_and_trigger_visitor_overstay_alerts(db_session)
    assert len(alerts) >= 1
    overstay_match = [a for a in alerts if a["plate"] == unique_plate]
    assert len(overstay_match) == 1
    assert overstay_match[0]["visitor_name"] == "Vikramaditya Verma"
    assert overstay_match[0]["overstay_minutes"] >= 50

    # Verify SecurityAlert in database
    sec_alert = (
        db_session.query(SecurityAlert)
        .filter(
            SecurityAlert.title.contains(unique_plate),
            SecurityAlert.status == AlertStatus.PENDING,
        )
        .first()
    )
    assert sec_alert is not None
    assert sec_alert.severity == AlertSeverity.HIGH
    assert "Vikramaditya Verma" in sec_alert.description
    assert "Directorate / Admin Block" in sec_alert.description

    # Verify active campus visitors listing
    active = get_active_campus_visitors(db_session)
    v_item = next((v for v in active if v["plate"] == unique_plate), None)
    assert v_item is not None
    assert v_item["is_overstay"] is True
    assert v_item["visitor_phone"] == "9876543210"
