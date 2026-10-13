import sys
import os
import time
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from backend.app.db import SessionLocal
from backend.app.models.gate import Gate, AccessDecision, SecurityAlert
from backend.app.models.observation import ObservationEvent
from backend.app.models.vehicle import Vehicle
from backend.app.models.identity import VehicleOwner
from backend.app.models.enums import ObservationSource, ObservedVehicleType, GateStatus
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from scripts.prototypes.phase5_identity_resolution.models import ResolutionStatus, MatchMethod, ResolutionResult
from scripts.prototypes.phase5_identity_resolution.resolver import IdentityResolver
from scripts.prototypes.phase5_identity_resolution.fixtures import get_test_fixtures

def ensure_test_infrastructure(db: Session):
    """
    Ensures that test gate GATE_PHASE5 and test vehicle identities exist.
    """
    # 1. Gate for phase5_test_cam
    gate = db.query(Gate).filter(Gate.camera_id == "phase5_test_cam").first()
    if not gate:
        gate = Gate(
            id="GATE_PHASE5",
            name="Phase 5 Test Entrance Gate",
            location="North Boundary CCTV Stream",
            status=GateStatus.ACTIVE,
            camera_id="phase5_test_cam",
            direction_capability="BIDIRECTIONAL"
        )
        db.add(gate)
        db.commit()
        print("  [INIT] Registered Gate 'GATE_PHASE5' mapped to camera 'phase5_test_cam'")
    else:
        print(f"  [INIT] Gate '{gate.id}' already mapped to camera '{gate.camera_id}'")

def simulate_real_frigate_traffic_stream(worker: FrigateMQTTWorker):
    """
    Publishes representative telemetry events from camera phase5_test_cam to frigate/events.
    Demonstrates Frigate object tracking, LPR recognition, and refinement.
    """
    print("\n--- [STEP 1] Publishing Live Traffic Video Telemetry to MQTT (phase5_test_cam) ---")

    pub_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    pub_client.loop_start()

    # Stream of events: vehicles passing through phase5_test_cam
    events = [
        # Event 1: Student vehicle detected with clean plate
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": ["PB 65 AB 0902", 0.96],
            "top_score": 0.91,
            "plate_detected": True
        },
        # Event 2: Faculty vehicle with minor OCR confusion (letter O instead of digit 0)
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": ["CHO1AB2222", 0.89],
            "top_score": 0.94,
            "plate_detected": True
        },
        # Event 3: Day-scholar student vehicle with OCR confusion (letter I instead of digit 1)
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "motorcycle",
            "sub_label": ["PB65ABI111", 0.93],
            "top_score": 0.88,
            "plate_detected": True
        },
        # Event 4: Ambiguous plate near-duplicate in cluster (PB65AB090X)
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": ["PB65AB090X", 0.87],
            "top_score": 0.89,
            "plate_detected": True
        },
        # Event 5: Unregistered visitor/unknown vehicle
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": ["PB65XY9999", 0.92],
            "top_score": 0.90,
            "plate_detected": True
        },
        # Event 6: Delivery motorcycle (Zomato)
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "motorcycle",
            "sub_label": ["PB65DL6666", 0.95],
            "top_score": 0.87,
            "plate_detected": True
        },
        # Event 7: Vehicle passing camera where LPR failed (no readable plate)
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": None,
            "top_score": 0.85,
            "plate_detected": False
        },
        # Event 8: Inactive / unrenewed student vehicle
        {
            "id": f"phase5-cam-evt-{uuid.uuid4().hex[:6]}",
            "camera": "phase5_test_cam",
            "label": "car",
            "sub_label": ["PB65AB7777", 0.94],
            "top_score": 0.92,
            "plate_detected": True
        }
    ]

    published_ids = []
    for evt in events:
        payload = {
            "type": "new",
            "after": {
                "id": evt["id"],
                "camera": evt["camera"],
                "frame_time": time.time(),
                "snapshot_time": time.time(),
                "label": evt["label"],
                "sub_label": evt["sub_label"],
                "top_score": evt["top_score"],
                "false_positive": False,
                "start_time": time.time(),
                "end_time": None,
                "score": evt["top_score"],
                "box": [100, 100, 300, 300],
                "area": 40000,
                "ratio": 1.0,
                "region": [0, 0, 1280, 720],
                "stationary": False,
                "motionless_count": 0,
                "position_changes": 1,
                "current_zones": [],
                "entered_zones": [],
                "has_clip": False,
                "has_snapshot": False
            }
        }
        pub_client.publish("frigate/events", json.dumps(payload))
        published_ids.append(evt["id"])
        time.sleep(0.1)

    time.sleep(1.0)
    pub_client.loop_stop()
    pub_client.disconnect()
    print(f"  -> Published {len(published_ids)} telemetry events to 'frigate/events'")
    return published_ids

