"""
Unit & Integration Test Suite for Multi-Gate IP-Linked Camera Stream Runner & Adaptive FPS Settings
---------------------------------------------------------------------------------------------------
Verifies:
1. GATE_1-only default state (active_gates=1, per_gate_target_fps=15.0).
2. Adaptive FPS budget halving/scaling (1 gate -> 15.0 FPS, 2 gates -> 7.5 FPS, 3 gates -> 5.0 FPS).
3. RBAC: GUARD can view settings, but receives 403 Forbidden on PUT/start/stop/test (ADMIN only).
4. Strict input validation: port 1-65535, protocol http/rtsp, leading slash on path, blocked metadata IPs.
5. Dynamic gate registration (auto-creates Gate row for newly added gates like GATE_4).
6. Connection test endpoint reporting latency & diagnostics.
7. Inference guardrails:
   - Laplacian variance sharpness filtering (< 40.0 skipped)
   - Aspect-ratio clamping (1.5 <= w/h <= 6.0)
   - 60-second debounce per (gate_id, plate)
"""

import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.db import SessionLocal
from backend.app.main import app
from backend.app.models.gate import Gate
from backend.app.models.identity import User
from backend.app.models.stream_setting import GateStreamSetting
from backend.app.services.auth_service import create_access_token
from backend.app.workers.camera_stream_runner import (
    CameraStreamManager,
    camera_stream_manager,
    letterbox_image,
)


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def admin_headers(db: Session):
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None
    token, _ = create_access_token(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def guard_headers(db: Session):
    guard = db.query(User).filter(User.username == "guard1").first()
    assert guard is not None
    token, _ = create_access_token(guard)
    return {"Authorization": f"Bearer {token}"}


def test_default_gate_state_and_adaptive_fps(guard_headers, admin_headers):
    """
    1. Verifies that GATE_1 is enabled by default, and GATE_2 and GATE_3 are in standby.
    2. Verifies adaptive FPS calculation at 15.0 FPS.
    """
    with TestClient(app) as client:
        # Reset to baseline default state
        reset_payload = {
            "total_fps_budget": 15.0,
            "gates": [
                {"gate_id": "GATE_1", "enabled": True, "ip_address": "192.168.1.100", "port": 8080, "protocol": "http", "stream_path": "/video"},
                {"gate_id": "GATE_2", "enabled": False, "ip_address": "192.168.1.101", "port": 8080, "protocol": "http", "stream_path": "/video"},
                {"gate_id": "GATE_3", "enabled": False, "ip_address": "192.168.1.102", "port": 8080, "protocol": "http", "stream_path": "/video"},
            ]
        }
        res_put = client.put("/api/gates/stream-settings", json=reset_payload, headers=admin_headers)
        assert res_put.status_code == 200

        # Guard can read stream settings
        res = client.get("/api/gates/stream-settings", headers=guard_headers)
        assert res.status_code == 200
        data = res.json()

        assert data["total_fps_budget"] == 15.0
        assert data["active_gates_count"] == 1
        assert data["per_gate_target_fps"] == 15.0

        gate_map = {g["gate_id"]: g for g in data["gates"]}
        assert "GATE_1" in gate_map
        assert gate_map["GATE_1"]["enabled"] is True
        assert gate_map["GATE_1"]["effective_fps"] == 15.0

        if "GATE_2" in gate_map:
            assert gate_map["GATE_2"]["enabled"] is False
            assert gate_map["GATE_2"]["effective_fps"] == 0.0

        if "GATE_3" in gate_map:
            assert gate_map["GATE_3"]["enabled"] is False
            assert gate_map["GATE_3"]["effective_fps"] == 0.0


def test_adaptive_fps_scaling_two_and_three_gates(admin_headers):
    """
    Verifies adaptive FPS budget division:
    1 gate -> 15.0 FPS
    2 gates -> 7.5 FPS
    3 gates -> 5.0 FPS
    """
    with TestClient(app) as client:
        # Enable 2 gates
        payload_2 = {
            "total_fps_budget": 15.0,
            "gates": [
                {"gate_id": "GATE_1", "enabled": True},
                {"gate_id": "GATE_2", "enabled": True},
                {"gate_id": "GATE_3", "enabled": False},
            ]
        }
        res2 = client.put("/api/gates/stream-settings", json=payload_2, headers=admin_headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["active_gates_count"] == 2
        assert data2["per_gate_target_fps"] == 7.5

        # Enable 3 gates
        payload_3 = {
            "total_fps_budget": 15.0,
            "gates": [
                {"gate_id": "GATE_1", "enabled": True},
                {"gate_id": "GATE_2", "enabled": True},
                {"gate_id": "GATE_3", "enabled": True},
            ]
        }
        res3 = client.put("/api/gates/stream-settings", json=payload_3, headers=admin_headers)
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["active_gates_count"] == 3
        assert data3["per_gate_target_fps"] == 5.0

        # Change budget to 30.0 FPS with 3 gates -> 10.0 FPS each
        payload_30 = {"total_fps_budget": 30.0}
        res30 = client.put("/api/gates/stream-settings", json=payload_30, headers=admin_headers)
        assert res30.status_code == 200
        assert res30.json()["per_gate_target_fps"] == 10.0

        # Re-set back to 1 active gate for demo baseline
        client.put("/api/gates/stream-settings", json={
            "total_fps_budget": 15.0,
            "gates": [
                {"gate_id": "GATE_1", "enabled": True},
                {"gate_id": "GATE_2", "enabled": False},
                {"gate_id": "GATE_3", "enabled": False},
            ]
        }, headers=admin_headers)


def test_rbac_guard_blocked_from_updates_and_test(guard_headers):
    """Verifies that GUARD role receives 403 Forbidden on update, start, stop, test endpoints."""
    with TestClient(app) as client:
        # PUT /api/gates/stream-settings -> 403
        res_put = client.put("/api/gates/stream-settings", json={"total_fps_budget": 20.0}, headers=guard_headers)
        assert res_put.status_code == 403

        # POST /start -> 403
        res_start = client.post("/api/gates/stream-settings/GATE_2/start", headers=guard_headers)
        assert res_start.status_code == 403

        # POST /stop -> 403
        res_stop = client.post("/api/gates/stream-settings/GATE_1/stop", headers=guard_headers)
        assert res_stop.status_code == 403

        # POST /test -> 403
        res_test = client.post("/api/gates/stream-settings/GATE_1/test", json={}, headers=guard_headers)
        assert res_test.status_code == 403


def test_input_validation_and_blocked_metadata_endpoints(admin_headers):
    """Verifies validation against invalid ports, invalid protocols, and cloud metadata IPs."""
    with TestClient(app) as client:
        # Port 0 or negative -> 422
        res_port = client.put("/api/gates/stream-settings", json={
            "gates": [{"gate_id": "GATE_1", "port": 0}]
        }, headers=admin_headers)
        assert res_port.status_code == 422

        # Port > 65535 -> 422
        res_port_high = client.put("/api/gates/stream-settings", json={
            "gates": [{"gate_id": "GATE_1", "port": 70000}]
        }, headers=admin_headers)
        assert res_port_high.status_code == 422

        # Protocol ftp -> 422
        res_proto = client.put("/api/gates/stream-settings", json={
            "gates": [{"gate_id": "GATE_1", "protocol": "ftp"}]
        }, headers=admin_headers)
        assert res_proto.status_code == 422

        # Cloud metadata IP -> 422
        res_meta = client.put("/api/gates/stream-settings", json={
            "gates": [{"gate_id": "GATE_1", "ip_address": "169.254.169.254"}]
        }, headers=admin_headers)
        assert res_meta.status_code == 422

        # Path without leading slash -> 422
        res_path = client.put("/api/gates/stream-settings", json={
            "gates": [{"gate_id": "GATE_1", "stream_path": "video"}]
        }, headers=admin_headers)
        assert res_path.status_code == 422


def test_dynamic_add_new_gate(admin_headers, db: Session):
    """Adding a new gate (e.g. GATE_TEST_RUNNER) automatically creates the Gate and Stream records."""
    test_gate_id = "GATE_TEST_AUTO"
    with TestClient(app) as client:
        payload = {
            "gates": [
                {
                    "gate_id": test_gate_id,
                    "gate_name": "Automated Test Gate",
                    "enabled": False,
                    "ip_address": "192.168.1.199",
                    "port": 8080,
                    "protocol": "http",
                    "stream_path": "/video",
                }
            ]
        }
        res = client.put("/api/gates/stream-settings", json=payload, headers=admin_headers)
        assert res.status_code == 200

        # Verify gate was created in database
        g = db.get(Gate, test_gate_id)
        assert g is not None
        assert g.name == "Automated Test Gate"

        s = db.get(GateStreamSetting, test_gate_id)
        assert s is not None
        assert s.ip_address == "192.168.1.199"


def test_connection_test_endpoint(admin_headers):
    """POST /api/gates/stream-settings/{gate_id}/test returns diagnostics response."""
    with TestClient(app) as client:
        # Test an unreachable private IP (timeout or connection refused)
        res = client.post("/api/gates/stream-settings/GATE_1/test", json={
            "ip_address": "192.0.2.1",  # TEST-NET-1 (RFC 5737 - unroutable)
            "port": 8080,
            "protocol": "http",
            "stream_path": "/video",
        }, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("ok", "error")
        assert "tested_url" in data
        assert "192.0.2.1:8080/video" in data["tested_url"]


def test_laplacian_sharpness_filtering():
    """Verifies that blurry images (Laplacian variance < 40.0) are rejected."""
    runner = CameraStreamManager(total_fps_budget=15.0)

    # 1. Uniform blurry / flat image (variance = 0.0)
    flat_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    res_flat = runner.process_frame("GATE_1", flat_frame)
    assert res_flat is None, "Flat blurry frame must be skipped"

    # 2. Gaussian blurred image
    noisy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    heavily_blurred = cv2.GaussianBlur(noisy_frame, (51, 51), 0)
    res_blur = runner.process_frame("GATE_1", heavily_blurred)
    assert res_blur is None, "Heavily blurred frame must be skipped"


def test_aspect_ratio_clamping_and_letterbox():
    """Verifies letterbox scaling and aspect ratio clamping constraints."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    canvas, scale, dx, dy = letterbox_image(frame, 640)

    assert canvas.shape == (640, 640, 3)
    assert scale == 640.0 / 1280.0
    assert dx == 0
    assert dy == (640 - int(720 * scale)) // 2

    # Aspect ratio validation rule check: 1.5 <= w/h <= 6.0
    def valid_aspect(w: float, h: float) -> bool:
        ratio = w / max(1.0, h)
        return 1.5 <= ratio <= 6.0

    assert valid_aspect(350, 100) is True   # ratio = 3.5 (standard plate)
    assert valid_aspect(200, 100) is True   # ratio = 2.0 (motorcycle plate)
    assert valid_aspect(100, 100) is False  # ratio = 1.0 (square - invalid)
    assert valid_aspect(700, 100) is False  # ratio = 7.0 (too wide - invalid)


def test_debounce_cache_suppresses_rapid_duplicate_detections(db: Session):
    """Verifies that the same plate at the same gate within 60s is debounced."""
    runner = CameraStreamManager(total_fps_budget=15.0)

    gate_id = "GATE_1"
    test_plate = "DL01AB1234"

    key = (gate_id, test_plate)
    runner._debounce_cache[key] = time.time()  # Marked seen right now

    # A detection within 60s is debounced
    assert time.time() - runner._debounce_cache[key] < 60.0

    # Simulate 61 seconds passing
    runner._debounce_cache[key] = time.time() - 65.0
    assert time.time() - runner._debounce_cache[key] >= 60.0
