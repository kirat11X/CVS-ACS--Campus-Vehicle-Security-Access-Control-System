"""Shared fixtures for the audit regression scenarios."""
import os
import random
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.app.config import DATABASE_URL
from backend.app.db import SessionLocal
from backend.app.main import app
from backend.app.models import Gate, User, Vehicle, VehicleOwner
from backend.app.models.enums import PersonType, ResidenceType, VehicleCategory, VehicleStatus
from backend.app.services.auth_service import create_access_token, hash_password

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENV_BIN = os.path.join(PROJECT_ROOT, ".venv", "bin")

_client = None


def client() -> TestClient:
    """In-process client. Not used as a context manager, so the MQTT lifespan never starts."""
    global _client
    if _client is None:
        _client = TestClient(app, raise_server_exceptions=False)
    return _client


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def ensure_gates() -> None:
    with SessionLocal() as db:
        for gate_id, name, camera in (
            ("GATE_1", "Main North Gate", "gate_cam"),
            ("GATE_2", "South Campus Gate", "gate_2_cam"),
            ("GATE_3", "Hostel East Gate", "gate_3_cam"),
        ):
            if not db.get(Gate, gate_id):
                db.add(Gate(id=gate_id, name=name, camera_id=camera, status="ACTIVE"))
        db.commit()


def make_user(role: str):
    """Creates an active user and returns (user_id, bearer token)."""
    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        user = User(
            username=f"audit_{role.lower()}_{tag}", email=f"audit_{role.lower()}_{tag}@campus.edu",
            full_name=f"Audit {role.title()}", role=role, hashed_password=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token, _ = create_access_token(user)
        return user.id, token


def unique_plate(prefix: str = "PB10") -> str:
    letters = "".join(random.choice("ACEFHJKLMNPRTUVWXY") for _ in range(2))
    return f"{prefix}{letters}{random.randint(1000, 9999)}"


def register_vehicle(plate: str, owner_name: str = "Audit Owner", residence: str = "BH-4, Room 312"):
    """Registers an ACTIVE student vehicle with an owner directly in the registry; returns (vehicle_id, owner_id)."""
    with SessionLocal() as db:
        owner = VehicleOwner(
            identifier=f"AUDIT-{uuid.uuid4().hex[:10]}", full_name=owner_name, email="owner@campus.edu",
            phone="+910000000000", person_type=PersonType.STUDENT, residence_type=ResidenceType.HOSTELLER,
            residence=residence, status="ACTIVE",
        )
        db.add(owner)
        db.flush()
        vehicle = Vehicle(
            raw_plate=plate, normalized_plate=plate, vehicle_category=VehicleCategory.STUDENT,
            status=VehicleStatus.ACTIVE, owner_id=owner.id,
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id, owner.id


def frigate_018_event(event_id: str, camera: str = "gate_cam", plate=None, plate_score=None,
                      label: str = "car", known_plate_name=None, top_score: float = 0.9) -> dict:
    """
    A frigate/events message shaped like Frigate 0.18 TrackedObject.to_dict(): the LPR read is
    always in `recognized_license_plate` as (plate, score); `sub_label` is (name, score) only when
    the plate matches a configured known_plates entry (frigate/data_processing/common/license_plate/mixin.py).
    """
    now = time.time()
    after = {
        "id": event_id, "camera": camera, "frame_time": now, "snapshot": None, "snapshot_clean": True,
        "label": label, "sub_label": [known_plate_name, plate_score] if known_plate_name else None,
        "top_score": top_score, "false_positive": False, "start_time": now, "end_time": None,
        "score": top_score, "computed_score": top_score, "box": [100, 150, 200, 250], "area": 10000,
        "ratio": 1.0, "region": [0, 0, 320, 320], "active": True, "stationary": False,
        "motionless_count": 0, "position_changes": 1, "current_zones": [], "entered_zones": [],
        "has_clip": False, "has_snapshot": True, "attributes": {}, "current_attributes": [],
        "recognized_license_plate": [plate, plate_score] if plate else None,
    }
    return {"type": "new", "before": after, "after": after}


@contextmanager
def fresh_schema():
    """A throwaway empty schema in the scratch database; yields a DATABASE_URL whose search_path selects it."""
    name = f"audit_fresh_{uuid.uuid4().hex[:8]}"
    engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    sep = "&" if "?" in DATABASE_URL else "?"
    try:
        yield name, f"{DATABASE_URL}{sep}options=-csearch_path={name}"
    finally:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        engine.dispose()


def run_tool(args, database_url: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Runs a project tool (alembic, python -c ...) in a subprocess against database_url."""
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONPATH": PROJECT_ROOT}
    return subprocess.run(args, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def tables_in(schema: str) -> set:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"), {"s": schema}
        ).all()
    engine.dispose()
    return {r[0] for r in rows}


PYTHON = sys.executable
