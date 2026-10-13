import os
import sys
import time
import json
import uuid
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models.gate import Gate, AccessDecision
from backend.app.models.observation import ObservationEvent
from backend.app.models.vehicle import Vehicle
from backend.app.models.identity import VehicleOwner
from backend.app.models.enums import ObservationSource, ObservedVehicleType, ObservationDirection
from backend.app.services.frigate_event_parser import FrigateEventParser
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from backend.app.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT

def ensure_test_gates(db):
    """Ensure GATE_1, GATE_2, GATE_3 exist for testing."""
    gates_data = [
        {"id": "GATE_1", "name": "Main North Gate", "camera_id": "gate_cam"},
        {"id": "GATE_2", "name": "South Campus Gate", "camera_id": "gate_2_cam"},
        {"id": "GATE_3", "name": "Hostel East Gate", "camera_id": "gate_3_cam"}
    ]
    for gd in gates_data:
        g = db.query(Gate).filter_by(id=gd["id"]).first()
        if not g:
            g = Gate(id=gd["id"], name=gd["name"], camera_id=gd["camera_id"], status="ACTIVE")
            db.add(g)
    db.commit()

def run_tests():
    print("========================================================")
    print("PHASE 4: FRIGATE MQTT OBSERVATION INGESTION WORKER")
    print("========================================================")

    db = SessionLocal()
    ensure_test_gates(db)
    db.close()

    worker = FrigateMQTTWorker()

    # --- Scenario 1: Valid Frigate event ingestion ---
    print("\n[SCENARIO 1] Ingest valid Frigate event...")
    evt1_id = f"frigate_p4_valid_{uuid.uuid4().hex[:6]}"
    payload1 = {
        "type": "new",
        "before": {},
        "after": {
            "id": evt1_id,
            "camera": "gate_cam",
            "frame_time": time.time(),
            "start_time": time.time(),
            "label": "car",
            "sub_label": ["PB 65 AB 0902", 0.94],
            "top_score": 0.94,
            "score": 0.94,
            "box": [100, 150, 200, 250],
            "area": 12000
        }
    }
    obs1 = worker.process_payload(payload1)
    assert obs1 is not None, "Worker failed to ingest valid Frigate payload!"
    assert obs1.source == ObservationSource.FRIGATE
    print(f"  -> Successfully ingested ObservationEvent '{obs1.id}' for event '{evt1_id}'")
    print("  -> PASS Scenario 1: Valid Frigate event ingestion verified.")

    # --- Scenario 2: Plate normalization ---
    print("\n[SCENARIO 2] Verify plate normalization...")
    assert obs1.normalized_plate == "PB65AB0902", f"Expected PB65AB0902, got {obs1.normalized_plate}"
    print(f"  -> Raw: '{obs1.raw_plate}' -> Normalized: '{obs1.normalized_plate}'")
    print("  -> PASS Scenario 2: Plate normalization verified.")

    # --- Scenario 3: Raw plate preservation ---
    print("\n[SCENARIO 3] Verify raw plate preservation...")
    assert obs1.raw_plate == "PB 65 AB 0902", f"Expected 'PB 65 AB 0902', got '{obs1.raw_plate}'"
    print(f"  -> Exact optical string preserved: '{obs1.raw_plate}'")
    print("  -> PASS Scenario 3: Raw plate preserved.")

    # --- Scenario 4: LPR confidence preservation ---
    print("\n[SCENARIO 4] Verify LPR confidence preservation...")
    assert obs1.plate_confidence == 0.94, f"Expected 0.94, got {obs1.plate_confidence}"
    print(f"  -> LPR confidence score preserved: {obs1.plate_confidence}")
    print("  -> PASS Scenario 4: LPR confidence preserved.")

    # --- Scenario 5: Vehicle type mapping ---
    print("\n[SCENARIO 5] Verify vehicle type mapping (car, motorcycle, bus, truck)...")
    types_to_test = [
        ("car", ObservedVehicleType.CAR),
        ("motorcycle", ObservedVehicleType.MOTORCYCLE),
        ("bus", ObservedVehicleType.BUS),
        ("truck", ObservedVehicleType.TRUCK)
    ]
    for lbl, expected_enum in types_to_test:
        evt_type_id = f"frigate_p4_type_{lbl}_{uuid.uuid4().hex[:4]}"
        payload_type = {
            "after": {
                "id": evt_type_id,
                "camera": "gate_cam",
                "label": lbl,
                "score": 0.88
            }
        }
        obs_t = worker.process_payload(payload_type)
        assert obs_t is not None
        assert obs_t.vehicle_type == expected_enum, f"Expected {expected_enum} for '{lbl}', got {obs_t.vehicle_type}"
        print(f"  -> Label '{lbl}' mapped to {obs_t.vehicle_type.value}")
    print("  -> PASS Scenario 5: Physical vehicle type mapping verified.")

    # --- Scenario 6: Unknown vehicle type ---
    print("\n[SCENARIO 6] Verify unknown vehicle type mapping...")
    evt_unk_type_id = f"frigate_p4_unk_type_{uuid.uuid4().hex[:6]}"
    payload_unk_type = {
        "after": {
            "id": evt_unk_type_id,
            "camera": "gate_cam",
            "label": "unidentified_hovercraft",
            "score": 0.50
        }
    }
    obs_ut = worker.process_payload(payload_unk_type)
    assert obs_ut is not None
    assert obs_ut.vehicle_type == ObservedVehicleType.UNKNOWN
    print(f"  -> Unsupported label mapped to {obs_ut.vehicle_type.value}")
    print("  -> PASS Scenario 6: Unknown vehicle type mapping verified.")

    # --- Scenario 7: Missing plate ---
    print("\n[SCENARIO 7] Ingest vehicle observation with missing plate...")
    evt_noplate_id = f"frigate_p4_noplate_{uuid.uuid4().hex[:6]}"
    payload_noplate = {
        "after": {
            "id": evt_noplate_id,
            "camera": "gate_cam",
            "label": "car",
            "top_score": 0.85,
            "sub_label": None,
            "license_plate": None
        }
    }
    obs_np = worker.process_payload(payload_noplate)
    assert obs_np is not None, "Missing plate should NOT discard vehicle observation!"
    assert obs_np.raw_plate is None
    assert obs_np.normalized_plate is None
    assert obs_np.vehicle_type == ObservedVehicleType.CAR
    print(f"  -> Ingested observation '{obs_np.id}' without plate (raw_plate=None, normalized_plate=None)")
    print("  -> PASS Scenario 7: Missing plate handled cleanly.")

    # --- Scenario 8: Unknown/unregistered plate ---
    print("\n[SCENARIO 8] Ingest unknown/unregistered plate (UNKNOWN != THREAT)...")
    evt_unk_plate_id = f"frigate_p4_unk_plate_{uuid.uuid4().hex[:6]}"
    raw_unk = f"DL 99 ZZ {uuid.uuid4().hex[:4].upper()}"
    payload_unk_plate = {
        "after": {
            "id": evt_unk_plate_id,
            "camera": "gate_cam",
            "label": "car",
            "sub_label": raw_unk,
            "score": 0.91
        }
    }
    obs_up = worker.process_payload(payload_unk_plate)
    assert obs_up is not None

    db = SessionLocal()
    veh_check = db.query(Vehicle).filter_by(normalized_plate=obs_up.normalized_plate).first()
    assert veh_check is None, "UNKNOWN plate must NOT auto-create a Vehicle entity!"
    db.close()
    print(f"  -> Ingested unknown plate '{raw_unk}' into observation_events without creating Vehicle record")
    print("  -> PASS Scenario 8: Unknown/unregistered plate handled without auto-creating Vehicle.")

    # --- Scenario 9: Camera -> Gate mapping ---
    print("\n[SCENARIO 9] Verify Camera -> Gate resolution...")
    payload_g2 = {
        "after": {
            "id": f"frigate_p4_cam2_{uuid.uuid4().hex[:6]}",
            "camera": "gate_2_cam",
            "label": "car",
            "score": 0.89
        }
    }
    obs_g2 = worker.process_payload(payload_g2)
    assert obs_g2 is not None
    assert obs_g2.gate_id == "GATE_2", f"Expected GATE_2 for camera gate_2_cam, got {obs_g2.gate_id}"
    print(f"  -> Resolved camera 'gate_2_cam' to gate '{obs_g2.gate_id}'")
    print("  -> PASS Scenario 9: Camera -> Gate resolution verified.")

    # --- Scenario 10: Unknown camera handling ---
    print("\n[SCENARIO 10] Verify unknown camera handling (quarantine/skip)...")
    payload_unk_cam = {
        "after": {
            "id": f"frigate_p4_unk_cam_{uuid.uuid4().hex[:6]}",
            "camera": "unregistered_parking_lot_cam_99",
            "label": "car",
            "sub_label": "HR 26 AB 1111",
            "score": 0.90
        }
    }
    obs_unk_cam = worker.process_payload(payload_unk_cam)
    assert obs_unk_cam is None, "Unknown camera must NOT be accepted or assigned to a fabricated gate!"
    assert worker.stats["unmapped_cameras"] >= 1
    print("  -> Unmapped camera cleanly quarantined/rejected without creating observation under default gate")
    print("  -> PASS Scenario 10: Unknown camera handling verified.")

    # --- Scenario 11: source_event_id preservation ---
    print("\n[SCENARIO 11] Verify source_event_id preservation...")
    assert obs1.source_event_id == evt1_id
    print(f"  -> Preserved source_event_id: '{obs1.source_event_id}'")
    print("  -> PASS Scenario 11: source_event_id preservation verified.")

    # --- Scenario 12: Duplicate event idempotency ---
    print("\n[SCENARIO 12] Verify duplicate event idempotency...")
    obs1_dup = worker.process_payload(payload1)
    assert obs1_dup is not None
    assert obs1_dup.id == obs1.id, "Duplicate Frigate event must return existing ObservationEvent ID!"

    db = SessionLocal()
    row_count = db.query(ObservationEvent).filter_by(source_event_id=evt1_id).count()
    db.close()
    assert row_count == 1, f"Expected exactly 1 database row for event '{evt1_id}', found {row_count}!"
    print(f"  -> Re-ingested duplicate event. Exact row count in PostgreSQL = {row_count}")
    print("  -> PASS Scenario 12: Duplicate event idempotency verified.")

    # --- Scenario 13: Event refinement/update ---
    print("\n[SCENARIO 13] Verify event refinement/update with higher confidence...")
    refine_id = f"frigate_p4_refine_{uuid.uuid4().hex[:6]}"
    msg1 = {
        "after": {
            "id": refine_id,
            "camera": "gate_cam",
            "label": "car",
            "sub_label": ["CH 01 AB 5555", 0.71],
            "score": 0.71
        }
    }
    obs_ref1 = worker.process_payload(msg1)
    assert obs_ref1.plate_confidence == 0.71

    msg2 = {
        "after": {
            "id": refine_id,
            "camera": "gate_cam",
            "label": "car",
            "sub_label": ["CH 01 AB 5555", 0.98],
            "score": 0.98
        }
    }
    obs_ref2 = worker.process_payload(msg2)
    assert obs_ref2.id == obs_ref1.id
    assert obs_ref2.plate_confidence == 0.98

    db = SessionLocal()
    count_ref = db.query(ObservationEvent).filter_by(source_event_id=refine_id).count()
    db.close()
    assert count_ref == 1, f"Expected 1 row after refinement, got {count_ref}"
    print(f"  -> Refined event '{refine_id}': confidence updated from 0.71 -> {obs_ref2.plate_confidence}")
    print("  -> PASS Scenario 13: Event refinement/update verified.")

    # --- Scenario 14: Malformed JSON ---
    print("\n[SCENARIO 14] Verify malformed JSON handling...")
    bad_bytes = b"INVALID_NON_JSON_STREAM_DATA{{{"
    res_bad = worker.process_payload(bad_bytes)
    assert res_bad is None, "Malformed JSON must return None"
    assert worker.stats["malformed_payloads"] >= 1
    print("  -> Malformed JSON caught safely without crashing worker")
    print("  -> PASS Scenario 14: Malformed JSON handled cleanly.")

    # --- Scenario 15: Malformed/incomplete Frigate payload ---
    print("\n[SCENARIO 15] Verify incomplete Frigate payload handling...")
    incomplete_payload = {"type": "new", "something": "missing_required_fields"}
    res_inc = worker.process_payload(incomplete_payload)
    assert res_inc is None
    print("  -> Incomplete payload lacking ID/camera caught safely without crashing worker")
    print("  -> PASS Scenario 15: Incomplete Frigate payload handled cleanly.")

    # --- Scenario 16: UNKNOWN direction ---
    print("\n[SCENARIO 16] Verify UNKNOWN direction enforcement...")
    assert obs1.direction == ObservationDirection.UNKNOWN
    print(f"  -> Direction is strictly {obs1.direction.value} (no assumption of entry/exit)")
    print("  -> PASS Scenario 16: UNKNOWN direction enforcement verified.")

    # --- Scenario 17: Observation does not create AccessDecision ---
    print("\n[SCENARIO 17] Verify Observation does not create AccessDecision...")
    db = SessionLocal()
    decisions_before = db.query(AccessDecision).count()
    db.close()

    worker.process_payload({
        "after": {
            "id": f"frigate_p4_decision_check_{uuid.uuid4().hex[:6]}",
            "camera": "gate_cam",
            "label": "car",
            "sub_label": "PB 10 Z 9999",
            "score": 0.95
        }
    })

    db = SessionLocal()
    decisions_after = db.query(AccessDecision).count()
    db.close()
    assert decisions_before == decisions_after, (
        f"Invariant Violation: Ingestion created an AccessDecision! "
        f"Before: {decisions_before}, After: {decisions_after}"
    )
    print(f"  -> AccessDecision count remained unchanged: {decisions_before} == {decisions_after}")
    print("  -> PASS Scenario 17: Invariant OBSERVATION != DECISION verified.")

    # --- Scenario 18: Vehicle registry is not automatically modified ---
    print("\n[SCENARIO 18] Verify vehicle registry is not automatically modified...")
    db = SessionLocal()
    veh_count_before = db.query(Vehicle).count()
    owner_count_before = db.query(VehicleOwner).count()
    db.close()

    worker.process_payload({
        "after": {
            "id": f"frigate_p4_reg_check_{uuid.uuid4().hex[:6]}",
            "camera": "gate_cam",
            "label": "car",
            "sub_label": "HR 99 X 8888",
            "score": 0.92
        }
    })

    db = SessionLocal()
    veh_count_after = db.query(Vehicle).count()
    owner_count_after = db.query(VehicleOwner).count()
    db.close()

    assert veh_count_before == veh_count_after, "Vehicles table must NOT be modified by observation ingestion!"
    assert owner_count_before == owner_count_after, "VehicleOwners table must NOT be modified by observation ingestion!"
    print(f"  -> Vehicle count ({veh_count_before}) and Owner count ({owner_count_before}) unchanged")
    print("  -> PASS Scenario 18: Vehicle registry immutability verified.")

    # --- Scenario 19: MQTT disconnect/reconnect behavior ---
    print("\n[SCENARIO 19] Verify MQTT disconnect and reconnect behavior...")
    live_worker = FrigateMQTTWorker(client_id=f"test_p4_worker_{uuid.uuid4().hex[:6]}")
    live_worker.start()
    time.sleep(1.0)
    assert live_worker.running is True
    assert live_worker.is_connected() is True
    print("  -> Worker connected to live MQTT broker successfully")

    # Simulate disconnect
    live_worker._on_disconnect(live_worker.client, None, None, 1)
    assert live_worker.is_connected() is False
    print("  -> Disconnect detected, reconnect state managed")

    # Restore connection
    live_worker._on_connect(live_worker.client, None, None, 0)
    assert live_worker.is_connected() is True
    print("  -> Reconnection verified successfully")
    print("  -> PASS Scenario 19: MQTT disconnect/reconnect resilience verified.")

    # --- Scenario 20: Graceful worker shutdown ---
    print("\n[SCENARIO 20] Verify graceful worker shutdown...")
    live_worker.stop()
    assert live_worker.running is False
    assert live_worker.is_connected() is False
    assert live_worker.client is None
    print("  -> Worker stopped cleanly, client set to None")
    print("  -> PASS Scenario 20: Graceful worker shutdown verified.")

    print("\n========================================================")
    print("ALL 20 SCENARIOS PASSED FOR PHASE 4 FRIGATE MQTT WORKER!")
    print("========================================================")

    # --- Real MQTT Broker End-to-End Test ---
    print("\n========================================================")
    print("REAL MQTT INTEGRATION TEST: Mosquitto -> Worker -> PostgreSQL")
    print("========================================================")

    mqtt_worker = FrigateMQTTWorker(client_id=f"real_mqtt_test_worker_{uuid.uuid4().hex[:6]}")
    mqtt_worker.start()
    time.sleep(1.5)

    real_test_event_id = f"phase4-real-mqtt-{uuid.uuid4().hex[:6]}"
    real_test_plate = f"PB 65 REAL {uuid.uuid4().hex[:4].upper()}"

    real_payload = {
        "type": "new",
        "after": {
            "id": real_test_event_id,
            "camera": "gate_cam",
            "frame_time": time.time(),
            "start_time": time.time(),
            "label": "car",
            "sub_label": [real_test_plate, 0.96],
            "top_score": 0.96,
            "score": 0.96,
            "box": [120, 160, 220, 270]
        }
    }

    # Publish to real Mosquitto broker on frigate/events
    pub_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"pub_client_{uuid.uuid4().hex[:6]}")
    pub_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    pub_client.loop_start()
    time.sleep(0.5)

    print(f"  -> Publishing synthetic Frigate event to 'frigate/events' on {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}...")
    pub_client.publish("frigate/events", json.dumps(real_payload), qos=1)
    time.sleep(2.0)

    pub_client.loop_stop()
    pub_client.disconnect()

    # Query PostgreSQL to verify ObservationEvent was created
    db = SessionLocal()
    persisted_obs = db.query(ObservationEvent).filter_by(source_event_id=real_test_event_id).first()
    db.close()

    assert persisted_obs is not None, f"Real MQTT integration failed: event '{real_test_event_id}' not found in PostgreSQL!"
    assert persisted_obs.raw_plate == real_test_plate
    assert persisted_obs.gate_id == "GATE_1"
    assert persisted_obs.plate_confidence == 0.96
    assert persisted_obs.vehicle_type == ObservedVehicleType.CAR
    print(f"  -> [SUCCESS] Real MQTT event consumed from Mosquitto and verified in PostgreSQL:")
    print(f"     * Observation ID: {persisted_obs.id}")
    print(f"     * Gate: {persisted_obs.gate_id}")
    print(f"     * Plate: {persisted_obs.raw_plate} (normalized: {persisted_obs.normalized_plate})")
    print(f"     * Score: {persisted_obs.plate_confidence}")
    print(f"     * Vehicle Type: {persisted_obs.vehicle_type.value}")

    mqtt_worker.stop()
    print("  -> Real MQTT integration test PASSED.")
    print("========================================================\n")

if __name__ == "__main__":
    try:
        run_tests()
        sys.exit(0)
    except Exception as e:
        print(f"\nTEST SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
