import os
import sys
import time
import json
import uuid
import queue
import random
import threading
from datetime import datetime, timezone, timedelta
import httpx
import uvicorn
from sqlalchemy import text, func

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import (
    User, VehicleOwner, Visitor, Vehicle, Gate, AccessDecision, EntryExitLog, SecurityAlert,
    ObservationEvent, ObservationResolution, ObservationFeedEvent,
    ObservationSource, ResolutionOutcome, VehicleStatus,
)
from backend.app.services.auth_service import hash_password
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker
from backend.app.config import GUARD_REGISTRATION_MAX_VALIDITY_HOURS

BASE_URL = "http://127.0.0.1:8000"
SAFE_LETTERS = "ACEHJKLMNPRTUVWXY"  # no OCR-confusable letters

OBS_COLUMNS = [
    "gate_id", "camera_id", "observed_at", "source", "source_event_id", "raw_plate", "normalized_plate",
    "plate_confidence", "vehicle_type", "vehicle_confidence", "direction", "metadata_payload",
    "created_by_id", "note", "created_at", "updated_at",
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

def new_plate_pair():
    """Returns (registered plate, OCR-confused read of it with 0->O and 8->B)."""
    letters = "".join(random.choice(SAFE_LETTERS) for _ in range(2))
    tail = "".join(random.choice("134679") for _ in range(3))
    return f"PB10{letters}8{tail}", f"PB1O{letters}B{tail}"

def frigate_payload(event_id, plate=None, plate_score=None, label="car", camera="gate_cam"):
    after = {"id": event_id, "camera": camera, "label": label, "frame_time": time.time(), "top_score": 0.9, "score": 0.9}
    if plate is not None:
        after["sub_label"] = [plate, plate_score]
    return {"type": "new", "before": {}, "after": after}

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def obs_row(obs_id):
    with SessionLocal() as db:
        o = db.get(ObservationEvent, obs_id)
        return {c: getattr(o, c) for c in OBS_COLUMNS}

def counts():
    with SessionLocal() as db:
        return {
            "vehicles": db.query(Vehicle).count(),
            "owners": db.query(VehicleOwner).count(),
            "visitors": db.query(Visitor).count(),
            "access_decisions": db.query(AccessDecision).count(),
            # Phase 6 movement rows are expected; rows carrying an access decision are not
            "entry_exit_logs": db.query(EntryExitLog).filter(EntryExitLog.decision.isnot(None)).count(),
            "security_alerts": db.query(SecurityAlert).count(),
        }

def all_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from all_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from all_keys(v)

class SSEReader(threading.Thread):
    """Reads /feed/stream in the background and queues parsed events."""

    def __init__(self, token, since_id=None, last_event_id=None):
        super().__init__(daemon=True)
        self.headers = {**auth(token), "Accept": "text/event-stream"}
        if last_event_id is not None:
            self.headers["Last-Event-ID"] = str(last_event_id)
        self.params = {"since_id": since_id} if since_id is not None else {}
        self.events = queue.Queue()
        self.status_code = None
        self.response = None
        self.error = None

    def run(self):
        try:
            with httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(5.0, read=60.0)) as client:
                with client.stream("GET", "/feed/stream", headers=self.headers, params=self.params) as resp:
                    self.response = resp
                    self.status_code = resp.status_code
                    event = {}
                    for line in resp.iter_lines():
                        if line == "":
                            if event:
                                if "data" in event:
                                    event["json"] = json.loads(event["data"])
                                self.events.put(event)
                                event = {}
                            continue
                        if line.startswith(":"):
                            continue
                        field, _, value = line.partition(":")
                        value = value[1:] if value.startswith(" ") else value
                        if field == "data":
                            event["data"] = event["data"] + "\n" + value if "data" in event else value
                        else:
                            event[field] = value
        except Exception as e:  # closed by the test or server shutdown
            self.error = e

    def wait_for(self, predicate, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self.events.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if predicate(ev):
                return ev
        raise AssertionError("Timed out waiting for SSE event")

    def close(self):
        try:
            if self.response is not None:
                self.response.close()
        except Exception:
            pass

def sse_item_for(obs_id, kind=None):
    def predicate(ev):
        if ev.get("event") != "feed":
            return False
        entry = ev["json"]
        if entry["item"]["observation"]["id"] != str(obs_id):
            return False
        return kind is None or entry["kind"] == kind
    return predicate

def run_tests():
    print("========================================================")
    print("PHASE 5C: LIVE PLATE FEED, REGISTRY LINKAGE & MANUAL ENTRY")
    print("========================================================")

    client = httpx.Client(base_url=BASE_URL, timeout=15.0)
    worker = FrigateMQTTWorker()
    test_obs_ids = []

    def feed_item(token, obs_id, since_id):
        """Latest feed entry for obs_id among changes after since_id."""
        found, cursor = None, since_id
        while True:
            r = client.get("/feed", params={"since_id": cursor, "limit": 200}, headers=auth(token))
            assert r.status_code == 200, r.text
            page = r.json()
            for entry in page["entries"]:
                if entry["item"]["observation"]["id"] == str(obs_id):
                    found = entry
            cursor = page["cursor"]
            if not page["has_more"]:
                return found

    def cursor_now(token):
        r = client.get("/feed", params={"limit": 1}, headers=auth(token))
        assert r.status_code == 200, r.text
        return r.json()["cursor"]

    def ingest(event_id, plate=None, score=None):
        obs = worker.process_payload(frigate_payload(event_id, plate, score))
        assert obs is not None, f"Worker failed to ingest {event_id}"
        test_obs_ids.append(obs.id)
        return obs

    # --- Setup ---
    db = SessionLocal()
    ensure_test_gates(db)
    run_tag = uuid.uuid4().hex[:6]
    passwords = {}
    users = {}
    for role in ("ADMIN", "SUPERVISOR", "GUARD"):
        pw = uuid.uuid4().hex
        u = User(
            username=f"p5c_{role.lower()}_{run_tag}", email=f"p5c_{role.lower()}_{run_tag}@campus.edu",
            full_name=f"Phase 5C {role.title()}", role=role, hashed_password=hash_password(pw),
        )
        db.add(u)
        users[role], passwords[role] = u, pw
    inactive_pw = uuid.uuid4().hex
    inactive = User(
        username=f"p5c_inactive_{run_tag}", email=f"p5c_inactive_{run_tag}@campus.edu",
        full_name="Phase 5C Former Guard", role="GUARD", hashed_password=hash_password(inactive_pw), is_active=False,
    )
    db.add(inactive)
    db.commit()
    for u in [*users.values(), inactive]:
        db.refresh(u)
    db.close()
    baseline = counts()

    # --- Scenario 1: Authentication ---
    print("\n[SCENARIO 1] Authentication: login, /auth/me, bad credentials, inactive users, forged tokens...")
    tokens = {}
    for role, u in users.items():
        r = client.post("/auth/login", json={"username": u.username, "password": passwords[role]})
        assert r.status_code == 200, f"{role} login failed: {r.text}"
        assert r.json()["user"]["role"] == role
        tokens[role] = r.json()["access_token"]
    admin, supervisor, guard = tokens["ADMIN"], tokens["SUPERVISOR"], tokens["GUARD"]
    me = client.get("/auth/me", headers=auth(guard))
    assert me.status_code == 200 and me.json()["username"] == users["GUARD"].username
    assert client.post("/auth/login", json={"username": users["GUARD"].username, "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": inactive.username, "password": inactive_pw}).status_code == 401
    assert client.get("/auth/me", headers=auth(guard[:-2] + "xx")).status_code == 401
    assert client.get("/auth/me", headers=auth("not-a-token")).status_code == 401
    print("  -> Three roles logged in; wrong password, inactive account and forged tokens rejected with 401")
    print("  -> PASS Scenario 1: Authentication verified.")

    # --- Scenario 2: Unauthenticated access is rejected ---
    print("\n[SCENARIO 2] Endpoints reject requests without a token...")
    unauth = [
        client.get("/feed"),
        client.get("/feed/stream"),
        client.post("/observations/manual", json={"gate_id": "GATE_1", "plate": "PB10AA1111", "direction": "ENTRY"}),
        client.post("/resolutions", json={"observation_id": str(uuid.uuid4()), "chosen_vehicle_id": "none"}),
        client.post("/vehicles", json={"plate": "PB10AA1111", "vehicle_category": "VISITOR"}),
        client.get("/owners", params={"q": "test"}),
        client.post("/owners", json={"identifier": "X", "full_name": "X", "person_type": "STUDENT"}),
    ]
    assert all(r.status_code == 401 for r in unauth), [r.status_code for r in unauth]
    print(f"  -> {len(unauth)} endpoints returned 401 without credentials")
    print("  -> PASS Scenario 2: Authentication enforced.")

    # --- Scenario 3: Registry fixtures (ADMIN) ---
    print("\n[SCENARIO 3] Build registry fixtures via ADMIN (owner + ACTIVE/SUSPENDED/BLACKLISTED/expired vehicles)...")
    owner_identifier = f"STUDENT-2026-P5C{run_tag.upper()}"
    r = client.post("/owners", headers=auth(admin), json={
        "identifier": owner_identifier, "full_name": f"Harleen Kaur {run_tag}", "email": f"harleen_{run_tag}@campus.edu",
        "phone": "+919800011122", "person_type": "STUDENT", "residence_type": "HOSTELLER",
        "residence": "BH-4, Room 312", "department": "Computer Science & Engineering",
    })
    assert r.status_code == 201, r.text
    owner = r.json()
    active_plate, active_variant = new_plate_pair()
    suspended_plate, _ = new_plate_pair()
    blacklisted_plate, _ = new_plate_pair()
    expired_plate, _ = new_plate_pair()
    now = datetime.now(timezone.utc)

    def admin_register(plate, category="STUDENT", **extra):
        resp = client.post("/vehicles", headers=auth(admin), json={"plate": plate, "vehicle_category": category, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()["vehicle"]

    active_vehicle = admin_register(active_plate, owner_id=owner_identifier, make_model="Hyundai i20", color="White")
    suspended_vehicle = admin_register(suspended_plate, owner_id=owner_identifier)
    blacklisted_vehicle = admin_register(blacklisted_plate, category="UNKNOWN")
    expired_vehicle = admin_register(
        expired_plate, category="VISITOR",
        valid_from=(now - timedelta(days=10)).isoformat(), valid_until=(now - timedelta(days=1)).isoformat(),
    )
    for plate, st in ((suspended_plate, "SUSPENDED"), (blacklisted_plate, "BLACKLISTED")):
        resp = client.put(f"/vehicles/{plate}", headers=auth(admin), json={"status": st})
        assert resp.status_code == 200 and resp.json()["vehicle"]["status"] == st, resp.text
    print(f"  -> Owner {owner_identifier} (HOSTELLER, BH-4); vehicles {active_plate}, {suspended_plate} (SUSPENDED), "
          f"{blacklisted_plate} (BLACKLISTED), {expired_plate} (window ended)")
    print("  -> PASS Scenario 3: Registry fixtures created.")

    registry_counts = counts()
    c0 = cursor_now(guard)

    # --- Scenario 4: LINKED ---
    print("\n[SCENARIO 4] Confident exact read of an ACTIVE registered plate -> LINKED...")
    obs_linked = ingest(f"p5c_linked_{run_tag}", active_plate, 0.95)
    entry = feed_item(guard, obs_linked.id, c0)
    item = entry["item"]
    assert entry["kind"] == "OBSERVATION_CREATED"
    assert item["link_status"] == "LINKED" and item["link_basis"] == "EXACT_PLATE"
    assert item["vehicle"]["id"] == active_vehicle["id"] and item["vehicle"]["registry_status"] == "ACTIVE"
    assert item["owner"]["institutional_id"] == owner_identifier
    assert item["residence"]["residence"] == "BH-4, Room 312" and item["residence"]["residence_type"] == "HOSTELLER"
    assert item["suggestions"] == [] and item["observation"]["direction"] == "UNKNOWN"
    print(f"  -> {active_plate}: LINKED to {item['owner']['name']} ({item['residence']['residence']}), direction UNKNOWN")
    print("  -> PASS Scenario 4: LINKED verified.")

    # --- Scenario 5: LINKED_INACTIVE ---
    print("\n[SCENARIO 5] Registered but inactive (SUSPENDED / BLACKLISTED / window ended) -> LINKED_INACTIVE...")
    for plate, expected_status, expected_flag in (
        (suspended_plate, "SUSPENDED", None),
        (blacklisted_plate, "BLACKLISTED", None),
        (expired_plate, "ACTIVE", "VALIDITY_ENDED"),
    ):
        obs = ingest(f"p5c_inactive_{expected_status.lower()}_{run_tag}", plate, 0.93)
        item = feed_item(guard, obs.id, c0)["item"]
        assert item["link_status"] == "LINKED_INACTIVE", item["link_status"]
        assert item["vehicle"]["registry_status"] == expected_status
        if expected_flag:
            assert expected_flag in item["flags"], item["flags"]
        assert "THREAT" not in json.dumps(item).upper()
        print(f"  -> {plate}: LINKED_INACTIVE, registry status '{expected_status}' as recorded"
              + (f", flag {expected_flag}" if expected_flag else ""))
    print("  -> PASS Scenario 5: LINKED_INACTIVE verified; no THREAT label produced.")

    # --- Scenario 6: NOT_LINKED ---
    print("\n[SCENARIO 6] Confident read of an unregistered plate -> NOT_LINKED, no suggestions...")
    unregistered_plate, _ = new_plate_pair()
    obs_unreg = ingest(f"p5c_unreg_{run_tag}", unregistered_plate, 0.96)
    item = feed_item(guard, obs_unreg.id, c0)["item"]
    assert item["link_status"] == "NOT_LINKED" and item["vehicle"] is None and item["suggestions"] == []
    obs_conf_variant = ingest(f"p5c_conf_variant_{run_tag}", active_variant, 0.97)
    item = feed_item(guard, obs_conf_variant.id, c0)["item"]
    assert item["link_status"] == "NOT_LINKED" and item["suggestions"] == [], "Confident reads must not get fuzzy suggestions"
    print(f"  -> {unregistered_plate}: NOT_LINKED; near-miss {active_variant} at 0.97 also NOT_LINKED with no suggestions")
    print("  -> PASS Scenario 6: NOT_LINKED verified.")

    # --- Scenario 7: LOW_CONFIDENCE ---
    print("\n[SCENARIO 7] Low-confidence read -> LOW_CONFIDENCE with scored suggestions, never auto-resolved...")
    obs_low = ingest(f"p5c_low_{run_tag}", active_variant, 0.55)
    item = feed_item(guard, obs_low.id, c0)["item"]
    assert item["link_status"] == "LOW_CONFIDENCE" and item["vehicle"] is None and item["link_basis"] is None
    assert "LOW_PLATE_CONFIDENCE" in item["flags"]
    sims = [s["similarity"] for s in item["suggestions"]]
    assert sims == sorted(sims, reverse=True)
    match = [s for s in item["suggestions"] if s["vehicle_id"] == active_vehicle["id"]]
    assert match and match[0]["similarity"] >= 0.9, item["suggestions"]
    obs_low_exact = ingest(f"p5c_low_exact_{run_tag}", active_plate, 0.5)
    item_exact = feed_item(guard, obs_low_exact.id, c0)["item"]
    assert item_exact["link_status"] == "LOW_CONFIDENCE" and item_exact["vehicle"] is None
    assert item_exact["suggestions"][0]["vehicle_id"] == active_vehicle["id"] and item_exact["suggestions"][0]["similarity"] == 1.0
    print(f"  -> {active_variant} @0.55: suggestion {match[0]['plate']} similarity {match[0]['similarity']} (not applied)")
    print(f"  -> {active_plate} @0.50: exact registry plate still LOW_CONFIDENCE, offered as suggestion 1.0")
    print("  -> PASS Scenario 7: LOW_CONFIDENCE verified.")

    # --- Scenario 8: NO_PLATE ---
    print("\n[SCENARIO 8] Detection without a plate -> NO_PLATE...")
    obs_noplate = ingest(f"p5c_noplate_{run_tag}")
    item = feed_item(guard, obs_noplate.id, c0)["item"]
    assert item["link_status"] == "NO_PLATE" and item["suggestions"] == [] and item["observation"]["plate"]["raw"] is None
    print("  -> PASS Scenario 8: NO_PLATE verified.")

    # --- Scenario 9: No registry rows created by ingestion or resolution ---
    print("\n[SCENARIO 9] Ingestion and linkage resolution never create Vehicle / Owner / Visitor rows...")
    client.get("/feed", headers=auth(guard))  # full snapshot resolution as well
    after = counts()
    for key in ("vehicles", "owners", "visitors"):
        assert after[key] == registry_counts[key], f"{key}: {registry_counts[key]} -> {after[key]}"
    print(f"  -> vehicles={after['vehicles']}, owners={after['owners']}, visitors={after['visitors']} unchanged")
    print("  -> PASS Scenario 9: No auto-creation of registry records.")

    # --- Scenario 10: Update in place by source_event_id ---
    print("\n[SCENARIO 10] Frigate refinement of the same source_event_id updates the same feed item...")
    upd_event = f"p5c_update_{run_tag}"
    c_before = cursor_now(guard)
    first = ingest(upd_event, active_variant, 0.6)
    c_mid = cursor_now(guard)
    assert feed_item(guard, first.id, c_before)["item"]["link_status"] == "LOW_CONFIDENCE"
    second = ingest(upd_event, active_plate, 0.97)
    assert second.id == first.id
    with SessionLocal() as s:
        rows = s.query(ObservationEvent).filter_by(source=ObservationSource.FRIGATE, source_event_id=upd_event).count()
    assert rows == 1, rows
    r = client.get("/feed", params={"since_id": c_mid, "limit": 200}, headers=auth(guard))
    mine = [e for e in r.json()["entries"] if e["item"]["observation"]["id"] == str(first.id)]
    assert len(mine) == 1 and mine[0]["kind"] == "OBSERVATION_UPDATED", mine
    assert mine[0]["item"]["link_status"] == "LINKED" and mine[0]["item"]["observation"]["plate"]["confidence"] == 0.97
    r = client.get("/feed", params={"since_id": c_before, "limit": 200}, headers=auth(guard))
    mine = [e for e in r.json()["entries"] if e["item"]["observation"]["id"] == str(first.id)]
    assert len(mine) == 1 and mine[0]["kind"] == "OBSERVATION_UPDATED", "Create+update must collapse to one item"
    snap = client.get("/feed", params={"limit": 200}, headers=auth(guard)).json()
    assert sum(1 for e in snap["entries"] if e["item"]["observation"]["id"] == str(first.id)) == 1
    print(f"  -> One DB row, one feed item ({first.id}); LOW_CONFIDENCE @0.60 -> LINKED @0.97 as OBSERVATION_UPDATED")
    print("  -> PASS Scenario 10: Update-in-place verified.")

    # --- Scenario 11: Manual observation ---
    print("\n[SCENARIO 11] Guard logs a manual sighting; camera rows are untouched...")
    camera_rows_before = {oid: obs_row(oid) for oid in test_obs_ids}
    r = client.post("/observations/manual", headers=auth(guard), json={
        "gate_id": "GATE_1", "plate": active_plate.lower(), "direction": "ENTRY", "note": "Plate read at barrier by guard",
    })
    assert r.status_code == 201, r.text
    manual = r.json()
    mobs = manual["observation"]
    assert mobs["source"] == "MANUAL" and mobs["direction"] == "ENTRY" and mobs["camera_id"] is None
    assert mobs["plate"]["confidence"] is None and mobs["plate"]["normalized"] == active_plate
    assert mobs["created_by"]["username"] == users["GUARD"].username and mobs["note"] == "Plate read at barrier by guard"
    assert manual["link_status"] == "LINKED" and "MANUAL_ENTRY" in manual["flags"] and not mobs["has_snapshot"]
    with SessionLocal() as s:
        row = s.get(ObservationEvent, uuid.UUID(mobs["id"]))
        assert row.created_by_id == users["GUARD"].id and row.source == ObservationSource.MANUAL
    for oid, before in camera_rows_before.items():
        assert obs_row(oid) == before, f"Camera observation {oid} changed after manual entry"
    for role_token in (supervisor, admin):
        rr = client.post("/observations/manual", headers=auth(role_token), json={"gate_id": "GATE_2", "plate": unregistered_plate, "direction": "UNKNOWN"})
        assert rr.status_code == 201, rr.text
    assert client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_404", "plate": "PB10AA1111", "direction": "EXIT"}).status_code == 404
    assert client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_1", "plate": "- -", "direction": "EXIT"}).status_code == 400
    assert client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_1", "plate": "PB10AA1111"}).status_code == 422
    r = client.post("/observations", json={"gate_id": "GATE_1", "source": "MANUAL", "raw_plate": "PB10AA1111"})
    assert r.status_code == 400, "Generic ingestion must not accept MANUAL without created_by"
    snap = client.get(f"/feed/snapshots/{mobs['id']}", headers=auth(guard))
    assert snap.status_code == 404
    print(f"  -> MANUAL row {mobs['id']} by {mobs['created_by']['username']}, direction ENTRY (guard-chosen), no camera/confidence")
    print(f"  -> {len(camera_rows_before)} camera rows byte-identical; SUPERVISOR/ADMIN also accepted; bad gate 404, bad plate 400, missing direction 422")
    print("  -> PASS Scenario 11: Manual observation verified.")

    # --- Scenario 12: Append-only guard resolution ---
    print("\n[SCENARIO 12] Guard confirmation is append-only and never mutates the observation...")
    low_before = obs_row(obs_low.id)
    r = client.post("/resolutions", headers=auth(guard), json={
        "observation_id": str(obs_low.id), "chosen_vehicle_id": active_vehicle["id"], "note": "Verified visually",
    })
    assert r.status_code == 201, r.text
    first_res = r.json()
    assert first_res["item"]["link_status"] == "LINKED" and first_res["item"]["link_basis"] == "GUARD_CONFIRMED"
    assert first_res["resolution"]["created_by"]["username"] == users["GUARD"].username
    r = client.post("/resolutions", headers=auth(supervisor), json={"observation_id": str(obs_low.id), "chosen_vehicle_id": "none"})
    assert r.status_code == 201, r.text
    assert r.json()["item"]["link_status"] == "NOT_LINKED" and r.json()["resolution"]["outcome"] == "NONE_OF_THESE"
    assert r.json()["item"]["suggestions"], "Suggestions stay available for revision of low-confidence reads"
    assert obs_row(obs_low.id) == low_before, "Observation row was mutated by a resolution"
    with SessionLocal() as s:
        res_rows = s.query(ObservationResolution).filter_by(observation_id=obs_low.id).order_by(ObservationResolution.created_at).all()
        assert len(res_rows) == 2
        assert res_rows[0].outcome == ResolutionOutcome.VEHICLE_CONFIRMED and str(res_rows[0].chosen_vehicle_id) == active_vehicle["id"]
        assert res_rows[0].created_by_id == users["GUARD"].id and res_rows[1].created_by_id == users["SUPERVISOR"].id
        first_id = res_rows[0].id
    for stmt in ("UPDATE observation_resolutions SET note = 'tampered' WHERE id = :id",
                 "DELETE FROM observation_resolutions WHERE id = :id"):
        with SessionLocal() as s:
            try:
                s.execute(text(stmt), {"id": first_id})
                s.commit()
                raise AssertionError(f"Database accepted: {stmt}")
            except AssertionError:
                raise
            except Exception as e:
                s.rollback()
                assert "append-only" in str(e), e
    with SessionLocal() as s:
        res = s.get(ObservationResolution, first_id)
        res.note = "tampered via ORM"
        try:
            s.commit()
            raise AssertionError("ORM update of a resolution was accepted")
        except ValueError:
            s.rollback()
    with SessionLocal() as s:
        assert s.get(ObservationResolution, first_id).note == "Verified visually"
    assert client.post("/resolutions", headers=auth(guard), json={"observation_id": str(uuid.uuid4()), "chosen_vehicle_id": "none"}).status_code == 404
    assert client.post("/resolutions", headers=auth(guard), json={"observation_id": str(obs_low.id), "chosen_vehicle_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/resolutions", headers=auth(guard), json={"observation_id": str(obs_low.id), "chosen_vehicle_id": "maybe"}).status_code == 422
    print("  -> 2 resolution rows (GUARD confirm, SUPERVISOR 'none'); latest shown; observation row unchanged")
    print("  -> Raw SQL UPDATE/DELETE and ORM update rejected as append-only")
    print("  -> PASS Scenario 12: Append-only resolution verified.")

    # --- Scenario 13: Permission matrix ---
    print("\n[SCENARIO 13] Permission matrix for registration, owners and registry mutation...")
    window = {"valid_from": now.isoformat(), "valid_until": (now + timedelta(hours=12)).isoformat()}
    perm_plate = lambda: new_plate_pair()[0]
    matrix = [
        ("GUARD STUDENT", guard, {"plate": perm_plate(), "vehicle_category": "STUDENT", **window}, 403),
        ("GUARD FACULTY", guard, {"plate": perm_plate(), "vehicle_category": "FACULTY", **window}, 403),
        ("GUARD STAFF", guard, {"plate": perm_plate(), "vehicle_category": "STAFF", **window}, 403),
        ("SUPERVISOR STUDENT", supervisor, {"plate": perm_plate(), "vehicle_category": "STUDENT", **window}, 403),
        ("GUARD VISITOR no window", guard, {"plate": perm_plate(), "vehicle_category": "VISITOR"}, 400),
        ("GUARD VISITOR window too long", guard, {"plate": perm_plate(), "vehicle_category": "VISITOR", "valid_until": (now + timedelta(hours=GUARD_REGISTRATION_MAX_VALIDITY_HOURS + 2)).isoformat()}, 400),
        ("GUARD VISITOR window in past", guard, {"plate": perm_plate(), "vehicle_category": "VISITOR", "valid_from": (now - timedelta(days=2)).isoformat(), "valid_until": (now - timedelta(days=1)).isoformat()}, 400),
        ("GUARD VISITOR duplicate plate", guard, {"plate": active_plate.lower().replace("10", "-10-"), "vehicle_category": "VISITOR", **window}, 409),
        ("ADMIN STAFF", admin, {"plate": perm_plate(), "vehicle_category": "STAFF"}, 201),
        ("GUARD VISITOR with window", guard, {"plate": perm_plate(), "vehicle_category": "VISITOR", **window}, 201),
        ("SUPERVISOR DELIVERY with window", supervisor, {"plate": perm_plate(), "vehicle_category": "DELIVERY", **window}, 201),
    ]
    guard_visitor_plate = None
    for label, token, body, expected in matrix:
        resp = client.post("/vehicles", headers=auth(token), json=body)
        assert resp.status_code == expected, f"{label}: expected {expected}, got {resp.status_code} {resp.text}"
        if label == "GUARD VISITOR with window":
            guard_visitor_plate = resp.json()["vehicle"]["plate"]
        print(f"  -> POST /vehicles {label}: {resp.status_code}")
    with SessionLocal() as s:
        v = s.query(Vehicle).filter_by(normalized_plate=guard_visitor_plate).one()
        assert v.created_by_id == users["GUARD"].id and v.valid_until is not None
    owner_body = {"identifier": f"FACULTY-P5C-{run_tag}", "full_name": "Dr. Test Owner", "person_type": "FACULTY"}
    assert client.post("/owners", headers=auth(guard), json=owner_body).status_code == 403
    assert client.post("/owners", headers=auth(supervisor), json=owner_body).status_code == 403
    assert client.post("/owners", headers=auth(admin), json={**owner_body, "identifier": owner_identifier}).status_code == 409
    found = client.get("/owners", params={"q": f"harleen kaur {run_tag}"}, headers=auth(guard))
    assert found.status_code == 200 and [o["institutional_id"] for o in found.json()] == [owner_identifier], found.text
    assert client.get("/owners", params={"q": owner_identifier.lower()}, headers=auth(supervisor)).json()[0]["id"] == owner["id"]
    assert client.get("/owners", params={"q": "%"}, headers=auth(guard)).status_code == 422
    assert client.put(f"/vehicles/{guard_visitor_plate}", headers=auth(guard), json={"vehicle_category": "STUDENT"}).status_code == 403
    assert client.put(f"/vehicles/{guard_visitor_plate}", headers=auth(supervisor), json={"status": "ACTIVE"}).status_code == 403
    assert client.delete(f"/vehicles/{guard_visitor_plate}", headers=auth(guard)).status_code == 403
    assert client.delete(f"/vehicles/{guard_visitor_plate}", headers=auth(admin)).status_code == 200
    with SessionLocal() as s:
        assert s.query(Vehicle).filter_by(normalized_plate=guard_visitor_plate).one().status == VehicleStatus.INACTIVE
    print("  -> POST /owners: GUARD 403, SUPERVISOR 403, duplicate 409; GET /owners?q= by name and ID for staff")
    print("  -> PUT/DELETE /vehicles: GUARD/SUPERVISOR 403; ADMIN DELETE soft-deactivates (row kept, INACTIVE)")
    print("  -> PASS Scenario 13: Permission matrix verified.")

    # --- Scenario 14: SSE stream ---
    print("\n[SCENARIO 14] SSE stream emits new observations, in-place updates, registrations and resolutions...")
    reader = SSEReader(guard)
    reader.start()
    ready = reader.wait_for(lambda ev: ev.get("event") == "ready", timeout=10)
    assert reader.status_code == 200
    sse_plate, _ = new_plate_pair()
    sse_event = f"p5c_sse_{run_tag}"
    obs_sse = ingest(sse_event, sse_plate, 0.92)
    ev_new = reader.wait_for(sse_item_for(obs_sse.id, "OBSERVATION_CREATED"))
    assert ev_new["json"]["item"]["link_status"] == "NOT_LINKED"
    assert int(ev_new["id"]) > ready["json"]["cursor"]
    print(f"  -> ready (cursor {ready['json']['cursor']}); new observation pushed as event id {ev_new['id']}")
    ingest(sse_event, sse_plate, 0.99)
    ev_upd = reader.wait_for(sse_item_for(obs_sse.id, "OBSERVATION_UPDATED"))
    assert ev_upd["json"]["item"]["observation"]["plate"]["confidence"] == 0.99 and int(ev_upd["id"]) > int(ev_new["id"])
    print(f"  -> refinement pushed as OBSERVATION_UPDATED for the same item (event id {ev_upd['id']})")
    resp = client.post("/vehicles", headers=auth(guard), json={"plate": sse_plate, "vehicle_category": "VISITOR", **window, "notes": "Registered from live feed"})
    assert resp.status_code == 201, resp.text
    ev_reg = reader.wait_for(sse_item_for(obs_sse.id, "REGISTRY_UPDATED"))
    assert ev_reg["json"]["item"]["link_status"] == "LINKED" and ev_reg["json"]["item"]["vehicle"]["category"] == "VISITOR"
    print("  -> guard registration of the unlinked plate pushed REGISTRY_UPDATED -> LINKED")
    resp = client.post("/resolutions", headers=auth(guard), json={"observation_id": str(obs_sse.id), "chosen_vehicle_id": "none", "note": "Different vehicle"})
    assert resp.status_code == 201
    ev_res = reader.wait_for(sse_item_for(obs_sse.id, "RESOLUTION_ADDED"))
    assert ev_res["json"]["item"]["link_status"] == "NOT_LINKED" and ev_res["json"]["item"]["resolution"]["note"] == "Different vehicle"
    print("  -> guard resolution pushed RESOLUTION_ADDED")
    reader.close()

    # since_id=0 would replay the whole log; Last-Event-ID (sent on reconnect) must win.
    resumed = SSEReader(guard, since_id=0, last_event_id=int(ev_upd["id"]) - 1)
    resumed.start()
    first_feed = resumed.wait_for(lambda ev: ev.get("event") == "feed", timeout=10)
    assert int(first_feed["id"]) >= int(ev_upd["id"]), "Last-Event-ID must take precedence over since_id"
    resumed.wait_for(sse_item_for(obs_sse.id), timeout=10) if first_feed["json"]["item"]["observation"]["id"] != str(obs_sse.id) else None
    resumed.close()
    print(f"  -> reconnect with Last-Event-ID resumed after cursor {int(ev_upd['id']) - 1} (first event id {first_feed['id']})")
    print("  -> PASS Scenario 14: SSE stream verified.")

    # --- Scenario 15: Polling fallback pagination ---
    print("\n[SCENARIO 15] Polling fallback GET /feed?since_id= pages through changes with a cursor...")
    c_page = cursor_now(guard)
    paged_ids = {ingest(f"p5c_page_{i}_{run_tag}", new_plate_pair()[0], 0.9).id for i in range(3)}
    seen, cursor, pages = set(), c_page, 0
    while True:
        page = client.get("/feed", params={"since_id": cursor, "limit": 1}, headers=auth(guard)).json()
        pages += 1
        assert page["cursor"] >= cursor
        seen |= {uuid.UUID(e["item"]["observation"]["id"]) for e in page["entries"]}
        cursor = page["cursor"]
        if not page["has_more"]:
            break
    assert paged_ids <= seen and pages >= 3, (pages, paged_ids - seen)
    print(f"  -> 3 new observations delivered across {pages} pages of limit=1")
    print("  -> PASS Scenario 15: Polling fallback verified.")

    # --- Scenario 16: Invariants ---
    print("\n[SCENARIO 16] Invariants: no access decisions, entry/exit logs or alerts; no decision/threat fields...")
    final = counts()
    for key in ("access_decisions", "entry_exit_logs", "security_alerts"):
        assert final[key] == baseline[key], f"{key}: {baseline[key]} -> {final[key]}"
    snapshot = client.get("/feed", params={"limit": 200}, headers=auth(guard)).json()
    banned = {"decision", "threat", "access", "allowed", "denied", "barrier"}
    keys = {k.lower() for k in all_keys(snapshot)}
    assert not (keys & banned), keys & banned
    print(f"  -> AccessDecision {final['access_decisions']}, EntryExitLog with decision {final['entry_exit_logs']}, "
          f"SecurityAlert {final['security_alerts']} (all unchanged; 0 created)")
    print("  -> PASS Scenario 16: Invariants preserved.")

    print("\n========================================================")
    print("PHASE 5C: ALL 16 SCENARIOS PASSED")
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
