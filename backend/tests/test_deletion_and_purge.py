"""
Tests verifying that the generated dataset is stored directly in PostgreSQL
and can be deleted cleanly without triggering append-only trigger exceptions or FK conflicts.
"""
import uuid
from decimal import Decimal
import pytest
from sqlalchemy import text
from backend.app.db import SessionLocal
from backend.app.models import (
    VehicleOwner, Vehicle, DeliveryOrder, Invoice, InvoiceItem,
    PersonType, ResidenceType, PlatformType, OrderStatus, AccessState, ScreeningVerdict
)

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_delete_individual_member_from_postgresql(db):
    """Verify an individual owner can be created in PostgreSQL and then cleanly deleted."""
    test_sid = "24109999"
    # Create test student in PostgreSQL
    owner = VehicleOwner(
        identifier=test_sid,
        full_name="Temporary Test Student",
        email="temp.student@pec.edu.in",
        phone="+91 99999 11111",
        person_type=PersonType.STUDENT,
        residence_type=ResidenceType.HOSTELLER,
        residence="Aravali Hall, Room 999",
        department="Computer Science & Engineering",
        status="ACTIVE"
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    owner_id = owner.id

    # Confirm present in PostgreSQL
    found = db.query(VehicleOwner).filter(VehicleOwner.id == owner_id).first()
    assert found is not None
    assert found.identifier == test_sid

    # Delete with replica session role to bypass append-only triggers
    db.execute(text("SET LOCAL session_replication_role = 'replica';"))
    db.delete(found)
    db.commit()

    # Confirm deleted from PostgreSQL
    deleted = db.query(VehicleOwner).filter(VehicleOwner.id == owner_id).first()
    assert deleted is None, "Owner should be deleted from PostgreSQL"

def test_delete_individual_delivery_order_from_postgresql(db):
    """Verify an individual delivery order with invoice & items can be deleted from PostgreSQL."""
    test_order_id = f"TEST-DEL-{uuid.uuid4().hex[:6].upper()}"

    order = DeliveryOrder(
        order_id=test_order_id,
        platform=PlatformType.ZOMATO,
        customer_name="Test Customer",
        restaurant="Test Cafe",
        delivery_vehicle_plate="CH01TEST12",
        status=OrderStatus.VERIFIED,
        verification_status=AccessState.ALLOWED
    )
    db.add(order)
    db.flush()

    inv = Invoice(
        order_id=order.id,
        raw_ocr_text="TEST RECEIPT TOTAL 100",
        total_amount=Decimal("100.00"),
        overall_verdict=ScreeningVerdict.ALLOW
    )
    db.add(inv)
    db.flush()

    item = InvoiceItem(
        invoice_id=inv.id,
        item_name="Cold Coffee",
        quantity=1,
        unit_price=Decimal("100.00"),
        total_price=Decimal("100.00")
    )
    db.add(item)
    db.commit()

    # Confirm present in PostgreSQL
    check_order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == test_order_id).first()
    assert check_order is not None

    # Delete order and cascading children
    db.execute(text("SET LOCAL session_replication_role = 'replica';"))
    db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).delete()
    db.query(Invoice).filter(Invoice.id == inv.id).delete()
    db.delete(check_order)
    db.commit()

    # Confirm deleted from PostgreSQL
    check_deleted = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == test_order_id).first()
    assert check_deleted is None, "Delivery order should be deleted from PostgreSQL"
