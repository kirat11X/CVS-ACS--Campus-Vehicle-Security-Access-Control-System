"""
Comprehensive Test Suite for Backend Core Features:
1. PROD-001 WhatsApp Provider abstraction & entrypoint leakage elimination
2. Access Control Policy Engine (Phase 5)
3. Security Review Queue (Phases 11-12)
4. Vehicle History & Movement Logs (Phase 6)
5. Lane & Direction Confirmation / Provisional Status
"""
import os
import sys
import uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.main import app
from backend.app.models.base import Base, utc_now
from backend.app.models.delivery import DeliveryOrder, Invoice, InvoiceItem
from backend.app.models.enums import (
    AccessState,
    AlertSeverity,
    AlertStatus,
    DirectionMethod,
    GuardDecision,
    LaneRole,
    ObservationDirection,
    ObservationSource,
    ObservedVehicleType,
    PlatformType,
    ReasonCode,
    ScreeningVerdict,
    UserRole,
    VehicleCategory,
    VehicleStatus,
)
from backend.app.models.gate import AccessDecision, EntryExitLog, Gate, SecurityAlert
from backend.app.models.identity import User, VehicleOwner
from backend.app.models.movement import CameraLane
from backend.app.models.observation import ObservationEvent
from backend.app.models.vehicle import Vehicle
from backend.app.services.direction_resolver import direction_resolver
from backend.app.services.policy_engine import evaluate_access_policy
from backend.app.whatsapp import (
    CloudAPIWhatsAppProvider,
    LocalIntakeWhatsAppProvider,
    MockWhatsAppProvider,
    WhatsAppProvider,
    get_whatsapp_provider,
)

# In-memory SQLite database for test isolation
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_1_whatsapp_providers():
    print("\n--- [TEST 1] WhatsApp Provider Abstraction ---")
    # Base class check
    assert issubclass(LocalIntakeWhatsAppProvider, WhatsAppProvider)
    assert issubclass(CloudAPIWhatsAppProvider, WhatsAppProvider)
    assert issubclass(MockWhatsAppProvider, WhatsAppProvider)

    # Provider instance
    mock_prov = MockWhatsAppProvider()
    assert mock_prov.is_available() is True
    res = mock_prov.send_message("9999999999", "Test alert")
    assert res.get("status") == "delivered"
    assert len(mock_prov.sent_messages) == 1

    local_prov = LocalIntakeWhatsAppProvider()
    assert local_prov.name == "local"

    cloud_prov = CloudAPIWhatsAppProvider()
    assert cloud_prov.name == "meta"

    print("  -> WhatsApp Provider classes verified.")


