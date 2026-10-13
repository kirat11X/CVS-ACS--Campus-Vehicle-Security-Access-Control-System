"""
Finding: GET /vehicles/{plate}/history pulled in every observation that ANY guard resolution had
ever confirmed as this vehicle, including confirmations a guard later replaced. A sighting the guard
re-assigned to vehicle B stayed in vehicle A's timeline (the latest-resolution-wins rule was ignored),
placing a vehicle at a gate the guard had already said it was not at.
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models.enums import ObservationSource
from backend.app.schemas.observation import ObservationCreate
from backend.app.services.observation_service import ObservationService
from scripts.audit_regressions.common import auth, client, ensure_gates, make_user, register_vehicle, unique_plate


def superseded_confirmation_leaves_old_vehicle_timeline():
    ensure_gates()
    plate_a, plate_b = unique_plate("HR26"), unique_plate("CH01")
    vehicle_a, _ = register_vehicle(plate_a)
    vehicle_b, _ = register_vehicle(plate_b)
    with SessionLocal() as db:
        obs = ObservationService.create_or_update_observation(db, ObservationCreate(
            gate_id="GATE_2", camera_id="gate_2_cam", source=ObservationSource.FRIGATE,
            source_event_id=f"audit-hist-{uuid.uuid4().hex[:8]}", raw_plate=unique_plate("XX00"), plate_confidence=0.4,
        ))
        obs_id = str(obs.id)
    _, guard = make_user("GUARD")
    for chosen in (vehicle_a, vehicle_b):
        r = client().post("/resolutions", headers=auth(guard), json={"observation_id": obs_id, "chosen_vehicle_id": str(chosen)})
        assert r.status_code == 201, r.text

    def sightings(plate):
        hist = client().get(f"/vehicles/{plate}/history", headers=auth(guard))
        assert hist.status_code == 200, hist.text
        return {t["sighting"]["observation"]["id"] for t in hist.json()["timeline"] if t["type"] == "SIGHTING"}

    assert obs_id in sightings(plate_b), "the latest confirmation (vehicle B) must show the sighting"
    assert obs_id not in sightings(plate_a), "a sighting re-assigned to vehicle B is still in vehicle A's history"


SCENARIOS = [
    ("superseded_confirmation_leaves_old_vehicle_timeline", superseded_confirmation_leaves_old_vehicle_timeline),
]
