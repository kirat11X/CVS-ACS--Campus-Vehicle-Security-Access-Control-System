import os
import sys
import time
import json
import uuid
import random
import threading
from datetime import datetime, timezone, timedelta
import httpx
import uvicorn
from sqlalchemy import text

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import (
    User, Gate, Vehicle, AccessDecision, EntryExitLog, ObservationEvent, ObservationResolution,
    VehicleLinkEvent, ObservationDirection,
)
from backend.app.services.auth_service import hash_password
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from backend.app.config import MOVEMENT_DEBOUNCE_SECONDS, PRESENCE_LONG_STAY_HOURS

BASE_URL = "http://127.0.0.1:8000"
SAFE_LETTERS = "ACEHJKLMNPRTUVWXY"
OBS_COLUMNS = [
    "gate_id", "camera_id", "observed_at", "source", "source_event_id", "raw_plate", "normalized_plate",
    "plate_confidence", "vehicle_type", "vehicle_confidence", "direction", "metadata_payload",
    "created_by_id", "note", "created_at", "updated_at",
]
LOG_COLUMNS = [
    "vehicle_id", "plate", "normalized_plate", "gate_id", "direction", "timestamp", "confidence", "decision",
    "reason_code", "frigate_event_id", "observation_id", "correction_of_id", "direction_method",
    "direction_confidence", "direction_evidence", "plate_source", "created_by_id", "note", "created_at", "updated_at",
]