def test_2_policy_engine():
    print("\n--- [TEST 2] Access Control Policy Engine ---")
    # 1. Registered vehicle with known owner + confidence >= 0.70 + no cargo alerts -> ALLOW
    r1 = evaluate_access_policy(
        vehicle_registration_status="ACTIVE",
        owner_status="ACTIVE",
        plate_confidence=0.88,
        plate="PB65AB1234",
    )
    assert r1.decision == "ALLOW"
    assert r1.reason_code == ReasonCode.ALLOW_REGISTERED_VEHICLE.value
    assert r1.policy_version == "1.0"
    print("  -> Rule 1 (Registered Vehicle ALLOW): PASS")

    # 2. Plate read with confidence < 0.70 -> REVIEW
    r2 = evaluate_access_policy(
        vehicle_registration_status="ACTIVE",
        owner_status="ACTIVE",
        plate_confidence=0.62,
        plate="PB65AB1234",
    )
    assert r2.decision == "REVIEW"
    assert r2.reason_code == ReasonCode.REVIEW_LOW_CONFIDENCE_PLATE.value
    print("  -> Rule 2 (Low Confidence Plate REVIEW): PASS")

    # 3. Unreadable plate -> REVIEW
    r3 = evaluate_access_policy(plate="UNREADABLE", plate_confidence=0.95)
    assert r3.decision == "REVIEW"
    assert r3.reason_code == ReasonCode.REVIEW_UNREADABLE_PLATE.value
    print("  -> Rule 3 (Unreadable Plate REVIEW): PASS")

    # 4. Unknown vehicle -> REVIEW
    r4 = evaluate_access_policy(vehicle_registration_status=None, plate="CH01AB1111", plate_confidence=0.85)
    assert r4.decision == "REVIEW"
    assert r4.reason_code == ReasonCode.REVIEW_UNKNOWN_VEHICLE.value
    print("  -> Rule 4 (Unknown Vehicle REVIEW): PASS")

    # 5. Cargo screening with restricted items -> ALERT
    r5 = evaluate_access_policy(
        vehicle_registration_status="ACTIVE",
        owner_status="ACTIVE",
        plate_confidence=0.90,
        plate="PB65AB1234",
        cargo_alerts=["HAZMAT"],
    )
    assert r5.decision == "ALERT"
    assert r5.reason_code == ReasonCode.ALERT_RESTRICTED_ITEM.value
    print("  -> Rule 5 (Restricted Cargo Item ALERT): PASS")

    # 6. Cargo screening uncertain -> REVIEW
    r6 = evaluate_access_policy(
        vehicle_registration_status="ACTIVE",
        owner_status="ACTIVE",
        plate_confidence=0.90,
        plate="PB65AB1234",
        is_cargo_uncertain=True,
    )
    assert r6.decision == "REVIEW"
    assert r6.reason_code == ReasonCode.REVIEW_CARGO_SCREENING_UNCERTAIN.value
    print("  -> Rule 6 (Cargo Screening Uncertain REVIEW): PASS")

    # 7. Stolen or blacklisted vehicle -> ALERT
    r7 = evaluate_access_policy(
        vehicle_registration_status="BLACKLISTED",
        plate_confidence=0.90,
        plate="PB65AB1234",
    )
    assert r7.decision == "ALERT"
    assert r7.reason_code == ReasonCode.ALERT_BLACKLISTED_VEHICLE.value
    print("  -> Rule 7 (Blacklisted Vehicle ALERT): PASS")


