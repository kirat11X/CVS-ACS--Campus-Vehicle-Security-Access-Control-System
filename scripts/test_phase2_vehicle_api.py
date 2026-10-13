import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
import threading
import httpx
import uvicorn

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import VehicleOwner, Vehicle, User, PersonType, ResidenceType, VehicleCategory, VehicleStatus
from backend.app.services.auth_service import hash_password
from backend.app.services.plate_normalizer import normalize_plate
from backend.app.services.vehicle_identity_service import vehicle_identity_service

def start_backend():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def run_tests():
    # Setup test owners directly in database for identity association
    db = SessionLocal()
    
    # 1. Hosteller student
    hosteller_student = VehicleOwner(
        identifier=f"STUDENT-2026-H{uuid.uuid4().hex[:4].upper()}",
        full_name="Aman Preet Singh",
        email=f"aman_{uuid.uuid4().hex[:4]}@campus.edu",
        phone="+919811122233",
        person_type=PersonType.STUDENT,
        residence_type=ResidenceType.HOSTELLER,
        residence="BH-4, Room 312",
        department="Computer Science & Engineering",
        status="ACTIVE"
    )
    # 2. Day Scholar student
    day_scholar_student = VehicleOwner(
        identifier=f"STUDENT-2026-D{uuid.uuid4().hex[:4].upper()}",
        full_name="Priya Sharma",
        email=f"priya_{uuid.uuid4().hex[:4]}@campus.edu",
        phone="+919844455566",
        person_type=PersonType.STUDENT,
        residence_type=ResidenceType.DAY_SCHOLAR,
        residence="Sector 15, Chandigarh",
        department="Electronics & Communication",
        status="ACTIVE"
    )
    # 3. Faculty member
    faculty_owner = VehicleOwner(
        identifier=f"FACULTY-2026-F{uuid.uuid4().hex[:4].upper()}",
        full_name="Dr. Rajesh Verma",
        email=f"verma_{uuid.uuid4().hex[:4]}@campus.edu",
        phone="+919877788899",
        person_type=PersonType.FACULTY,
        residence_type=ResidenceType.OFF_CAMPUS,
        residence="Panchkula Sector 4",
        department="Mechanical Engineering",
        status="ACTIVE"
    )
    # Registry administrator (Phase 5C: vehicle registration requires an authenticated ADMIN)
    admin_password = uuid.uuid4().hex
    registry_admin = User(
        username=f"p2_admin_{uuid.uuid4().hex[:6]}",
        email=f"p2_admin_{uuid.uuid4().hex[:6]}@campus.edu",
        full_name="Phase 2 Registry Admin",
        role="ADMIN",
        hashed_password=hash_password(admin_password)
    )
    db.add_all([hosteller_student, day_scholar_student, faculty_owner, registry_admin])
    db.commit()
    db.refresh(hosteller_student)
    db.refresh(day_scholar_student)
    db.refresh(faculty_owner)
    db.refresh(registry_admin)
    db.close()

    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10.0)
    resp_login = client.post("/auth/login", json={"username": registry_admin.username, "password": admin_password})
    assert resp_login.status_code == 200, f"Admin login failed: {resp_login.text}"
    client.headers["Authorization"] = f"Bearer {resp_login.json()['access_token']}"

    print("========================================================")
    print("PHASE 2: VEHICLE REGISTRY + IDENTITY ASSOCIATION TESTS")
    print("========================================================")

    # --- Scenario 1: Create Student Vehicle (Hosteller) ---
    print("\n[SCENARIO 1] Create student vehicle (Hosteller)...")
    plate_1_raw = f"PB 65 AB {uuid.uuid4().hex[:4].upper()}"
    plate_1_norm = normalize_plate(plate_1_raw)
    
    resp1 = client.post("/vehicles", json={
        "plate": plate_1_raw,
        "vehicle_category": "STUDENT",
        "owner_id": hosteller_student.identifier,
        "make_model": "Maruti Swift",
        "color": "Red",
        "valid_from": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        "valid_until": (datetime.now(timezone.utc) + timedelta(days=360)).isoformat(),
        "notes": "Hostel parking authorized"
    })
    assert resp1.status_code == 201, f"Failed to register vehicle: {resp1.text}"
    v1_data = resp1.json()
    print(f"  -> Created vehicle: {v1_data['vehicle']['plate']}, owner: {v1_data['owner']['name']}")
    assert v1_data["vehicle"]["plate"] == plate_1_norm
    assert v1_data["vehicle"]["raw_plate"] == plate_1_raw
    print("  -> PASS Scenario 1: Created student vehicle.")

    # --- Scenario 2: Plate Normalization ---
    print("\n[SCENARIO 2] Verify plate normalization...")
    assert v1_data["vehicle"]["plate"] == plate_1_norm
    assert " " not in v1_data["vehicle"]["plate"]
    assert "-" not in v1_data["vehicle"]["plate"]
    print(f"  -> Raw: '{plate_1_raw}' -> Normalized: '{plate_1_norm}'")
    print("  -> PASS Scenario 2: Plate correctly normalized.")

    # --- Scenario 3: Reject Duplicate Normalized Plate ---
    print("\n[SCENARIO 3] Reject duplicate normalized plate with 409 Conflict...")
    # Vary casing and punctuation
    variant_plate = f"{plate_1_raw.lower().replace(' ', '-')}"
    resp_dup = client.post("/vehicles", json={
        "plate": variant_plate,
        "vehicle_category": "STUDENT",
        "owner_id": hosteller_student.identifier
    })
    assert resp_dup.status_code == 409, f"Expected 409 Conflict, got {resp_dup.status_code}: {resp_dup.text}"
    print(f"  -> Duplicate attempt '{variant_plate}' correctly rejected: {resp_dup.json().get('detail')}")
    print("  -> PASS Scenario 3: Duplicate normalized plate rejected.")

    # --- Scenario 4: Retrieve Vehicle by Plate (varying format) ---
    print("\n[SCENARIO 4] Retrieve vehicle by plate with un-normalized lookup...")
    resp_get = client.get(f"/vehicles/{variant_plate}")
    assert resp_get.status_code == 200, f"Lookup failed: {resp_get.text}"
    retrieved = resp_get.json()
    assert retrieved["vehicle"]["plate"] == plate_1_norm
    print(f"  -> Successfully queried with '{variant_plate}', resolved to '{retrieved['vehicle']['plate']}'")
    print("  -> PASS Scenario 4: Plate lookup is tolerant to formatting.")

    # --- Scenario 5: Retrieve Vehicle + Owner Association ---
    print("\n[SCENARIO 5] Verify Vehicle -> Owner association...")
    assert retrieved["owner"] is not None
    assert retrieved["owner"]["institutional_id"] == hosteller_student.identifier
    assert retrieved["owner"]["name"] == hosteller_student.full_name
    print(f"  -> Owner identity: {retrieved['owner']['name']} ({retrieved['owner']['institutional_id']})")
    print("  -> PASS Scenario 5: Vehicle -> Owner identity association verified.")

    # --- Scenario 6: Verify Hosteller Context ---
    print("\n[SCENARIO 6] Verify Hosteller residence context...")
    assert retrieved["context"]["person_type"] == "STUDENT"
    assert retrieved["context"]["residence_type"] == "HOSTELLER"
    assert "BH-4" in retrieved["context"]["residence"]
    assert retrieved["context"]["is_active"] is True
    print(f"  -> Context: Person={retrieved['context']['person_type']}, Residence={retrieved['context']['residence_type']} ({retrieved['context']['residence']})")
    print("  -> PASS Scenario 6: Hosteller context verified.")

    # --- Scenario 7: Create Day Scholar Vehicle & Verify Context ---
    print("\n[SCENARIO 7] Create Day-Scholar vehicle and verify Day-Scholar context...")
    plate_2_raw = f"CH 01 CD {uuid.uuid4().hex[:4].upper()}"
    plate_2_norm = normalize_plate(plate_2_raw)
    
    resp2 = client.post("/vehicles", json={
        "plate": plate_2_raw,
        "vehicle_category": "STUDENT",
        "owner_id": day_scholar_student.identifier,
        "make_model": "Honda Activa",
        "color": "Black"
    })
    assert resp2.status_code == 201
    v2_data = resp2.json()
    assert v2_data["context"]["person_type"] == "STUDENT"
    assert v2_data["context"]["residence_type"] == "DAY_SCHOLAR"
    print(f"  -> Context: Person={v2_data['context']['person_type']}, Residence={v2_data['context']['residence_type']} ({v2_data['owner']['residence']})")
    print("  -> PASS Scenario 7: Day-Scholar context verified.")

    # --- Scenario 8: Filter Vehicles by Category ---
    print("\n[SCENARIO 8] Filter vehicles by category (STUDENT)...")
    resp_cat = client.get("/vehicles?category=STUDENT")
    assert resp_cat.status_code == 200
    cat_list = resp_cat.json()
    assert len(cat_list) >= 2
    assert all(item["vehicle"]["category"] == "STUDENT" for item in cat_list)
    print(f"  -> Retrieved {len(cat_list)} STUDENT vehicles")
    print("  -> PASS Scenario 8: Category filtering verified.")

    # --- Scenario 9: Filter Vehicles by Status ---
    print("\n[SCENARIO 9] Filter vehicles by status (ACTIVE)...")
    resp_stat = client.get("/vehicles?status=ACTIVE")
    assert resp_stat.status_code == 200
    active_list = resp_stat.json()
    assert all(item["vehicle"]["status"] == "ACTIVE" for item in active_list)
    print(f"  -> Retrieved {len(active_list)} ACTIVE vehicles")
    print("  -> PASS Scenario 9: Status filtering verified.")

    # --- Scenario 10: Update Vehicle Metadata via PUT ---
    print("\n[SCENARIO 10] Update vehicle metadata (color & notes)...")
    resp_upd = client.put(f"/vehicles/{plate_1_norm}", json={
        "color": "Metallic Blue",
        "notes": "Updated parking sticker #ST-902-B"
    })
    assert resp_upd.status_code == 200
    upd_data = resp_upd.json()
    assert upd_data["vehicle"]["color"] == "Metallic Blue"
    assert upd_data["vehicle"]["notes"] == "Updated parking sticker #ST-902-B"

    # Also verify that attempting to mutate plate itself is rejected!
    resp_plate_mut = client.put(f"/vehicles/{plate_1_norm}", json={
        "plate": "PB99ZZ9999"
    })
    assert resp_plate_mut.status_code == 400
    print(f"  -> Plate mutation attempt rejected: {resp_plate_mut.json().get('detail')}")
    print("  -> PASS Scenario 10: Vehicle update succeeded and plate mutation was rejected.")

    # --- Scenario 11: Soft Delete / Deactivate Vehicle ---
    print("\n[SCENARIO 11] Soft-delete vehicle via DELETE /vehicles/{plate}...")
    resp_del = client.delete(f"/vehicles/{plate_1_norm}")
    assert resp_del.status_code == 200
    del_data = resp_del.json()
    assert del_data["status"] == "success"
    assert del_data["vehicle_status"] == "INACTIVE"
    print(f"  -> Deactivation response: {del_data['message']}")
    print("  -> PASS Scenario 11: Soft delete endpoint returned success.")

    # --- Scenario 12: Verify Historical Database Record Remains ---
    print("\n[SCENARIO 12] Verify vehicle row is still physically present in database...")
    db = SessionLocal()
    persisted_veh = db.query(Vehicle).filter_by(normalized_plate=plate_1_norm).first()
    db.close()
    assert persisted_veh is not None, "Vehicle was physically deleted! Soft delete required."
    assert persisted_veh.status == VehicleStatus.INACTIVE
    print(f"  -> Verified row persists in DB: ID={persisted_veh.id}, Plate={persisted_veh.normalized_plate}, Status={persisted_veh.status.value}")
    print("  -> PASS Scenario 12: Historical record preserved in database for auditing.")

    # --- Scenario 13: Unknown Plate Returns 404 ---
    print("\n[SCENARIO 13] Verify unknown plate returns 404 Not Found...")
    resp_unknown = client.get("/vehicles/DL99XX9999")
    assert resp_unknown.status_code == 404
    print(f"  -> 404 response: {resp_unknown.json().get('detail')}")
    print("  -> PASS Scenario 13: Unknown plate lookup returned 404.")

    # --- Scenario 14: Invalid Owner Association Rejected ---
    print("\n[SCENARIO 14] Verify invalid owner association is rejected with 404...")
    resp_bad_owner = client.post("/vehicles", json={
        "plate": "PB01AB0001",
        "vehicle_category": "STUDENT",
        "owner_id": "STUDENT-NONEXISTENT-999"
    })
    assert resp_bad_owner.status_code == 404
    print(f"  -> Invalid owner rejected: {resp_bad_owner.json().get('detail')}")
    print("  -> PASS Scenario 14: Invalid owner association rejected.")

    # --- Scenario 15: Expired Vehicle Representation ---
    print("\n[SCENARIO 15] Verify expired vehicle representation and is_active flag...")
    plate_expired_raw = f"HR 26 EX {uuid.uuid4().hex[:4].upper()}"
    plate_expired_norm = normalize_plate(plate_expired_raw)
    
    resp_exp = client.post("/vehicles", json={
        "plate": plate_expired_raw,
        "vehicle_category": "FACULTY",
        "owner_id": faculty_owner.identifier,
        "valid_from": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
        "valid_until": (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()  # Expired 35 days ago
    })
    assert resp_exp.status_code == 201
    exp_data = resp_exp.json()
    assert exp_data["vehicle"]["is_active"] is False
    assert exp_data["context"]["is_active"] is False
    print(f"  -> Expired vehicle: plate={exp_data['vehicle']['plate']}, is_active={exp_data['vehicle']['is_active']}")
    print("  -> PASS Scenario 15: Expired vehicle correctly evaluates is_active=False.")

    print("\n========================================================")
    print("ALL 15 SCENARIOS PASSED FOR PHASE 2 VEHICLE REGISTRY API!")
    print("========================================================")

if __name__ == "__main__":
    server_thread = threading.Thread(target=start_backend, daemon=True)
    server_thread.start()
    time.sleep(2.0)

    try:
        run_tests()
    except Exception as e:
        print(f"\nTEST SUITE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
