"""
Finding: (source, source_event_id) idempotency was check-then-insert with no lock and no unique
constraint (the index was non-unique). Two concurrent ingestions of one Frigate event - e.g. two
backend processes on the same broker, or the MQTT worker racing POST /observations - both saw no
row and both inserted, so one vehicle passage became two observations (and two movements).
"""
import threading
import uuid

from backend.app.db import SessionLocal
from backend.app.models import ObservationEvent
from backend.app.models.enums import ObservationSource
from backend.app.schemas.observation import ObservationCreate
from backend.app.services import observation_service as observation_module
from backend.app.services.observation_service import ObservationService
from scripts.audit_regressions.common import ensure_gates, unique_plate


def concurrent_duplicate_event_creates_one_row():
    ensure_gates()
    event_id = f"audit-race-{uuid.uuid4().hex[:8]}"
    plate = unique_plate()
    barrier = threading.Barrier(2)
    original = observation_module.record_feed_event
    errors = []

    def paused_record_feed_event(db, observation_id, kind):
        # Runs after the existence check and the INSERT, before COMMIT: hold both writers here so
        # each has decided "new row" before either commits. Code that serialises writers before the
        # check never gets both threads here, so the wait times out instead of deadlocking.
        try:
            barrier.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return original(db, observation_id, kind)

    def ingest(score):
        try:
            with SessionLocal() as db:
                ObservationService.create_or_update_observation(db, ObservationCreate(
                    gate_id="GATE_1", camera_id="gate_cam", source=ObservationSource.FRIGATE,
                    source_event_id=event_id, raw_plate=plate, plate_confidence=score,
                ))
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(f"{type(exc).__name__}: {exc}")

    observation_module.record_feed_event = paused_record_feed_event
    try:
        threads = [threading.Thread(target=ingest, args=(s,)) for s in (0.71, 0.98)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        observation_module.record_feed_event = original

    with SessionLocal() as db:
        rows = db.query(ObservationEvent).filter_by(source=ObservationSource.FRIGATE, source_event_id=event_id).all()
    assert len(rows) == 1, f"one Frigate event produced {len(rows)} observation rows (errors: {errors})"
    assert not errors, f"a concurrent update was lost: {errors}"
    assert rows[0].plate_confidence == 0.98, f"best read not kept: {rows[0].plate_confidence}"


SCENARIOS = [
    ("concurrent_duplicate_event_creates_one_row", concurrent_duplicate_event_creates_one_row),
]