def test_3_security_review_queue_and_triage():
    print("\n--- [TEST 3] Security Review Queue & Triage ---")
    db = TestingSessionLocal()
    # Seed gate and guard
    gate = Gate(id="GATE_1", name="Main Gate", camera_id="cam_main", status="ACTIVE")
    db.merge(gate)

    guard = User(
        id=uuid.uuid4(),
        username="guard_test",
        full_name="Officer Singh",
        email="singh@campus.edu",
        role=UserRole.GUARD,
        hashed_password="hash",
    )
    db.add(guard)
    db.commit()

    # Create low-confidence observation (access event requiring review)
    obs = ObservationEvent(
        id=uuid.uuid4(),
        gate_id="GATE_1",
        camera_id="cam_main",
        source=ObservationSource.FRIGATE,
        source_event_id="evt_test_101",
        raw_plate="PB65??1234",
        normalized_plate="PB651234",
        plate_confidence=0.55,  # low confidence
        vehicle_type=ObservedVehicleType.CAR,
        direction=ObservationDirection.UNKNOWN,
    )
    db.add(obs)

    # Create delivery order & invoice with restricted item (cargo event requiring review)
    order = DeliveryOrder(
        id=uuid.uuid4(),
        order_id="ORD-TEST-999",
        platform=PlatformType.ZOMATO,
        gate_id="GATE_1",
        delivery_vehicle_plate="DL01XY9999",
    )
    db.add(order)
    db.flush()

    invoice = Invoice(
        id=uuid.uuid4(),
        order_id=order.id,
        gate_id="GATE_1",
        confidence=0.88,
        source="LOCAL_INTAKE",
        overall_verdict=ScreeningVerdict.ALERT,
    )
    db.add(invoice)
    db.flush()

    item = InvoiceItem(
        id=uuid.uuid4(),
        invoice_id=invoice.id,
        item_name="Fireworks Sparkler",
        category="PYROTECHNICS",
        verdict=ScreeningVerdict.ALERT,
        reason_code="RESTRICTED_EXPLOSIVE",
    )
    db.add(item)
    db.commit()

    # Authenticate as guard
    app.dependency_overrides[require_staff] = lambda: CurrentUser(
        id=guard.id, username=guard.username, full_name=guard.full_name, role=UserRole.GUARD
    )

    # 1. GET /security/reviews
    resp = client.get("/security/reviews")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 2
    review_ids = [item["review_id"] for item in data["items"]]
    assert f"obs_{obs.id}" in review_ids
    assert f"cargo_{invoice.id}" in review_ids
    print(f"  -> GET /security/reviews: {data['total']} items returned (includes obs and cargo).")

    # 2. POST /security/reviews/{review_id}/triage for access observation
    triage_payload = {
        "action": "ALLOW",
        "guard_id": str(guard.id),
        "reason_notes": "Driver presented verified faculty ID card; plate confirmed physically as PB65AB1234.",
        "gate_override": "GATE_1",
    }
    resp2 = client.post(f"/security/reviews/obs_{obs.id}/triage", json=triage_payload)
    assert resp2.status_code == 200, resp2.text
    res_data2 = resp2.json()
    assert res_data2["status"] == "SUCCESS"
    assert res_data2["action"] == "ALLOW"
    print(f"  -> POST /security/reviews/obs_{obs.id}/triage (ALLOW): PASS, audit_id={res_data2['audit_id']}")

    # Verify immutable audit record in database
    audit_row = db.get(AccessDecision, uuid.UUID(res_data2["audit_id"]))
    assert audit_row is not None
    assert audit_row.decision == AccessState.ALLOWED
    assert audit_row.reason_code == "GUARD_ALLOW"
    assert "PB65" in audit_row.plate
    print("  -> Immutable AccessDecision persisted in DB: PASS")

    # 3. POST /security/reviews/{review_id}/triage for cargo invoice
    cargo_triage_payload = {
        "action": "REJECT",
        "guard_id": str(guard.id),
        "reason_notes": "Restricted pyrotechnic items prohibited on campus. Gate entry refused.",
    }
    resp3 = client.post(f"/security/reviews/cargo_{invoice.id}/triage", json=cargo_triage_payload)
    assert resp3.status_code == 200, resp3.text
    res_data3 = resp3.json()
    assert res_data3["status"] == "SUCCESS"
    assert res_data3["action"] == "REJECT"
    print(f"  -> POST /security/reviews/cargo_{invoice.id}/triage (REJECT): PASS, audit_id={res_data3['audit_id']}")

    db.close()


