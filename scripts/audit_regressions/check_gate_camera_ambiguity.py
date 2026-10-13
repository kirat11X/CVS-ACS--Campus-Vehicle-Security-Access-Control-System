"""
Finding: nothing stopped two gates from claiming the same Frigate camera (gates.camera_id is not
unique and POST/PUT /gates never checked), and FrigateEventParser.resolve_camera_to_gate took
`.first()` without ordering. Events from a shared camera went to an arbitrary gate - including a
soft-deactivated one. The development database already has 12 gates on camera `temp_cam`.
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models import Gate
from backend.app.models.enums import GateStatus
from backend.app.services.frigate_event_parser import FrigateEventParser
from scripts.audit_regressions.common import auth, client, make_user


def second_live_gate_cannot_claim_a_camera():
    _, admin = make_user("ADMIN")
    camera = f"audit_cam_{uuid.uuid4().hex[:6]}"
    first, second = (f"AUDIT_{uuid.uuid4().hex[:6].upper()}" for _ in range(2))
    assert client().post("/gates", headers=auth(admin), json={"id": first, "name": "A", "camera_id": camera}).status_code == 201
    created = client().post("/gates", headers=auth(admin), json={"id": second, "name": "B", "camera_id": camera})
    moved = client().put(f"/gates/GATE_3", headers=auth(admin), json={"camera_id": camera})
    with SessionLocal() as db:  # undo whatever was accepted so no two live gates share a camera
        db.get(Gate, "GATE_3").camera_id = "gate_3_cam"
        if db.get(Gate, second) is not None:
            db.get(Gate, second).status = GateStatus.INACTIVE
        db.commit()
    assert (created.status_code, moved.status_code) == (409, 409), (
        f"a camera already used by a live gate was accepted: POST -> {created.status_code}, PUT -> {moved.status_code}"
    )


def camera_resolves_to_the_live_gate():
    camera = f"audit_cam_{uuid.uuid4().hex[:6]}"
    retired, live = (f"AUDIT_{uuid.uuid4().hex[:6].upper()}" for _ in range(2))
    with SessionLocal() as db:
        # A retired gate that sorts first by id, and the gate that now owns the camera.
        db.add(Gate(id=f"AAA_{retired}", name="Retired", camera_id=camera, status=GateStatus.INACTIVE))
        db.add(Gate(id=live, name="Live", camera_id=camera, status=GateStatus.ACTIVE))
        db.commit()
        resolved = {FrigateEventParser.resolve_camera_to_gate(camera, db).id for _ in range(5)}
    assert resolved == {live}, f"camera '{camera}' resolved to {resolved}, expected the live gate {live}"


SCENARIOS = [
    ("second_live_gate_cannot_claim_a_camera", second_live_gate_cannot_claim_a_camera),
    ("camera_resolves_to_the_live_gate", camera_resolves_to_the_live_gate),
]
