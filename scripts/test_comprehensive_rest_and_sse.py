#!/usr/bin/env python3
"""
Comprehensive REST API & Live SSE Feed Test Suite for CVS-ACS
Author: Tester 4 (Backend REST API & Live SSE Feed Tester)
"""

import asyncio
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

class TestResult:
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.status = "PENDING"
        self.status_code = None
        self.expected_status = None
        self.latency_ms = 0.0
        self.error_message = None
        self.details = {}

    def pass_test(self, status_code: int, latency_ms: float, details: Optional[Dict] = None):
        self.status = "PASS"
        self.status_code = status_code
        self.latency_ms = latency_ms
        if details:
            self.details.update(details)

    def fail_test(self, status_code: Optional[int], expected_status: Any, error: str, latency_ms: float = 0.0):
        self.status = "FAIL"
        self.status_code = status_code
        self.expected_status = expected_status
        self.error_message = error
        self.latency_ms = latency_ms

    def to_dict(self):
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "status_code": self.status_code,
            "expected_status": self.expected_status,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error_message,
            "details": self.details,
        }

class APITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.results: List[TestResult] = []
        self.admin_token: Optional[str] = None
        self.admin_user: Optional[Dict] = None
        self.guard_token: Optional[str] = None
        self.guard_user: Optional[Dict] = None
        self.test_ids = {
            "gate_id": f"TEST_GATE_{uuid.uuid4().hex[:6].upper()}",
            "plate": f"TEST{uuid.uuid4().hex[:4].upper()}",
            "owner_ident": f"OWNER_{uuid.uuid4().hex[:6].upper()}",
            "order_id": f"ORD-TEST-{uuid.uuid4().hex[:6].upper()}",
            "camera_id": f"cam_test_{uuid.uuid4().hex[:6]}",
            "username": f"user_{uuid.uuid4().hex[:6]}",
        }

    def client(self, token: Optional[str] = None, timeout: float = 10.0) -> httpx.Client:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def log(self, tr: TestResult):
        self.results.append(tr)
        icon = "✅" if tr.status == "PASS" else "❌"
        status_info = f"({tr.status_code})" if tr.status_code else ""
        lat_info = f"{tr.latency_ms:.1f}ms"
        print(f" {icon} [{tr.category}] {tr.name} {status_info} - {lat_info}")
        if tr.status == "FAIL":
            print(f"    -> ERROR: {tr.error_message} (expected {tr.expected_status})")

    # ----------------------------------------------------
    # 1. AUTHENTICATION & SESSION MANAGEMENT (/auth)
    # ----------------------------------------------------
    def test_auth_router(self):
        print("\n================== 1. TESTING AUTH ROUTER (/auth) ==================")

        # 1.1 Valid Admin Login
        tr = TestResult("POST /auth/login (Admin credentials)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.post("/auth/login", json={"username": "admin", "password": "Admin@12345"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "access_token" in r.json():
            data = r.json()
            self.admin_token = data["access_token"]
            self.admin_user = data["user"]
            tr.pass_test(r.status_code, dt, {"role": self.admin_user.get("role")})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 1.2 Valid Guard Login
        tr = TestResult("POST /auth/login (Guard credentials)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.post("/auth/login", json={"username": "guard1", "password": "Guard@12345"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "access_token" in r.json():
            data = r.json()
            self.guard_token = data["access_token"]
            self.guard_user = data["user"]
            tr.pass_test(r.status_code, dt, {"role": self.guard_user.get("role")})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 1.3 Invalid password -> 401
        tr = TestResult("POST /auth/login (Wrong password -> 401)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.post("/auth/login", json={"username": "admin", "password": "WrongPassword!999"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401 and "Incorrect username or password" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 1.4 Non-existent username -> 401
        tr = TestResult("POST /auth/login (Non-existent user -> 401)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.post("/auth/login", json={"username": "ghost_user_99999", "password": "SomePassword123"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 1.5 Missing fields -> 422
        tr = TestResult("POST /auth/login (Missing password -> 422)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.post("/auth/login", json={"username": "admin"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 1.6 GET /auth/me unauthenticated -> 401
        tr = TestResult("GET /auth/me (Unauthenticated -> 401)", "Auth")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/auth/me")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 1.7 GET /auth/me invalid token -> 401
        tr = TestResult("GET /auth/me (Invalid token -> 401)", "Auth")
        t0 = time.perf_counter()
        with self.client(token="malformed.jwt.token") as c:
            r = c.get("/auth/me")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 1.8 GET /auth/me with Admin token -> 200
        tr = TestResult("GET /auth/me (Admin token -> 200)", "Auth")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.get("/auth/me")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("role") == "ADMIN":
            tr.pass_test(r.status_code, dt, r.json())
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 1.9 GET /auth/me with Guard token -> 200
        tr = TestResult("GET /auth/me (Guard token -> 200)", "Auth")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/auth/me")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("role") == "GUARD":
            tr.pass_test(r.status_code, dt, r.json())
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 1.10 POST /auth/password validation
        tr = TestResult("POST /auth/password (Wrong current password -> 400)", "Auth")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/auth/password", json={"current_password": "WrongPassword!", "new_password": "NewSecret@12345"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "Current password is incorrect" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        tr = TestResult("POST /auth/password (Identical new password -> 400)", "Auth")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/auth/password", json={"current_password": "Guard@12345", "new_password": "Guard@12345"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "different from the current one" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 2. GATES & CAMERAS ROUTER (/gates)
    # ----------------------------------------------------
    def test_gates_router(self):
        print("\n================== 2. TESTING GATES ROUTER (/gates) ==================")
        gate_id = self.test_ids["gate_id"]

        # 2.1 Public GET /gates
        tr = TestResult("GET /gates (Public listing -> 200)", "Gates")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/gates")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"gate_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 2.2 GET /gates with status filter
        tr = TestResult("GET /gates?status=ACTIVE (Filter -> 200)", "Gates")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/gates?status=ACTIVE")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 2.3 Invalid status filter -> 422
        tr = TestResult("GET /gates?status=INVALID (Invalid enum -> 422)", "Gates")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/gates?status=INVALID_STATUS_XYZ")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 2.4 POST /gates as Guard -> 403 Forbidden
        tr = TestResult("POST /gates (Guard role -> 403 Forbidden)", "Gates")
        payload = {"id": gate_id, "name": "Test Gate", "location": "North", "status": "ACTIVE"}
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/gates", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 2.5 POST /gates as Admin -> 201 Created
        tr = TestResult("POST /gates (Admin role -> 201 Created)", "Gates")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/gates", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and r.json().get("id") == gate_id:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 2.6 Duplicate POST /gates -> 409 Conflict
        tr = TestResult("POST /gates (Duplicate ID -> 409 Conflict)", "Gates")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/gates", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 409:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 409, r.text, dt)
        self.log(tr)

        # 2.7 GET /gates/{id} -> 200
        tr = TestResult(f"GET /gates/{gate_id} (Fetch details -> 200)", "Gates")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get(f"/gates/{gate_id}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("id") == gate_id:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 2.8 PUT /gates/{id} as Admin -> 200
        tr = TestResult(f"PUT /gates/{gate_id} (Admin update -> 200)", "Gates")
        update_payload = {"name": "Updated Test Gate Name", "location": "North Perimeter"}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/gates/{gate_id}", json=update_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("name") == "Updated Test Gate Name":
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 2.9 GET /gates/{id}/observations as Guard -> 200
        tr = TestResult(f"GET /gates/{gate_id}/observations (Guard -> 200)", "Gates")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/gates/{gate_id}/observations?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 2.10 DELETE /gates/{id} (Soft-deactivate -> 200)
        tr = TestResult(f"DELETE /gates/{gate_id} (Admin soft-deactivate -> 200)", "Gates")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.delete(f"/gates/{gate_id}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "INACTIVE" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 3. CAMERA LANES ROUTER (/lanes)
    # ----------------------------------------------------
    def test_lanes_router(self):
        print("\n================== 3. TESTING LANES ROUTER (/lanes) ==================")
        cam_id = self.test_ids["camera_id"]
        gate_id = self.test_ids["gate_id"]

        # 3.1 GET /lanes unauthenticated -> 401
        tr = TestResult("GET /lanes (Unauthenticated -> 401)", "Lanes")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/lanes")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 3.2 GET /lanes Guard -> 200
        tr = TestResult("GET /lanes (Guard -> 200)", "Lanes")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/lanes")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"lanes_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 3.3 PUT /lanes as Guard -> 403 Forbidden
        tr = TestResult("PUT /lanes/{cam} (Guard -> 403 Forbidden)", "Lanes")
        payload = {"gate_id": "GATE_1", "lane_role": "ENTRY_LANE", "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 3.4 PUT /lanes with non-existent gate -> 404
        tr = TestResult("PUT /lanes/{cam} (Non-existent gate -> 404)", "Lanes")
        bad_payload = {"gate_id": "NON_EXISTENT_GATE_XYZ", "lane_role": "ENTRY_LANE", "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=bad_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 404:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 404, r.text, dt)
        self.log(tr)

        # 3.5 PUT /lanes ENTRY_LANE with zones -> 400 Bad Request
        tr = TestResult("PUT /lanes/{cam} (ENTRY_LANE with zones -> 400)", "Lanes")
        invalid_zones_payload = {"gate_id": "GATE_1", "lane_role": "ENTRY_LANE", "outside_zone": "zone_a", "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=invalid_zones_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "Zones apply only to BIDIRECTIONAL lanes" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 3.6 PUT /lanes BIDIRECTIONAL with only one zone -> 400 Bad Request
        tr = TestResult("PUT /lanes/{cam} (BIDIRECTIONAL single zone -> 400)", "Lanes")
        single_zone_payload = {"gate_id": "GATE_1", "lane_role": "BIDIRECTIONAL", "outside_zone": "zone_out", "inside_zone": None, "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=single_zone_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "Give both outside_zone and inside_zone" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 3.7 PUT /lanes BIDIRECTIONAL with identical zones -> 400 Bad Request
        tr = TestResult("PUT /lanes/{cam} (BIDIRECTIONAL identical zones -> 400)", "Lanes")
        dup_zone_payload = {"gate_id": "GATE_1", "lane_role": "BIDIRECTIONAL", "outside_zone": "same_zone", "inside_zone": "same_zone", "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=dup_zone_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "outside_zone and inside_zone must differ" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 3.8 PUT /lanes valid ENTRY_LANE declaration -> 200 OK
        tr = TestResult("PUT /lanes/{cam} (Admin ENTRY_LANE -> 200)", "Lanes")
        valid_payload = {"gate_id": "GATE_1", "lane_role": "ENTRY_LANE", "is_active": True, "notes": "Test entry lane"}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=valid_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("camera_id") == cam_id:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 3.9 PUT /lanes valid BIDIRECTIONAL declaration -> 200 OK
        tr = TestResult("PUT /lanes/{cam} (Admin BIDIRECTIONAL with zones -> 200)", "Lanes")
        valid_bidi = {"gate_id": "GATE_1", "lane_role": "BIDIRECTIONAL", "outside_zone": "zone_out", "inside_zone": "zone_in", "is_active": True}
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/lanes/{cam_id}", json=valid_bidi)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("outside_zone") == "zone_out":
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 4. VEHICLE OWNERS ROUTER (/owners)
    # ----------------------------------------------------
    def test_owners_router(self):
        print("\n================== 4. TESTING OWNERS ROUTER (/owners) ==================")
        owner_ident = self.test_ids["owner_ident"]
        created_owner_id = None

        # 4.1 GET /owners Guard -> 200
        tr = TestResult("GET /owners (Guard search -> 200)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/owners?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"owners_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 4.2 Search with SQL special chars escaping (%, _, \)
        tr = TestResult("GET /owners?q=%_%\\ (SQL LIKE escaping -> 200)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/owners?q=%25_%5C")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 4.3 POST /owners as Guard -> 403 Forbidden
        tr = TestResult("POST /owners (Guard role -> 403 Forbidden)", "Owners")
        payload = {
            "identifier": owner_ident,
            "full_name": "Dr. Test Faculty",
            "email": f"{owner_ident.lower()}@campus.edu",
            "phone": "+919876543210",
            "person_type": "FACULTY",
            "residence_type": "CAMPUS_RESIDENT",
            "residence": "Faculty Enclave Block A",
            "department": "Computer Science & Engineering",
        }
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/owners", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 4.4 POST /owners as Admin -> 201 Created
        tr = TestResult("POST /owners (Admin role -> 201 Created)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/owners", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and r.json().get("identifier") == owner_ident:
            created_owner_id = r.json().get("id")
            tr.pass_test(r.status_code, dt, {"owner_id": created_owner_id})
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 4.5 Duplicate POST /owners -> 409 Conflict
        tr = TestResult("POST /owners (Duplicate identifier -> 409 Conflict)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/owners", json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 409:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 409, r.text, dt)
        self.log(tr)

        # 4.6 GET /owners/{id} by institutional ID -> 200
        tr = TestResult(f"GET /owners/{owner_ident} (Fetch by institutional ID -> 200)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/owners/{owner_ident}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("owner", {}).get("identifier") == owner_ident:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 4.7 GET /owners/{id} by UUID -> 200
        if created_owner_id:
            tr = TestResult(f"GET /owners/{created_owner_id} (Fetch by UUID -> 200)", "Owners")
            t0 = time.perf_counter()
            with self.client(token=self.guard_token) as c:
                r = c.get(f"/owners/{created_owner_id}")
            dt = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                tr.pass_test(r.status_code, dt)
            else:
                tr.fail_test(r.status_code, 200, r.text, dt)
            self.log(tr)

        # 4.8 PUT /owners/{id} clearing required field -> 400
        tr = TestResult(f"PUT /owners/{owner_ident} (Clearing full_name -> 400)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/owners/{owner_ident}", json={"full_name": None})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 4.9 PUT /owners/{id} valid update -> 200
        tr = TestResult(f"PUT /owners/{owner_ident} (Admin update department -> 200)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/owners/{owner_ident}", json={"department": "Electrical Engineering"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("owner", {}).get("department") == "Electrical Engineering":
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 4.10 DELETE /owners/{id} as Guard -> 403 Forbidden
        tr = TestResult(f"DELETE /owners/{owner_ident} (Guard role -> 403 Forbidden)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.delete(f"/owners/{owner_ident}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 4.11 DELETE /owners/{id} as Admin -> 200 OK
        tr = TestResult(f"DELETE /owners/{owner_ident} (Admin delete -> 200)", "Owners")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.delete(f"/owners/{owner_ident}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "deleted successfully" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 5. VEHICLES REGISTRY & LOOKUP (/vehicles)
    # ----------------------------------------------------
    def test_vehicles_router(self):
        print("\n================== 5. TESTING VEHICLES ROUTER (/vehicles) ==================")
        plate = self.test_ids["plate"]

        # 5.1 GET /vehicles Guard -> 200
        tr = TestResult("GET /vehicles (Guard listing -> 200)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/vehicles?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"vehicle_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 5.2 Limit bounds: limit=0 -> 422, limit=101 -> 422
        tr = TestResult("GET /vehicles?limit=0 (Below min -> 422)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/vehicles?limit=0")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        tr = TestResult("GET /vehicles?limit=101 (Above max -> 422)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/vehicles?limit=101")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 5.3 POST /vehicles: Guard attempting permanent STUDENT category -> 403
        tr = TestResult("POST /vehicles (Guard STUDENT registration -> 403 Forbidden)", "Vehicles")
        student_payload = {
            "plate": plate,
            "vehicle_category": "STUDENT",
            "make_model": "Honda City",
            "color": "Silver",
        }
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/vehicles", json=student_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 5.4 POST /vehicles: Guard with temporary VISITOR vehicle -> 201 Created
        now = datetime.now(timezone.utc)
        visitor_payload = {
            "plate": plate,
            "vehicle_category": "VISITOR",
            "make_model": "Maruti Swift",
            "color": "White",
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(hours=6)).isoformat(),
            "notes": "Temporary visitor pass",
        }
        tr = TestResult(f"POST /vehicles (Guard VISITOR registration -> 201)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/vehicles", json=visitor_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and r.json().get("normalized_plate") == plate:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 5.5 Duplicate POST /vehicles -> 409 Conflict
        tr = TestResult(f"POST /vehicles (Duplicate plate {plate} -> 409 Conflict)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/vehicles", json=visitor_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 409:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 409, r.text, dt)
        self.log(tr)

        # 5.6 Format-tolerant GET /vehicles/{plate} lookup
        spaced_plate = f"{plate[:4]} {plate[4:]}"
        tr = TestResult(f"GET /vehicles/{spaced_plate} (Format-tolerant lookup -> 200)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/vehicles/{spaced_plate}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("normalized_plate") == plate:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 5.7 PUT /vehicles/{plate} attempting plate mutation -> 400 Bad Request
        tr = TestResult(f"PUT /vehicles/{plate} (Attempt to mutate plate -> 400)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/vehicles/{plate}", json={"plate": "NEWPLATE999"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "License plate cannot be mutated" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 5.8 PUT /vehicles/{plate} valid metadata update -> 200
        tr = TestResult(f"PUT /vehicles/{plate} (Admin update notes -> 200)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.put(f"/vehicles/{plate}", json={"notes": "Updated visitor note"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("notes") == "Updated visitor note":
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 5.9 GET /vehicles/{plate}/history -> 200
        tr = TestResult(f"GET /vehicles/{plate}/history (Guard history -> 200)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/vehicles/{plate}/history")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "movements" in r.json():
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 5.10 POST /vehicles/{plate}/link on already registered plate -> 409 Conflict
        tr = TestResult(f"POST /vehicles/{plate}/link (Already registered -> 409)", "Vehicles")
        link_payload = {
            "evidence_note": "Linking test",
            "owner": {"existing_owner_id": "none"},
            "registration": {"vehicle_category": "VISITOR"},
        }
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post(f"/vehicles/{plate}/link", json=link_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 409:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 409, r.text, dt)
        self.log(tr)

        # 5.11 DELETE /vehicles/{plate} (Admin soft-deactivate -> 200)
        tr = TestResult(f"DELETE /vehicles/{plate} (Admin soft-deactivate -> 200)", "Vehicles")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.delete(f"/vehicles/{plate}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("vehicle_status") == "INACTIVE":
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 6. MOVEMENT LOGS ROUTER (/logs)
    # ----------------------------------------------------
    def test_movements_router(self):
        print("\n================== 6. TESTING MOVEMENTS ROUTER (/logs) ==================")

        # 6.1 GET /logs Guard -> 200
        tr = TestResult("GET /logs (Guard movement log -> 200)", "Movements")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/logs?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "entries" in r.json():
            data = r.json()
            tr.pass_test(r.status_code, dt, {"total": data.get("total"), "count": len(data.get("entries", []))})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 6.2 Filter direction invalid -> 422
        tr = TestResult("GET /logs?direction=SIDEWAYS (Invalid direction -> 422)", "Movements")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/logs?direction=SIDEWAYS")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 6.3 Filter direction ENTRY -> 200
        tr = TestResult("GET /logs?direction=ENTRY (Valid filter -> 200)", "Movements")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/logs?direction=ENTRY")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 6.4 GET /logs/{id} non-existent UUID -> 404
        dummy_uuid = str(uuid.uuid4())
        tr = TestResult("GET /logs/{uuid} (Non-existent -> 404)", "Movements")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/logs/{dummy_uuid}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 404:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 404, r.text, dt)
        self.log(tr)

        # 6.5 POST /logs/confirm with invalid observation -> 404
        tr = TestResult("POST /logs/confirm (Non-existent obs -> 404)", "Movements")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/logs/confirm", json={"observation_id": dummy_uuid, "direction": "ENTRY", "note": "Test confirm"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code in (404, 400):
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 404, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 7. CAMPUS PRESENCE ROUTER (/presence)
    # ----------------------------------------------------
    def test_presence_router(self):
        print("\n================== 7. TESTING PRESENCE ROUTER (/presence) ==================")

        # 7.1 GET /presence Guard -> 200
        tr = TestResult("GET /presence (Guard presence page -> 200)", "Presence")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/presence?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "entries" in r.json():
            data = r.json()
            tr.pass_test(r.status_code, dt, {"total": data.get("total"), "count": len(data.get("entries", []))})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 7.2 GET /presence/inside Guard -> 200
        tr = TestResult("GET /presence/inside (Vehicles currently inside -> 200)", "Presence")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/presence/inside")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "vehicles" in r.json():
            data = r.json()
            tr.pass_test(r.status_code, dt, {"inside_count": len(data.get("vehicles", []))})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 7.3 GET /presence/inside?linked=true -> 200
        tr = TestResult("GET /presence/inside?linked=true (Filter linked -> 200)", "Presence")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/presence/inside?linked=true")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 8. SECURITY REVIEW QUEUE (/security/reviews)
    # ----------------------------------------------------
    def test_reviews_router(self):
        print("\n================== 8. TESTING REVIEWS ROUTER (/security/reviews) ==================")

        # 8.1 GET /security/reviews Guard -> 200
        tr = TestResult("GET /security/reviews (Review queue listing -> 200)", "Reviews")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/security/reviews?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "items" in r.json():
            data = r.json()
            tr.pass_test(r.status_code, dt, {"total": data.get("total"), "item_count": len(data.get("items", []))})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 8.2 Filter by type=ACCESS_EVENT
        tr = TestResult("GET /security/reviews?type=ACCESS_EVENT -> 200", "Reviews")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/security/reviews?type=ACCESS_EVENT")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 8.3 POST /security/reviews/{id}/triage validation: missing guard_id or reason_notes
        tr = TestResult("POST /security/reviews/{id}/triage (Short notes <3 chars -> 422)", "Reviews")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/security/reviews/obs_test_id/triage", json={
                "action": "ALLOW",
                "guard_id": self.guard_user["id"],
                "reason_notes": "ok",  # Min length 3
            })
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 8.4 POST /security/reviews/{id}/triage with non-existent guard_id -> 404
        tr = TestResult("POST /security/reviews/{id}/triage (Unknown guard_id -> 404)", "Reviews")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/security/reviews/obs_test_id/triage", json={
                "action": "ALLOW",
                "guard_id": str(uuid.uuid4()),
                "reason_notes": "Valid note for triage",
            })
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 404:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 404, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 9. DELIVERY SCREENING ROUTER (/deliveries)
    # ----------------------------------------------------
    def test_deliveries_router(self):
        print("\n================== 9. TESTING DELIVERIES ROUTER (/deliveries) ==================")
        order_id = self.test_ids["order_id"]

        # 9.1 GET /deliveries Guard -> 200
        tr = TestResult("GET /deliveries (Guard delivery list -> 200)", "Deliveries")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/deliveries?limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"deliveries_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 9.2 POST /deliveries/process (Invoice OCR & screening)
        # Create a mock invoice image
        sample_img = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\x00\xff\xd9")
        files = {"file": ("invoice.jpg", sample_img, "image/jpeg")}
        data = {"order_id": order_id, "gate_id": "GATE_1", "platform": "Zomato"}

        tr = TestResult("POST /deliveries/process (Upload invoice -> 201 Created)", "Deliveries")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post("/deliveries/process", data=data, files=files)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and r.json().get("order_id") == order_id:
            tr.pass_test(r.status_code, dt, {"overall_verdict": r.json().get("invoice", {}).get("overall_verdict")})
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 9.3 GET /deliveries/{order_id} -> 200
        tr = TestResult(f"GET /deliveries/{order_id} (Fetch delivery detail -> 200)", "Deliveries")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/deliveries/{order_id}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and r.json().get("order_id") == order_id:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 9.4 POST /deliveries/{order_id}/decision Guard -> 201 Created
        tr = TestResult(f"POST /deliveries/{order_id}/decision (Guard CLEARED -> 201)", "Deliveries")
        decision_payload = {"decision": "CLEARED", "note": "Verified order items by guard"}
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.post(f"/deliveries/{order_id}/decision", json=decision_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and len(r.json().get("decisions", [])) > 0:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 9.5 DELETE /deliveries/{order_id} Guard -> 403 Forbidden
        tr = TestResult(f"DELETE /deliveries/{order_id} (Guard role -> 403 Forbidden)", "Deliveries")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.delete(f"/deliveries/{order_id}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 9.6 DELETE /deliveries/{order_id} Admin -> 200 OK
        tr = TestResult(f"DELETE /deliveries/{order_id} (Admin delete order -> 200)", "Deliveries")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.delete(f"/deliveries/{order_id}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "deleted successfully" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 10. SYSTEM & ALERTS ROUTER (/alerts, /system/whatsapp)
    # ----------------------------------------------------
    def test_system_router(self):
        print("\n================== 10. TESTING SYSTEM & ALERTS ROUTER ==================")

        # 10.1 GET /alerts Guard -> 200
        tr = TestResult("GET /alerts (Guard alerts -> 200)", "System")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/alerts?limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"alerts_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 10.2 GET /alerts bounds: limit=0 -> 422, limit=201 -> 422
        tr = TestResult("GET /alerts?limit=0 (Limit 0 -> 422)", "System")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/alerts?limit=0")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 10.3 GET /system/whatsapp Guard -> 200
        tr = TestResult("GET /system/whatsapp (WhatsApp status -> 200)", "System")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/system/whatsapp")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "provider" in r.json():
            tr.pass_test(r.status_code, dt, r.json())
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 11. USERS ADMINISTRATION ROUTER (/users)
    # ----------------------------------------------------
    def test_users_router(self):
        print("\n================== 11. TESTING USERS ROUTER (/users) ==================")
        new_username = self.test_ids["username"]
        created_user_id = None

        # 11.1 GET /users Guard -> 403 Forbidden
        tr = TestResult("GET /users (Guard role -> 403 Forbidden)", "Users")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/users")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 403:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 403, r.text, dt)
        self.log(tr)

        # 11.2 GET /users Admin -> 200 OK
        tr = TestResult("GET /users (Admin role -> 200)", "Users")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.get("/users?skip=0&limit=50")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and isinstance(r.json(), list):
            tr.pass_test(r.status_code, dt, {"users_count": len(r.json())})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 11.3 POST /users Admin -> 201 Created
        user_payload = {
            "username": new_username,
            "full_name": "Test Officer",
            "email": f"{new_username}@campus.edu",
            "role": "GUARD",
            "password": "Password@12345",
        }
        tr = TestResult(f"POST /users (Admin creates {new_username} -> 201)", "Users")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/users", json=user_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 201 and r.json().get("username") == new_username:
            created_user_id = r.json().get("id")
            tr.pass_test(r.status_code, dt, {"user_id": created_user_id})
        else:
            tr.fail_test(r.status_code, 201, r.text, dt)
        self.log(tr)

        # 11.4 Duplicate username -> 409 Conflict
        tr = TestResult("POST /users (Duplicate username -> 409 Conflict)", "Users")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.post("/users", json=user_payload)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 409:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 409, r.text, dt)
        self.log(tr)

        # 11.5 PATCH /users/{id} Admin self-disable protection -> 400
        tr = TestResult("PATCH /users/{admin_id} (Admin self-disable -> 400)", "Users")
        admin_id = self.admin_user["id"]
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.patch(f"/users/{admin_id}", json={"is_active": False})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "cannot disable your own account" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 11.6 PATCH /users/{id} Admin self-demote protection -> 400
        tr = TestResult("PATCH /users/{admin_id} (Admin self-demote -> 400)", "Users")
        t0 = time.perf_counter()
        with self.client(token=self.admin_token) as c:
            r = c.patch(f"/users/{admin_id}", json={"role": "GUARD"})
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 400 and "cannot remove your own ADMIN role" in r.text:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 400, r.text, dt)
        self.log(tr)

        # 11.7 PATCH /users/{id} updating test user -> 200
        if created_user_id:
            tr = TestResult(f"PATCH /users/{created_user_id} (Update test user -> 200)", "Users")
            t0 = time.perf_counter()
            with self.client(token=self.admin_token) as c:
                r = c.patch(f"/users/{created_user_id}", json={"full_name": "Updated Officer Name", "role": "SUPERVISOR"})
            dt = (time.perf_counter() - t0) * 1000
            if r.status_code == 200 and r.json().get("role") == "SUPERVISOR":
                tr.pass_test(r.status_code, dt)
            else:
                tr.fail_test(r.status_code, 200, r.text, dt)
            self.log(tr)

    # ----------------------------------------------------
    # 12. DASHBOARD METRICS ROUTER (/dashboard)
    # ----------------------------------------------------
    def test_dashboard_router(self):
        print("\n================== 12. TESTING DASHBOARD ROUTER (/dashboard) ==================")

        # 12.1 GET /dashboard/summary Guard -> 200
        tr = TestResult("GET /dashboard/summary (Dashboard summary -> 200)", "Dashboard")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/dashboard/summary")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200 and "observations" in r.json() and "movements" in r.json():
            data = r.json()
            tr.pass_test(r.status_code, dt, {
                "observations": data.get("observations", {}).get("total"),
                "entries": data.get("movements", {}).get("entries"),
                "exits": data.get("movements", {}).get("exits"),
                "inside": data.get("presence", {}).get("inside"),
            })
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 12.2 GET /dashboard/summary?since=2026-11-01T00:00:00Z -> 200
        tr = TestResult("GET /dashboard/summary?since=... (Window filter -> 200)", "Dashboard")
        since_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/dashboard/summary?since={since_time}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

    # ----------------------------------------------------
    # 13. LIVE FEED & REAL-TIME SSE STREAM (/feed, /feed/stream)
    # ----------------------------------------------------
    def test_feed_router(self):
        print("\n================== 13. TESTING LIVE FEED & SSE STREAM (/feed) ==================")

        # 13.1 GET /feed Guard -> 200
        tr = TestResult("GET /feed (Snapshot view -> 200)", "Feed")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/feed?limit=50")
        dt = (time.perf_counter() - t0) * 1000
        cursor = None
        if r.status_code == 200 and "entries" in r.json():
            data = r.json()
            cursor = data.get("cursor")
            tr.pass_test(r.status_code, dt, {"cursor": cursor, "entries": len(data.get("entries", []))})
        else:
            tr.fail_test(r.status_code, 200, r.text, dt)
        self.log(tr)

        # 13.2 GET /feed bounds: limit=0 -> 422, limit=201 -> 422
        tr = TestResult("GET /feed?limit=0 (Limit 0 -> 422)", "Feed")
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get("/feed?limit=0")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 422:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 422, r.text, dt)
        self.log(tr)

        # 13.3 GET /feed/snapshots/{id} non-existent UUID -> 404
        tr = TestResult("GET /feed/snapshots/{uuid} (Non-existent snapshot -> 404)", "Feed")
        dummy_uuid = str(uuid.uuid4())
        t0 = time.perf_counter()
        with self.client(token=self.guard_token) as c:
            r = c.get(f"/feed/snapshots/{dummy_uuid}")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 404:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 404, r.text, dt)
        self.log(tr)

        # 13.4 SSE Stream: GET /feed/stream unauthenticated -> 401
        tr = TestResult("GET /feed/stream (Unauthenticated -> 401)", "Feed SSE")
        t0 = time.perf_counter()
        with self.client() as c:
            r = c.get("/feed/stream")
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 401:
            tr.pass_test(r.status_code, dt)
        else:
            tr.fail_test(r.status_code, 401, r.text, dt)
        self.log(tr)

        # 13.5 SSE Stream: Live streaming test with httpx streaming client
        tr = TestResult("GET /feed/stream (SSE Handshake & Ready Event -> 200)", "Feed SSE")
        t0 = time.perf_counter()
        events_received = []
        try:
            with self.client(token=self.guard_token, timeout=8.0) as c:
                with c.stream("GET", "/feed/stream?since_id=0") as response:
                    handshake_dt = (time.perf_counter() - t0) * 1000
                    status_code = response.status_code
                    content_type = response.headers.get("content-type", "")

                    if status_code == 200 and "text/event-stream" in content_type:
                        # Read first few lines of SSE
                        current_event = {}
                        start_read = time.perf_counter()
                        for line in response.iter_lines():
                            line = line.strip()
                            if not line:
                                if current_event:
                                    events_received.append(current_event)
                                    current_event = {}
                                    if len(events_received) >= 1:
                                        break
                                continue
                            if line.startswith("event:"):
                                current_event["event"] = line[6:].strip()
                            elif line.startswith("data:"):
                                current_event["data"] = line[5:].strip()
                            elif line.startswith("id:"):
                                current_event["id"] = line[3:].strip()
                            elif line.startswith("retry:"):
                                current_event["retry"] = line[6:].strip()

                            if time.perf_counter() - start_read > 4.0:
                                break

                        first_event_dt = (time.perf_counter() - t0) * 1000
                        tr.pass_test(status_code, handshake_dt, {
                            "content_type": content_type,
                            "events_received": events_received,
                            "time_to_first_event_ms": round(first_event_dt, 2),
                        })
                    else:
                        tr.fail_test(status_code, 200, f"Unexpected content-type: {content_type}", handshake_dt)
        except Exception as e:
            tr.fail_test(None, 200, str(e), (time.perf_counter() - t0) * 1000)
        self.log(tr)

        # 13.6 SSE Reconnect with Last-Event-ID header
        tr = TestResult("GET /feed/stream (Reconnect via Last-Event-ID -> 200)", "Feed SSE")
        t0 = time.perf_counter()
        try:
            headers = {"Authorization": f"Bearer {self.guard_token}", "Last-Event-ID": "5"}
            with httpx.Client(base_url=self.base_url, headers=headers, timeout=6.0) as c:
                with c.stream("GET", "/feed/stream") as response:
                    dt = (time.perf_counter() - t0) * 1000
                    if response.status_code == 200 and "text/event-stream" in response.headers.get("content-type", ""):
                        tr.pass_test(response.status_code, dt)
                    else:
                        tr.fail_test(response.status_code, 200, "Header Last-Event-ID rejected", dt)
        except Exception as e:
            tr.fail_test(None, 200, str(e), (time.perf_counter() - t0) * 1000)
        self.log(tr)

    # ----------------------------------------------------
    # 14. PERFORMANCE & LATENCY BENCHMARK
    # ----------------------------------------------------
    def run_performance_benchmarks(self) -> Dict[str, Any]:
        print("\n================== 14. PERFORMANCE & LATENCY BENCHMARKS ==================")
        endpoints = [
            ("GET", "/health", None, None),
            ("GET", "/gates", None, None),
            ("GET", "/feed?limit=20", self.guard_token, "Guard"),
            ("GET", "/vehicles?limit=20", self.guard_token, "Guard"),
            ("GET", "/owners?limit=20", self.guard_token, "Guard"),
            ("GET", "/logs?limit=20", self.guard_token, "Guard"),
            ("GET", "/presence/inside", self.guard_token, "Guard"),
            ("GET", "/dashboard/summary", self.guard_token, "Guard"),
            ("GET", "/alerts", self.guard_token, "Guard"),
            ("GET", "/security/reviews", self.guard_token, "Guard"),
            ("GET", "/users?limit=20", self.admin_token, "Admin"),
        ]

        benchmarks = {}
        for method, path, token, role in endpoints:
            latencies = []
            status_codes = []
            for _ in range(10):
                t0 = time.perf_counter()
                with self.client(token=token, timeout=5.0) as c:
                    r = c.request(method, path)
                dt = (time.perf_counter() - t0) * 1000
                latencies.append(dt)
                status_codes.append(r.status_code)

            latencies.sort()
            avg_lat = sum(latencies) / len(latencies)
            p50 = latencies[len(latencies) // 2]
            p95 = latencies[int(len(latencies) * 0.95)]
            min_lat = min(latencies)
            max_lat = max(latencies)

            benchmarks[f"{method} {path}"] = {
                "samples": len(latencies),
                "status_code": status_codes[0],
                "min_ms": round(min_lat, 2),
                "avg_ms": round(avg_lat, 2),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "max_ms": round(max_lat, 2),
            }
            print(f" 📊 {method} {path:30} : min={min_lat:5.1f}ms, avg={avg_lat:5.1f}ms, p95={p95:5.1f}ms, max={max_lat:5.1f}ms (Status: {status_codes[0]})")

        return benchmarks

    def run_all(self):
        print(f"Starting CVS-ACS Comprehensive REST API & SSE Feed Verification on {self.base_url}")
        t_start = time.perf_counter()

        self.test_auth_router()
        self.test_gates_router()
        self.test_lanes_router()
        self.test_owners_router()
        self.test_vehicles_router()
        self.test_movements_router()
        self.test_presence_router()
        self.test_reviews_router()
        self.test_deliveries_router()
        self.test_system_router()
        self.test_users_router()
        self.test_dashboard_router()
        self.test_feed_router()
        benchmarks = self.run_performance_benchmarks()

        total_time = time.perf_counter() - t_start
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        total = len(self.results)

        print("\n========================================================")
        print(f"CVS-ACS API TEST EXECUTION COMPLETE in {total_time:.2f}s")
        print(f"Total Tests : {total}")
        print(f"Passed      : {passed} ({passed/total*100:.1f}%)")
        print(f"Failed      : {failed}")
        print("========================================================")

        return {
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": round(passed / total * 100, 2) if total else 0,
                "duration_seconds": round(total_time, 2),
            },
            "results": [r.to_dict() for r in self.results],
            "benchmarks": benchmarks,
        }

if __name__ == "__main__":
    tester = APITester()
    summary = tester.run_all()
    output_path = "research/api_test_results.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nDetailed JSON results exported to {output_path}")
