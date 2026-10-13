"""
Finding: GET /api/events/frigate was unauthenticated and returned the last 50 raw messages from
frigate/# - every plate read, and (for frigate/<camera>/<label>/snapshot topics) the JPEG frame bytes
decoded as text - to anyone on the network.
"""
import uuid
from types import SimpleNamespace

from backend.app.mqtt import mqtt_manager
from scripts.audit_regressions.common import auth, client, make_user, unique_plate


def _buffer_event(plate):
    msg = SimpleNamespace(topic="frigate/events", payload=(
        '{"after": {"id": "audit-buf-%s", "camera": "gate_cam", "recognized_license_plate": ["%s", 0.9]}}'
        % (uuid.uuid4().hex[:6], plate)
    ).encode())
    mqtt_manager._on_message(None, None, msg)


def anonymous_cannot_read_raw_mqtt_buffer():
    plate = unique_plate()
    _buffer_event(plate)
    resp = client().get("/api/events/frigate")
    assert resp.status_code == 401, (
        f"anonymous GET /api/events/frigate -> {resp.status_code}; plate in body: {plate in resp.text}"
    )


def admin_can_still_read_buffer():
    plate = unique_plate()
    _buffer_event(plate)
    _, guard = make_user("GUARD")
    _, admin = make_user("ADMIN")
    assert client().get("/api/events/frigate", headers=auth(guard)).status_code == 403
    resp = client().get("/api/events/frigate", headers=auth(admin))
    assert resp.status_code == 200 and plate in resp.text


SCENARIOS = [
    ("anonymous_cannot_read_raw_mqtt_buffer", anonymous_cannot_read_raw_mqtt_buffer),
    ("admin_can_still_read_buffer", admin_can_still_read_buffer),
]
