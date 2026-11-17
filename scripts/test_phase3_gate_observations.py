import os
import sys
import time
import uuid
import threading
from datetime import datetime, timezone
import httpx
import uvicorn

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models.gate import Gate, AccessDecision
from backend.app.models.observation import ObservationEvent
from backend.app.models.vehicle import Vehicle
from backend.app.models.enums import GateStatus, ObservationSource, ObservedVehicleType, ObservationDirection
from backend.app.models.identity import User
from backend.app.services.auth_service import hash_password
from backend.app.services.plate_normalizer import normalize_plate

def start_backend():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def run_tests():
    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10.0)

    # Observation reads need a staff token (they expose plate sightings): log in as an ADMIN
    db = SessionLocal()
    admin_password = uuid.uuid4().hex
    gate_admin = User(
        username=f"p3_admin_{uuid.uuid4().hex[:6]}",
        email=f"p3_admin_{uuid.uuid4().hex[:6]}@campus.edu",
        full_name="Phase 3 Gate Admin",
        role="ADMIN",
        hashed_password=hash_password(admin_password)
    )
    db.add(gate_admin)
    db.commit()
    db.refresh(gate_admin)
    db.close()
    resp_login = client.post("/auth/login", json={"username": gate_admin.username, "password": admin_password})
    assert resp_login.status_code == 200, f"Admin login failed: {resp_login.text}"
    client.headers["Authorization"] = f"Bearer {resp_login.json()['access_token']}"

    print("========================================================")
    print("PHASE 3: GATE REGISTRY & GATE OBSERVATION MANAGEMENT")
    print("========================================================")

    # --- Scenario 1: Create GATE_1 ---
    print("\n[SCENARIO 1] Register GATE_1...")
    resp_g1 = client.post("/gates", json={
        "id": "GATE_1",
        "name": "Main North Gate",
        "camera_id": "gate_cam",
        "location": "North Perimeter Main Entrance",
        "status": "ACTIVE",
        "direction_capability": "BIDIRECTIONAL"
    })
    if resp_g1.status_code == 409:
        print("  -> GATE_1 already exists in registry (verified 409 Conflict duplicate rejection).")
    else:
        assert resp_g1.status_code == 201, f"Failed to create GATE_1: {resp_g1.text}"
        print("  -> Created GATE_1 successfully.")
    print("  -> PASS Scenario 1: GATE_1 registration verified.")

    # --- Scenario 2: Create GATE_2 ---
    print("\n[SCENARIO 2] Register GATE_2...")
    resp_g2 = client.post("/gates", json={
        "id": "GATE_2",
        "name": "South Campus Gate",
        "camera_id": "gate_2_cam",
        "location": "South Perimeter Staff & Visitor Entry",
        "status": "ACTIVE",
        "direction_capability": "BIDIRECTIONAL"
    })
    if resp_g2.status_code == 409:
        print("  -> GATE_2 already exists in registry (verified 409 Conflict duplicate rejection).")
    else:
        assert resp_g2.status_code == 201, f"Failed to create GATE_2: {resp_g2.text}"
        print("  -> Created GATE_2 successfully.")
    print("  -> PASS Scenario 2: GATE_2 registration verified.")

    # --- Scenario 3: Create GATE_3 ---
    print("\n[SCENARIO 3] Register GATE_3...")
    resp_g3 = client.post("/gates", json={
        "id": "GATE_3",
        "name": "Hostel East Gate",
        "camera_id": "gate_3_cam",
        "location": "East Perimeter Hostel Block Entrance",
        "status": "ACTIVE",
        "direction_capability": "BIDIRECTIONAL"
    })
    if resp_g3.status_code == 409:
        print("  -> GATE_3 already exists in registry (verified 409 Conflict duplicate rejection).")
    else:
        assert resp_g3.status_code == 201, f"Failed to create GATE_3: {resp_g3.text}"
        print("  -> Created GATE_3 successfully.")
    print("  -> PASS Scenario 3: GATE_3 registration verified.")

    # --- Scenario 4: Retrieve gates ---
    print("\n[SCENARIO 4] Retrieve all configured gates...")
    resp_list = client.get("/gates")
    assert resp_list.status_code == 200
    gates = resp_list.json()
    gate_ids = [g["id"] for g in gates]
    assert "GATE_1" in gate_ids
    assert "GATE_2" in gate_ids
    assert "GATE_3" in gate_ids
    print(f"  -> Successfully retrieved {len(gates)} gates: {gate_ids}")
    print("  -> PASS Scenario 4: Gate listing verified.")

    # --- Scenario 5: Retrieve gate by ID ---
    print("\n[SCENARIO 5] Retrieve gate by ID (GATE_1)...")
    resp_get_g1 = client.get("/gates/GATE_1")
    assert resp_get_g1.status_code == 200
    g1_data = resp_get_g1.json()
    assert g1_data["id"] == "GATE_1"
    assert g1_data["camera_id"] == "gate_cam"
    print(f"  -> Retrieved GATE_1: name='{g1_data['name']}', camera='{g1_data['camera_id']}', status='{g1_data['status']}'")
    print("  -> PASS Scenario 5: Gate retrieval by ID verified.")

    # --- Scenario 6: Update gate metadata ---
    print("\n[SCENARIO 6] Update gate metadata (location and description)...")
    updated_loc = f"North Perimeter Main Entrance (Updated {uuid.uuid4().hex[:4]})"
    resp_put = client.put("/gates/GATE_1", json={"location": updated_loc})
    assert resp_put.status_code == 200
    assert resp_put.json()["location"] == updated_loc
    print(f"  -> Updated GATE_1 location: '{updated_loc}'")
    print("  -> PASS Scenario 6: Gate metadata update verified.")

    # --- Scenario 7: Change gate operational status ---
    print("\n[SCENARIO 7] Change gate operational status to MAINTENANCE then ACTIVE...")
    resp_maint = client.put("/gates/GATE_1", json={"status": "MAINTENANCE"})
    assert resp_maint.status_code == 200
    assert resp_maint.json()["status"] == "MAINTENANCE"
    print("  -> GATE_1 status successfully changed to MAINTENANCE")
    
    resp_active = client.put("/gates/GATE_1", json={"status": "ACTIVE"})
    assert resp_active.status_code == 200
    assert resp_active.json()["status"] == "ACTIVE"
    print("  -> GATE_1 status restored to ACTIVE")
    print("  -> PASS Scenario 7: Gate operational status transitions verified.")

    # --- Scenario 8: Create a Frigate observation ---
    print("\n[SCENARIO 8] Create a Frigate vehicle observation...")
    track_event_id = f"frigate_evt_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    raw_test_plate = "pb 65 ab 0902"
    resp_obs1 = client.post("/observations", json={
        "gate_id": "GATE_1",
        "camera_id": "gate_cam",
        "source": "FRIGATE",
        "source_event_id": track_event_id,
        "raw_plate": raw_test_plate,
        "plate_confidence": 0.94,
        "vehicle_type": "MOTORCYCLE",
        "vehicle_confidence": 0.91,
        "direction": "UNKNOWN",
        "metadata_payload": {"frigate_score": 0.94, "box": [100, 150, 200, 250]}
    })
    assert resp_obs1.status_code == 201, f"Failed to record observation: {resp_obs1.text}"
    obs1 = resp_obs1.json()
    print(f"  -> Ingested observation ID: {obs1['id']}")
    print("  -> PASS Scenario 8: Frigate observation ingested.")

    # --- Scenario 9: Normalize observed plate ---
    print("\n[SCENARIO 9] Verify plate normalization...")
    assert obs1["plate"]["normalized"] == "PB65AB0902"
    assert " " not in obs1["plate"]["normalized"]
    print(f"  -> Raw: '{raw_test_plate}' -> Normalized: '{obs1['plate']['normalized']}'")
    print("  -> PASS Scenario 9: Plate normalization verified.")

    # --- Scenario 10: Preserve raw plate ---
    print("\n[SCENARIO 10] Verify raw plate preservation...")
    assert obs1["plate"]["raw"] == raw_test_plate
    print(f"  -> Raw plate accurately preserved: '{obs1['plate']['raw']}'")
    print("  -> PASS Scenario 10: Raw plate preserved.")

    # --- Scenario 11: Preserve LPR confidence ---
    print("\n[SCENARIO 11] Verify LPR confidence preservation...")
    assert obs1["plate"]["confidence"] == 0.94
    print(f"  -> Plate confidence preserved: {obs1['plate']['confidence']}")
    print("  -> PASS Scenario 11: LPR confidence preserved.")

    # --- Scenario 12: Preserve vehicle type separately from institutional category ---
    print("\n[SCENARIO 12] Verify observed vehicle type is separated from institutional category...")
    assert obs1["vehicle_observation"]["type"] == "MOTORCYCLE"
    assert obs1["vehicle_observation"]["confidence"] == 0.91
    # Verify no institutional category (e.g. STUDENT, DELIVERY) exists in observation
    assert "category" not in obs1
    assert "vehicle_category" not in obs1
    print(f"  -> Sensor vehicle type: {obs1['vehicle_observation']['type']} (confidence: {obs1['vehicle_observation']['confidence']})")
    print("  -> PASS Scenario 12: Physical vehicle type separated from institutional category.")

    # --- Scenario 13: Preserve Frigate event ID ---
    print("\n[SCENARIO 13] Verify Frigate event ID preservation...")
    assert obs1["source_event_id"] == track_event_id
    print(f"  -> Frigate source_event_id: '{obs1['source_event_id']}'")
    print("  -> PASS Scenario 13: Frigate event ID preserved.")

    # --- Scenario 14: Retrieve observations for a gate ---
    print("\n[SCENARIO 14] Retrieve observations for GATE_1...")
    resp_gate_obs = client.get("/gates/GATE_1/observations")
    assert resp_gate_obs.status_code == 200
    gate_obs_list = resp_gate_obs.json()
    assert len(gate_obs_list) >= 1
    found_obs = any(o["id"] == obs1["id"] for o in gate_obs_list)
    assert found_obs
    print(f"  -> Retrieved {len(gate_obs_list)} observations for GATE_1; matched observation {obs1['id']}")
    print("  -> PASS Scenario 14: Gate observations retrieval verified.")

    # --- Scenario 15: Retrieve observations for a plate ---
    print("\n[SCENARIO 15] Retrieve observations for plate (format-tolerant)...")
    # Query with unformatted/hyphenated plate
    resp_plate_obs = client.get("/vehicles/pb-65-ab-0902/observations")
    assert resp_plate_obs.status_code == 200
    plate_obs_list = resp_plate_obs.json()
    assert len(plate_obs_list) >= 1
    assert any(o["id"] == obs1["id"] for o in plate_obs_list)
    print(f"  -> Successfully queried with 'pb-65-ab-0902', matched observation {obs1['id']}")
    print("  -> PASS Scenario 15: Plate observations retrieval verified.")

    # --- Scenario 16: Handle unknown plate ---
    print("\n[SCENARIO 16] Ingest observation with completely unknown plate...")
    unknown_raw_plate = f"DL 99 ZZ {uuid.uuid4().hex[:4].upper()}"
    unknown_norm_plate = normalize_plate(unknown_raw_plate)
    
    resp_unknown = client.post("/observations", json={
        "gate_id": "GATE_2",
        "source": "FRIGATE",
        "source_event_id": f"unknown_evt_{uuid.uuid4().hex[:6]}",
        "raw_plate": unknown_raw_plate,
        "plate_confidence": 0.88,
        "vehicle_type": "CAR",
        "direction": "UNKNOWN"
    })
    assert resp_unknown.status_code == 201
    unk_obs = resp_unknown.json()
    assert unk_obs["plate"]["normalized"] == unknown_norm_plate
    
    # Confirm the unknown plate is NOT auto-registered in Vehicle registry
    db = SessionLocal()
    veh_in_db = db.query(Vehicle).filter_by(normalized_plate=unknown_norm_plate).first()
    assert veh_in_db is None, "Unknown vehicle should NOT be automatically registered!"
    db.close()
    print(f"  -> Unknown plate '{unknown_raw_plate}' ingested without creating vehicle entity")
    print("  -> PASS Scenario 16: Unknown plate handled cleanly.")

    # --- Scenario 17: Handle missing/unknown direction ---
    print("\n[SCENARIO 17] Handle observation with UNKNOWN direction...")
    assert obs1["direction"] == "UNKNOWN"
    print(f"  -> Direction correctly preserved as: '{obs1['direction']}'")
    print("  -> PASS Scenario 17: Unknown direction handled cleanly.")

    # --- Scenario 18: Deduplication / Idempotency ---
    print("\n[SCENARIO 18] Verify deduplication: re-posting same Frigate event refines record...")
    resp_dedup = client.post("/observations", json={
        "gate_id": "GATE_1",
        "source": "FRIGATE",
        "source_event_id": track_event_id,
        "raw_plate": "PB 65 AB 0902",
        "plate_confidence": 0.98,  # Higher confidence refinement from a subsequent frame
        "vehicle_type": "MOTORCYCLE",
        "vehicle_confidence": 0.95,
        "direction": "ENTRY",
        "metadata_payload": {"frigate_score": 0.98, "frame": 45}
    })
    assert resp_dedup.status_code == 201
    obs_dedup = resp_dedup.json()
    assert obs_dedup["id"] == obs1["id"], "Same Frigate event ID should update existing record, not create duplicate ID!"
    assert obs_dedup["plate"]["confidence"] == 0.98
    assert obs_dedup["direction"] == "ENTRY"

    # Confirm only 1 database row exists for this source_event_id
    db = SessionLocal()
    count_rows = db.query(ObservationEvent).filter_by(source_event_id=track_event_id).count()
    assert count_rows == 1, f"Expected exactly 1 observation row, found {count_rows}!"
    db.close()
    print(f"  -> Re-ingested Frigate event '{track_event_id}'. Database row count = {count_rows}, confidence updated to 0.98")
    print("  -> PASS Scenario 18: Deduplication and idempotency verified.")

    # --- Scenario 19: Historical observations remain after gate deactivation ---
    print("\n[SCENARIO 19] Verify historical observations persist after gate deactivation...")
    test_gate_id = f"GATE_TEST_{uuid.uuid4().hex[:4].upper()}"
    client.post("/gates", json={
        "id": test_gate_id,
        "name": "Temporary Event Gate",
        "camera_id": "temp_cam",
        "status": "ACTIVE"
    })
    
    resp_temp_obs = client.post("/observations", json={
        "gate_id": test_gate_id,
        "raw_plate": "HR 26 TEMP 01",
        "plate_confidence": 0.92,
        "vehicle_type": "BUS"
    })
    assert resp_temp_obs.status_code == 201
    temp_obs_id = resp_temp_obs.json()["id"]

    # Deactivate the gate
    resp_deact = client.delete(f"/gates/{test_gate_id}")
    assert resp_deact.status_code == 200
    
    # Verify gate is INACTIVE
    gate_check = client.get(f"/gates/{test_gate_id}").json()
    assert gate_check["status"] == "INACTIVE"

    # Verify historical observation is STILL present and queryable
    resp_hist_obs = client.get(f"/observations/{temp_obs_id}")
    assert resp_hist_obs.status_code == 200
    assert resp_hist_obs.json()["gate"]["id"] == test_gate_id
    print(f"  -> Gate '{test_gate_id}' soft-deactivated; historical observation '{temp_obs_id}' remains fully accessible")
    print("  -> PASS Scenario 19: Historical observations preserved across gate deactivation.")

    # --- Scenario 20: Observation creation does NOT create an AccessDecision ---
    print("\n[SCENARIO 20] Explicit Invariant Test: ObservationEvent != AccessDecision...")
    db = SessionLocal()
    decisions_count_before = db.query(AccessDecision).count()
    
    # Ingest a new observation
    resp_inv_obs = client.post("/observations", json={
        "gate_id": "GATE_3",
        "raw_plate": "CH 01 AB 8888",
        "plate_confidence": 0.99,
        "vehicle_type": "CAR"
    })
    assert resp_inv_obs.status_code == 201
    inv_obs = resp_inv_obs.json()
    
    decisions_count_after = db.query(AccessDecision).count()
    db.close()
    
    # Assert zero access decisions created
    assert decisions_count_before == decisions_count_after, (
        f"Invariant Violation: Ingesting an ObservationEvent created an AccessDecision! "
        f"Before: {decisions_count_before}, After: {decisions_count_after}"
    )
    
    # Assert observation response contains NO access decision, NO threat status, and NO owner
    assert "decision" not in inv_obs
    assert "threat" not in inv_obs
    assert "owner" not in inv_obs
    print(f"  -> AccessDecision count remained unchanged ({decisions_count_before} -> {decisions_count_after})")
    print("  -> Observation response strictly contains sensory data (No 'decision', No 'threat', No 'owner')")
    print("  -> PASS Scenario 20: Invariant OBSERVATION != DECISION fully verified.")

    print("\n========================================================")
    print("ALL 20 SCENARIOS PASSED FOR PHASE 3 GATE OBSERVATION API!")
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
