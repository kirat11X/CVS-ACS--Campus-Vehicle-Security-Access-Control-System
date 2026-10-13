"""
Finding: registry and observation reads were unauthenticated. GET /vehicles/{plate} returned the
owner's name, phone, email and hostel room to anyone who knew a plate (plate -> person lookup),
GET /vehicles listed every owner, and the observation endpoints exposed every plate sighting.
"""
import uuid

from backend.app.models.enums import ObservationSource
from backend.app.schemas.observation import ObservationCreate
from backend.app.db import SessionLocal
from backend.app.services.observation_service import ObservationService
from scripts.audit_regressions.common import auth, client, ensure_gates, make_user, register_vehicle, unique_plate

PERSONAL_READS = (
    "/vehicles/{plate}",
    "/vehicles?residence_type=HOSTELLER",
    "/vehicles/{plate}/observations",
    "/observations?plate={plate}",
    "/observations/{obs_id}",
    "/gates/GATE_1/observations",
)


def _fixture():
    ensure_gates()
    plate = unique_plate()
    register_vehicle(plate, owner_name="Audit Hosteller", residence="BH-4, Room 312")
    with SessionLocal() as db:
        obs = ObservationService.create_or_update_observation(db, ObservationCreate(
            gate_id="GATE_1", camera_id="gate_cam", source=ObservationSource.FRIGATE,
            source_event_id=f"audit-read-{uuid.uuid4().hex[:8]}", raw_plate=plate, plate_confidence=0.95,
        ))
        obs_id = obs.id
    return plate, obs_id


def anonymous_reads_are_rejected():
    plate, obs_id = _fixture()
    exposed = []
    for template in PERSONAL_READS:
        path = template.format(plate=plate, obs_id=obs_id)
        resp = client().get(path)
        if resp.status_code != 401:
            leaked = "BH-4, Room 312" in resp.text or "+910000000000" in resp.text or plate in resp.text
            exposed.append(f"{path} -> {resp.status_code}{' (owner/plate data in body)' if leaked else ''}")
    assert not exposed, "anonymous callers can read personal data: " + "; ".join(exposed)


def staff_reads_still_work():
    plate, obs_id = _fixture()
    _, guard = make_user("GUARD")
    for template in PERSONAL_READS:
        path = template.format(plate=plate, obs_id=obs_id)
        resp = client().get(path, headers=auth(guard))
        assert resp.status_code == 200, f"{path} with a GUARD token -> {resp.status_code}: {resp.text[:200]}"


SCENARIOS = [
    ("anonymous_reads_are_rejected", anonymous_reads_are_rejected),
    ("staff_reads_still_work", staff_reads_still_work),
]