def test_4_vehicle_history_and_movements():
    print("\n--- [TEST 4] Vehicle History & Movement Timeline ---")
    db = TestingSessionLocal()
    gate = db.get(Gate, "GATE_1")
    if not gate:
        gate = Gate(id="GATE_1", name="Main Gate", camera_id="cam_main", status="ACTIVE")
        db.add(gate)
        db.commit()

    plate_test = "PB65XY8888"
    v = Vehicle(
        id=uuid.uuid4(),
        raw_plate=plate_test,
        normalized_plate=plate_test,
        vehicle_category=VehicleCategory.FACULTY,
        status=VehicleStatus.ACTIVE,
    )
    db.add(v)
    db.commit()

    # Add access decision
    dec = AccessDecision(
        id=uuid.uuid4(),
        plate=plate_test,
        normalized_plate=plate_test,
        gate_id="GATE_1",
        decision=AccessState.ALLOWED,
        reason_code=ReasonCode.ALLOW_REGISTERED_VEHICLE.value,
        reason="Registered faculty vehicle",
        confidence=0.96,
        timestamp=utc_now(),
    )
    db.add(dec)
    db.flush()

    # Add movement log
    log = EntryExitLog(
        id=uuid.uuid4(),
        vehicle_id=v.id,
        plate=plate_test,
        normalized_plate=plate_test,
        gate_id="GATE_1",
        direction=ObservationDirection.ENTRY,
        direction_method=DirectionMethod.CAMERA_ROLE,
        direction_confidence=0.95,
        decision=AccessState.ALLOWED,
        reason_code=ReasonCode.ALLOW_REGISTERED_VEHICLE.value,
        decision_id=dec.id,
        timestamp=utc_now(),
        note="Normal verified entry",
    )
    db.add(log)
    db.commit()

    # Test GET /vehicles/{plate}/history
    resp = client.get(f"/vehicles/{plate_test}/history")
    assert resp.status_code == 200, resp.text
    hist = resp.json()
    assert hist["plate"] == plate_test
    assert hist["registered"] is True
    assert len(hist["timeline"]) >= 1

    item = hist["timeline"][0]
    assert item["gate"]["id"] == "GATE_1"
    assert item["direction"] == "ENTRY"
    assert item["decision"] == "ALLOWED"
    assert item["reason_code"] == ReasonCode.ALLOW_REGISTERED_VEHICLE.value
    assert item["guard_override_notes"] == "Normal verified entry"
    print("  -> GET /vehicles/{plate}/history returned full timeline (gate, direction, decision, reason_code, notes): PASS")

    # Test GET /logs
    resp_logs = client.get("/logs", params={"plate": plate_test})
    assert resp_logs.status_code == 200, resp_logs.text
    logs_data = resp_logs.json()
    assert logs_data["total"] >= 1
    m_entry = logs_data["items"][0]
    assert m_entry["direction"] == "ENTRY"
    assert m_entry["decision"] == "ALLOWED"
    assert m_entry["reason_code"] == ReasonCode.ALLOW_REGISTERED_VEHICLE.value
    print("  -> GET /logs returned movement entry with decision & reason_code: PASS")
    db.close()


def test_5_lane_direction_and_provisional():
    print("\n--- [TEST 5] Lane Direction & Provisional Status ---")
    db = TestingSessionLocal()
    # 1. Observation from camera without lane role -> Direction UNKNOWN, provisional = True
    obs_unmapped = ObservationEvent(
        id=uuid.uuid4(),
        gate_id="GATE_1",
        camera_id="cam_unmapped",
        source=ObservationSource.FRIGATE,
        source_event_id="evt_prov_1",
        raw_plate="PB65AA1111",
        normalized_plate="PB65AA1111",
        plate_confidence=0.9,
        direction=ObservationDirection.UNKNOWN,
    )
    db.add(obs_unmapped)
    db.commit()

    res_unknown = direction_resolver.resolve(db, obs_unmapped)
    assert res_unknown.is_known is False
    assert res_unknown.is_provisional is True
    print("  -> Unmapped camera observation is provisional (is_provisional=True): PASS")

    # 2. Camera with declared ENTRY_LANE -> Direction ENTRY, provisional = False
    lane = CameraLane(
        camera_id="cam_entry_lane",
        gate_id="GATE_1",
        lane_role=LaneRole.ENTRY_LANE,
        is_active=True,
    )
    db.merge(lane)

    obs_entry = ObservationEvent(
        id=uuid.uuid4(),
        gate_id="GATE_1",
        camera_id="cam_entry_lane",
        source=ObservationSource.FRIGATE,
        source_event_id="evt_entry_1",
        raw_plate="PB65AA2222",
        normalized_plate="PB65AA2222",
        plate_confidence=0.9,
        direction=ObservationDirection.UNKNOWN,
    )
    db.add(obs_entry)
    db.commit()

    res_entry = direction_resolver.resolve(db, obs_entry)
    assert res_entry.is_known is True
    assert res_entry.direction == ObservationDirection.ENTRY
    assert res_entry.is_provisional is False
    print("  -> CameraLane ENTRY_LANE resolves direction to ENTRY and establishes confirmed status (is_provisional=False): PASS")
    db.close()


if __name__ == "__main__":
    test_1_whatsapp_providers()
    test_2_policy_engine()
    test_3_security_review_queue_and_triage()
    test_4_vehicle_history_and_movements()
    test_5_lane_direction_and_provisional()
    print("\n========================================================")
    print("ALL BACKEND CORE FEATURE TESTS PASSED SUCCESSFULLY!")
    print("========================================================")