def start_backend():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def wait_for_backend(timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Backend did not start")

def ensure_test_gates(db):
    for gd in [
        {"id": "GATE_1", "name": "Main North Gate", "camera_id": "gate_cam"},
        {"id": "GATE_2", "name": "South Campus Gate", "camera_id": "gate_2_cam"},
        {"id": "GATE_3", "name": "Hostel East Gate", "camera_id": "gate_3_cam"},
    ]:
        if not db.query(Gate).filter_by(id=gd["id"]).first():
            db.add(Gate(id=gd["id"], name=gd["name"], camera_id=gd["camera_id"], status="ACTIVE"))
    db.commit()

def new_plate():
    letters = "".join(random.choice(SAFE_LETTERS) for _ in range(2))
    digits = "".join(random.choice("1345679") for _ in range(4))
    return f"CH01{letters}{digits}"

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def ts(dt: datetime) -> float:
    return dt.timestamp()

def obs_row(obs_id):
    with SessionLocal() as db:
        o = db.get(ObservationEvent, obs_id)
        return {c: getattr(o, c) for c in OBS_COLUMNS}

def log_rows(ids):
    with SessionLocal() as db:
        return {i: {c: getattr(db.get(EntryExitLog, i), c) for c in LOG_COLUMNS} for i in ids}

def run_tests():
    print("========================================================")
    print("PHASE 6: MOVEMENT LOGGING, DIRECTION PROVENANCE, PRESENCE & LINKING")
    print("========================================================")

    client = httpx.Client(base_url=BASE_URL, timeout=20.0)
    worker = FrigateMQTTWorker()
    created_movement_rows = set()
    tag = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)

    def ingest(event_id, camera, plate=None, score=0.95, frame_time=None, zones=None):
        after = {"id": event_id, "camera": camera, "label": "car", "top_score": 0.9, "score": 0.9,
                 "frame_time": frame_time if frame_time is not None else time.time()}
        if plate is not None:
            after["sub_label"] = [plate, score]
        if zones is not None:
            after["entered_zones"] = zones
        obs = worker.process_payload({"type": "update", "before": {}, "after": after})
        assert obs is not None, f"Worker failed to ingest {event_id}"
        return obs

    def movements_of(obs_id):
        with SessionLocal() as db:
            return db.query(EntryExitLog).filter(EntryExitLog.observation_id == obs_id).all()

    def feed_item(token, obs_id, since_id):
        found, cursor = None, since_id
        while True:
            page = client.get("/feed", params={"since_id": cursor, "limit": 200}, headers=auth(token)).json()
            for entry in page["entries"]:
                if entry["item"]["observation"]["id"] == str(obs_id):
                    found = entry
            cursor = page["cursor"]
            if not page["has_more"]:
                return found

    def cursor_now(token):
        return client.get("/feed", params={"limit": 1}, headers=auth(token)).json()["cursor"]

    def logs(token, **params):
        r = client.get("/logs", params={"limit": 200, **params}, headers=auth(token))
        assert r.status_code == 200, r.text
        return r.json()

    def detail(token, log_id):
        r = client.get(f"/logs/{log_id}", headers=auth(token))
        assert r.status_code == 200, r.text
        d = r.json()
        created_movement_rows.update(uuid.UUID(row["id"]) for row in d["rows"])
        return d

    def movement_id_for(obs):
        rows = movements_of(obs.id)
        assert len(rows) == 1, f"expected 1 root movement for {obs.id}, got {len(rows)}"
        created_movement_rows.add(rows[0].id)
        return rows[0].id

    # --- Setup ---
    db = SessionLocal()
    ensure_test_gates(db)
    passwords, users = {}, {}
    for role in ("ADMIN", "SUPERVISOR", "GUARD"):
        pw = uuid.uuid4().hex
        u = User(username=f"p6_{role.lower()}_{tag}", email=f"p6_{role.lower()}_{tag}@campus.edu",
                 full_name=f"Phase 6 {role.title()}", role=role, hashed_password=hash_password(pw))
        db.add(u)
        users[role], passwords[role] = u, pw
    db.commit()
    for u in users.values():
        db.refresh(u)
    access_decisions_start = db.query(AccessDecision).count()
    decision_logs_start = db.query(EntryExitLog).filter(EntryExitLog.decision.isnot(None)).count()
    db.close()
    tokens = {}
    for role, u in users.items():
        r = client.post("/auth/login", json={"username": u.username, "password": passwords[role]})
        assert r.status_code == 200, r.text
        tokens[role] = r.json()["access_token"]
    admin, supervisor, guard = tokens["ADMIN"], tokens["SUPERVISOR"], tokens["GUARD"]

    cam_in, cam_out = f"p6_in_{tag}", f"p6_out_{tag}"
    cam_out3, cam_bi = f"p6_out3_{tag}", f"p6_bi_{tag}"
    cam_named = f"p6_main_entry_cam_{tag}"
    outside_zone, inside_zone = f"road_{tag}", f"campus_{tag}"

    # --- Scenario 1: Lane configuration (declared, ADMIN only) ---
    print("\n[SCENARIO 1] ADMIN declares camera lane roles; validation and permissions...")
    lanes = [
        (cam_in, {"gate_id": "GATE_2", "lane_role": "ENTRY_LANE"}),
        (cam_out, {"gate_id": "GATE_2", "lane_role": "EXIT_LANE"}),
        (cam_out3, {"gate_id": "GATE_3", "lane_role": "EXIT_LANE"}),
        (cam_bi, {"gate_id": "GATE_3", "lane_role": "BIDIRECTIONAL", "outside_zone": outside_zone, "inside_zone": inside_zone}),
        (cam_named, {"gate_id": "GATE_1", "lane_role": "BIDIRECTIONAL", "notes": "name says entry; no zones declared"}),
    ]
    for camera, body in lanes:
        r = client.put(f"/lanes/{camera}", headers=auth(admin), json=body)
        assert r.status_code == 200, r.text
    assert client.put(f"/lanes/{cam_in}", headers=auth(guard), json=lanes[0][1]).status_code == 403
    assert client.put(f"/lanes/{cam_in}", headers=auth(supervisor), json=lanes[0][1]).status_code == 403
    assert client.put(f"/lanes/x_{tag}", headers=auth(admin), json={"gate_id": "GATE_2", "lane_role": "ENTRY_LANE", "outside_zone": "a", "inside_zone": "b"}).status_code == 400
    assert client.put(f"/lanes/x_{tag}", headers=auth(admin), json={"gate_id": "GATE_2", "lane_role": "BIDIRECTIONAL", "outside_zone": "a"}).status_code == 400
    assert client.put(f"/lanes/x_{tag}", headers=auth(admin), json={"gate_id": "NO_SUCH_GATE", "lane_role": "ENTRY_LANE"}).status_code == 404
    assert client.put("/lanes/gate_2_cam", headers=auth(admin), json={"gate_id": "GATE_3", "lane_role": "ENTRY_LANE"}).status_code == 409
    listed = {l["camera_id"] for l in client.get("/lanes", headers=auth(guard)).json()}
    assert {c for c, _ in lanes} <= listed
    print(f"  -> 5 lanes declared (ENTRY/EXIT at GATE_2, EXIT + BIDIRECTIONAL zones at GATE_3, zone-less BIDIRECTIONAL at GATE_1)")
    print("  -> GUARD/SUPERVISOR 403; zones on non-bidirectional 400; single zone 400; unknown gate 404; camera of other gate 409")
    print("  -> PASS Scenario 1: Lane configuration verified.")

    # --- Scenario 2: Direction by declared camera role ---
    print("\n[SCENARIO 2] Declared ENTRY_LANE / EXIT_LANE give CAMERA_ROLE direction; observation row keeps sensor value...")
    plate_a = new_plate()
    t_a = now - timedelta(hours=3)
    obs_a_in = ingest(f"p6_a_in_{tag}", cam_in, plate_a, 0.95, ts(t_a))
    obs_a_out = ingest(f"p6_a_out_{tag}", cam_out, plate_a, 0.95, ts(t_a + timedelta(minutes=10)))
    assert obs_a_in.gate_id == "GATE_2", "camera -> gate must resolve via the declared lane"
    a_in = detail(guard, movement_id_for(obs_a_in))["movement"]
    a_out = detail(guard, movement_id_for(obs_a_out))["movement"]
    assert a_in["direction"] == "ENTRY" and a_in["direction_method"] == "CAMERA_ROLE"
    assert a_out["direction"] == "EXIT" and a_out["direction_method"] == "CAMERA_ROLE"
    rows = detail(guard, a_in["id"])["rows"]
    assert rows[0]["direction_evidence"]["lane_role"] == "ENTRY_LANE" and rows[0]["direction_evidence"]["camera_id"] == cam_in
    assert obs_row(obs_a_in.id)["direction"] == ObservationDirection.UNKNOWN, "raw observation direction must not be mutated"
    with SessionLocal() as s:
        root = s.get(EntryExitLog, uuid.UUID(a_in["id"]))
        assert root.decision is None and root.reason_code is None
    print(f"  -> {plate_a}: ENTRY (camera role, lane {cam_in}) then EXIT (camera role, lane {cam_out}); observation.direction still UNKNOWN")
    print("  -> PASS Scenario 2: Camera-role direction verified.")

    # --- Scenario 3: Zone order (both ways) and no inference from names ---
    print("\n[SCENARIO 3] BIDIRECTIONAL lane: zone order gives direction both ways; insufficient evidence stays UNKNOWN...")
    plate_z1, plate_z2, plate_z3 = new_plate(), new_plate(), new_plate()
    obs_z_in = ingest(f"p6_z_in_{tag}", cam_bi, plate_z1, 0.95, ts(now - timedelta(hours=2)), [outside_zone, inside_zone])
    obs_z_out = ingest(f"p6_z_out_{tag}", cam_bi, plate_z2, 0.95, ts(now - timedelta(hours=2)), [inside_zone, outside_zone])
    z_in = detail(guard, movement_id_for(obs_z_in))
    z_out = detail(guard, movement_id_for(obs_z_out))
    assert z_in["movement"]["direction"] == "ENTRY" and z_in["movement"]["direction_method"] == "ZONE_ORDER"
    assert z_out["movement"]["direction"] == "EXIT" and z_out["movement"]["direction_method"] == "ZONE_ORDER"
    assert z_in["rows"][0]["direction_evidence"]["entered_zones"] == [outside_zone, inside_zone]
    late_event = f"p6_z_late_{tag}"
    obs_z_late = ingest(late_event, cam_bi, plate_z3, 0.95, ts(now - timedelta(hours=2)), [outside_zone])
    assert movements_of(obs_z_late.id) == [], "a single zone is not enough evidence"
    ingest(late_event, cam_bi, plate_z3, 0.96, None, [outside_zone, inside_zone])
    z_late = detail(guard, movement_id_for(obs_z_late))["movement"]
    assert z_late["direction"] == "ENTRY" and z_late["direction_method"] == "ZONE_ORDER"
    c_named = cursor_now(guard)
    obs_named = ingest(f"p6_named_{tag}", cam_named, new_plate(), 0.95)
    assert movements_of(obs_named.id) == [], f"camera named '{cam_named}' must not imply ENTRY"
    named_item = feed_item(guard, obs_named.id, c_named)["item"]
    assert named_item["direction"]["direction"] == "UNKNOWN" and named_item["direction"]["evidence"]["reason"] == "BIDIRECTIONAL_WITHOUT_ZONES"
    obs_gate_cam = ingest(f"p6_gatecam_{tag}", "gate_cam", new_plate(), 0.95)
    assert movements_of(obs_gate_cam.id) == []
    gate_cam_item = feed_item(guard, obs_gate_cam.id, c_named)["item"]
    assert gate_cam_item["direction"]["evidence"]["reason"] == "NO_LANE_CONFIG" and gate_cam_item["movement_status"] == "DIRECTION_UNKNOWN"
    print(f"  -> [{outside_zone}, {inside_zone}] -> ENTRY; reverse -> EXIT; single zone -> no log until a later update completed the order")
    print(f"  -> '{cam_named}' (zone-less) and unconfigured gate_cam -> UNKNOWN, no movement")
    print("  -> PASS Scenario 3: Zone-order direction verified; names never interpreted.")

    # --- Scenario 4: UNKNOWN creates no log; guard confirmation ---
    print("\n[SCENARIO 4] UNKNOWN creates no movement; guard Confirm creates GUARD_CONFIRMED without touching the observation...")
    before = obs_row(obs_gate_cam.id)
    c4 = cursor_now(guard)
    r = client.post("/logs/confirm", headers=auth(guard), json={"observation_id": str(obs_gate_cam.id), "direction": "ENTRY", "note": "Seen entering at north gate"})
    assert r.status_code == 201, r.text
    confirmed = r.json()
    created_movement_rows.update(uuid.UUID(x["id"]) for x in confirmed["rows"])
    assert confirmed["movement"]["direction_method"] == "GUARD_CONFIRMED" and confirmed["movement"]["direction"] == "ENTRY"
    assert confirmed["movement"]["recorded_by"]["username"] == users["GUARD"].username
    assert confirmed["movement"]["observation_id"] == str(obs_gate_cam.id)
    assert confirmed["rows"][0]["direction_evidence"]["derived_before_confirmation"]["direction"] == "UNKNOWN"
    assert obs_row(obs_gate_cam.id) == before, "Confirmation mutated the observation"
    again = client.post("/logs/confirm", headers=auth(supervisor), json={"observation_id": str(obs_gate_cam.id), "direction": "EXIT"})
    assert again.status_code == 409
    entry = feed_item(guard, obs_gate_cam.id, c4)
    assert entry["kind"] == "MOVEMENT_UPDATED" and entry["item"]["movement_status"] == "LOGGED"
    assert entry["item"]["movement"]["method"] == "GUARD_CONFIRMED"
    assert client.post("/logs/confirm", headers=auth(guard), json={"observation_id": str(uuid.uuid4()), "direction": "ENTRY"}).status_code == 404
    assert client.post("/logs/confirm", headers=auth(guard), json={"observation_id": str(obs_named.id), "direction": "SIDEWAYS"}).status_code == 422
    r = client.post("/logs/confirm", headers=auth(admin), json={"observation_id": str(obs_named.id), "direction": "EXIT"})
    assert r.status_code == 201
    created_movement_rows.update(uuid.UUID(x["id"]) for x in r.json()["rows"])
    print("  -> GUARD_CONFIRMED movement by guard; observation byte-identical; second confirm 409; feed pushed MOVEMENT_UPDATED")
    print("  -> PASS Scenario 4: Guard confirmation verified.")

    # --- Scenario 5: Idempotency and debounce ---
    print(f"\n[SCENARIO 5] One movement per source_event_id; repeats within {MOVEMENT_DEBOUNCE_SECONDS}s collapse...")
    plate_d = new_plate()
    t_d = now - timedelta(hours=1)
    rep_event = f"p6_rep_{tag}"
    obs_rep = None
    for score in (0.90, 0.93, 0.97):
        obs_rep = ingest(rep_event, cam_in, plate_d, score, ts(t_d))
    movement_id_for(obs_rep)
    with SessionLocal() as s:
        assert s.query(EntryExitLog).filter(EntryExitLog.correction_of_id == movements_of(obs_rep.id)[0].id).count() == 0
    c5 = cursor_now(guard)
    obs_dup = ingest(f"p6_dup_{tag}", cam_in, plate_d, 0.95, ts(t_d + timedelta(seconds=MOVEMENT_DEBOUNCE_SECONDS // 3)))
    assert movements_of(obs_dup.id) == [], "repeat within the window must not create a movement"
    assert feed_item(guard, obs_dup.id, c5)["item"]["movement_status"] == "REPEAT_NOT_LOGGED"
    obs_late = ingest(f"p6_after_{tag}", cam_in, plate_d, 0.95, ts(t_d + timedelta(seconds=MOVEMENT_DEBOUNCE_SECONDS * 2)))
    movement_id_for(obs_late)
    obs_other_dir = ingest(f"p6_otherdir_{tag}", cam_out, plate_d, 0.95, ts(t_d + timedelta(seconds=5)))
    movement_id_for(obs_other_dir)
    print("  -> 3 updates of one event: 1 movement; repeat 20 s later: REPEAT_NOT_LOGGED; 120 s later: new movement; opposite direction: logged")
    print("  -> PASS Scenario 5: Idempotency and debounce verified.")

    # --- Scenario 6: No plate read ---
    print("\n[SCENARIO 6] Entry without a plate: movement with plate NULL and NO_PLATE; guard plate is a correction row...")
    obs_np = ingest(f"p6_noplate_{tag}", cam_in, None, None, ts(now - timedelta(minutes=50)))
    np_id = movement_id_for(obs_np)
    np = detail(guard, np_id)["movement"]
    assert np["normalized_plate"] is None and "NO_PLATE" in np["flags"]
    inside = client.get("/presence/inside", headers=auth(guard)).json()
    assert str(np_id) in {m["id"] for m in inside["unattributed_entries"]}
    np_root_before = log_rows([np_id])
    plate_np = new_plate()
    r = client.post(f"/logs/{np_id}/corrections", headers=auth(guard), json={"plate": plate_np.lower(), "note": "Plate read by guard at booth"})
    assert r.status_code == 201, r.text
    np_after = r.json()
    created_movement_rows.update(uuid.UUID(x["id"]) for x in np_after["rows"])
    assert len(np_after["rows"]) == 2 and np_after["rows"][1]["correction_of_id"] == str(np_id)
    assert np_after["rows"][1]["plate_source"] == "GUARD_CORRECTION"
    assert np_after["movement"]["normalized_plate"] == plate_np and "NO_PLATE" not in np_after["movement"]["flags"]
    assert log_rows([np_id]) == np_root_before, "original no-plate row changed"
    print(f"  -> NO_PLATE movement listed under unattributed entries; guard supplied {plate_np} as a correction; original row unchanged")
    print("  -> PASS Scenario 6: No-plate handling verified.")

    # --- Scenario 7: Corrections and the effective view ---
    print("\n[SCENARIO 7] Direction and plate corrections append rows; the effective view uses the latest...")
    plate_e = new_plate()
    obs_e = ingest(f"p6_corr_{tag}", cam_in, plate_e, 0.95, ts(now - timedelta(minutes=40)))
    e_id = movement_id_for(obs_e)
    e_before = log_rows([e_id])
    c7 = cursor_now(guard)
    r = client.post(f"/logs/{e_id}/corrections", headers=auth(supervisor), json={"direction": "EXIT", "note": "Vehicle reversed out of the lane"})
    assert r.status_code == 201, r.text
    corr1 = r.json()
    corr1_id = corr1["rows"][1]["id"]
    assert corr1["movement"]["direction"] == "EXIT" and corr1["movement"]["direction_method"] == "GUARD_CONFIRMED" and corr1["movement"]["corrected"]
    plate_e2 = new_plate()
    r = client.post(f"/logs/{corr1_id}/corrections", headers=auth(guard), json={"plate": plate_e2, "note": "Plate misread; checked by guard"})
    assert r.status_code == 201, r.text
    corr2 = r.json()
    created_movement_rows.update(uuid.UUID(x["id"]) for x in corr2["rows"])
    assert [row["correction_of_id"] for row in corr2["rows"]] == [None, str(e_id), str(e_id)], "corrections must point at the root"
    eff = corr2["movement"]
    assert eff["direction"] == "EXIT" and eff["normalized_plate"] == plate_e2 and eff["correction_count"] == 2
    assert eff["last_corrected_by"]["username"] == users["GUARD"].username
    assert log_rows([e_id]) == e_before
    assert corr2["rows"][1]["direction"] == "EXIT" and corr2["rows"][1]["normalized_plate"] == plate_e
    assert client.post(f"/logs/{e_id}/corrections", headers=auth(guard), json={"direction": "EXIT", "note": "no change"}).status_code == 400
    assert client.post(f"/logs/{e_id}/corrections", headers=auth(guard), json={"note": "nothing"}).status_code == 422
    assert client.post(f"/logs/{e_id}/corrections", headers=auth(guard), json={"direction": "ENTRY", "note": "x"}).status_code == 422
    assert client.post(f"/logs/{uuid.uuid4()}/corrections", headers=auth(guard), json={"direction": "ENTRY", "note": "missing"}).status_code == 404
    assert feed_item(guard, obs_e.id, c7)["kind"] == "MOVEMENT_UPDATED"
    print(f"  -> ENTRY -> EXIT (supervisor), then plate {plate_e} -> {plate_e2} (guard): 3 rows, all corrections reference the root")
    print("  -> PASS Scenario 7: Corrections and effective view verified.")

    # --- Scenario 8: Sensor refinement vs guard correction ---
    print("\n[SCENARIO 8] Camera plate refinement appends a sensor correction; a guard's plate is never overridden...")
    p_first, p_second, p_guard, p_late = new_plate(), new_plate(), new_plate(), new_plate()
    ref_event = f"p6_refine_{tag}"
    obs_ref = ingest(ref_event, cam_in, p_first, 0.60, ts(now - timedelta(minutes=30)))
    ref_id = movement_id_for(obs_ref)
    ingest(ref_event, cam_in, p_second, 0.92)
    ref = detail(guard, ref_id)
    assert len(ref["rows"]) == 2 and ref["rows"][1]["created_by"] is None and ref["rows"][1]["plate_source"] == "OBSERVATION"
    assert ref["movement"]["normalized_plate"] == p_second
    r = client.post(f"/logs/{ref_id}/corrections", headers=auth(guard), json={"plate": p_guard, "note": "Guard read the plate"})
    assert r.status_code == 201
    ingest(ref_event, cam_in, p_late, 0.99)
    ref = detail(guard, ref_id)
    assert len(ref["rows"]) == 3 and ref["movement"]["normalized_plate"] == p_guard
    print(f"  -> {p_first} -> {p_second} by camera (system row); guard set {p_guard}; later camera read {p_late} ignored")
    print("  -> PASS Scenario 8: Refinement precedence verified.")

    # --- Scenario 9: Presence derivation and neutral flags ---
    print("\n[SCENARIO 9] Presence is derived from the latest effective movement; neutral flags...")
    plate_b, plate_c, plate_l = new_plate(), new_plate(), new_plate()
    obs_b = ingest(f"p6_b_{tag}", cam_out, plate_b, 0.95, ts(now - timedelta(hours=2)))
    obs_c1 = ingest(f"p6_c1_{tag}", cam_in, plate_c, 0.95, ts(now - timedelta(hours=2)))
    obs_c2 = ingest(f"p6_c2_{tag}", cam_in, plate_c, 0.95, ts(now - timedelta(hours=1, minutes=30)))
    obs_l = ingest(f"p6_long_{tag}", cam_in, plate_l, 0.95, ts(now - timedelta(hours=PRESENCE_LONG_STAY_HOURS + 6)))
    for o in (obs_b, obs_c1, obs_c2, obs_l):
        movement_id_for(o)

    def presence_for(plate):
        page = client.get("/presence", params={"q": plate}, headers=auth(guard)).json()
        matches = [e for e in page["items"] if e["normalized_plate"] == plate]
        assert len(matches) == 1, (plate, page)
        return matches[0]

    pa, pb, pc, pl = presence_for(plate_a), presence_for(plate_b), presence_for(plate_c), presence_for(plate_l)
    assert pa["status"] == "OUTSIDE" and pa["flags"] == [] and not pa["linked"]
    assert pb["status"] == "OUTSIDE" and pb["flags"] == ["EXIT_WITHOUT_ENTRY"]
    assert pc["status"] == "INSIDE" and pc["flags"] == ["ENTRY_WHILE_INSIDE"]
    assert pl["status"] == "INSIDE" and "LONG_STAY" in pl["flags"]
    reg_plate = new_plate()
    assert client.post("/vehicles", headers=auth(admin), json={"plate": reg_plate, "vehicle_category": "STAFF"}).status_code == 201
    pr = presence_for(reg_plate)
    assert pr["status"] == "UNKNOWN" and pr["linked"] and pr["last_movement"] is None
    inside = client.get("/presence/inside", headers=auth(guard)).json()
    inside_plates = {e["normalized_plate"] for e in inside["items"]}
    assert {plate_c, plate_l} <= inside_plates and not ({plate_a, plate_b} & inside_plates)
    assert all(e["status"] == "INSIDE" for e in inside["items"])
    assert any(not e["linked"] for e in inside["items"] if e["normalized_plate"] in (plate_c, plate_l))
    dump = json.dumps(inside).upper()
    assert "THREAT" not in dump and "VIOLATION" not in dump
    print(f"  -> {plate_a} OUTSIDE; {plate_b} OUTSIDE + EXIT_WITHOUT_ENTRY; {plate_c} INSIDE + ENTRY_WHILE_INSIDE; {plate_l} INSIDE + LONG_STAY")
    print(f"  -> registered {reg_plate} with no movement: UNKNOWN; /presence/inside lists unlinked plates; no threat/violation wording")
    print("  -> PASS Scenario 9: Presence derivation verified.")

    # --- Scenario 10: Movement log filters ---
    print("\n[SCENARIO 10] GET /logs filters: plate, gate, direction, date range, linked/unlinked, pagination...")
    la = logs(guard, plate=plate_a)
    assert la["total"] == 2 and [m["direction"] for m in la["items"]] == ["EXIT", "ENTRY"]
    assert logs(guard, plate=plate_a, direction="ENTRY")["total"] == 1
    assert logs(guard, plate=plate_a, gate_id="GATE_3")["total"] == 0
    window = logs(guard, plate=plate_a, date_from=(t_a - timedelta(minutes=1)).isoformat(), date_to=(t_a + timedelta(minutes=1)).isoformat())
    assert window["total"] == 1 and window["items"][0]["direction"] == "ENTRY"
    assert logs(guard, plate=plate_a, linked="true")["total"] == 0 and logs(guard, plate=plate_a, linked="false")["total"] == 2
    p1 = logs(guard, plate=plate_d, limit=1, skip=0)
    p2 = logs(guard, plate=plate_d, limit=1, skip=1)
    assert p1["total"] == 3 and p1["items"][0]["id"] != p2["items"][0]["id"]
    print(f"  -> plate/direction/gate/date/linked filters and limit/skip paging (total {p1['total']} for {plate_d})")
    print("  -> PASS Scenario 10: Movement log filters verified.")

    # --- Scenario 11: One timeline across all three gates ---
    print("\n[SCENARIO 11] GET /vehicles/{plate}/history merges movements and sightings across gates...")
    plate_h = new_plate()
    t_h = now - timedelta(hours=5)
    obs_h1 = ingest(f"p6_h1_{tag}", cam_in, plate_h, 0.95, ts(t_h))                              # GATE_2 entry
    obs_h2 = ingest(f"p6_h2_{tag}", "gate_cam", plate_h, 0.95, ts(t_h + timedelta(minutes=30)))   # GATE_1 sighting
    obs_h3 = ingest(f"p6_h3_{tag}", cam_out3, plate_h, 0.95, ts(t_h + timedelta(hours=1)))        # GATE_3 exit
    movement_id_for(obs_h1)
    movement_id_for(obs_h3)
    hist = client.get(f"/vehicles/{plate_h.lower()}/history", headers=auth(guard)).json()
    kinds = [(t["type"], t["gate"]["id"]) for t in hist["timeline"]]
    assert kinds == [("MOVEMENT", "GATE_3"), ("SIGHTING", "GATE_1"), ("MOVEMENT", "GATE_2")], kinds
    assert hist["presence"]["status"] == "OUTSIDE" and hist["registered"] is False
    assert hist["timeline"][1]["sighting"]["movement_status"] == "DIRECTION_UNKNOWN"
    print(f"  -> {plate_h}: entered at GATE_2, seen at GATE_1 (direction unknown), left at GATE_3; presence OUTSIDE")
    print("  -> PASS Scenario 11: Unified cross-gate history verified.")

    # --- Scenario 12: Linking an unknown vehicle to an owner ---
    print("\n[SCENARIO 12] Link an unknown plate to an owner; past records resolve on read; nothing rewritten...")
    plate_k = new_plate()
    obs_k1 = ingest(f"p6_k1_{tag}", cam_in, plate_k, 0.95, ts(now - timedelta(hours=4)))
    obs_k2 = ingest(f"p6_k2_{tag}", "gate_cam", plate_k, 0.95, ts(now - timedelta(hours=3)))
    k_id = movement_id_for(obs_k1)
    assert logs(guard, plate=plate_k)["items"][0]["linked"] is False
    k_rows_before = log_rows([k_id])
    obs_k1_before = obs_row(obs_k1.id)
    window_body = {"valid_from": now.isoformat(), "valid_until": (now + timedelta(hours=12)).isoformat()}
    sid = f"SID-{tag.upper()}"
    link_body = {
        "new_owner": {"person_type": "STUDENT", "identifier": sid, "full_name": f"Simran Gill {tag}",
                      "residence_type": "HOSTELLER", "residence": "BH-2, Room 104"},
        "vehicle_category": "VISITOR", **window_body,
        "evidence_note": "Student ID card checked at gate",
    }
    r = client.post(f"/vehicles/{plate_k}/link", headers=auth(guard), json=link_body)
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["link_event"]["method"] == "GUARD_VERIFIED_ID" and link["link_event"]["expires_at"] is not None
    assert link["link_event"]["linked_by"]["username"] == users["GUARD"].username
    assert link["vehicle"]["owner"]["institutional_id"] == sid and link["vehicle"]["context"]["residence"] == "BH-2, Room 104"
    assert link["retroactive"]["movements"] >= 1 and link["retroactive"]["sightings"] >= 1
    k_log = logs(guard, plate=plate_k)["items"][0]
    assert k_log["linked"] and k_log["owner"]["institutional_id"] == sid and k_log["link_basis"] == "EXACT_PLATE"
    hist_k = client.get(f"/vehicles/{plate_k}/history", headers=auth(guard)).json()
    assert hist_k["registered"] and hist_k["owner"]["name"] == f"Simran Gill {tag}" and len(hist_k["link_events"]) == 1
    assert hist_k["presence"]["status"] == "INSIDE" and hist_k["presence"]["linked"]
    sighting = next(t for t in hist_k["timeline"] if t["type"] == "SIGHTING")
    assert sighting["sighting"]["link_status"] == "LINKED" and sighting["sighting"]["observation"]["id"] == str(obs_k2.id)
    assert log_rows([k_id]) == k_rows_before and log_rows([k_id])[k_id]["vehicle_id"] is None, "past movement rows must not be rewritten"
    assert obs_row(obs_k1.id) == obs_k1_before
    owner_id = link["vehicle"]["owner"]["id"]

    assert client.post(f"/vehicles/{plate_k.lower()}/link", headers=auth(guard), json=link_body).status_code == 409
    second_plate = new_plate()
    assert client.post(f"/vehicles/{second_plate}/link", headers=auth(guard), json={**link_body, "vehicle_category": "STUDENT"}).status_code == 403
    no_window = {k: v for k, v in link_body.items() if k not in ("valid_from", "valid_until")}
    assert client.post(f"/vehicles/{second_plate}/link", headers=auth(supervisor), json=no_window).status_code == 400
    assert client.post(f"/vehicles/{second_plate}/link", headers=auth(guard), json={**link_body, "evidence_note": ""}).status_code == 422
    assert client.post(f"/vehicles/{second_plate}/link", headers=auth(guard), json={**link_body, "owner_id": owner_id}).status_code == 422
    assert client.post(f"/vehicles/{second_plate}/link", headers=auth(guard), json=link_body).status_code == 409, "identifier already exists"
    r = client.post(f"/vehicles/{second_plate}/link", headers=auth(admin), json={
        "owner_id": sid, "vehicle_category": "STUDENT", "evidence_note": "Verified against the student registry",
    })
    assert r.status_code == 201, r.text
    assert r.json()["link_event"]["method"] == "ADMIN" and r.json()["link_event"]["expires_at"] is None
    owned = client.get("/vehicles", params={"owner_id": sid}, headers=auth(admin)).json()
    assert {v["vehicle"]["plate"] for v in owned} == {plate_k, second_plate}, "one owner, many vehicles"
    assert not hasattr(Vehicle, "residence") and all(v["context"]["residence"] == "BH-2, Room 104" for v in owned)
    with SessionLocal() as s:
        event_id = s.query(VehicleLinkEvent.id).filter(VehicleLinkEvent.owner_id == uuid.UUID(owner_id)).first()[0]
    for stmt in ("UPDATE vehicle_link_events SET evidence_note = 'edited' WHERE id = :id", "DELETE FROM vehicle_link_events WHERE id = :id"):
        with SessionLocal() as s:
            try:
                s.execute(text(stmt), {"id": event_id})
                s.commit()
                raise AssertionError(f"Database accepted: {stmt}")
            except AssertionError:
                raise
            except Exception as e:
                s.rollback()
                assert "append-only" in str(e), e
    print(f"  -> GUARD linked {plate_k} (VISITOR, expires) to new STUDENT owner {sid} (GUARD_VERIFIED_ID); past movement + sighting now show the owner")
    print("  -> movement and observation rows unchanged; duplicate 409; STUDENT by guard 403; no window 400; no evidence 422")
    print(f"  -> ADMIN linked {second_plate} (STUDENT, permanent) to the same owner: 2 vehicles, residence only on owner")
    print("  -> PASS Scenario 12: Owner linking verified.")

    # --- Scenario 13: Permission matrix ---
    print("\n[SCENARIO 13] Permission matrix...")
    unauth = [
        client.get("/presence"), client.get("/presence/inside"), client.get("/logs"), client.get(f"/logs/{k_id}"),
        client.post("/logs/confirm", json={"observation_id": str(obs_dup.id), "direction": "ENTRY"}),
        client.post(f"/logs/{k_id}/corrections", json={"direction": "EXIT", "note": "x" * 5}),
        client.get("/lanes"), client.put(f"/lanes/{cam_in}", json=lanes[0][1]),
        client.post(f"/vehicles/{new_plate()}/link", json=link_body), client.get(f"/vehicles/{plate_k}/history"),
    ]
    assert all(r.status_code == 401 for r in unauth), [r.status_code for r in unauth]
    for token in (guard, supervisor, admin):
        assert client.get("/presence/inside", headers=auth(token)).status_code == 200
        assert client.get("/logs", params={"limit": 1}, headers=auth(token)).status_code == 200
    r = client.post("/logs/confirm", headers=auth(supervisor), json={"observation_id": str(obs_dup.id), "direction": "ENTRY", "note": "Supervisor review"})
    assert r.status_code == 201
    created_movement_rows.update(uuid.UUID(x["id"]) for x in r.json()["rows"])
    print(f"  -> {len(unauth)} endpoints 401 without a token; lanes PUT ADMIN-only (Scenario 1); link policy (Scenario 12)")
    print("  -> confirm/correct accepted for GUARD, SUPERVISOR and ADMIN")
    print("  -> PASS Scenario 13: Permission matrix verified.")

    # --- Scenario 14: Append-only movement rows and invariants ---
    print("\n[SCENARIO 14] Invariants: append-only movements, zero hard deletes, zero access decisions...")
    sample = next(iter(created_movement_rows))
    for stmt in ("UPDATE entry_exit_logs SET direction = 'EXIT' WHERE id = :id", "DELETE FROM entry_exit_logs WHERE id = :id"):
        with SessionLocal() as s:
            try:
                s.execute(text(stmt), {"id": sample})
                s.commit()
                raise AssertionError(f"Database accepted: {stmt}")
            except AssertionError:
                raise
            except Exception as e:
                s.rollback()
                assert "append-only" in str(e), e
    with SessionLocal() as s:
        row = s.get(EntryExitLog, sample)
        row.note = "edited via ORM"
        try:
            s.commit()
            raise AssertionError("ORM update of a movement row was accepted")
        except ValueError:
            s.rollback()
    with SessionLocal() as s:
        missing = [i for i in created_movement_rows if s.get(EntryExitLog, i) is None]
        assert not missing, f"movement rows disappeared: {missing}"
        new_rows = s.query(EntryExitLog).filter(EntryExitLog.id.in_(created_movement_rows)).all()
        assert all(r.decision is None and r.reason_code is None and r.decision_id is None for r in new_rows)
        assert s.query(AccessDecision).count() == access_decisions_start
        assert s.query(EntryExitLog).filter(EntryExitLog.decision.isnot(None)).count() == decision_logs_start
    print(f"  -> {len(created_movement_rows)} movement rows written by this run all still present; none carries a decision")
    print(f"  -> raw UPDATE/DELETE and ORM update rejected; AccessDecision count unchanged ({access_decisions_start})")
    print("  -> PASS Scenario 14: Invariants preserved.")

    # Retire this run's synthetic lanes (soft: is_active=false)
    for camera, body in lanes:
        client.put(f"/lanes/{camera}", headers=auth(admin), json={**body, "is_active": False})

    print("\n========================================================")
    print("PHASE 6: ALL 14 SCENARIOS PASSED")
    print("========================================================")

if __name__ == "__main__":
    server_thread = threading.Thread(target=start_backend, daemon=True)
    server_thread.start()
    wait_for_backend()

    try:
        run_tests()
    except Exception as e:
        print(f"\nTEST SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)
