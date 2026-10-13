"""
Finding: Frigate tracks `person` on gate_cam (config/frigate/config.yml) and the parser mapped any
unknown label to ObservedVehicleType.UNKNOWN, so every pedestrian became a vehicle observation. On a
camera declared ENTRY_LANE/EXIT_LANE each pedestrian then created a plate-less movement record and
showed up in "Inside campus" as an unattributed vehicle entry (vehicle != person).
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models import CameraLane, EntryExitLog, ObservationEvent
from backend.app.models.enums import LaneRole
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.audit_regressions.common import ensure_gates, frigate_018_event


def pedestrian_is_not_a_vehicle_observation():
    ensure_gates()
    camera = f"audit_entry_{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        db.add(CameraLane(camera_id=camera, gate_id="GATE_1", lane_role=LaneRole.ENTRY_LANE, is_active=True))
        db.commit()
    event_id = f"audit-person-{uuid.uuid4().hex[:8]}"
    FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}").process_payload(
        frigate_018_event(event_id, camera=camera, label="person")
    )
    with SessionLocal() as db:
        observations = db.query(ObservationEvent).filter_by(source_event_id=event_id).count()
        movements = db.query(EntryExitLog).filter_by(frigate_event_id=event_id).count()
    assert (observations, movements) == (0, 0), (
        f"a pedestrian produced {observations} vehicle observation(s) and {movements} movement record(s)"
    )


def unknown_vehicle_labels_are_still_kept():
    ensure_gates()
    event_id = f"audit-unknown-{uuid.uuid4().hex[:8]}"
    obs = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}").process_payload(
        frigate_018_event(event_id, label="unidentified_hovercraft")
    )
    assert obs is not None and obs.vehicle_type.value == "UNKNOWN", "unsupported vehicle labels must still map to UNKNOWN"


SCENARIOS = [
    ("pedestrian_is_not_a_vehicle_observation", pedestrian_is_not_a_vehicle_observation),
    ("unknown_vehicle_labels_are_still_kept", unknown_vehicle_labels_are_still_kept),
]
