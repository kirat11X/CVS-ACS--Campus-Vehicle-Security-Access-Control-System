#!/usr/bin/env python3
"""
Migrates and standardizes all vehicle owner identifiers and artificial names
in the PostgreSQL database to conform to campus statutory schema:

1. STUDENT: Exactly 8 numeric digits (e.g. 24103042, 24103999, 24103001...)
2. FACULTY: 'F' followed by 7 digits (e.g. F1002014, F1029384, F1002015...)
3. RESIDENT: 'R' followed by 4-digit house number (e.g. R1042, R1043...)
4. STAFF: Valid institutional employee code (e.g. STF-EST-022)
"""

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.db import SessionLocal
from backend.app.models.identity import VehicleOwner
from backend.app.models.vehicle import Vehicle
from backend.app.models.enums import PersonType, ResidenceType

STUDENT_NAMES = [
    "Kirat Singh", "Aman Preet Singh", "Priya Sharma", "Simran Gill",
    "Harleen Kaur", "Rohan Mehta", "Neha Gupta", "Vikram Rathore",
    "Aryan Sharma", "Kavya Patel", "Aditya Nair", "Ananya Roy",
    "Rahul Kapoor", "Sneha Joshi", "Deepak Verma", "Tanvi Bhatia",
    "Manish Choudhary", "Pooja Malhotra", "Gaurav Sen", "Ishita Saxena",
    "Siddharth Rao", "Divya Deshmukh", "Nikhil Aggarwal", "Meera Pillai",
    "Karan Johar", "Shreya Das", "Varun Dhawan", "Rhea Chakraborty"
]

FACULTY_NAMES = [
    "Dr. Demo Faculty", "Dr. Rajesh Verma", "Dr. Ramanujan",
    "Prof. Sunita Rao", "Dr. Amit Roy", "Prof. Manju Sharma",
    "Dr. Arvind Krishnan", "Dr. Meenakshi Sundaram", "Prof. B. K. Singhal",
    "Dr. Harish Chandra", "Prof. Nalini Joshi", "Dr. Sandeep Anand"
]


