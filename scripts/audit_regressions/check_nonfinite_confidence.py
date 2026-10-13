"""
Finding: NaN/Infinity in a Frigate message were not treated as malformed input. Python's json accepts
them, the parser's clamp max(0.0, min(1.0, nan)) turned a NaN score into 1.0 (maximum confidence),
and the INSERT then failed only because PostgreSQL's JSON type rejects NaN in metadata_payload - so
the event surfaced as a database error (with the SQL parameters, plate included, in the log) instead
of being counted as a malformed payload.
"""
import math
import uuid

from backend.app.db import SessionLocal
from backend.app.models import ObservationEvent
from backend.app.services.frigate_event_parser import FrigateEventParser
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.audit_regressions.common import ensure_gates, unique_plate


def nonfinite_json_is_a_malformed_payload():
    ensure_gates()
    worker = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}")
    outcomes = {}
    for token in ("NaN", "Infinity", "-Infinity"):
        event_id = f"audit-nan-{uuid.uuid4().hex[:8]}"
        raw = ('{"after": {"id": "%s", "camera": "gate_cam", "label": "car", "top_score": %s, '
               '"sub_label": ["%s", %s]}}' % (event_id, token, unique_plate(), token)).encode()
        before = dict(worker.stats)
        worker.process_payload(raw)
        with SessionLocal() as db:
            rows = db.query(ObservationEvent).filter_by(source_event_id=event_id).count()
        outcomes[token] = {
            "rows": rows,
            "malformed": worker.stats["malformed_payloads"] - before["malformed_payloads"],
            "db_errors": worker.stats["errors"] - before["errors"],
        }
    bad = {k: v for k, v in outcomes.items() if v != {"rows": 0, "malformed": 1, "db_errors": 0}}
    assert not bad, f"non-finite JSON not rejected as malformed: {bad}"


def nonfinite_score_never_becomes_confidence():
    ensure_gates()
    with SessionLocal() as db:
        parsed = FrigateEventParser.parse_event({"after": {
            "id": f"audit-nan-{uuid.uuid4().hex[:8]}", "camera": "gate_cam", "label": "car",
            "top_score": math.inf, "sub_label": [unique_plate(), math.nan],
        }}, db)
    assert parsed is not None
    assert (parsed.plate_confidence, parsed.vehicle_confidence) == (None, None), (
        f"non-finite scores parsed as plate={parsed.plate_confidence}, vehicle={parsed.vehicle_confidence}"
    )


SCENARIOS = [
    ("nonfinite_json_is_a_malformed_payload", nonfinite_json_is_a_malformed_payload),
    ("nonfinite_score_never_becomes_confidence", nonfinite_score_never_becomes_confidence),
]
