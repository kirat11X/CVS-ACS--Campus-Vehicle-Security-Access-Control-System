"""
Finding: FrigateEventParser did not understand Frigate 0.18 LPR events. Frigate always publishes
the plate read as recognized_license_plate = (plate, score) and sets sub_label = (name, score) only
when the plate matches a known_plates entry. The parser accepted recognized_license_plate only as a
string and preferred sub_label, so a real read was stored as NO_PLATE, and a known plate was stored
as its owner-given *name* instead of the plate text.
"""
import uuid

from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.audit_regressions.common import ensure_gates, frigate_018_event, unique_plate


def _ingest(payload):
    obs = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}").process_payload(payload)
    assert obs is not None, "worker rejected a well-formed Frigate 0.18 event"
    return obs


def recognized_plate_tuple_is_read():
    ensure_gates()
    plate = unique_plate()
    obs = _ingest(frigate_018_event(f"audit-018-{uuid.uuid4().hex[:8]}", plate=plate, plate_score=0.93))
    assert (obs.normalized_plate, obs.plate_confidence) == (plate, 0.93), (
        f"expected plate {plate!r} @0.93 from recognized_license_plate, stored "
        f"{obs.raw_plate!r} @{obs.plate_confidence}"
    )


def known_plate_name_is_not_the_plate():
    ensure_gates()
    plate = unique_plate()
    obs = _ingest(frigate_018_event(
        f"audit-018-{uuid.uuid4().hex[:8]}", plate=plate, plate_score=0.91, known_plate_name="Warden's car",
    ))
    assert obs.normalized_plate == plate, (
        f"known-plate sub_label leaked into the plate: stored {obs.raw_plate!r}, expected {plate!r}"
    )


def sub_label_alone_is_not_a_plate_in_018_events():
    ensure_gates()
    payload = frigate_018_event(f"audit-018-{uuid.uuid4().hex[:8]}", plate=None)
    payload["after"]["sub_label"] = ["amazon", 0.88]  # e.g. a Frigate+ attribute sub_label on a car
    obs = _ingest(payload)
    assert obs.raw_plate is None, f"non-plate sub_label stored as plate text: {obs.raw_plate!r}"


def legacy_string_sub_label_still_read():
    ensure_gates()
    plate = unique_plate()
    obs = _ingest({"after": {"id": f"audit-legacy-{uuid.uuid4().hex[:8]}", "camera": "gate_cam",
                             "label": "car", "sub_label": [plate, 0.9]}})
    assert (obs.normalized_plate, obs.plate_confidence) == (plate, 0.9)


SCENARIOS = [
    ("recognized_plate_tuple_is_read", recognized_plate_tuple_is_read),
    ("known_plate_name_is_not_the_plate", known_plate_name_is_not_the_plate),
    ("sub_label_alone_is_not_a_plate_in_018_events", sub_label_alone_is_not_a_plate_in_018_events),
    ("legacy_string_sub_label_still_read", legacy_string_sub_label_still_read),
]
