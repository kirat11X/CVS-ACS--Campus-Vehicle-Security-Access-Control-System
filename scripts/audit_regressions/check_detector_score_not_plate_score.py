"""
Finding: when an event carried plate text without an OCR score, the parser copied the object
detector's top_score into plate_confidence. A detector score says "this is a car", not "these
characters are right", yet a 0.95 car detection let an unscored OCR string pass the 0.80 confident-read
rule and auto-link to an owner. The resolver's own rule (and context.md 11A) is that a read with no
score is LOW_CONFIDENCE.
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models import ObservationEvent
from backend.app.models.enums import LinkStatus
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.audit_regressions.common import ensure_gates, register_vehicle, unique_plate


def unscored_read_is_low_confidence():
    ensure_gates()
    plate = unique_plate()
    register_vehicle(plate)
    obs = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}").process_payload({"after": {
        "id": f"audit-unscored-{uuid.uuid4().hex[:8]}", "camera": "gate_cam", "label": "car",
        "sub_label": plate, "top_score": 0.95, "score": 0.95,
    }})
    with SessionLocal() as db:
        row = db.get(ObservationEvent, obs.id)
        link = identity_resolution_service.resolve(db, row).link_status
        got = (row.plate_confidence, row.vehicle_confidence, link)
    assert got == (None, 0.95, LinkStatus.LOW_CONFIDENCE), (
        f"(plate_confidence, vehicle_confidence, link) = {got}; the detector score was used as an OCR score"
    )


SCENARIOS = [
    ("unscored_read_is_low_confidence", unscored_read_is_low_confidence),
]
