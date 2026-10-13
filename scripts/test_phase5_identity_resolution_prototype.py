import os
import sys
import uuid
from typing import Dict, Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models.gate import AccessDecision, SecurityAlert
from backend.app.models.vehicle import Vehicle
from backend.app.models.identity import VehicleOwner
from scripts.prototypes.phase5_identity_resolution.models import (
    ResolutionStatus,
    MatchMethod
)
from scripts.prototypes.phase5_identity_resolution.fuzzy_matcher import (
    FuzzyMatcher,
    compute_similarity
)
from scripts.prototypes.phase5_identity_resolution.resolver import IdentityResolver
from scripts.prototypes.phase5_identity_resolution.fixtures import get_test_fixtures
from scripts.prototypes.phase5_identity_resolution.evaluation import compute_metrics

def run_tests():
    print("========================================================")
    print("PHASE 5A: ISOLATED IDENTITY & CONTEXT RESOLUTION PROTOTYPE")
    print("========================================================")

    # 0. Database Baseline Counts for Invariant Checks
    db = SessionLocal()
    veh_count_start = db.query(Vehicle).count()
    owner_count_start = db.query(VehicleOwner).count()
    decision_count_start = db.query(AccessDecision).count()
    alert_count_start = db.query(SecurityAlert).count()
    db.close()

    resolver = IdentityResolver(
        registry=get_test_fixtures(),
        fuzzy_matcher=FuzzyMatcher(min_similarity=0.85, ambiguity_margin=0.08)
    )

    # --- Test 1: Exact normalized match ---
    print("\n[TEST 1] Exact normalized match...")
    obs1 = {"plate": "PB65AB0902", "plate_confidence": 0.98}
    r1 = resolver.resolve(obs1)
    assert r1.identity_status == ResolutionStatus.KNOWN
    assert r1.match_method == MatchMethod.EXACT_NORMALIZED
    assert r1.vehicle["plate"] == "PB65AB0902"
    assert r1.match_similarity == 1.0
    print(f"  -> Successfully resolved exact match: '{r1.vehicle['plate']}', status={r1.identity_status.value}")
    print("  -> PASS Test 1: Exact normalized match verified.")

    # --- Test 2: Case-insensitive normalization ---
    print("\n[TEST 2] Case-insensitive normalization...")
    obs2 = {"plate": "pb65ab0902", "plate_confidence": 0.95}
    r2 = resolver.resolve(obs2)
    assert r2.identity_status == ResolutionStatus.KNOWN
    assert r2.match_method == MatchMethod.EXACT_NORMALIZED
    assert r2.vehicle["plate"] == "PB65AB0902"
    print(f"  -> Input 'pb65ab0902' resolved to '{r2.vehicle['plate']}'")
    print("  -> PASS Test 2: Case-insensitive normalization verified.")

    # --- Test 3: Space/hyphen normalization ---
    print("\n[TEST 3] Space/hyphen normalization...")
    obs3 = {"plate": "PB-65-AB-0902", "plate_confidence": 0.92}
    r3 = resolver.resolve(obs3)
    assert r3.identity_status == ResolutionStatus.KNOWN
    assert r3.match_method == MatchMethod.EXACT_NORMALIZED
    assert r3.vehicle["plate"] == "PB65AB0902"
    print(f"  -> Input 'PB-65-AB-0902' resolved to '{r3.vehicle['plate']}'")
    print("  -> PASS Test 3: Space/hyphen normalization verified.")

    # --- Test 4: Missing plate ---
    print("\n[TEST 4] Missing plate (plate=None)...")
    obs4 = {"plate": None, "plate_confidence": 0.0}
    r4 = resolver.resolve(obs4)
    assert r4.identity_status == ResolutionStatus.UNKNOWN
    assert r4.match_method == MatchMethod.NO_PLATE
    assert r4.vehicle is None
    assert r4.owner is None
    print(f"  -> No plate correctly produced status={r4.identity_status.value}, method={r4.match_method.value}")
    print("  -> PASS Test 4: Missing plate handled cleanly.")

    # --- Test 5: Unknown plate ---
    print("\n[TEST 5] Unknown plate (DL99ZZ9999)...")
    obs5 = {"plate": "DL99ZZ9999", "plate_confidence": 0.90}
    r5 = resolver.resolve(obs5)
    assert r5.identity_status == ResolutionStatus.UNKNOWN
    assert r5.match_method == MatchMethod.NO_CANDIDATE
    assert r5.vehicle is None
    assert r5.owner is None
    print(f"  -> Unknown plate produced status={r5.identity_status.value}, method={r5.match_method.value}")
    print("  -> PASS Test 5: Unknown plate handled cleanly.")

    # --- Test 6: High-confidence fuzzy candidate ---
    print("\n[TEST 6] High-confidence fuzzy candidate (isolated typo)...")
    # PB65DL6666 with minor optical distortion: PB65DL666B (6 vs B)
    obs6 = {"plate": "PB65DL666B", "plate_confidence": 0.88}
    r6 = resolver.resolve(obs6)
    assert r6.identity_status == ResolutionStatus.KNOWN
    assert r6.match_method == MatchMethod.FUZZY_CONFIDENT
    assert r6.vehicle["plate"] == "PB65DL6666"
    assert r6.match_similarity >= 0.85
    print(f"  -> Fuzzy match 'PB65DL666B' -> '{r6.vehicle['plate']}' (similarity: {r6.match_similarity})")
    print("  -> PASS Test 6: High-confidence fuzzy candidate resolved.")

    # --- Test 7: Ambiguous fuzzy candidates ---
    print("\n[TEST 7] Ambiguous fuzzy candidates (near-duplicates)...")
    # PB65ABO902 observed when BOTH PB65AB0902 and PB65AB0903 exist in registry
    obs7 = {"plate": "PB65AB090X", "plate_confidence": 0.89}
    r7 = resolver.resolve(obs7)
    # Both PB65AB0902 and PB65AB0903 share 9/10 characters with PB65AB090X
    assert r7.identity_status == ResolutionStatus.AMBIGUOUS
    assert r7.match_method == MatchMethod.AMBIGUOUS_CANDIDATES
    assert len(r7.candidates) >= 2
    assert r7.vehicle is None, "AMBIGUOUS status must NOT arbitrarily bind a vehicle!"
    assert r7.owner is None, "AMBIGUOUS status must NOT arbitrarily bind an owner!"
    print(f"  -> Ambiguous match safely identified between {len(r7.candidates)} candidates:")
    for c in r7.candidates:
        print(f"     * {c.plate} (sim: {c.similarity_score})")
    print("  -> PASS Test 7: Ambiguity detection verified.")

    # --- Test 8: OCR confusion O vs 0 ---
    print("\n[TEST 8] OCR confusion O vs 0...")
    # CH01AB2222 observed as CH01AB222Z -> Let's test PB65AB1111 vs PB65AB111I (I/1) or CH01AB2222 vs CHO1AB2222 (O/0)
    obs8 = {"plate": "CHO1AB2222", "plate_confidence": 0.91}
    r8 = resolver.resolve(obs8)
    assert r8.identity_status == ResolutionStatus.KNOWN
    assert r8.vehicle["plate"] == "CH01AB2222"
    assert r8.match_similarity > 0.90
    print(f"  -> 'CHO1AB2222' (with letter O) successfully matched 'CH01AB2222' (sim: {r8.match_similarity})")
    print("  -> PASS Test 8: OCR confusion O vs 0 verified.")

    # --- Test 9: OCR confusion I vs 1 ---
    print("\n[TEST 9] OCR confusion I vs 1...")
    obs9 = {"plate": "PB65ABI111", "plate_confidence": 0.87}
    r9 = resolver.resolve(obs9)
    assert r9.identity_status == ResolutionStatus.KNOWN
    assert r9.vehicle["plate"] == "PB65AB1111"
    assert r9.match_similarity > 0.90
    print(f"  -> 'PB65ABI111' (with letter I) successfully matched 'PB65AB1111' (sim: {r9.match_similarity})")
    print("  -> PASS Test 9: OCR confusion I vs 1 verified.")

    # --- Test 10: Multiple vehicles with similar plates ---
    print("\n[TEST 10] Multiple vehicles with similar plates...")
    # Exact queries for the similar cluster must each return their own exact owner
    r10_a = resolver.resolve({"plate": "PB65AB0902"})
    r10_b = resolver.resolve({"plate": "PB65AB0903"})
    r10_c = resolver.resolve({"plate": "PB65AC0902"})
    assert r10_a.vehicle["plate"] == "PB65AB0902" and r10_a.owner["name"] == "Kirat Singh"
    assert r10_b.vehicle["plate"] == "PB65AB0903" and r10_b.owner["name"] == "Amit Kumar"
    assert r10_c.vehicle["plate"] == "PB65AC0902" and r10_c.owner["name"] == "Dr. Meenakshi Saini"
    print("  -> Cluster plates resolved to distinct owners: Kirat Singh, Amit Kumar, Dr. Meenakshi Saini")
    print("  -> PASS Test 10: Multiple similar plates handled deterministically.")

    # --- Test 11: Inactive vehicle ---
    print("\n[TEST 11] Inactive vehicle context preservation...")
    r11 = resolver.resolve({"plate": "PB65AB7777", "plate_confidence": 0.96})
    assert r11.identity_status == ResolutionStatus.KNOWN
    assert r11.vehicle["status"] == "INACTIVE"
    assert r11.vehicle["is_active"] is False
    assert r11.owner["name"] == "Alumnus Jaspreet Singh"
    print(f"  -> Preserved identity for inactive vehicle: Owner='{r11.owner['name']}', status={r11.vehicle['status']}, is_active={r11.vehicle['is_active']}")
    print("  -> PASS Test 11: Inactive vehicle context preserved.")

    # --- Test 12: Expired vehicle ---
    print("\n[TEST 12] Expired vehicle context preservation...")
    r12 = resolver.resolve({"plate": "HR26EX8888", "plate_confidence": 0.93})
    assert r12.identity_status == ResolutionStatus.KNOWN
    assert r12.vehicle["status"] == "EXPIRED"
    assert r12.vehicle["is_active"] is False
    print(f"  -> Preserved identity for expired vehicle: status={r12.vehicle['status']}, is_active={r12.vehicle['is_active']}")
    print("  -> PASS Test 12: Expired vehicle context preserved.")

    # --- Test 13: Suspended vehicle ---
    print("\n[TEST 13] Suspended vehicle context preservation...")
    r13 = resolver.resolve({"plate": "PB65SU9999", "plate_confidence": 0.94})
    assert r13.identity_status == ResolutionStatus.KNOWN
    assert r13.vehicle["status"] == "SUSPENDED"
    assert r13.vehicle["is_active"] is False
    assert r13.owner["name"] == "Harpreet Singh"
    print(f"  -> Preserved identity for suspended vehicle: Owner='{r13.owner['name']}', status={r13.vehicle['status']}, is_active={r13.vehicle['is_active']}")
    print("  -> PASS Test 13: Suspended vehicle context preserved.")

    # --- Test 14: Student identity resolution ---
    print("\n[TEST 14] Student identity resolution...")
    r14 = resolver.resolve({"plate": "PB65AB0902"})
    assert r14.owner["person_type"] == "STUDENT"
    assert r14.owner["department"] == "Computer Science & Engineering"
    print(f"  -> Student owner: {r14.owner['name']}, dept: {r14.owner['department']}")
    print("  -> PASS Test 14: Student identity resolved.")

    # --- Test 15: Faculty identity resolution ---
    print("\n[TEST 15] Faculty identity resolution...")
    r15 = resolver.resolve({"plate": "CH01AB2222"})
    assert r15.owner["person_type"] == "FACULTY"
    assert r15.owner["department"] == "Computer Science & Engineering"
    print(f"  -> Faculty owner: {r15.owner['name']}, dept: {r15.owner['department']}")
    print("  -> PASS Test 15: Faculty identity resolved.")

    # --- Test 16: Staff identity resolution ---
    print("\n[TEST 16] Staff identity resolution...")
    r16 = resolver.resolve({"plate": "CH01AB3333"})
    assert r16.owner["person_type"] == "STAFF"
    assert r16.owner["department"] == "Academic Administration"
    print(f"  -> Staff owner: {r16.owner['name']}, dept: {r16.owner['department']}")
    print("  -> PASS Test 16: Staff identity resolved.")

    # --- Test 17: Hosteller context ---
    print("\n[TEST 17] Hosteller residence context...")
    r17 = resolver.resolve({"plate": "PB65AB0902"})
    assert r17.residence["type"] == "HOSTELLER"
    assert r17.residence["value"] == "BH-4, Room 312"
    print(f"  -> Hosteller residence context: type={r17.residence['type']}, room={r17.residence['value']}")
    print("  -> PASS Test 17: Hosteller residence context verified.")

    # --- Test 18: Day-scholar context ---
    print("\n[TEST 18] Day-scholar residence context...")
    r18 = resolver.resolve({"plate": "PB65AB1111"})
    assert r18.residence["type"] == "DAY_SCHOLAR"
    assert r18.residence["value"] == "Sector 15, Chandigarh"
    print(f"  -> Day-scholar residence context: type={r18.residence['type']}, address={r18.residence['value']}")
    print("  -> PASS Test 18: Day-scholar residence context verified.")

    # --- Test 19: Visitor context ---
    print("\n[TEST 19] Visitor context resolution...")
    r19 = resolver.resolve({"plate": "DL03XY5555"})
    assert r19.identity_status == ResolutionStatus.KNOWN
    assert r19.visitor is not None
    assert r19.visitor["visitor_name"] == "Guest Speaker Dr. Gupta"
    assert r19.visitor["host_name"] == "Dr. Rajesh Sharma"
    assert r19.residence["type"] == "OFF_CAMPUS"
    print(f"  -> Visitor: {r19.visitor['visitor_name']}, host: {r19.visitor['host_name']}")
    print("  -> PASS Test 19: Visitor context verified.")

    # --- Test 20: Delivery vehicle context ---
    print("\n[TEST 20] Delivery vehicle context...")
    r20 = resolver.resolve({"plate": "PB65DL6666"})
    assert r20.identity_status == ResolutionStatus.KNOWN
    assert r20.delivery is not None
    assert r20.delivery["platform"] == "ZOMATO"
    assert r20.delivery["driver_name"] == "Ramesh Courier"
    print(f"  -> Delivery fleet: platform={r20.delivery['platform']}, driver={r20.delivery['driver_name']}")
    print("  -> PASS Test 20: Delivery vehicle context verified.")

    # --- Test 21: Perception confidence preserved ---
    print("\n[TEST 21] Perception confidence preservation...")
    obs21 = {"plate": "PB65AB0902", "plate_confidence": 0.9421}
    r21 = resolver.resolve(obs21)
    assert r21.perception_confidence == 0.9421
    print(f"  -> Preserved perception confidence: {r21.perception_confidence}")
    print("  -> PASS Test 21: Perception confidence preserved.")

    # --- Test 22: Match similarity preserved ---
    print("\n[TEST 22] Match similarity preserved distinct from perception confidence...")
    obs22 = {"plate": "PB65DL666B", "plate_confidence": 0.77}
    r22 = resolver.resolve(obs22)
    assert r22.perception_confidence == 0.77
    assert r22.match_similarity > 0.85
    assert r22.perception_confidence != r22.match_similarity
    print(f"  -> Perception confidence ({r22.perception_confidence}) and Match similarity ({r22.match_similarity}) kept separate")
    print("  -> PASS Test 22: Match similarity preserved distinct from perception confidence.")

    # --- Test 23: Unknown does not create Vehicle ---
    print("\n[TEST 23] Unknown plate does NOT create Vehicle...")
    db = SessionLocal()
    veh_count_before = db.query(Vehicle).count()
    db.close()
    resolver.resolve({"plate": "DL99UNKNOWN1", "plate_confidence": 0.95})
    db = SessionLocal()
    veh_count_after = db.query(Vehicle).count()
    db.close()
    assert veh_count_before == veh_count_after
    print("  -> PASS Test 23: Unknown plate did not create Vehicle record.")

    # --- Test 24: Unknown does not create Owner ---
    print("\n[TEST 24] Unknown plate does NOT create VehicleOwner...")
    db = SessionLocal()
    owner_count_before = db.query(VehicleOwner).count()
    db.close()
    resolver.resolve({"plate": "DL99UNKNOWN2", "plate_confidence": 0.95})
    db = SessionLocal()
    owner_count_after = db.query(VehicleOwner).count()
    db.close()
    assert owner_count_before == owner_count_after
    print("  -> PASS Test 24: Unknown plate did not create VehicleOwner record.")

    # --- Test 25: Resolution does not create AccessDecision ---
    print("\n[TEST 25] Resolution does NOT create AccessDecision...")
    db = SessionLocal()
    decision_count_before = db.query(AccessDecision).count()
    db.close()
    resolver.resolve({"plate": "PB65AB0902", "plate_confidence": 0.99})
    db = SessionLocal()
    decision_count_after = db.query(AccessDecision).count()
    db.close()
    assert decision_count_before == decision_count_after
    print(f"  -> AccessDecision count remained unchanged: {decision_count_before} == {decision_count_after}")
    print("  -> PASS Test 25: Invariant Resolution != AccessDecision verified.")

    # --- Test 26: Resolution does not create SecurityAlert ---
    print("\n[TEST 26] Resolution does NOT create SecurityAlert...")
    db = SessionLocal()
    alert_count_before = db.query(SecurityAlert).count()
    db.close()
    resolver.resolve({"plate": "PB65SU9999", "plate_confidence": 0.99})
    db = SessionLocal()
    alert_count_after = db.query(SecurityAlert).count()
    db.close()
    assert alert_count_before == alert_count_after
    print(f"  -> SecurityAlert count remained unchanged: {alert_count_before} == {alert_count_after}")
    print("  -> PASS Test 26: Invariant Resolution != SecurityAlert verified.")

    # --- Test 27: AMBIGUOUS never silently becomes KNOWN ---
    print("\n[TEST 27] AMBIGUOUS never silently becomes KNOWN...")
    ambig_obs = {"plate": "PB65AB090X", "plate_confidence": 0.99}
    r27 = resolver.resolve(ambig_obs)
    assert r27.identity_status == ResolutionStatus.AMBIGUOUS
    assert r27.identity_status != ResolutionStatus.KNOWN
    assert r27.vehicle is None
    assert r27.owner is None
    print(f"  -> Confirmed: AMBIGUOUS candidate strictly yields status={r27.identity_status.value} with vehicle=None")
    print("  -> PASS Test 27: Strict ambiguity safety verified.")

    # Final DB Integrity Verification
    db = SessionLocal()
    assert db.query(Vehicle).count() == veh_count_start
    assert db.query(VehicleOwner).count() == owner_count_start
    assert db.query(AccessDecision).count() == decision_count_start
    assert db.query(SecurityAlert).count() == alert_count_start
    db.close()

    # Evaluation Metrics Demonstration
    print("\n========================================================")
    print("EVALUATION METRICS SAMPLE ON SYNTHETIC BENCHMARK")
    print("========================================================")
    benchmark_dataset = [
        {"ground_truth_plate": "PB65AB0902", "result": r1},
        {"ground_truth_plate": "PB65AB0902", "result": r2},
        {"ground_truth_plate": "PB65AB0902", "result": r3},
        {"ground_truth_plate": None, "result": r4},
        {"ground_truth_plate": None, "result": r5},
        {"ground_truth_plate": "PB65DL6666", "result": r6},
        {"ground_truth_plate": "PB65AB0902", "result": r7},  # Ambiguous observation
        {"ground_truth_plate": "CH01AB2222", "result": r8},
        {"ground_truth_plate": "PB65AB1111", "result": r9},
        {"ground_truth_plate": "PB65AB7777", "result": r11},
        {"ground_truth_plate": "HR26EX8888", "result": r12},
        {"ground_truth_plate": "PB65SU9999", "result": r13},
    ]
    metrics = compute_metrics(benchmark_dataset)
    for k, v in metrics.items():
        print(f"  * {k}: {v}")
    assert metrics["false_identities"] == 0, "False identity count must be exactly 0!"
    print(f"  -> False Identity Rate: {metrics['false_identity_rate']} (0.0% false identity matches)")
    print("========================================================\n")
    print("ALL 27 TESTS PASSED FOR PHASE 5A PROTOTYPE!")
    print("========================================================")

if __name__ == "__main__":
    try:
        run_tests()
        sys.exit(0)
    except Exception as e:
        print(f"\nPHASE 5A TEST SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
