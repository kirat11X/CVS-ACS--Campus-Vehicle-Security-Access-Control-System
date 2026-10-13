import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.config import DATABASE_URL
from backend.app.models import (
    Base,
    VehicleCategory,
    VehicleStatus,
    AccessState,
    GateDirection,
    GateStatus,
    PlatformType,
    OrderStatus,
    AlertSeverity,
    AlertStatus,
    ReasonCode,
    User,
    VehicleOwner,
    Visitor,
    Vehicle,
    DeliveryVehicle,
    Gate,
    AccessDecision,
    EntryExitLog,
    SecurityAlert,
    DeliveryOrder,
    Invoice,
    InvoiceItem
)

def run_tests():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    now = datetime.now(timezone.utc)

    print("\n--- TEST 1: Create System Users ---")
    admin_user = User(
        username=f"admin_{uuid.uuid4().hex[:6]}",
        email=f"admin_{uuid.uuid4().hex[:6]}@campus.edu",
        full_name="Chief Security Officer",
        role="ADMIN"
    )
    guard_user = User(
        username=f"guard_{uuid.uuid4().hex[:6]}",
        email=f"guard_{uuid.uuid4().hex[:6]}@campus.edu",
        full_name="Gate 1 Officer",
        role="GUARD"
    )
    session.add_all([admin_user, guard_user])
    session.commit()
    print(f"  [PASS] Created users: {admin_user.username} ({admin_user.id}), {guard_user.username}")

    print("\n--- TEST 2: Create Gates ---")
    gate1 = session.query(Gate).filter_by(id="GATE_1").first()
    if not gate1:
        gate1 = Gate(id="GATE_1", name="Main North Gate", location="Sector North", status=GateStatus.ACTIVE, camera_id="gate_cam")
        session.add(gate1)
    gate2 = session.query(Gate).filter_by(id="GATE_2").first()
    if not gate2:
        gate2 = Gate(id="GATE_2", name="South Gate", location="Sector South", status=GateStatus.ACTIVE, camera_id="gate_2_cam")
        session.add(gate2)
    gate3 = session.query(Gate).filter_by(id="GATE_3").first()
    if not gate3:
        gate3 = Gate(id="GATE_3", name="Hostel East Gate", location="Hostel Sector", status=GateStatus.ACTIVE, camera_id="gate_3_cam")
        session.add(gate3)
    session.commit()
    print(f"  [PASS] Verified 3 Gates: GATE_1, GATE_2, GATE_3")

    print("\n--- TEST 3: Create Vehicle Owner (Student) ---")
    student = VehicleOwner(
        identifier=f"STUDENT-2026-{uuid.uuid4().hex[:4]}",
        full_name="Kirat Singh",
        email="kirat@campus.edu",
        phone="+919876543210",
        owner_type="STUDENT",
        department_or_hostel="Hostel Block B, Room 204"
    )
    session.add(student)
    session.commit()
    print(f"  [PASS] Created Student Owner: {student.full_name} ({student.identifier})")

    print("\n--- TEST 4: Create Registered Student Vehicle ---")
    test_plate_raw = "PB65 AB 1234"
    test_plate_norm = "PB65AB1234"
    
    # Check if already exists from earlier test
    existing = session.query(Vehicle).filter_by(normalized_plate=test_plate_norm).first()
    if existing:
        session.delete(existing)
        session.commit()

    student_car = Vehicle(
        raw_plate=test_plate_raw,
        normalized_plate=test_plate_norm,
        vehicle_category=VehicleCategory.STUDENT,
        status=VehicleStatus.ACTIVE,
        owner_id=student.id,
        make_model="Hyundai i20",
        color="White",
        valid_from=now - timedelta(days=30),
        valid_until=now + timedelta(days=335),
        notes="Authorized campus parking sticker #ST-902"
    )
    session.add(student_car)
    session.commit()
    print(f"  [PASS] Created Student Vehicle: {student_car.raw_plate} -> {student_car.normalized_plate}")

    print("\n--- TEST 5: Test Unique Constraint on normalized_plate ---")
    duplicate_car = Vehicle(
        raw_plate="pb65-ab-1234",
        normalized_plate=test_plate_norm,
        vehicle_category=VehicleCategory.STUDENT,
        status=VehicleStatus.ACTIVE
    )
    session.add(duplicate_car)
    try:
        session.commit()
        print("  [FAIL] Duplicate normalized_plate was allowed unexpectedly!", file=sys.stderr)
        sys.exit(1)
    except IntegrityError:
        session.rollback()
        print("  [PASS] Unique constraint correctly rejected duplicate normalized_plate!")

    print("\n--- TEST 6: Create Visitor & Visitor Vehicle ---")
    visitor = Visitor(
        visitor_name="Prof. Sharma",
        phone="+919123456780",
        purpose="Guest Lecture at Dept of Computer Science",
        host_owner_id=student.id,
        allowed_gate_id="GATE_1",
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(hours=8),
        status="ACTIVE"
    )
    session.add(visitor)
    session.commit()

    visitor_plate_raw = f"DL 03 XY {uuid.uuid4().hex[:4].upper()}"
    visitor_plate_norm = visitor_plate_raw.replace(" ", "")
    visitor_car = Vehicle(
        raw_plate=visitor_plate_raw,
        normalized_plate=visitor_plate_norm,
        vehicle_category=VehicleCategory.VISITOR,
        status=VehicleStatus.ACTIVE,
        visitor_id=visitor.id,
        make_model="Honda City",
        color="Silver"
    )
    session.add(visitor_car)
    session.commit()
    print(f"  [PASS] Created Visitor: {visitor.visitor_name} with vehicle {visitor_car.normalized_plate}")

    print("\n--- TEST 7: Create Delivery Order, Invoice & Items ---")
    order_id_code = f"ORD-2026-{uuid.uuid4().hex[:5].upper()}"
    deliv_plate_code = uuid.uuid4().hex[:4].upper()
    delivery_plate_raw = f"PB 65 DL {deliv_plate_code}"
    delivery_plate_norm = f"PB65DL{deliv_plate_code}"
    delivery_order = DeliveryOrder(
        order_id=order_id_code,
        platform=PlatformType.ZOMATO,
        customer_id=student.id,
        customer_name=student.full_name,
        restaurant="Campus Pizzeria",
        delivery_vehicle_plate=delivery_plate_norm,
        delivery_agent_name="Suresh Kumar",
        delivery_agent_phone="+919800011122",
        order_timestamp=now,
        status=OrderStatus.VERIFIED,
        verification_status=AccessState.ALLOWED,
        gate_id="GATE_1"
    )
    session.add(delivery_order)
    session.commit()

    invoice = Invoice(
        order_id=delivery_order.id,
        image_path="/media/invoices/test_inv.png",
        raw_ocr_text="CAMPUS FOOD DELIVERY INVOICE\nOrder ID: " + order_id_code,
        confidence=0.98,
        vendor="Zomato",
        subtotal=488.00,
        tax=25.90,
        total_amount=543.90
    )
    session.add(invoice)
    session.commit()

    item1 = InvoiceItem(invoice_id=invoice.id, item_name="Margherita Pizza", quantity=1, unit_price=299.0, total_price=299.0)
    item2 = InvoiceItem(invoice_id=invoice.id, item_name="Garlic Bread", quantity=1, unit_price=139.0, total_price=139.0)
    session.add_all([item1, item2])
    session.commit()
    print(f"  [PASS] Created Delivery Order ({delivery_order.order_id}) with Invoice and 2 items")

    print("\n--- TEST 8: Create Delivery Vehicle Fleet Profile ---")
    delivery_car = Vehicle(
        raw_plate=delivery_plate_raw,
        normalized_plate=delivery_plate_norm,
        vehicle_category=VehicleCategory.DELIVERY,
        status=VehicleStatus.ACTIVE,
        make_model="Bajaj Pulsar 150"
    )
    session.add(delivery_car)
    session.commit()

    delivery_profile = DeliveryVehicle(
        vehicle_id=delivery_car.id,
        platform=PlatformType.ZOMATO,
        driver_name="Suresh Kumar",
        driver_phone="+919800011122",
        is_verified=True
    )
    session.add(delivery_profile)
    session.commit()
    print(f"  [PASS] Created Delivery Fleet Profile: {delivery_profile.driver_name} -> {delivery_car.normalized_plate}")

    print("\n--- TEST 9: Create Access Decision & EntryExitLog ---")
    decision = AccessDecision(
        plate=student_car.raw_plate,
        normalized_plate=student_car.normalized_plate,
        gate_id="GATE_1",
        decision=AccessState.ALLOWED,
        reason_code=ReasonCode.VEHICLE_REGISTERED.value,
        reason="Active student vehicle registration verified.",
        confidence=0.97,
        context_data={"owner_id": student.identifier, "sticker": "ST-902"},
        timestamp=now
    )
    session.add(decision)
    session.commit()

    entry_log = EntryExitLog(
        vehicle_id=student_car.id,
        plate=student_car.raw_plate,
        normalized_plate=student_car.normalized_plate,
        gate_id="GATE_1",
        direction=GateDirection.ENTRY,
        timestamp=now,
        confidence=0.97,
        decision=AccessState.ALLOWED,
        reason_code=ReasonCode.VEHICLE_REGISTERED.value,
        frigate_event_id=f"frigate_evt_{uuid.uuid4().hex[:8]}",
        decision_id=decision.id
    )
    session.add(entry_log)
    session.commit()
    print(f"  [PASS] Created Access Decision ({decision.decision}) and EntryLog (ID: {entry_log.id})")

    print("\n--- TEST 10: Create Security Alert ---")
    alert = SecurityAlert(
        gate_id="GATE_1",
        log_id=entry_log.id,
        severity=AlertSeverity.LOW,
        status=AlertStatus.PENDING,
        title="Routine Verification Logged",
        description="Student entry recorded under normal gate operation.",
        assigned_to_id=guard_user.id
    )
    session.add(alert)
    session.commit()
    print(f"  [PASS] Created Security Alert: {alert.title} (Severity: {alert.severity})")

    print("\n--- TEST 11: Validate ORM Relationships Navigation ---")
    # Reload student from db and navigate relationships
    reloaded_student = session.query(VehicleOwner).filter_by(id=student.id).first()
    assert len(reloaded_student.vehicles) >= 1, "student.vehicles relationship failed"
    print(f"  -> Student owns {len(reloaded_student.vehicles)} vehicle(s): {[v.normalized_plate for v in reloaded_student.vehicles]}")
    
    assert reloaded_student.vehicles[0].owner.identifier == student.identifier
    print(f"  -> Vehicle owner navigation confirmed: {reloaded_student.vehicles[0].owner.full_name}")

    reloaded_gate = session.query(Gate).filter_by(id="GATE_1").first()
    assert len(reloaded_gate.entry_exit_logs) >= 1, "gate.entry_exit_logs relationship failed"
    print(f"  -> Gate 1 has {len(reloaded_gate.entry_exit_logs)} logged events")

    reloaded_order = session.query(DeliveryOrder).filter_by(id=delivery_order.id).first()
    assert len(reloaded_order.invoices) == 1, "order.invoices relationship failed"
    assert len(reloaded_order.invoices[0].items) == 2, "invoice.items relationship failed"
    print(f"  -> Order has {len(reloaded_order.invoices)} invoice with {len(reloaded_order.invoices[0].items)} items: {[i.item_name for i in reloaded_order.invoices[0].items]}")

    reloaded_visitor = session.query(Visitor).filter_by(id=visitor.id).first()
    assert reloaded_visitor.host_owner.identifier == student.identifier, "visitor.host_owner failed"
    assert len(reloaded_visitor.vehicles) == 1, "visitor.vehicles failed"
    print(f"  -> Visitor hosted by {reloaded_visitor.host_owner.full_name} with vehicle {reloaded_visitor.vehicles[0].normalized_plate}")

    session.close()
    print("\n========================================================")
    print("PHASE 1 DATABASE MODELS & MIGRATIONS: ALL CHECKS PASSED!")
    print("========================================================")

if __name__ == "__main__":
    run_tests()
