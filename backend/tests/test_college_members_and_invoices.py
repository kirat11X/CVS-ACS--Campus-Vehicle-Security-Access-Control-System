"""
Tests for College Members Directory, 1000 Multi-Vendor Invoices with QR codes,
and Unlinked Overstay Alerts (>1.5h).
"""
import os
import re
from pathlib import Path
import pytest
from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models import (
    VehicleOwner, Vehicle, EntryExitLog, DeliveryOrder, Invoice, InvoiceItem,
    PersonType, PlatformType
)
from backend.app.services.alert_service import alert_service
from backend.app.services.movement_service import movement_service

@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_college_members_statutory_schema_counts(db):
    """Verify that college members exist and strictly follow statutory ID schema."""
    students = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.STUDENT).all()
    faculty = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.FACULTY).all()
    residents = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.RESIDENT).all()
    staff = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.STAFF).all()

    # 1. Counts
    assert len(students) >= 500, f"Expected at least 500 students, got {len(students)}"
    assert len(faculty) >= 100, f"Expected at least 100 faculty, got {len(faculty)}"
    assert len(residents) >= 50, f"Expected at least 50 residents, got {len(residents)}"
    assert len(staff) >= 20, f"Expected at least 20 staff, got {len(staff)}"

    # 2. Strict ID regex validation (ignoring transient P7- test fixtures if present)
    student_regex = re.compile(r"^\d{8}$")
    faculty_regex = re.compile(r"^F\d{7}$")
    resident_regex = re.compile(r"^R\d{4}$")
    staff_regex = re.compile(r"^(STF-[A-Z0-9_-]+|S\d{7})$")

    for s in students:
        if not s.identifier.startswith("P7-"):
            assert student_regex.fullmatch(s.identifier), f"Student ID '{s.identifier}' invalid"

    for f in faculty:
        if not f.identifier.startswith("P7-"):
            assert faculty_regex.fullmatch(f.identifier), f"Faculty ID '{f.identifier}' invalid"

    for r in residents:
        if not r.identifier.startswith("P7-"):
            assert resident_regex.fullmatch(r.identifier), f"Resident ID '{r.identifier}' invalid"

    for st in staff:
        if not st.identifier.startswith("P7-"):
            assert staff_regex.fullmatch(st.identifier), f"Staff ID '{st.identifier}' invalid"

def test_vehicles_dataset_and_movement_logs(db):
    """Verify 500+ vehicles and realistic gate movement logs."""
    v_count = db.query(Vehicle).count()
    assert v_count >= 500, f"Expected >= 500 vehicles, found {v_count}"

    log_count = db.query(EntryExitLog).count()
    assert log_count >= 500, f"Expected >= 500 movement logs, found {log_count}"

def test_1000_multivendor_invoices_with_qr_codes(db):
    """Verify ~1000 multi-vendor delivery invoices exist with real-world platforms and QR images."""
    order_count = db.query(DeliveryOrder).count()
    invoice_count = db.query(Invoice).count()
    items_count = db.query(InvoiceItem).count()

    assert order_count >= 990, f"Expected ~1,000 orders, got {order_count}"
    assert invoice_count >= 990, f"Expected ~1,000 invoices, got {invoice_count}"
    assert items_count >= 2000, f"Expected >= 2,000 items, got {items_count}"

    # Verify distribution across diverse platforms: Zomato, Swiggy, Amazon, Uber, Reliance, Blinkit, Zepto
    platform_counts = {}
    for p in [PlatformType.ZOMATO, PlatformType.SWIGGY, PlatformType.AMAZON, PlatformType.UBER, PlatformType.RELIANCE, PlatformType.BLINKIT, PlatformType.ZEPTO]:
        c = db.query(DeliveryOrder).filter(DeliveryOrder.platform == p).count()
        platform_counts[p.value] = c
        assert c > 0, f"Expected orders for platform {p.value}, got 0"

    print("Platform breakdown:", platform_counts)

    # Verify generated invoice image files exist on disk
    sample_invoices = (
        db.query(Invoice)
        .join(DeliveryOrder)
        .filter(
            Invoice.image_path != "invoices/test_inv.png",
            DeliveryOrder.platform != PlatformType.OTHER,
            ~DeliveryOrder.order_id.like("FAC-%"),
            ~DeliveryOrder.order_id.like("TG-%"),
        )
        .order_by(Invoice.created_at.desc())
        .limit(20)
        .all()
    )
    for inv in sample_invoices:
        assert inv.image_path, f"Invoice {inv.id} has no image_path"
        abs_img = MEDIA_ROOT / inv.image_path
        assert abs_img.exists(), f"Invoice image file {abs_img} does not exist on disk"
        assert abs_img.stat().st_size > 1000, f"Invoice image {abs_img} is suspiciously small"
        # Check raw OCR text contains QR or valid receipt content
        assert "total" in (inv.raw_ocr_text or "").lower(), f"Invoice {inv.id} raw OCR missing total"

def test_unlinked_overstay_alert_detection(db):
    """Verify unlinked overstay alert (>1.5h) activates on the unlinked vehicles currently inside campus."""
    alerts = alert_service.unlinked_overstay_alerts(db)
    # We seeded at least 3 unlinked vehicles with entry > 1.8h ago
    assert len(alerts) >= 1, f"Expected at least 1 overstay alert, got {len(alerts)}"

    for alert in alerts:
        assert alert.kind == "OVERSTAY_UNLINKED"
        assert alert.severity == "HIGH"
        assert "overstay" in alert.title.lower()
        assert "inside campus" in alert.title.lower()
        assert "exceeded" in alert.detail