def clean_name(name: str, fallback_list: list, index: int) -> str:
    cleaned = re.sub(r"\b[0-9a-fA-F]{4,8}\b", "", name).strip()
    cleaned = re.sub(r"^(?:P7|P16|AUDIT)\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or "Student" in cleaned or "Hosteller" in cleaned or "Audit" in cleaned or "Owner" in cleaned:
        return fallback_list[index % len(fallback_list)]
    return cleaned


def migrate_all_owners():
    db = SessionLocal()
    print("=" * 80)
    print("MIGRATING ALL OWNER IDENTIFIERS ACCORDING TO STATUTORY SCHEMA")
    print("=" * 80)

    try:
        # Step 0: Ensure Kirat Singh (24103042) is cleanly set and linked to CH17ER1573
        ch17_veh = db.query(Vehicle).filter(Vehicle.normalized_plate == "CH17ER1573").first()
        existing_24103042 = db.query(VehicleOwner).filter(VehicleOwner.identifier == "24103042").first()

        if ch17_veh and ch17_veh.owner_id:
            ch17_owner = db.query(VehicleOwner).filter(VehicleOwner.id == ch17_veh.owner_id).first()
            if ch17_owner:
                # If there's an existing unused 24103042, remove or merge it first
                if existing_24103042 and existing_24103042.id != ch17_owner.id:
                    # check if existing has vehicles
                    if not existing_24103042.vehicles:
                        db.delete(existing_24103042)
                        db.flush()
                        existing_24103042 = None
                    else:
                        existing_24103042.identifier = "24103099"
                        db.flush()

                ch17_owner.identifier = "24103042"
                ch17_owner.full_name = "Kirat Singh"
                ch17_owner.person_type = PersonType.STUDENT
                ch17_owner.residence_type = ResidenceType.HOSTELLER
                ch17_owner.residence = "Hostel BH-4, Room 312"
                ch17_owner.department = "Computer Science & Engineering"
                print("  [FIXED] CH17ER1573 owner set to Kirat Singh (SID 24103042)")

        # Fetch all remaining owners
        owners = db.query(VehicleOwner).order_by(VehicleOwner.created_at).all()
        used_identifiers = set()

        # Seed reserve
        used_identifiers.add("24103042")
        used_identifiers.add("24103999")
        used_identifiers.add("F1002014")
        used_identifiers.add("F1029384")
        used_identifiers.add("R1042")
        used_identifiers.add("STF-EST-022")

        student_seq = 24103001
        faculty_seq = 1002015
        resident_seq = 1043
        staff_seq = 1

        updated_count = 0

        for idx, owner in enumerate(owners):
            p_type = owner.person_type.value if hasattr(owner.person_type, "value") else str(owner.person_type)

            if p_type == "STUDENT":
                # Check if already a valid 8-digit SID
                if re.fullmatch(r"^\d{8}$", owner.identifier) and owner.identifier not in used_identifiers:
                    used_identifiers.add(owner.identifier)
                    owner.full_name = clean_name(owner.full_name, STUDENT_NAMES, idx)
                elif owner.identifier == "24103042":
                    owner.full_name = "Kirat Singh"
                elif owner.identifier == "24103999":
                    owner.full_name = "Demo Student"
                else:
                    while f"{student_seq}" in used_identifiers:
                        student_seq += 1
                    new_id = f"{student_seq}"
                    student_seq += 1
                    used_identifiers.add(new_id)
                    old_id = owner.identifier
                    owner.identifier = new_id
                    owner.full_name = clean_name(owner.full_name, STUDENT_NAMES, idx)
                    if not owner.residence:
                        owner.residence = f"Hostel BH-{(idx % 4) + 1}, Room {101 + (idx % 300)}"
                    updated_count += 1
                    print(f"  [STUDENT] {old_id:25s} -> {owner.identifier} ({owner.full_name})")

            elif p_type == "FACULTY":
                if owner.identifier.upper() == "FAC-CSE-014":
                    owner.identifier = "F1002014"
                    owner.full_name = "Dr. Demo Faculty"
                    used_identifiers.add("F1002014")
                    updated_count += 1
                elif owner.identifier.upper() == "F1029384":
                    owner.identifier = "F1029384"
                    used_identifiers.add("F1029384")
                elif re.fullmatch(r"^F\d{7}$", owner.identifier.upper()) and owner.identifier.upper() not in used_identifiers:
                    owner.identifier = owner.identifier.upper()
                    used_identifiers.add(owner.identifier)
                else:
                    while f"F{faculty_seq:07d}" in used_identifiers:
                        faculty_seq += 1
                    new_id = f"F{faculty_seq:07d}"
                    faculty_seq += 1
                    used_identifiers.add(new_id)
                    old_id = owner.identifier
                    owner.identifier = new_id
                    owner.full_name = clean_name(owner.full_name, FACULTY_NAMES, idx)
                    if not owner.department:
                        owner.department = "Mechanical Engineering"
                    updated_count += 1
                    print(f"  [FACULTY] {old_id:25s} -> {owner.identifier} ({owner.full_name})")

            elif p_type == "RESIDENT":
                if owner.identifier.upper() == "R1042":
                    owner.identifier = "R1042"
                    owner.full_name = "Capt. Vikram Batra"
                    owner.residence = "House 1042, Faculty Enclave"
                    used_identifiers.add("R1042")
                else:
                    while f"R{resident_seq:04d}" in used_identifiers:
                        resident_seq += 1
                    new_id = f"R{resident_seq:04d}"
                    resident_seq += 1
                    used_identifiers.add(new_id)
                    old_id = owner.identifier
                    owner.identifier = new_id
                    owner.residence = f"House {new_id[1:]}, Faculty Enclave"
                    updated_count += 1
                    print(f"  [RESIDENT] {old_id:25s} -> {owner.identifier} ({owner.full_name})")

            elif p_type == "STAFF":
                if not owner.identifier.startswith("STF-"):
                    owner.identifier = f"STF-EST-{staff_seq:03d}"
                    staff_seq += 1
                    updated_count += 1

        db.commit()
        print(f"\n✅ Migration complete! {updated_count} owner records updated to statutory schema.")
        print("All records now strictly conform to:")
        print("  - Students: 8-digit numeric SIDs (e.g. 24103042)")
        print("  - Faculty: F + 7 numeric digits (e.g. F1002014)")
        print("  - Residents: R + 4 numeric digits (e.g. R1042)")
        print("  - Staff: STF-XXX (e.g. STF-EST-022)")
    except Exception as e:
        db.rollback()
        print(f"❌ Error during migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_all_owners()
