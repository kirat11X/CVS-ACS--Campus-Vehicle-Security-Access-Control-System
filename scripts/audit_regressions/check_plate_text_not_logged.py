"""
Finding: plate text (personal data under the DPDP Act 2023) was written to the shared application
log: the Frigate worker logged every new observation's plate at INFO, a database error during
ingestion logged the full SQL parameters (raw and normalized plate), and the /api/test/lpr-event and
/webhook/n8n-test handlers logged their whole request bodies (plate, invoice/customer fields).
"""
import logging
import uuid

from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.audit_regressions.common import client, ensure_gates, unique_plate


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        text = f"{record.name}: {record.getMessage()}"
        if record.exc_info:
            text += "\n" + logging.Formatter().formatException(record.exc_info)
        self.lines.append(text)


def _captured(action):
    handler = _Capture()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        action()
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    return handler.lines


def worker_logs_carry_no_plate():
    ensure_gates()
    plate = unique_plate()
    refined = unique_plate()
    worker = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}")
    event_id = f"audit-log-{uuid.uuid4().hex[:8]}"

    def ingest():
        worker.process_payload({"after": {"id": event_id, "camera": "gate_cam", "label": "car", "sub_label": [plate, 0.9]}})
        worker.process_payload({"after": {"id": event_id, "camera": "gate_cam", "label": "car", "sub_label": [refined, 0.95]}})

    leaked = [line for line in _captured(ingest) if plate in line or refined in line]
    assert not leaked, f"plate text written to the application log: {leaked}"


def database_error_logs_carry_no_plate():
    ensure_gates()
    plate = unique_plate()
    worker = FrigateMQTTWorker(client_id=f"audit_{uuid.uuid4().hex[:6]}")
    # raw_plate is VARCHAR(30): a 50-character read is parsed and then rejected while being stored
    # (by PostgreSQL before the schema had length limits, by ObservationCreate validation since).
    payload = {"after": {"id": f"audit-dberr-{uuid.uuid4().hex[:8]}", "camera": "gate_cam", "label": "car",
                         "sub_label": [plate + "X" * 40, 0.9]}}

    lines = _captured(lambda: worker.process_payload(payload))
    assert any("Error persisting Frigate observation" in line for line in lines), "fixture did not hit the database error path"
    leaked = [line[:300] for line in lines if plate in line]
    assert not leaked, f"database error log contains the plate: {leaked}"


def test_endpoints_log_no_personal_data():
    plate = unique_plate()

    def call():
        client().post("/api/test/lpr-event", json={"camera": "gate_cam", "plate_number": plate, "confidence": 0.9})
        client().post("/webhook/n8n-test", json={"source": "n8n", "event": "invoice",
                                                 "data": {"customer": "Audit Customer", "plate": plate}})

    leaked = [line for line in _captured(call) if plate in line or "Audit Customer" in line]
    assert not leaked, f"request bodies with personal data written to the log: {leaked}"


SCENARIOS = [
    ("worker_logs_carry_no_plate", worker_logs_carry_no_plate),
    ("database_error_logs_carry_no_plate", database_error_logs_carry_no_plate),
    ("test_endpoints_log_no_personal_data", test_endpoints_log_no_personal_data),
]
