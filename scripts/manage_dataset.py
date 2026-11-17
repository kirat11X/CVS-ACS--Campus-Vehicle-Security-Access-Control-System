#!/usr/bin/env python3
"""
PostgreSQL Dataset Management and Purge Utility.
Allows administrators to inspect, selectively purge, or completely reset the generated
test dataset (students, faculty, residents, staff, vehicles, movements, invoices with QR codes)
directly in PostgreSQL.

Usage:
    python scripts/manage_dataset.py --status
    python scripts/manage_dataset.py --purge-invoices [--force]
    python scripts/manage_dataset.py --purge-members [--force]
    python scripts/manage_dataset.py --purge-all [--force]
    python scripts/manage_dataset.py --seed
"""
import os
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import text
from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models import (
    VehicleOwner, Vehicle, VehicleLinkEvent, EntryExitLog, ObservationEvent,
    DeliveryOrder, Invoice, InvoiceItem, DeliveryDecision, PersonType
)

CORE_PROTECTED_IDENTIFIERS = {
    "24103042",  # Kirat Singh (Admin & Demo Student)
    "24103999",  # Demo Student
    "F1002014",  # Dr. Demo Faculty
    "R1042",     # Core Resident
    "STF-EST-022"# Core Staff
}

CORE_PROTECTED_PLATES = {
    "CH17ER1573", "CH01AB1234", "HR26DK0042", "PB65XY7788", "CH01AB1247", "CH01AB1248"
}

def get_dataset_status():
    db = SessionLocal()
    print("=" * 65)
    print("CURRENT POSTGRESQL DATASET STATUS")
    print("=" * 65)

    # 1. Members
    students = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.STUDENT).count()
    faculty = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.FACULTY).count()
    staff = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.STAFF).count()
    residents = db.query(VehicleOwner).filter(VehicleOwner.person_type == PersonType.RESIDENT).count()
    total_owners = db.query(VehicleOwner).count()

    print(f"Vehicle Owners (Total: {total_owners}):")
    print(f"  • Students:              {students}")
    print(f"  • Faculty Members:       {faculty}")
    print(f"  • Staff / Administration:{staff}")
    print(f"  • Campus Residents:      {residents}")

    # 2. Vehicles & Movements
    vehicles = db.query(Vehicle).count()
    links = db.query(VehicleLinkEvent).count()
    movements = db.query(EntryExitLog).count()
    observations = db.query(ObservationEvent).count()

    print(f"\nVehicles & Movements:")
    print(f"  • Registered Vehicles:   {vehicles}")
    print(f"  • Vehicle Link Events:   {links}")
    print(f"  • Gate Movement Logs:    {movements}")
    print(f"  • Observation Events:    {observations}")

    # 3. Deliveries & Invoices
    orders = db.query(DeliveryOrder).count()
    invoices = db.query(Invoice).count()
    items = db.query(InvoiceItem).count()
    decisions = db.query(DeliveryDecision).count()

    inv_files = list((MEDIA_ROOT / "invoices").glob("*.png")) + list((MEDIA_ROOT / "invoices").glob("*.pdf"))

    print(f"\nDeliveries & Invoices:")
    print(f"  • Delivery Orders:       {orders}")
    print(f"  • Invoices in DB:        {invoices}")
    print(f"  • Invoice Items:         {items}")
    print(f"  • Delivery Decisions:    {decisions}")
    print(f"  • Invoice Files on Disk: {len(inv_files)} in {MEDIA_ROOT / 'invoices'}")
    print("=" * 65)
    db.close()

def purge_invoices(force=False):
    if not force:
        confirm = input("Are you sure you want to PURGE all delivery orders & invoices from PostgreSQL? [y/N]: ")
        if confirm.lower() != "y":
            print("Purge cancelled.")
            return

    db = SessionLocal()
    print("\nPurging multi-vendor invoices & delivery orders from PostgreSQL...")
    try:
        # Disable triggers for administrative purge
        db.execute(text("SET LOCAL session_replication_role = 'replica';"))

        # 1. Delete decisions & items
        dec_del = db.query(DeliveryDecision).delete(synchronize_session=False)
        item_del = db.query(InvoiceItem).delete(synchronize_session=False)

        # 2. Delete physical image files
        invoices = db.query(Invoice).all()
        files_removed = 0
        for inv in invoices:
            if inv.image_path:
                p = MEDIA_ROOT / inv.image_path
                if p.exists() and "demo" not in str(p):
                    try:
                        p.unlink()
                        files_removed += 1
                    except Exception:
                        pass

        inv_del = db.query(Invoice).delete(synchronize_session=False)
        ord_del = db.query(DeliveryOrder).delete(synchronize_session=False)

        db.commit()
        print(f"Successfully purged from PostgreSQL:")
        print(f"  • {ord_del} Delivery Orders deleted")
        print(f"  • {inv_del} Invoices deleted")
        print(f"  • {item_del} Invoice Items deleted")
        print(f"  • {dec_del} Delivery Decisions deleted")
        print(f"  • {files_removed} image files removed from media/invoices/")
    except Exception as e:
        db.rollback()
        print(f"ERROR purging invoices: {e}")
    finally:
        db.close()

