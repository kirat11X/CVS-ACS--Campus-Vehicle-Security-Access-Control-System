#!/usr/bin/env python3
"""
Seed script for 500 Students, 100 Faculty, 50 Residents, 20 Staff, and 500 Vehicles.
Strictly adheres to Institutional ID statutory schemas:
- Student ID: exactly 8 numeric digits (24103001..24103500)
- Faculty ID: 'F' + 7 digits (F1000001..F1000100)
- Residence ID: 'R' + 4 digits (R1001..R1050)
- Staff ID: 'STF-' + alphanumeric (STF-EST-001..STF-ADM-020)

Also seeds 500+ registered & visitor/delivery vehicles, link events, gate movements,
and overstay scenarios (>1.5h unlinked vehicles inside campus).
"""
import os
import sys
import uuid
import random
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import (
    Gate, GateStatus, GateDirection, DirectionMethod, LogPlateSource,
    PersonType, ResidenceType, User, UserRole,
    Vehicle, VehicleCategory, VehicleStatus, VehicleOwner, VehicleLinkEvent,
    LinkMethod, ObservationEvent, ObservationSource, ObservedVehicleType, ObservationDirection
)
from backend.app.models.gate import EntryExitLog
from backend.app.services.plate_normalizer import normalize_plate, format_plate_display
from backend.app.services.identifier_validator import validate_and_normalize_identifier

# Seed for reproducibility
random.seed(24103042)

PEC_DEPARTMENTS = [
    "Computer Science & Engineering",
    "Electronics & Communication Engineering",
    "Electrical Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
    "Aerospace Engineering",
    "Metallurgical & Materials Engineering",
    "Production & Industrial Engineering"
]

STUDENT_HOSTELS = [
    "Aravali Hall",
    "Kurukshetra Hall",
    "Himalaya Hall",
    "Shivalik Hall",
    "Kalpana Chawla Hall",
    "Vindhya Hall"
]

FIRST_NAMES_M = [
    "Aarav", "Aditya", "Akash", "Aman", "Amit", "Anand", "Ankit", "Ansh", "Arjun", "Arman",
    "Aryan", "Ayush", "Bhavya", "Chetan", "Chirag", "Daksh", "Deepak", "Dev", "Dhruv", "Divyansh",
    "Gaurav", "Harsh", "Harshit", "Himanshu", "Ishaan", "Jay", "Kabir", "Karan", "Kartik", "Kavya",
    "Keshav", "Kirat", "Krish", "Kunal", "Laksh", "Madhav", "Manan", "Manish", "Mayank", "Mohit",
    "Nakul", "Naman", "Navdeep", "Nikhil", "Nitin", "Om", "Parth", "Pranav", "Pranay", "Prashant",
    "Prateek", "Rahul", "Raj", "Rajat", "Rajiv", "Rakesh", "Rishi", "Rohan", "Rohit", "Sahil",
    "Samarth", "Sameer", "Sanchit", "Sarthak", "Shivam", "Shourya", "Siddharth", "Sparsh", "Suraj", "Tanmay",
    "Tarun", "Tejas", "Utkarsh", "Vaibhav", "Varun", "Vedant", "Vikas", "Vinay", "Vishal", "Yash"
]

FIRST_NAMES_F = [
    "Aadya", "Aahana", "Aastha", "Akanksha", "Ananya", "Anika", "Anjali", "Anushka", "Avani", "Bhavna",
    "Charu", "Deepika", "Dia", "Disha", "Diya", "Garima", "Gauri", "Gunjan", "Isha", "Ishita",
    "Jahnavi", "Khushi", "Kirti", "Komal", "Lavanya", "Mahika", "Mansi", "Meera", "Muskan", "Navya",
    "Neha", "Nidhi", "Niharika", "Pallavi", "Pari", "Parul", "Pragya", "Pranjal", "Prerna", "Priya",
    "Radhika", "Rhea", "Richa", "Riddhi", "Ritu", "Riya", "Sakshi", "Sanya", "Saumya", "Shreya",
    "Simran", "Sneha", "Sonam", "Srishti", "Swati", "Tanya", "Tarini", "Tanvi", "Urvi", "Vaishnavi"
]

LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Bansal", "Mittal", "Garg", "Jain", "Aggarwal",
    "Malhotra", "Khurana", "Sethi", "Bhatia", "Chopra", "Soni", "Mehta", "Dhillon", "Gill", "Sandhu",
    "Sidhu", "Grewal", "Brar", "Chauhan", "Rathore", "Yadav", "Pandey", "Mishra", "Tiwari", "Dubey",
    "Patel", "Shah", "Reddy", "Nair", "Iyer", "Rao", "Joshi", "Saxena", "Bhatnagar", "Mathur"
]

# Prominent PEC Faculty Profiles (pec.ac.in)
PEC_FACULTY_ROSTER = [
    ("Dr. Divya Bansal", "Computer Science & Engineering", "Professor & Head"),
    ("Dr. Poonam Saini", "Computer Science & Engineering", "Associate Professor"),
    ("Dr. Sudesh Rani", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Kanu Goel", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Mayank Gupta", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Manish Kumar", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Rupali Verma", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Satnam Kaur", "Computer Science & Engineering", "Assistant Professor"),
    ("Prof. Mamta Dabra", "Computer Science & Engineering", "Assistant Professor"),
    ("Dr. Sanjeev Kumar", "Computer Science & Engineering", "Professor"),
    ("Dr. Trishikhi Bagga", "Computer Science & Engineering", "Associate Professor"),
    ("Dr. Akashdeep Kaur", "Computer Science & Engineering", "Assistant Professor"),

    ("Dr. Perminderjit Singh", "Mechanical Engineering", "Professor & Head"),
    ("Dr. Sarabjit Singh", "Mechanical Engineering", "Professor"),
    ("Dr. Kamal Kumar", "Mechanical Engineering", "Associate Professor"),
    ("Dr. Gurjeet Singh", "Mechanical Engineering", "Assistant Professor"),
    ("Prof. Ankit Yadav", "Mechanical Engineering", "Assistant Professor"),
    ("Prof. Chanderkant Susheel", "Mechanical Engineering", "Assistant Professor"),
    ("Prof. Ram Singh", "Mechanical Engineering", "Assistant Professor"),
    ("Prof. Sheetal Soda", "Mechanical Engineering", "Assistant Professor"),
    ("Dr. R.M. Belokar", "Mechanical Engineering", "Professor"),
    ("Dr. Sushant Samir", "Mechanical Engineering", "Professor"),
    ("Dr. Rajesh Kumar", "Mechanical Engineering", "Associate Professor"),
    ("Dr. Ravinderjit Singh Walia", "Mechanical Engineering", "Professor"),

    ("Dr. Jagdish Kumar", "Electrical Engineering", "Professor & Head"),
    ("Dr. Balwinder Singh Surjan", "Electrical Engineering", "Professor"),
    ("Dr. Puneet Chawla", "Electrical Engineering", "Professor"),
    ("Dr. Rintu Khanna", "Electrical Engineering", "Professor"),
    ("Dr. Tilak Thakur", "Electrical Engineering", "Professor"),
    ("Dr. Jaimala Gambhir", "Electrical Engineering", "Associate Professor"),
    ("Dr. Loveleen Kaur Taneja", "Electrical Engineering", "Associate Professor"),
    ("Dr. Manohar Singh", "Electrical Engineering", "Associate Professor"),
    ("Dr. Ajay Kumar", "Electrical Engineering", "Assistant Professor"),
    ("Prof. Amita Kumari", "Electrical Engineering", "Assistant Professor"),
    ("Prof. Dhiraj Bharat", "Electrical Engineering", "Assistant Professor"),
    ("Dr. R.K. Jarial", "Electrical Engineering", "Professor"),

    ("Dr. Neena Gupta", "Electronics & Communication Engineering", "Professor & Head"),
    ("Dr. Arun Kumar Singh", "Electronics & Communication Engineering", "Professor"),
    ("Dr. Simranjit Singh", "Electronics & Communication Engineering", "Associate Professor"),
    ("Dr. Divya Dhawan", "Electronics & Communication Engineering", "Associate Professor"),
    ("Dr. Sanjeev Rai", "Electronics & Communication Engineering", "Professor"),
    ("Dr. Gurpurneet Kaur", "Electronics & Communication Engineering", "Assistant Professor"),
    ("Dr. Kuldeep Sharma", "Electronics & Communication Engineering", "Assistant Professor"),
    ("Prof. Jagjit Singh", "Electronics & Communication Engineering", "Assistant Professor"),
    ("Prof. Harinder Kaur", "Electronics & Communication Engineering", "Assistant Professor"),
    ("Dr. Sandeep Singh", "Electronics & Communication Engineering", "Associate Professor"),

    ("Dr. Siby John", "Civil Engineering", "Professor & Head"),
    ("Dr. Umesh Sharma", "Civil Engineering", "Professor"),
    ("Dr. Sarita Singla", "Civil Engineering", "Professor"),
    ("Dr. R.R. Singh", "Civil Engineering", "Professor"),
    ("Dr. Geeta Arora", "Civil Engineering", "Associate Professor"),
    ("Dr. Mohit Kumar", "Civil Engineering", "Assistant Professor"),
    ("Dr. Arshdeep Singh", "Civil Engineering", "Assistant Professor"),
    ("Prof. Parveen Aggarwal", "Civil Engineering", "Assistant Professor"),
    ("Dr. S.K. Singh", "Civil Engineering", "Professor"),
    ("Dr. C.S. Rao", "Civil Engineering", "Associate Professor"),

    ("Dr. Rakesh Kumar", "Aerospace Engineering", "Professor & Head"),
    ("Dr. T.K. Jindal", "Aerospace Engineering", "Professor"),
    ("Dr. Tejinder Kumar", "Aerospace Engineering", "Associate Professor"),
    ("Prof. Ankur Gupta", "Aerospace Engineering", "Assistant Professor"),
    ("Prof. Poonam Kumari", "Aerospace Engineering", "Assistant Professor"),
    ("Dr. Sushil Kumar", "Aerospace Engineering", "Assistant Professor"),

    ("Dr. Uma Batra", "Metallurgical & Materials Engineering", "Professor & Head"),
    ("Dr. J.D. Sharma", "Metallurgical & Materials Engineering", "Professor"),
    ("Dr. Sushant K. Rawal", "Metallurgical & Materials Engineering", "Associate Professor"),
    ("Dr. Mamta Sharma", "Metallurgical & Materials Engineering", "Assistant Professor"),
    ("Prof. Rahul Chhibber", "Metallurgical & Materials Engineering", "Associate Professor"),

    ("Dr. N.M. Suri", "Production & Industrial Engineering", "Professor & Head"),
    ("Dr. P.K. Khosla", "Production & Industrial Engineering", "Professor"),
    ("Dr. B.S. Pabla", "Production & Industrial Engineering", "Professor"),
    ("Dr. Ravinderjit Walia", "Production & Industrial Engineering", "Professor"),
    ("Prof. Jaswinder Singh", "Production & Industrial Engineering", "Assistant Professor"),
]

CAR_MODELS = [
    ("Honda City", "White"), ("Hyundai Creta", "Silver"), ("Maruti Brezza", "Grey"),
    ("Toyota Innova", "White"), ("Kia Seltos", "Red"), ("Tata Nexon", "Blue"),
    ("Skoda Slavia", "Black"), ("Volkswagen Virtus", "Grey"), ("Maruti Swift", "White"),
    ("Hyundai i20", "Blue"), ("Tata Punch", "Brown"), ("Mahindra Thar", "Black"),
    ("Toyota Fortuner", "White"), ("Honda Amaze", "Silver"), ("MG Hector", "Black")
]

BIKE_MODELS = [
    ("Royal Enfield Classic 350", "Black"), ("Honda Activa 6G", "Grey"),
    ("Yamaha R15 V4", "Blue"), ("KTM Duke 200", "Orange"),
    ("TVS Jupiter 125", "White"), ("Suzuki Access 125", "Blue"),
    ("Bajaj Pulsar NS200", "Black"), ("Hero Splendor Plus", "Silver"),
    ("Ather 450X", "White"), ("Ola S1 Pro", "Black")
]

RTO_SERIES = ["CH01", "PB65", "PB08", "PB10", "PB11", "HR03", "HR70", "HR26", "DL01", "DL04"]

def generate_plate(rto=None, alpha_len=2):
    rto = rto or random.choice(RTO_SERIES)
    letters = "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=alpha_len))
    num = f"{random.randint(100, 9999):04d}"
    return f"{rto}{letters}{num}"

def seed_all():
    db = SessionLocal()
    print("=" * 70)
    print("STARTING COMPREHENSIVE COLLEGE MEMBERS & VEHICLE DATASET GENERATION")
    print("=" * 70)

    admin_user = db.query(User).filter(User.role == "ADMIN").first()
    if not admin_user:
        admin_user = User(
            username="admin",
            email="admin@campus.edu",
            full_name="Campus Administrator",
            role="ADMIN"
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

    gates = {g.id: g for g in db.query(Gate).all()}
    if not gates:
        for gid, name, cam in [("GATE_1", "Main North Gate", "gate_cam"), ("GATE_2", "South Gate", "gate_2_cam"), ("GATE_3", "Hostel East Gate", "gate_3_cam")]:
            g = Gate(id=gid, name=name, camera_id=cam, status=GateStatus.ACTIVE)
            db.add(g)
            gates[gid] = g
        db.commit()

    created_members = 0
    created_vehicles = 0
    created_movements = 0

    # -------------------------------------------------------------
    # 1. 500 STUDENTS (IDs 24103001..24103500)
    # -------------------------------------------------------------
    print("\n[1/5] Generating 500 Students (IDs: 24103001..24103500)...")
    student_owners = []
    existing_ids = {o.identifier for o in db.query(VehicleOwner.identifier).all()}

    for i in range(1, 501):
        sid = f"2410{3000 + i:04d}"  # 24103001 to 24103500
        # Check schema validity
        valid_id = validate_and_normalize_identifier(sid, PersonType.STUDENT)
        assert valid_id == sid, f"Invalid student id generated: {sid}"

        if sid in existing_ids:
            owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == sid).first()
            student_owners.append(owner)
            continue

        gender = random.choice(["M", "F"])
        first_name = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
        last_name = random.choice(LAST_NAMES)
        full_name = f"{first_name} {last_name}"
        dept = random.choice(PEC_DEPARTMENTS)
        is_hosteller = (random.random() < 0.75)

        if is_hosteller:
            res_type = ResidenceType.HOSTELLER
            hostel = random.choice(STUDENT_HOSTELS)
            room_no = f"Room {random.randint(101, 440)}"
            residence = f"{hostel}, {room_no}"
        else:
            res_type = ResidenceType.DAY_SCHOLAR
            residence = f"Sector {random.choice([11, 15, 21, 35, 38, 44])}, Chandigarh"

        email = f"{first_name.lower()}.{last_name.lower()}{sid[-4:]}@pec.edu.in"
        phone = f"+91 {random.choice([98140, 98150, 98720, 98880, 99150])} {random.randint(10000, 99999)}"

        owner = VehicleOwner(
            identifier=sid,
            full_name=full_name,
            email=email,
            phone=phone,
            person_type=PersonType.STUDENT,
            residence_type=res_type,
            residence=residence,
            department=dept,
            status="ACTIVE",
            created_by_id=admin_user.id
        )
        db.add(owner)
        student_owners.append(owner)
        created_members += 1

    db.commit()
    print(f"  -> Added {created_members} new students (Total target: 500)")

    # -------------------------------------------------------------
    # 2. 100 FACULTY (IDs F1000001..F1000100)
    # -------------------------------------------------------------
    print("\n[2/5] Generating 100 PEC Faculty (IDs: F1000001..F1000100)...")
    faculty_owners = []
    faculty_created = 0

    # Expand faculty roster to 100 entries if needed
    full_faculty_list = list(PEC_FACULTY_ROSTER)
    while len(full_faculty_list) < 100:
        gender = random.choice(["M", "F"])
        fname = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
        lname = random.choice(LAST_NAMES)
        dept = random.choice(PEC_DEPARTMENTS)
        desig = random.choice(["Assistant Professor", "Associate Professor", "Professor"])
        full_faculty_list.append((f"Dr. {fname} {lname}", dept, desig))

    for i in range(1, 101):
        fid = f"F{1000000 + i:07d}"  # F1000001 to F1000100
        valid_id = validate_and_normalize_identifier(fid, PersonType.FACULTY)
        assert valid_id == fid, f"Invalid faculty id generated: {fid}"

        if fid in existing_ids:
            owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == fid).first()
            faculty_owners.append(owner)
            continue

        fac_name, fac_dept, fac_desig = full_faculty_list[i - 1]
        on_campus = (random.random() < 0.6)
        if on_campus:
            res_type = ResidenceType.UNKNOWN
            residence = f"Faculty Enclave, House {1000 + i}"
        else:
            res_type = ResidenceType.OFF_CAMPUS
            residence = f"Sector {random.choice([11, 12, 14, 15, 21])}, Chandigarh"

        clean_name = fac_name.replace("Dr. ", "").replace("Prof. ", "").strip().lower().replace(" ", ".")
        email = f"{clean_name}@pec.edu.in"
        phone = f"+91 9417{random.randint(100000, 999999)}"

        owner = VehicleOwner(
            identifier=fid,
            full_name=fac_name,
            email=email,
            phone=phone,
            person_type=PersonType.FACULTY,
            residence_type=res_type,
            residence=residence,
            department=f"{fac_dept} ({fac_desig})",
            status="ACTIVE",
            created_by_id=admin_user.id
        )
        db.add(owner)
        faculty_owners.append(owner)
        faculty_created += 1

    db.commit()
    print(f"  -> Added {faculty_created} new faculty members (Total target: 100)")

    # -------------------------------------------------------------
    # 3. 50 RESIDENTS (IDs R1001..R1050)
    # -------------------------------------------------------------
    print("\n[3/5] Generating 50 Campus Residents (IDs: R1001..R1050)...")
    resident_owners = []
    residents_created = 0

    for i in range(1, 51):
        rid = f"R{1000 + i:04d}"  # R1001 to R1050
        valid_id = validate_and_normalize_identifier(rid, PersonType.RESIDENT)
        assert valid_id == rid, f"Invalid resident id generated: {rid}"

        if rid in existing_ids:
            owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == rid).first()
            resident_owners.append(owner)
            continue

        gender = random.choice(["M", "F"])
        fname = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
        lname = random.choice(LAST_NAMES)
        full_name = f"{fname} {lname}"
        residence = f"Campus Residential Quarters, House {1000 + i}"

        owner = VehicleOwner(
            identifier=rid,
            full_name=full_name,
            email=f"{fname.lower()}.{rid.lower()}@campus.edu",
            phone=f"+91 9876{random.randint(100000, 999999)}",
            person_type=PersonType.RESIDENT,
            residence_type=ResidenceType.UNKNOWN,
            residence=residence,
            department="Campus Residential Complex",
            status="ACTIVE",
            created_by_id=admin_user.id
        )
        db.add(owner)
        resident_owners.append(owner)
        residents_created += 1

    db.commit()
    print(f"  -> Added {residents_created} new residents (Total target: 50)")

    # -------------------------------------------------------------
    # 4. 20 ADMINISTRATION / STAFF (IDs STF-EST-001..STF-SEC-005)
    # -------------------------------------------------------------
    print("\n[4/5] Generating 20 Administration & Campus Staff (IDs: STF-EST-001..)...")
    staff_owners = []
    staff_created = 0

    staff_depts = [
        ("STF-EST", "Estate & Maintenance Office"),
        ("STF-ADM", "Dean Academics & Student Welfare"),
        ("STF-SEC", "Chief Security Office"),
        ("STF-REG", "Registrar Secretariat")
    ]

    staff_idx = 1
    for prefix, s_dept in staff_depts:
        for num in range(1, 6):
            stid = f"{prefix}-{num:03d}"
            valid_id = validate_and_normalize_identifier(stid, PersonType.STAFF)
            assert valid_id == stid, f"Invalid staff id generated: {stid}"

            if stid in existing_ids:
                owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == stid).first()
                staff_owners.append(owner)
                continue

            fname = random.choice(FIRST_NAMES_M)
            lname = random.choice(LAST_NAMES)
            full_name = f"{fname} {lname}"

            owner = VehicleOwner(
                identifier=stid,
                full_name=full_name,
                email=f"{fname.lower()}.{stid.lower().replace('-', '')}@pec.edu.in",
                phone=f"+91 9815{random.randint(100000, 999999)}",
                person_type=PersonType.STAFF,
                residence_type=ResidenceType.OFF_CAMPUS,
                residence=f"Sector {random.choice([19, 20, 22, 27])}, Chandigarh",
                department=s_dept,
                status="ACTIVE",
                created_by_id=admin_user.id
            )
            db.add(owner)
            staff_owners.append(owner)
            staff_created += 1
            staff_idx += 1

    db.commit()
    print(f"  -> Added {staff_created} new staff members (Total target: 20)")

    # -------------------------------------------------------------
    # 5. 500 VEHICLES & SIGHTINGS / OVERSTAY DATASET
    # -------------------------------------------------------------
    print("\n[5/5] Generating 500 Vehicles, Link Events & Movement Logs...")
    existing_plates = {v.normalized_plate for v in db.query(Vehicle.normalized_plate).all()}

    # Vehicle distribution:
    # ~100 Faculty cars
    # ~250 Student bikes / cars
    # ~50 Resident vehicles
    # ~20 Staff vehicles
    # ~50 Delivery bikes (Swiggy, Zomato, Amazon, Blinkit, Zepto)
    # ~30 Ride hailing / Visitor cars
    vehicles_to_create = []

    # 1. Faculty Vehicles (1 per faculty)
    for f in faculty_owners:
        plate = generate_plate(random.choice(["CH01", "PB65", "PB08", "HR70"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        model, color = random.choice(CAR_MODELS)
        vehicles_to_create.append((plate, norm, VehicleCategory.FACULTY, f, model, color))
        existing_plates.add(norm)

    # 2. Student Vehicles (~250 vehicles for students)
    selected_students = random.sample(student_owners, min(250, len(student_owners)))
    for s in selected_students:
        plate = generate_plate(random.choice(["CH01", "PB65", "PB10", "PB11", "HR03", "DL01"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        is_bike = (random.random() < 0.70)
        model, color = random.choice(BIKE_MODELS if is_bike else CAR_MODELS)
        vehicles_to_create.append((plate, norm, VehicleCategory.STUDENT, s, model, color))
        existing_plates.add(norm)

    # 3. Resident Vehicles (1 per resident)
    for r in resident_owners:
        plate = generate_plate(random.choice(["CH01", "PB65", "HR70"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        model, color = random.choice(CAR_MODELS if random.random() < 0.6 else BIKE_MODELS)
        vehicles_to_create.append((plate, norm, VehicleCategory.RESIDENT, r, model, color))
        existing_plates.add(norm)

    # 4. Staff Vehicles (1 per staff)
    for st in staff_owners:
        plate = generate_plate(random.choice(["CH01", "PB65", "HR26"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        model, color = random.choice(BIKE_MODELS if random.random() < 0.6 else CAR_MODELS)
        vehicles_to_create.append((plate, norm, VehicleCategory.STAFF, st, model, color))
        existing_plates.add(norm)

    # 5. Delivery Vehicles (50 commercial 2-wheelers, unlinked or delivery category)
    for d_i in range(50):
        plate = generate_plate(random.choice(["CH01", "PB65", "HR03"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        model, color = random.choice(BIKE_MODELS)
        vehicles_to_create.append((plate, norm, VehicleCategory.DELIVERY, None, model, color))
        existing_plates.add(norm)

    # 6. Ride Hailing / Visitor Vehicles (30 cars)
    for v_i in range(30):
        plate = generate_plate(random.choice(["CH01", "PB08", "DL04"]))
        norm = normalize_plate(plate)
        if norm in existing_plates:
            continue
        cat = VehicleCategory.RIDE_HAILING if random.random() < 0.6 else VehicleCategory.VISITOR
        model, color = random.choice(CAR_MODELS)
        vehicles_to_create.append((plate, norm, cat, None, model, color))
        existing_plates.add(norm)

    now = datetime.now(timezone.utc)
    all_saved_vehicles = []

    for plate, norm, cat, owner, model, color in vehicles_to_create:
        v = Vehicle(
            normalized_plate=norm,
            raw_plate=plate,
            vehicle_category=cat,
            status=VehicleStatus.ACTIVE,
            owner_id=owner.id if owner else None,
            make_model=model,
            color=color,
            valid_from=now - timedelta(days=180),
            valid_until=now + timedelta(days=365)
        )
        db.add(v)
        db.flush()
        all_saved_vehicles.append(v)
        created_vehicles += 1

        if owner:
            link = VehicleLinkEvent(
                vehicle_id=v.id,
                owner_id=owner.id,
                method=LinkMethod.ADMIN,
                evidence_note=f"Campus Security Institutional Registration for {owner.identifier} ({owner.full_name})",
                linked_by_id=admin_user.id,
                linked_at=now - timedelta(days=random.randint(10, 100))
            )
            db.add(link)

    db.commit()
    print(f"  -> Created {created_vehicles} new vehicles with link events.")

    # -------------------------------------------------------------
    # 6. Movement Logs & Overstay Setup
    # -------------------------------------------------------------
    print("\nGenerating realistic Gate Entry/Exit movements across past 48 hours...")
    # Select ~35 vehicles to be CURRENTLY INSIDE campus
    # Amongst them:
    # - 25 registered vehicles (Students & Faculty)
    # - 5 unlinked delivery/visitor vehicles entered 1.8 to 2.5 hours ago (TRIGGERS OVERSTAY_UNLINKED alert!)
    inside_vehicles = random.sample(all_saved_vehicles, min(35, len(all_saved_vehicles)))

    # Ensure at least 3 unlinked delivery/visitor vehicles are in this list
    unlinked_inside = [v for v in inside_vehicles if not v.owner_id]
    if len(unlinked_inside) < 3:
        candidate_unlinked = [v for v in all_saved_vehicles if not v.owner_id and v not in inside_vehicles]
        for extra in candidate_unlinked[: 3 - len(unlinked_inside)]:
            inside_vehicles.append(extra)

    # Movements for ~400 vehicles with both ENTRY and EXIT (already departed)
    departed_vehicles = [v for v in all_saved_vehicles if v not in inside_vehicles]

    for v in departed_vehicles:
        # Came in between 48h and 6h ago, left 1-4 hours later
        entry_time = now - timedelta(hours=random.uniform(6.0, 48.0))
        stay_duration = timedelta(hours=random.uniform(0.5, 4.0))
        exit_time = entry_time + stay_duration
        gate = random.choice(list(gates.values()))

        # Entry Log
        entry_log = EntryExitLog(
            vehicle_id=v.id,
            plate=v.raw_plate,
            normalized_plate=v.normalized_plate,
            gate_id=gate.id,
            direction=GateDirection.ENTRY,
            timestamp=entry_time,
            confidence=0.96,
            direction_method=DirectionMethod.CAMERA_ROLE,
            plate_source=LogPlateSource.OBSERVATION
        )
        db.add(entry_log)

        # Exit Log
        exit_gate = random.choice(list(gates.values()))
        exit_log = EntryExitLog(
            vehicle_id=v.id,
            plate=v.raw_plate,
            normalized_plate=v.normalized_plate,
            gate_id=exit_gate.id,
            direction=GateDirection.EXIT,
            timestamp=exit_time,
            confidence=0.95,
            direction_method=DirectionMethod.CAMERA_ROLE,
            plate_source=LogPlateSource.OBSERVATION
        )
        db.add(exit_log)
        created_movements += 2

    # Now handle the CURRENTLY INSIDE vehicles (ONLY ENTRY, no EXIT yet)
    for v in inside_vehicles:
        gate = random.choice(list(gates.values()))
        if not v.owner_id:
            # Overstay candidate: entered 1.8 to 2.5 hours ago!
            entry_time = now - timedelta(hours=random.uniform(1.8, 2.5))
        else:
            # Regular resident/student inside: entered 0.2 to 1.2 hours ago
            entry_time = now - timedelta(hours=random.uniform(0.2, 1.2))

        entry_log = EntryExitLog(
            vehicle_id=v.id,
            plate=v.raw_plate,
            normalized_plate=v.normalized_plate,
            gate_id=gate.id,
            direction=GateDirection.ENTRY,
            timestamp=entry_time,
            confidence=0.97,
            direction_method=DirectionMethod.CAMERA_ROLE,
            plate_source=LogPlateSource.OBSERVATION
        )
        db.add(entry_log)
        created_movements += 1

    db.commit()
    print(f"  -> Created {created_movements} movement logs.")
    print(f"  -> {len(inside_vehicles)} vehicles currently inside campus.")
    unlinked_overstay_count = sum(1 for v in inside_vehicles if not v.owner_id)
    print(f"  -> {unlinked_overstay_count} unlinked vehicles inside campus with >1.5h duration (Ready for Overstay Alert testing).")

    print("\n" + "=" * 70)
    print("COLLEGE MEMBERS & VEHICLES SEEDING COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    db.close()

if __name__ == "__main__":
    seed_all()
