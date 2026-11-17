"""
Unit tests for Unlinked & Transient Vehicle Campus Overstay Alerts.

Verifies:
1. Unlinked vehicle inside campus for > 1.5 hours generates HIGH severity OVERSTAY_UNLINKED alert.
2. Unlinked vehicle inside campus for < 1.5 hours does NOT generate overstay alert.
3. Delivery vehicle inside campus for > 1.5 hours generates alert.
4. Linked student vehicle inside campus does not trigger unlinked overstay alert.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from backend.app.schemas.delivery import AlertItem
from backend.app.schemas.movement import InsideResponse, PresenceEntry, MovementEntry, LinkedVehicle
from backend.app.schemas.observation import GateSummary
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.alert_service import AlertService


@pytest.fixture
def alert_service():
    return AlertService()


def make_presence_entry(
    plate: str,
    linked: bool,
    category: str = "UNKNOWN",
    owner: bool = False,
    hours_ago: float = 2.0,
    gate_id: str = "GATE_1",
) -> PresenceEntry:
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(hours=hours_ago)

    veh = LinkedVehicle(
        id=uuid.uuid4(), plate=plate, raw_plate=plate, category=category, status="ACTIVE", is_active=True, registry_status="ACTIVE"
    ) if linked else None

    own = OwnerContextResponse(
        id=str(uuid.uuid4()), institutional_id="24103042", name="Student Owner",
        person_type="STUDENT", status="ACTIVE"
    ) if owner else None

    mov = MovementEntry(
        id=uuid.uuid4(),
        gate=GateSummary(id=gate_id, name="Main North Gate"),
        timestamp=entry_time,
        direction="ENTRY",
        direction_method="CAMERA_ROLE",
        plate=plate,
        normalized_plate=plate,
        linked=linked,
    )

    return PresenceEntry(
        subject=plate,
        status="INSIDE",
        normalized_plate=plate,
        linked=linked,
        vehicle=veh,
        owner=own,
        inside_since=entry_time,
        last_movement=mov,
    )


def test_unlinked_vehicle_overstay_triggers_alert(alert_service):
    # Unlinked car inside for 2.5 hours (> 1.5h threshold)
    entry = make_presence_entry("DL01AB9999", linked=False, hours_ago=2.5, gate_id="GATE_1")
    mock_db = MagicMock()

    with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
        mock_inside.return_value = InsideResponse(total=1, items=[entry], unattributed_entries=[])
        alerts = alert_service.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

    assert len(alerts) == 1
    a = alerts[0]
    assert a.kind == "OVERSTAY_UNLINKED"
    assert a.severity == "HIGH"
    assert "DL01AB9999" in a.title
    assert "overstay" in a.title.lower()
    assert "GATE_1" in a.detail
    assert a.ref == "DL01AB9999"


def test_unlinked_vehicle_recent_entry_does_not_trigger(alert_service):
    # Unlinked car entered only 0.5 hours ago (< 1.5h threshold)
    entry = make_presence_entry("DL01AB9999", linked=False, hours_ago=0.5)
    mock_db = MagicMock()

    with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
        mock_inside.return_value = InsideResponse(total=1, items=[entry], unattributed_entries=[])
        alerts = alert_service.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

    assert len(alerts) == 0


def test_delivery_vehicle_overstay_triggers_alert(alert_service):
    # Delivery vehicle inside campus for 1.8 hours
    entry = make_presence_entry("HR26DL1234", linked=True, category="DELIVERY", owner=False, hours_ago=1.8, gate_id="GATE_2")
    mock_db = MagicMock()

    with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
        mock_inside.return_value = InsideResponse(total=1, items=[entry], unattributed_entries=[])
        alerts = alert_service.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

    assert len(alerts) == 1
    assert alerts[0].kind == "OVERSTAY_UNLINKED"
    assert alerts[0].severity == "HIGH"
    assert "Delivery vehicle" in alerts[0].title


def test_linked_student_vehicle_does_not_trigger(alert_service):
    # Registered student vehicle inside for 3 hours (normal student parking)
    entry = make_presence_entry("CH01AB1234", linked=True, category="STUDENT", owner=True, hours_ago=3.0)
    mock_db = MagicMock()

    with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
        mock_inside.return_value = InsideResponse(total=1, items=[entry], unattributed_entries=[])
        alerts = alert_service.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

    assert len(alerts) == 0