def purge_members(force=False):
    if not force:
        confirm = input("Are you sure you want to PURGE generated students, faculty, and residents from PostgreSQL? [y/N]: ")
        if confirm.lower() != "y":
            print("Purge cancelled.")
            return

    db = SessionLocal()
    print("\nPurging generated members & linked vehicles from PostgreSQL...")
    try:
        db.execute(text("SET LOCAL session_replication_role = 'replica';"))

        # Find target generated owners (exclude protected core identifiers)
        target_owners = db.query(VehicleOwner).filter(~VehicleOwner.identifier.in_(CORE_PROTECTED_IDENTIFIERS)).all()
        target_owner_ids = [o.id for o in target_owners]
        print(f"Identified {len(target_owner_ids)} generated member records to purge.")

        # 1. Unlink or delete link events
        del_links = db.query(VehicleLinkEvent).filter(VehicleLinkEvent.owner_id.in_(target_owner_ids)).delete(synchronize_session=False)

        # 2. Dissociate or delete non-protected vehicles
        target_vehicles = db.query(Vehicle).filter(
            Vehicle.owner_id.in_(target_owner_ids) |
            (~Vehicle.normalized_plate.in_(CORE_PROTECTED_PLATES) & Vehicle.owner_id.is_(None))
        ).all()
        target_veh_ids = [v.id for v in target_vehicles]

        # Delete movement logs for these vehicles
        del_logs = db.query(EntryExitLog).filter(EntryExitLog.vehicle_id.in_(target_veh_ids)).delete(synchronize_session=False)

        # Delete vehicles
        del_vehs = db.query(Vehicle).filter(Vehicle.id.in_(target_veh_ids)).delete(synchronize_session=False)

        # 3. Delete owners
        del_owners = db.query(VehicleOwner).filter(VehicleOwner.id.in_(target_owner_ids)).delete(synchronize_session=False)

        db.commit()
        print(f"Successfully purged from PostgreSQL:")
        print(f"  • {del_owners} Member rows deleted")
        print(f"  • {del_vehs} Generated Vehicles deleted")
        print(f"  • {del_links} Vehicle Links deleted")
        print(f"  • {del_logs} Movement Logs deleted")
        print(f"  • Core protected records preserved safely.")
    except Exception as e:
        db.rollback()
        print(f"ERROR purging members: {e}")
    finally:
        db.close()

def purge_all(force=False):
    if not force:
        confirm = input("Are you sure you want to PURGE ALL generated test datasets from PostgreSQL? [y/N]: ")
        if confirm.lower() != "y":
            print("Purge cancelled.")
            return
    purge_invoices(force=True)
    purge_members(force=True)
    print("\nDataset purge complete. Base PostgreSQL state restored.")

def reseed():
    print("\nTriggering seeder scripts...")
    from scripts.seed_college_members import seed_all as seed_members
    from scripts.generate_multivendor_invoices import generate_1000_invoices
    seed_members()
    generate_1000_invoices()

def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Dataset Management and Purge Utility")
    parser.add_argument("--status", action="store_true", help="Print current counts of dataset records in PostgreSQL")
    parser.add_argument("--purge-invoices", action="store_true", help="Purge delivery orders & invoices from PostgreSQL")
    parser.add_argument("--purge-members", action="store_true", help="Purge generated students, faculty, residents from PostgreSQL")
    parser.add_argument("--purge-all", action="store_true", help="Purge all generated test data from PostgreSQL")
    parser.add_argument("--seed", action="store_true", help="Re-seed all 1,000 invoices and members into PostgreSQL")
    parser.add_argument("--force", action="store_true", help="Bypass interactive confirmation prompt")

    args = parser.parse_args()

    if args.purge_all:
        purge_all(force=args.force)
    elif args.purge_invoices:
        purge_invoices(force=args.force)
    elif args.purge_members:
        purge_members(force=args.force)
    elif args.seed:
        reseed()
    else:
        get_dataset_status()

if __name__ == "__main__":
    main()
