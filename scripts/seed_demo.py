"""
Seeds the mid-term demo data (Phase 7). Idempotent: creates what is missing, never deletes,
never overwrites an existing row or password.

    PYTHONPATH=. .venv/bin/python scripts/seed_demo.py [--no-sightings] [--no-delivery] [--reset-demo-passwords]

* Gates GATE_1..3 (checked; created only if missing).
* Owners: Demo Student (SID 24103999, hostel), Dr. Demo Faculty (FAC-CSE-014, CSE Department),
  Estate Office Staff (STF-EST-022, Estate Office).
* Vehicles: CH01AB1234 -> student, HR26DK0042 -> staff, PB65XY7788 -> faculty, plus CH01AB1247
  (faculty) and CH01AB1248 (staff) so a read of CH01AB124 has several close plates (NEEDS REVIEW).
  UP32KL5567 and CH04MN3090 stay unregistered. Each new vehicle gets an ADMIN VehicleLinkEvent.
* Accounts: guard1 / Guard@12345 (GUARD), admin / Admin@12345 (ADMIN), only if missing
  (existing passwords are kept unless --reset-demo-passwords is given).
* media/demo/invoice_D-20481.png (+ .pdf): the slide-8 sample invoice.
* Demo guard sightings of the slide-6/7 reads (only for plates never seen before) and the
  screening of order D-20481 (only if that order was never screened).
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PIL import Image, ImageDraw, ImageFont

from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models import (
    DeliveryOrder, DeliverySource, Gate, GateStatus, Invoice, LinkMethod, ObservationDirection, ObservationEvent,
    PersonType, ResidenceType, User, UserRole, Vehicle, VehicleCategory, VehicleLinkEvent, VehicleOwner, VehicleStatus,
)
from backend.app.schemas.feed import ManualObservationCreate
from backend.app.services.auth_service import hash_password, verify_password
from backend.app.services.feed_events import record_registry_update
from backend.app.services.observation_service import ObservationService
from backend.app.services.plate_normalizer import format_plate_display

DEMO_ORDER = "D-20481"
INVOICE_PNG = MEDIA_ROOT / "demo" / f"invoice_{DEMO_ORDER}.png"
INVOICE_PDF = MEDIA_ROOT / "demo" / f"invoice_{DEMO_ORDER}.pdf"

GATES = [
    ("GATE_1", "Main North Gate", "gate_cam"),
    ("GATE_2", "South Gate", "gate_2_cam"),
    ("GATE_3", "Hostel East Gate", "gate_3_cam"),
]
ACCOUNTS = [
    ("guard1", "Gate 1 Guard", "guard1@campus.edu", UserRole.GUARD, "Guard@12345"),
    ("admin", "Campus Admin", "admin@campus.edu", UserRole.ADMIN, "Admin@12345"),
]
OWNERS = [
    dict(identifier="24103999", full_name="Demo Student", person_type=PersonType.STUDENT,
         residence_type=ResidenceType.HOSTELLER, residence="Hostel BH-4, Room 212", department="Computer Science & Engineering"),
    dict(identifier="F1002014", full_name="Dr. Demo Faculty", person_type=PersonType.FACULTY,
         residence_type=ResidenceType.OFF_CAMPUS, residence="Sector 12, Chandigarh", department="CSE Department"),
    dict(identifier="R1042", full_name="Col. R. S. Verma (Retd.)", person_type=PersonType.RESIDENT,
         residence_type=ResidenceType.OFF_CAMPUS, residence="House 1042, Campus Enclave", department=None),
    dict(identifier="STF-EST-022", full_name="Estate Office Staff", person_type=PersonType.STAFF,
         residence_type=ResidenceType.OFF_CAMPUS, residence="Sector 25, Chandigarh", department="Estate Office"),
]
VEHICLES = [
    ("CH01AB1234", VehicleCategory.STUDENT, "24103999", "Honda Activa", "Grey"),
    ("HR26DK0042", VehicleCategory.STAFF, "STF-EST-022", "Maruti Swift", "White"),
    ("PB65XY7788", VehicleCategory.FACULTY, "F1002014", "Hyundai Creta", "Blue"),
    ("CH01AB1247", VehicleCategory.FACULTY, "F1002014", "Hero Splendor", "Black"),
    ("CH01AB1248", VehicleCategory.STAFF, "STF-EST-022", "Tata Nexon", "Red"),
]
UNREGISTERED = ["UP32KL5567", "CH04MN3090"]
# Slide 6 / 7 reads, typed by a guard ("Simulate a plate"): (read, gate, direction)
SIGHTINGS = [
    ("CH01AB11234", "GATE_2", ObservationDirection.ENTRY),  # 1 extra character -> CH01AB1234 (student)
    ("HR26DK004Z", "GATE_1", ObservationDirection.ENTRY),   # Z read for 2 -> HR26DK0042 (staff)
    ("PB65XY7788", "GATE_3", ObservationDirection.ENTRY),   # exact -> faculty
    ("CH01AB124", "GATE_2", ObservationDirection.ENTRY),    # several close plates -> NEEDS REVIEW
    ("UP332KL5567", "GATE_1", ObservationDirection.ENTRY),  # not in registry -> UNLINKED
]
INVOICE_LINES = [
    ("Instant noodles 70g", 4, "56.00"),
    ("Cola 750 ml", 2, "80.00"),
    ("Toilet cleaner 500 ml", 1, "99.00"),
    ("Cigarettes pack of 20", 1, "350.00"),
    ("Notebook A4 ruled", 2, "90.00"),
]

def say(status: str, message: str) -> None:
    print(f"  [{status:<9}] {message}")

def _font(size: int, bold: bool = False):
    names = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    for folder in ("/usr/share/fonts/dejavu-sans-fonts", "/usr/share/fonts/liberation-sans-fonts", "/usr/share/fonts/truetype/dejavu"):
        for name in names:
            path = Path(folder) / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)

def generate_invoice(order_id: str = DEMO_ORDER, png_path: Path = INVOICE_PNG, pdf_path: Path = INVOICE_PDF) -> None:
    """The slide-8 sample invoice: large, clear type so OCR reads it reliably."""
    width, height = 1000, 1240
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    ink, muted = (20, 20, 20), (110, 110, 110)
    regular, bold, small = _font(34), _font(34, bold=True), _font(26)
    left, qty_right, amount_right = 60, 700, 940

    def right(x, y, text, font, fill=ink):
        d.text((x - d.textlength(text, font=font), y), text, font=font, fill=fill)

    d.text((left, 50), "DEMO MART", font=_font(60, bold=True), fill=ink)
    d.text((left, 130), "TAX INVOICE · SAMPLE", font=_font(30), fill=muted)
    d.text((left, 200), f"Order #{order_id}", font=bold, fill=ink)
    right(amount_right, 200, "10 Oct 2026", regular)
    d.line((left, 270, amount_right, 270), fill=ink, width=3)
    d.text((left, 295), "Item", font=bold, fill=ink)
    right(qty_right, 295, "Qty", bold)
    right(amount_right, 295, "Amount", bold)
    d.line((left, 352, amount_right, 352), fill=muted, width=2)
    y = 380
    for name, qty, amount in INVOICE_LINES:
        d.text((left, y), name, font=regular, fill=ink)
        right(qty_right, y, str(qty), regular)
        right(amount_right, y, amount, regular)
        y += 70
    d.line((left, y + 5, amount_right, y + 5), fill=muted, width=2)
    y += 30
    for label, amount, font in (("Subtotal", "675.00", regular), ("Delivery", "25.00", regular), ("TOTAL", "700.00", _font(40, bold=True))):
        d.text((left, y), label, font=font, fill=ink)
        right(amount_right, y, amount, font)
        y += 70
    d.line((left, y + 10, amount_right, y + 10), fill=ink, width=3)
    d.text((left, y + 40), "Sample invoice for demonstration · not a real order", font=small, fill=muted)

    png_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(png_path, "PNG")
    if pdf_path is not None:
        img.save(pdf_path, "PDF", resolution=150.0)
    say("written", f"{png_path}" + (f" and {pdf_path.name}" if pdf_path is not None else ""))

def seed_gates(db) -> None:
    for gate_id, name, camera in GATES:
        gate = db.get(Gate, gate_id)
        if gate:
            say("exists", f"{gate_id} {gate.name} ({gate.status.value}, camera {gate.camera_id})")
            continue
        camera_taken = db.query(Gate.id).filter(Gate.camera_id == camera, Gate.status != GateStatus.INACTIVE).first()
        db.add(Gate(id=gate_id, name=name, camera_id=None if camera_taken else camera, status=GateStatus.ACTIVE))
        db.commit()
        say("created", f"{gate_id} {name}")

def seed_accounts(db, reset_passwords: bool = False) -> User:
    admin = None
    for username, full_name, email, role, password in ACCOUNTS:
        user = db.query(User).filter(User.username == username).first()
        if user and reset_passwords and not verify_password(password, user.hashed_password):
            user.hashed_password = hash_password(password)  # explicit opt-in only
            db.commit()
            say("updated", f"{username} ({user.role}) password set to the demo password (--reset-demo-passwords)")
        elif user:
            works = verify_password(password, user.hashed_password)
            say("exists", f"{username} ({user.role}) password left unchanged; demo password {'works' if works else 'does NOT work'}"
                + ("" if user.is_active else "; account is DISABLED"))
        else:
            if db.query(User.id).filter(User.email == email).first():
                email = f"{username}.demo@campus.edu"
            user = User(username=username, full_name=full_name, email=email, role=role.value,
                        hashed_password=hash_password(password), is_active=True)
            db.add(user)
            db.commit()
            say("created", f"{username} / {password} ({role.value})")
        if role == UserRole.ADMIN and user.role == UserRole.ADMIN.value:
            admin = user
    if admin is None:
        admin = db.query(User).filter(User.role == UserRole.ADMIN.value, User.is_active.is_(True)).first()
    return admin

def seed_owners(db, admin: User) -> None:
    for spec in OWNERS:
        owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == spec["identifier"]).first()
        if owner:
            say("exists", f"owner {owner.identifier} {owner.full_name} ({owner.person_type.value})")
            continue
        db.add(VehicleOwner(status="ACTIVE", created_by_id=admin.id if admin else None, **spec))
        db.commit()
        say("created", f"owner {spec['identifier']} {spec['full_name']} ({spec['person_type'].value})")

def seed_vehicles(db, admin: User) -> None:
    for plate, category, owner_identifier, make_model, color in VEHICLES:
        owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == owner_identifier).one()
        vehicle = db.query(Vehicle).filter(Vehicle.normalized_plate == plate).first()
        if vehicle:
            note = "" if vehicle.owner_id == owner.id else " (WARNING: linked to another owner, left as is)"
            say("exists", f"{plate} {vehicle.vehicle_category.value} {vehicle.status.value}{note}")
            continue
        vehicle = Vehicle(raw_plate=format_plate_display(plate), normalized_plate=plate, vehicle_category=category,
                          status=VehicleStatus.ACTIVE, owner_id=owner.id, make_model=make_model, color=color,
                          notes="Demo vehicle (scripts/seed_demo.py)", created_by_id=admin.id if admin else None)
        db.add(vehicle)
        db.flush()
        if admin:
            db.add(VehicleLinkEvent(vehicle_id=vehicle.id, owner_id=owner.id, method=LinkMethod.ADMIN,
                                    evidence_note="Demo seed (scripts/seed_demo.py)", linked_by_id=admin.id))
        record_registry_update(db, plate)
        db.commit()
        say("created", f"{plate} {category.value} -> {owner.full_name} ({owner.identifier})")
    for plate in UNREGISTERED:
        if db.query(Vehicle.id).filter(Vehicle.normalized_plate == plate).first():
            say("WARNING", f"{plate} should stay unregistered for the demo but is in the registry (left as is)")
        else:
            say("ok", f"{plate} is not registered (as intended)")

def seed_sightings(db, guard: User) -> None:
    for read, gate_id, direction in SIGHTINGS:
        if db.query(ObservationEvent.id).filter(ObservationEvent.normalized_plate == read).first():
            say("exists", f"sighting of {read} already recorded")
            continue
        ObservationService.create_manual_observation(
            db, ManualObservationCreate(gate_id=gate_id, plate=read, direction=direction,
                                        note="Demo sighting (scripts/seed_demo.py)"), guard.id)
        say("created", f"guard sighting {read} at {gate_id} ({direction.value})")

def seed_delivery(db) -> None:
    from backend.app.services.delivery_screening_service import delivery_screening_service
    order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == DEMO_ORDER).first()
    if order and db.query(Invoice.id).filter(Invoice.order_id == order.id, Invoice.source.isnot(None)).first():
        say("exists", f"order {DEMO_ORDER} already screened")
        return
    invoice = delivery_screening_service.process(db, order_id=DEMO_ORDER, content=INVOICE_PNG.read_bytes(),
                                                 source=DeliverySource.LOCAL_INTAKE, sender="demo-rider", gate_id="GATE_1")
    say("created", f"screened {DEMO_ORDER}: {invoice.reply_text} (overall {invoice.overall_verdict.value}, {invoice.ocr_engine})")

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-sightings", action="store_true", help="Do not record the demo guard sightings")
    parser.add_argument("--no-delivery", action="store_true", help="Do not screen the demo invoice")
    parser.add_argument("--reset-demo-passwords", action="store_true",
                        help="Set guard1 / admin to the demo passwords even if the accounts already exist")
    args = parser.parse_args()

    print("Seeding demo data (idempotent; nothing is deleted or overwritten)")
    generate_invoice()
    with SessionLocal() as db:
        seed_gates(db)
        admin = seed_accounts(db, reset_passwords=args.reset_demo_passwords)
        seed_owners(db, admin)
        seed_vehicles(db, admin)
        guard = db.query(User).filter(User.username == "guard1").first()
        if not args.no_sightings and guard:
            seed_sightings(db, guard)
        if not args.no_delivery:
            seed_delivery(db)
    print("Done.")

if __name__ == "__main__":
    main()
