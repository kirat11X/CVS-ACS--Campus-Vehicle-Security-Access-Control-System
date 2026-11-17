import os
import sys
import time
import uuid
import random
import threading
from datetime import datetime, timezone, timedelta
import httpx
import uvicorn

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal
from backend.app.models import User, Gate, AccessDecision, VehicleOwner, Vehicle, ObservationEvent
from backend.app.services.auth_service import hash_password
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker

BASE_URL = "http://127.0.0.1:8000"
SAFE_LETTERS = "ACEHJKLMNPRTUVWXY"

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
    ]:
        if not db.query(Gate).filter_by(id=gd["id"]).first():
            db.add(Gate(id=gd["id"], name=gd["name"], camera_id=gd["camera_id"], status="ACTIVE"))
    db.commit()

def new_plate():
    letters = "".join(random.choice(SAFE_LETTERS) for _ in range(2))
    digits = "".join(random.choice("1345679") for _ in range(4))
    return f"CH16{letters}{digits}"

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def run_tests():
    print("========================================================")
    print("PHASE 16: CONSOLE API (CORS, DASHBOARD, USERS, OWNERS, VEHICLE SEARCH)")
    print("========================================================")

    client = httpx.Client(base_url=BASE_URL, timeout=20.0)
    worker = FrigateMQTTWorker()
    tag = uuid.uuid4().hex[:6]

    db = SessionLocal()
    ensure_test_gates(db)
    passwords, users = {}, {}
    for role in ("ADMIN", "SUPERVISOR", "GUARD"):
        pw = uuid.uuid4().hex
        u = User(username=f"p16_{role.lower()}_{tag}", email=f"p16_{role.lower()}_{tag}@campus.edu",
                 full_name=f"Phase 16 {role.title()}", role=role, hashed_password=hash_password(pw))
        db.add(u)
        users[role], passwords[role] = u, pw
    db.commit()
    for u in users.values():
        db.refresh(u)
    access_decisions_start = db.query(AccessDecision).count()
    db.close()

    def login(username, password):
        return client.post("/auth/login", json={"username": username, "password": password})

    tokens = {}
    for role, u in users.items():
        r = login(u.username, passwords[role])
        assert r.status_code == 200, r.text
        tokens[role] = r.json()["access_token"]
    admin, supervisor, guard = tokens["ADMIN"], tokens["SUPERVISOR"], tokens["GUARD"]

    def ingest(event_id, plate, score, camera="gate_cam"):
        after = {"id": event_id, "camera": camera, "label": "car", "top_score": 0.9, "score": 0.9,
                 "frame_time": time.time(), "sub_label": [plate, score]}
        obs = worker.process_payload({"type": "update", "before": {}, "after": after})
        assert obs is not None, f"Worker failed to ingest {event_id}"
        return obs

    # --- Scenario 1: CORS for the mobile app origins only ---
    print("\n[SCENARIO 1] CORS preflight: Capacitor origins allowed, other origins not...")
    for origin in ("capacitor://localhost", "https://localhost"):
        r = client.options("/feed", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        })
        assert r.status_code == 200, (origin, r.status_code, r.text)
        assert r.headers.get("access-control-allow-origin") == origin, r.headers
        assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()
        assert "access-control-allow-credentials" not in r.headers
    r = client.options("/feed", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") is None, r.headers
    r = client.get("/health", headers={"Origin": "capacitor://localhost"})
    assert r.headers.get("access-control-allow-origin") == "capacitor://localhost"
    print("  -> capacitor://localhost and https://localhost allowed (no credentials); https://evil.example refused")
    print("  -> PASS Scenario 1")

    # --- Scenario 2: Dashboard summary matches the movement log and presence views ---
    print("\n[SCENARIO 2] GET /dashboard/summary is staff-only and agrees with /logs and /presence/inside...")
    assert client.get("/dashboard/summary").status_code == 401
    since = (datetime.now(timezone.utc) - timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
    s = client.get("/dashboard/summary", params={"since": since.isoformat()}, headers=auth(guard))
    assert s.status_code == 200, s.text
    s = s.json()
    assert s["bucket_minutes"] == 60 and 6 <= len(s["activity"]) <= 7, (s["bucket_minutes"], len(s["activity"]))
    assert datetime.fromisoformat(s["activity"][0]["start"]) == since
    entries = client.get("/logs", params={"direction": "ENTRY", "date_from": since.isoformat(), "limit": 1}, headers=auth(guard)).json()["total"]
    exits = client.get("/logs", params={"direction": "EXIT", "date_from": since.isoformat(), "limit": 1}, headers=auth(guard)).json()["total"]
    inside = client.get("/presence/inside", headers=auth(guard)).json()
    assert s["movements"] == {"entries": entries, "exits": exits}, (s["movements"], entries, exits)
    assert s["presence"]["inside"] == inside["total"]
    assert s["presence"]["inside_linked"] == sum(1 for e in inside["items"] if e["linked"])
    assert s["presence"]["unattributed_entries"] == len(inside["unattributed_entries"])
    assert sum(b["entries"] for b in s["activity"]) == entries and sum(b["exits"] for b in s["activity"]) == exits
    assert sum(b["observations"] for b in s["activity"]) == s["observations"]["total"]
    reg = s["registry"]
    assert reg["vehicles"] == sum(reg["vehicles_by_status"].values()) == sum(reg["vehicles_by_category"].values())
    with SessionLocal() as d:
        assert reg["vehicles"] == d.query(Vehicle).count() and reg["owners"] == d.query(VehicleOwner).count()
    week = client.get("/dashboard/summary", params={"since": "2020-01-01T00:00:00Z"}, headers=auth(supervisor)).json()
    clamp = datetime.now(timezone.utc) - datetime.fromisoformat(week["since"])
    assert timedelta(days=6, hours=23) < clamp <= timedelta(days=7, minutes=1) and week["bucket_minutes"] == 1440
    print(f"  -> entries {entries}, exits {exits}, inside {inside['total']} match /logs and /presence/inside")
    print("  -> buckets start at `since`; a window older than 7 days is clamped to 7 days with daily buckets")

    before = s["observations"]
    plate = new_plate()
    low = ingest(f"p16_low_{tag}", plate, 0.42)
    r = client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_1", "plate": new_plate(), "direction": "UNKNOWN"})
    assert r.status_code == 201, r.text
    after = client.get("/dashboard/summary", params={"since": since.isoformat()}, headers=auth(guard)).json()["observations"]
    assert after["total"] == before["total"] + 2 and after["manual"] == before["manual"] + 1
    assert after["camera"] == before["camera"] + 1
    assert after["low_confidence_unresolved"] == before["low_confidence_unresolved"] + 1
    r = client.post("/resolutions", headers=auth(guard), json={"observation_id": str(low.id), "chosen_vehicle_id": "none"})
    assert r.status_code == 201, r.text
    resolved = client.get("/dashboard/summary", params={"since": since.isoformat()}, headers=auth(guard)).json()["observations"]
    assert resolved["low_confidence_unresolved"] == before["low_confidence_unresolved"]
    print("  -> a 0.42 camera read counts as unresolved low confidence until a guard records a resolution")
    print("  -> PASS Scenario 2")

    # --- Scenario 3: User administration ---
    print("\n[SCENARIO 3] /users: ADMIN only, never deleted, role and deactivation apply immediately...")
    for token, code in ((guard, 403), (supervisor, 403), (None, 401)):
        assert client.get("/users", headers=auth(token) if token else {}).status_code == code
    new_username, new_pw = f"p16_new_{tag}", uuid.uuid4().hex
    body = {"username": new_username, "full_name": "Gate 2 Night Guard", "email": f"p16_new_{tag}@campus.edu",
            "role": "GUARD", "password": new_pw}
    assert client.post("/users", headers=auth(guard), json=body).status_code == 403
    r = client.post("/users", headers=auth(admin), json=body)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["role"] == "GUARD" and created["is_active"] and "hashed_password" not in created and "password" not in created
    assert client.post("/users", headers=auth(admin), json=body).status_code == 409
    assert client.post("/users", headers=auth(admin), json={**body, "username": f"p16_dup_{tag}", "email": body["email"].upper()}).status_code == 409
    assert client.post("/users", headers=auth(admin), json={**body, "username": "bad name!"}).status_code == 422
    assert client.post("/users", headers=auth(admin), json={**body, "username": f"p16_short_{tag}", "password": "short"}).status_code == 422
    listed = client.get("/users", params={"q": new_username}, headers=auth(admin)).json()
    assert [u["username"] for u in listed] == [new_username] and all("hashed_password" not in u for u in listed)

    r = login(new_username, new_pw)
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    assert client.get("/dashboard/summary", headers=auth(new_token)).status_code == 200
    assert client.get("/users", headers=auth(new_token)).status_code == 403
    r = client.patch(f"/users/{created['id']}", headers=auth(admin), json={"role": "SUPERVISOR", "full_name": "Night Supervisor"})
    assert r.status_code == 200 and r.json()["role"] == "SUPERVISOR"
    me = client.get("/auth/me", headers=auth(new_token)).json()
    assert me["role"] == "SUPERVISOR" and me["full_name"] == "Night Supervisor"
    assert client.patch(f"/users/{created['id']}", headers=auth(admin), json={"username": "renamed"}).status_code == 422
    assert client.patch(f"/users/{created['id']}", headers=auth(admin), json={"role": None}).status_code == 400
    r = client.patch(f"/users/{created['id']}", headers=auth(admin), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/auth/me", headers=auth(new_token)).status_code == 401
    assert login(new_username, new_pw).status_code == 401
    reset_pw = uuid.uuid4().hex
    assert client.patch(f"/users/{created['id']}", headers=auth(admin), json={"is_active": True, "password": reset_pw}).status_code == 200
    assert login(new_username, new_pw).status_code == 401 and login(new_username, reset_pw).status_code == 200
    admin_id = str(users["ADMIN"].id)
    assert client.patch(f"/users/{admin_id}", headers=auth(admin), json={"is_active": False}).status_code == 400
    assert client.patch(f"/users/{admin_id}", headers=auth(admin), json={"role": "GUARD"}).status_code == 400
    assert client.patch(f"/users/{uuid.uuid4()}", headers=auth(admin), json={"full_name": "x"}).status_code == 404
    print("  -> GUARD/SUPERVISOR 403; duplicate username/email (case-insensitive) 409; hash never returned")
    print("  -> role change and deactivation take effect on the existing token; reset password works")
    print("  -> an admin cannot disable or demote their own account")
    print("  -> PASS Scenario 3")

    # --- Scenario 4: Own password change ---
    print("\n[SCENARIO 4] POST /auth/password changes only your own password, with the current one...")
    g = users["GUARD"]
    assert client.post("/auth/password", json={"current_password": "x", "new_password": "y" * 8}).status_code == 401
    assert client.post("/auth/password", headers=auth(guard), json={"current_password": "wrong", "new_password": "z" * 12}).status_code == 400
    assert client.post("/auth/password", headers=auth(guard), json={"current_password": passwords["GUARD"], "new_password": passwords["GUARD"]}).status_code == 400
    assert client.post("/auth/password", headers=auth(guard), json={"current_password": passwords["GUARD"], "new_password": "short"}).status_code == 422
    changed_pw = uuid.uuid4().hex
    assert client.post("/auth/password", headers=auth(guard), json={"current_password": passwords["GUARD"], "new_password": changed_pw}).status_code == 204
    assert login(g.username, passwords["GUARD"]).status_code == 401 and login(g.username, changed_pw).status_code == 200
    print("  -> wrong current 400, unchanged 400, too short 422, success 204; old password stops working")
    print("  -> PASS Scenario 4")

    # --- Scenario 5: Owner directory, detail and edit ---
    print("\n[SCENARIO 5] /owners: browse without a query, detail with vehicles, ADMIN edit propagates via the person...")
    page = client.get("/owners", params={"limit": 5}, headers=auth(guard))
    assert page.status_code == 200 and len(page.json()) <= 5
    next_page = client.get("/owners", params={"limit": 5, "skip": 5}, headers=auth(guard)).json()
    assert not {o["id"] for o in page.json()} & {o["id"] for o in next_page}, "pages overlap"
    assert client.get("/owners", params={"q": "%"}, headers=auth(guard)).status_code == 422
    identifier = f"P16-STUDENT-{tag}"
    r = client.post("/owners", headers=auth(admin), json={
        "identifier": identifier, "full_name": f"Simran Gill {tag}", "phone": "+919811100000",
        "person_type": "STUDENT", "residence_type": "HOSTELLER", "residence": "GH-1, Room 210",
    })
    assert r.status_code == 201, r.text
    owner = r.json()
    hostellers = client.get("/owners", params={"q": tag, "residence_type": "HOSTELLER", "person_type": "STUDENT"}, headers=auth(guard)).json()
    assert [o["id"] for o in hostellers] == [owner["id"]]
    assert client.get("/owners", params={"q": tag, "residence_type": "DAY_SCHOLAR"}, headers=auth(guard)).json() == []

    owned_plate = new_plate()
    r = client.post("/vehicles", headers=auth(admin), json={"plate": owned_plate, "vehicle_category": "STUDENT", "owner_id": identifier})
    assert r.status_code == 201, r.text
    for key in (owner["id"], identifier):
        d = client.get(f"/owners/{key}", headers=auth(supervisor))
        assert d.status_code == 200, d.text
        assert d.json()["owner"]["id"] == owner["id"] and [v["vehicle"]["plate"] for v in d.json()["vehicles"]] == [owned_plate]
    assert client.get(f"/owners/NO-SUCH-{tag}", headers=auth(guard)).status_code == 404

    sighting = ingest(f"p16_owned_{tag}", owned_plate, 0.97)
    cursor = client.get("/feed", params={"limit": 1}, headers=auth(guard)).json()["cursor"]
    assert client.put(f"/owners/{owner['id']}", headers=auth(guard), json={"residence": "x"}).status_code == 403
    assert client.put(f"/owners/{owner['id']}", headers=auth(admin), json={"identifier": "NEW-ID"}).status_code == 422
    assert client.put(f"/owners/{owner['id']}", headers=auth(admin), json={"full_name": None}).status_code == 400
    assert client.put(f"/owners/{owner['id']}", headers=auth(admin), json={"full_name": "   "}).status_code == 400
    r = client.put(f"/owners/{owner['id']}", headers=auth(admin), json={
        "residence_type": "DAY_SCHOLAR", "residence": "Sector 15, Chandigarh", "phone": None,
    })
    assert r.status_code == 200, r.text
    updated = r.json()["owner"]
    assert updated["residence_type"] == "DAY_SCHOLAR" and updated["residence"] == "Sector 15, Chandigarh"
    assert updated["phone"] is None and updated["institutional_id"] == identifier and updated["name"] == f"Simran Gill {tag}"
    assert r.json()["vehicles"][0]["context"]["residence_type"] == "DAY_SCHOLAR"
    changes = client.get("/feed", params={"since_id": cursor, "limit": 200}, headers=auth(guard)).json()["entries"]
    re_emitted = [e for e in changes if e["item"]["observation"]["id"] == str(sighting.id)]
    assert re_emitted and re_emitted[-1]["kind"] == "REGISTRY_UPDATED", [e["kind"] for e in changes]
    assert re_emitted[-1]["item"]["residence"]["residence_type"] == "DAY_SCHOLAR"
    with SessionLocal() as d:
        assert d.query(ObservationEvent).filter(ObservationEvent.id == sighting.id).count() == 1
    print("  -> directory browsable without a query (q='%' still 422), filters by person and residence type")
    print("  -> detail by UUID or institutional ID lists the owner's vehicles; unknown 404")
    print("  -> GUARD 403; identifier immutable (422); null clears an optional field, not a required one")
    print("  -> residence edit re-emitted the owner's recent sighting on the feed as REGISTRY_UPDATED")
    print("  -> PASS Scenario 5")

    # --- Scenario 6: Vehicle search by plate fragment ---
    print("\n[SCENARIO 6] GET /vehicles?q= matches a format-tolerant plate fragment, newest first...")
    spaced = f"{owned_plate[:4].lower()} {owned_plate[4:6]}-{owned_plate[6:]}"
    found = client.get("/vehicles", params={"q": spaced}, headers=auth(guard)).json()
    assert [v["vehicle"]["plate"] for v in found] == [owned_plate], found
    second = new_plate()
    r = client.post("/vehicles", headers=auth(admin), json={"plate": second, "vehicle_category": "STAFF"})
    assert r.status_code == 201
    newest = client.get("/vehicles", params={"q": "CH16", "limit": 100}, headers=auth(guard)).json()
    plates = [v["vehicle"]["plate"] for v in newest]
    assert plates.index(second) < plates.index(owned_plate), "newest registration first"
    assert client.get("/vehicles", params={"q": "%%"}, headers=auth(guard)).status_code == 200
    exact = client.get("/vehicles", params={"plate": owned_plate}, headers=auth(guard)).json()
    assert [v["vehicle"]["plate"] for v in exact] == [owned_plate], "exact plate filter unchanged"
    print(f"  -> '{spaced}' finds {owned_plate}; newest registration listed first; exact ?plate= unchanged")
    print("  -> PASS Scenario 6")

    # --- Scenario 7: Invariants ---
    print("\n[SCENARIO 7] Invariants: no access decisions, no deleted accounts...")
    with SessionLocal() as d:
        assert d.query(AccessDecision).count() == access_decisions_start
        assert d.query(User).filter(User.username == new_username).count() == 1
    print(f"  -> AccessDecision count unchanged ({access_decisions_start}); deactivated account still present")
    print("  -> PASS Scenario 7")

    print("\n========================================================")
    print("PHASE 16: ALL 7 SCENARIOS PASSED")
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