def run_evaluation():
    print("================================================================================")
    print("PHASE 5A: END-TO-END VIDEO EVALUATION HARNESS")
    print("Video Stream -> Frigate LPR -> MQTT -> Phase 4 Worker -> Observation -> Phase 5A")
    print("================================================================================")

    db = SessionLocal()

    # Pre-test invariant counts
    decisions_before = db.query(AccessDecision).count()
    alerts_before = db.query(SecurityAlert).count()
    vehicles_before = db.query(Vehicle).count()
    owners_before = db.query(VehicleOwner).count()

    # 1. Ensure test infrastructure
    ensure_test_infrastructure(db)

    # 2. Start Phase 4 Ingestion Worker
    print("\n--- [STEP 2] Starting Persistent Phase 4 Worker ---")
    worker = FrigateMQTTWorker(client_id="phase5a_eval_worker")
    worker.start()
    time.sleep(1.0)

    # 3. Stream telemetry from phase5_test_cam
    published_ids = simulate_real_frigate_traffic_stream(worker)

    # Allow worker to ingest and persist
    print("\n--- [STEP 3] Ingesting Telemetry into PostgreSQL (observation_events) ---")
    timeout = time.time() + 6.0
    while time.time() < timeout:
        ingested_count = db.query(ObservationEvent).filter(
            ObservationEvent.source_event_id.in_(published_ids)
        ).count()
        if ingested_count >= len(published_ids):
            break
        time.sleep(0.3)

    worker.stop()
    print(f"  -> Successfully ingested {ingested_count} observations into 'observation_events' table.")

    # 4. Fetch the ingested observation records
    observations = db.query(ObservationEvent).filter(
        ObservationEvent.source_event_id.in_(published_ids)
    ).order_by(ObservationEvent.observed_at.asc()).all()

    # Also grab recent observations from GATE_1 and GATE_2 for cross-gate evaluation
    historical_obs = db.query(ObservationEvent).filter(
        ObservationEvent.gate_id.in_(["GATE_1", "GATE_2"])
    ).order_by(ObservationEvent.observed_at.desc()).limit(4).all()

    all_eval_obs = list(observations) + list(historical_obs)

    # 5. Initialize the Frozen Phase 5A Identity Resolver
    print("\n--- [STEP 4] Initializing Frozen Phase 5A Identity Resolver ---")
    print("  * min_similarity: 0.85 (FROZEN)")
    print("  * ambiguity_margin: 0.08 (FROZEN)")
    print("  * OCR confusion weighting: 0.25 penalty (FROZEN)")
    resolver = IdentityResolver()

    # 6. Evaluate Observations through Phase 5A Resolver
    print("\n--- [STEP 5] Evaluating Observations Through Temporary Bridge ---")
    
    results = []
    for obs in all_eval_obs:
        obs_payload = {
            "id": str(obs.id),
            "gate_id": obs.gate_id,
            "camera_id": obs.camera_id,
            "plate": obs.raw_plate,
            "plate_confidence": obs.plate_confidence,
            "vehicle_type": obs.vehicle_type.value if obs.vehicle_type else "UNKNOWN",
            "observed_at": obs.observed_at.isoformat() if obs.observed_at else None
        }

        # Invoke frozen Phase 5A resolver
        res: ResolutionResult = resolver.resolve(obs_payload)

        # Context formatting
        ctx_desc = "None"
        if res.identity_status == ResolutionStatus.KNOWN:
            vehicle_info = res.vehicle or {}
            owner_info = res.owner or {}
            residence_info = res.residence or {}
            visitor_info = res.visitor or {}
            delivery_info = res.delivery or {}

            if owner_info:
                p_type = owner_info.get("person_type", "")
                name = owner_info.get("name", "")
                dept = owner_info.get("department", "")
                r_type = residence_info.get("type", "")
                r_val = residence_info.get("value", "")
                ctx_desc = f"{p_type}: {name} ({r_type}: {r_val})" if r_val else f"{p_type}: {name} ({dept})"
            elif visitor_info:
                v_name = visitor_info.get("visitor_name", "")
                host = visitor_info.get("host_name", "")
                ctx_desc = f"VISITOR: {v_name} (Host: {host})"
            elif delivery_info:
                plat = delivery_info.get("platform", "")
                driver = delivery_info.get("driver_name", "")
                ctx_desc = f"DELIVERY: {plat} ({driver})"
            else:
                ctx_desc = f"VEHICLE: status={vehicle_info.get('status')}"
        elif res.identity_status == ResolutionStatus.AMBIGUOUS:
            cands = [f"{c.plate} ({c.similarity_score:.2f})" for c in (res.candidates or [])]
            ctx_desc = f"Ambiguous candidates: {', '.join(cands)}"
        elif res.identity_status == ResolutionStatus.UNKNOWN:
            ctx_desc = f"Reason: {res.match_method.value if res.match_method else 'UNKNOWN'}"

        results.append({
            "time": obs.observed_at.strftime("%H:%M:%S") if obs.observed_at else "-",
            "gate": obs.gate_id,
            "camera": obs.camera_id or "-",
            "observed_plate": obs.raw_plate or "<NONE>",
            "lpr_conf": f"{obs.plate_confidence:.2f}" if obs.plate_confidence else "-",
            "type": obs.vehicle_type.value if obs.vehicle_type else "-",
            "status": res.identity_status.value,
            "method": res.match_method.value if res.match_method else "-",
            "match_sim": f"{res.match_similarity:.2f}" if res.match_similarity else "-",
            "context": ctx_desc
        })

    # 7. Print Publication-Grade Evaluation Table
    print("\n" + "=" * 130)
    print(f"{'TIME':<10} | {'GATE':<12} | {'OBSERVED PLATE':<15} | {'LPR':<6} | {'STATUS':<10} | {'METHOD':<18} | {'SIM':<6} | {'RESOLVED IDENTITY & CONTEXT'}")
    print("-" * 130)
    for r in results:
        print(f"{r['time']:<10} | {r['gate']:<12} | {r['observed_plate']:<15} | {r['lpr_conf']:<6} | {r['status']:<10} | {r['method']:<18} | {r['match_sim']:<6} | {r['context']}")
    print("=" * 130)

    # 8. Controlled OCR Perturbation Experiment on Ground-Truth
    print("\n--- [STEP 6] Controlled OCR Perturbation Experiment (Ground Truth: PB65AB0902) ---")
    perturbation_tests = [
        ("PB 65 AB 0902", "Exact Normalized match", ResolutionStatus.KNOWN, MatchMethod.EXACT_NORMALIZED),
        ("pb-65-ab-0902", "Format variations (lowercase + hyphens)", ResolutionStatus.KNOWN, MatchMethod.EXACT_NORMALIZED),
        ("CHO1AB2222", "OCR letter O vs digit 0 ('O' in place of '0')", ResolutionStatus.KNOWN, MatchMethod.FUZZY_CONFIDENT),
        ("PB65ABI111", "OCR letter I vs digit 1 ('I' in place of '1')", ResolutionStatus.KNOWN, MatchMethod.FUZZY_CONFIDENT),
        ("PB65AB090X", "Near-duplicate ambiguous candidate in cluster", ResolutionStatus.AMBIGUOUS, MatchMethod.AMBIGUOUS_CANDIDATES),
        ("PB65XY9999", "Unregistered vehicle plate", ResolutionStatus.UNKNOWN, MatchMethod.NO_CANDIDATE),
        ("", "Empty / missing plate observation", ResolutionStatus.UNKNOWN, MatchMethod.NO_PLATE),
    ]

    print(f"{'INPUT STRING':<18} | {'DESCRIPTION':<38} | {'STATUS':<10} | {'METHOD':<20} | {'OUTCOME'}")
    print("-" * 105)
    perturbation_all_passed = True
    for p_str, desc, exp_status, exp_method in perturbation_tests:
        test_payload = {
            "plate": p_str if p_str else None,
            "plate_confidence": 0.92,
            "gate_id": "GATE_PHASE5"
        }
        p_res = resolver.resolve(test_payload)
        status_ok = (p_res.identity_status == exp_status)
        method_ok = (p_res.match_method == exp_method)
        passed = status_ok and method_ok
        if not passed:
            perturbation_all_passed = False
        outcome_str = "PASS" if passed else f"FAIL (got {p_res.identity_status.value}/{p_res.match_method.value})"
        print(f"{p_str or '<EMPTY>':<18} | {desc:<38} | {p_res.identity_status.value:<10} | {p_res.match_method.value:<20} | {outcome_str}")
    print("-" * 105)

    # 9. Verify Invariants
    print("\n--- [STEP 7] Verifying System Invariants ---")
    decisions_after = db.query(AccessDecision).count()
    alerts_after = db.query(SecurityAlert).count()
    vehicles_after = db.query(Vehicle).count()
    owners_after = db.query(VehicleOwner).count()

    assert decisions_before == decisions_after, f"AccessDecision mutated! Before: {decisions_before}, After: {decisions_after}"
    print(f"  [OK] Invariant 1: AccessDecision unchanged (Count: {decisions_after})")

    assert alerts_before == alerts_after, f"SecurityAlert mutated! Before: {alerts_before}, After: {alerts_after}"
    print(f"  [OK] Invariant 2: SecurityAlert unchanged (Count: {alerts_after})")

    assert vehicles_before == vehicles_after, f"Vehicle count mutated! Before: {vehicles_before}, After: {vehicles_after}"
    print(f"  [OK] Invariant 3: Vehicle registry unchanged (Count: {vehicles_after})")

    assert owners_before == owners_after, f"VehicleOwner count mutated! Before: {owners_before}, After: {owners_after}"
    print(f"  [OK] Invariant 4: VehicleOwner registry unchanged (Count: {owners_after})")

    assert perturbation_all_passed, "One or more perturbation experiments failed expectations!"
    print("  [OK] Invariant 5: All OCR perturbation experiments passed with zero false certainty.")

    print("\n================================================================================")
    print("END-TO-END EVALUATION HARNESS COMPLETED SUCCESSFULLY!")
    print("================================================================================")
    db.close()

if __name__ == "__main__":
    run_evaluation()
