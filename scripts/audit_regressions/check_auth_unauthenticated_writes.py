"""
Finding: POST/PUT/DELETE /gates and POST /observations accepted anonymous requests. Anyone on the
network could remap a gate's camera (so real camera events are dropped as "unmapped" or credited to
another gate), deactivate gates, or post a FRIGATE observation with an existing source_event_id and
overwrite the plate a real camera recorded for that passage.
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models import Gate, ObservationEvent
from backend.app.models.enums import GateStatus, ObservationSource
from backend.app.schemas.observation import ObservationCreate
from backend.app.services.observation_service import ObservationService
from scripts.audit_regressions.common import auth, client, ensure_gates, make_user, unique_plate


def anonymous_gate_writes_are_rejected():
    ensure_gates()
    gate_id = f"AUDIT_{uuid.uuid4().hex[:6].upper()}"
    attempts = {
        "POST /gates": client().post("/gates", json={"id": gate_id, "name": "Rogue gate", "camera_id": "gate_cam"}),
        "PUT /gates/GATE_1": client().put("/gates/GATE_1", json={"camera_id": f"rogue_{gate_id}"}),
        "DELETE /gates/GATE_2": client().delete("/gates/GATE_2"),
    }
    with SessionLocal() as db:  # undo whatever was accepted so later scenarios still map gate_cam
        camera = db.get(Gate, "GATE_1").camera_id
        db.get(Gate, "GATE_1").camera_id = "gate_cam"
        db.get(Gate, "GATE_2").status = GateStatus.ACTIVE
        rogue = db.get(Gate, gate_id)
        if rogue is not None:
            rogue.camera_id, rogue.status = f"rogue_{gate_id.lower()}", GateStatus.INACTIVE
        db.commit()
    accepted = [f"{k} -> {r.status_code}" for k, r in attempts.items() if r.status_code != 401]
    assert not accepted, f"anonymous gate writes accepted ({'; '.join(accepted)}); GATE_1 camera became {camera!r}"


def anonymous_observation_cannot_rewrite_camera_read():
    ensure_gates()
    event_id = f"audit-real-{uuid.uuid4().hex[:8]}"
    real_plate = unique_plate()
    with SessionLocal() as db:
        ObservationService.create_or_update_observation(db, ObservationCreate(
            gate_id="GATE_1", camera_id="gate_cam", source=ObservationSource.FRIGATE,
            source_event_id=event_id, raw_plate=real_plate, plate_confidence=0.81,
        ))
    resp = client().post("/observations", json={
        "gate_id": "GATE_1", "source": "FRIGATE", "source_event_id": event_id,
        "raw_plate": "FAKE0000", "plate_confidence": 1.0,
    })
    with SessionLocal() as db:
        stored = db.query(ObservationEvent).filter_by(source_event_id=event_id).one().raw_plate
    assert resp.status_code == 401, (
        f"anonymous POST /observations -> {resp.status_code}; camera read {real_plate!r} is now {stored!r}"
    )
    assert stored == real_plate


def roles_on_write_endpoints():
    ensure_gates()
    _, guard = make_user("GUARD")
    _, admin = make_user("ADMIN")
    gate_id = f"AUDIT_{uuid.uuid4().hex[:6].upper()}"
    body = {"id": gate_id, "name": "Audit gate", "camera_id": f"cam_{gate_id.lower()}"}
    assert client().post("/gates", json=body, headers=auth(guard)).status_code == 403
    assert client().post("/gates", json=body, headers=auth(admin)).status_code == 201
    assert client().put(f"/gates/{gate_id}", json={"location": "x"}, headers=auth(admin)).status_code == 200
    assert client().delete(f"/gates/{gate_id}", headers=auth(admin)).status_code == 200
    obs = {"gate_id": "GATE_1", "source": "FRIGATE", "source_event_id": f"audit-{uuid.uuid4().hex[:8]}"}
    assert client().post("/observations", json=obs, headers=auth(guard)).status_code == 403
    assert client().post("/observations", json=obs, headers=auth(admin)).status_code == 201
    assert client().get("/gates").status_code == 200, "gate list stays public (no personal data)"


SCENARIOS = [
    ("anonymous_gate_writes_are_rejected", anonymous_gate_writes_are_rejected),
    ("anonymous_observation_cannot_rewrite_camera_read", anonymous_observation_cannot_rewrite_camera_read),
    ("roles_on_write_endpoints", roles_on_write_endpoints),
]
