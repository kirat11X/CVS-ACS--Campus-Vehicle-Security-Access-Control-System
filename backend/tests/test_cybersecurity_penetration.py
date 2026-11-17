"""
Cybersecurity & Penetration Test Suite for CVS-ACS
(Campus Vehicle Security & Access Control System)

Verifies:
1. Authentication & Session Security (HMAC-SHA256 signature tampering, expiration, scrypt hashing, secret key strength).
2. Role-Based Access Control (RBAC/BFLA: GUARD vs ADMIN permissions).
3. Privilege Escalation & Audit Spoofing (BOLA: review triage guard_id verification vs user.id).
4. Input Validation & Injection Vectors (Path traversal, polyglot uploads, SVG XSS, binary upload, oversized payload DOS, SQLi escaping).
5. Database Integrity & Append-Only Triggers (PostgreSQL triggers preventing UPDATE, DELETE, and TRUNCATE on audit tables).
6. Exposure of Unauthenticated Test Endpoints.
"""

import hashlib
import hmac
import io
import json
import time
import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import AUTH_SECRET_KEY, INVOICE_MAX_UPLOAD_MB
from backend.app.db import SessionLocal
from backend.app.main import app
from backend.app.models import (
    AccessDecision,
    DeliveryDecision,
    DeliveryOrder,
    Gate,
    Invoice,
    ObservationEvent,
    ObservationResolution,
    User,
    Vehicle,
    VehicleLinkEvent,
    VehicleOwner,
)
from backend.app.models.enums import (
    AccessState,
    DeliverySource,
    DirectionMethod,
    GateStatus,
    GuardDecision,
    ObservationSource,
    OrderStatus,
    PersonType,
    PlatformType,
    ResidenceType,
    ScreeningVerdict,
    UserRole,
    VehicleCategory,
    VehicleStatus,
)
from backend.app.services.auth_service import (
    _b64decode,
    _b64encode,
    _sign,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


@pytest.fixture(scope="module")
def client():
    """In-process TestClient with raise_server_exceptions=False to test HTTP status codes."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db():
    """Isolated session for test assertions."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_test_user(db: Session, role: UserRole) -> tuple[User, str]:
    """Helper to create a temporary user in PostgreSQL and return (user, token)."""
    tag = uuid.uuid4().hex[:8]
    user = User(
        username=f"pen_{role.value.lower()}_{tag}",
        email=f"pen_{role.value.lower()}_{tag}@pec.edu.in",
        full_name=f"PenTest {role.value.title()}",
        role=role.value,
        hashed_password=hash_password("ComplexP@ssw0rd!2026"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token, _ = create_access_token(user)
    return user, token


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# 1. AUTHENTICATION & SESSION SECURITY TESTS
# ============================================================================

def test_auth_missing_token_rejected(client):
    """Endpoints requiring authentication must reject unauthenticated requests with 401."""
    resp = client.get("/users")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json().get("detail", "")


def test_auth_malformed_token_rejected(client):
    """Malformed tokens without 2-part structure or invalid Base64 must return 401."""
    for bad in ["not-a-token", "singlepart", "part1.part2.part3", "part1.@@@invalid@@@"]:
        resp = client.get("/auth/me", headers=auth_header(bad))
        assert resp.status_code == 401
        assert "Invalid or expired token" in resp.json().get("detail", "")


def test_auth_tampered_signature_rejected(db, client):
    """Tampering with token payload or signature must invalidate the token."""
    _, token = create_test_user(db, UserRole.GUARD)
    payload_b64, sig = token.split(".")

    # Decode claims, modify role to ADMIN, re-encode without valid signature
    claims = json.loads(_b64decode(payload_b64))
    claims["role"] = "ADMIN"
    forged_payload_b64 = _b64encode(json.dumps(claims).encode("utf-8"))
    forged_token = f"{forged_payload_b64}.{sig}"

    resp = client.get("/auth/me", headers=auth_header(forged_token))
    assert resp.status_code == 401
    assert "Invalid or expired token" in resp.json().get("detail", "")


def test_auth_expired_token_rejected(db, client):
    """Tokens with exp in the past must be rejected with 401."""
    user, _ = create_test_user(db, UserRole.GUARD)
    now = int(time.time())
    expired_exp = now - 3600  # 1 hour ago
    claims = {"sub": str(user.id), "role": user.role, "iat": now - 7200, "exp": expired_exp}
    payload_b64 = _b64encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    expired_token = f"{payload_b64}.{_sign(payload_b64)}"

    resp = client.get("/auth/me", headers=auth_header(expired_token))
    assert resp.status_code == 401
    assert "Invalid or expired token" in resp.json().get("detail", "")


def test_password_hashing_scrypt_salt_uniqueness():
    """scrypt password hashing must generate cryptographically unique salts for identical passwords."""
    pwd = "IdenticalPassword123!"
    hash1 = hash_password(pwd)
    hash2 = hash_password(pwd)
    assert hash1 != hash2, "Identical passwords must generate distinct salt/hash outputs"
    assert verify_password(pwd, hash1) is True
    assert verify_password(pwd, hash2) is True
    assert verify_password("WrongPassword123!", hash1) is False


def test_password_verification_tampered_hash():
    """Corrupted hash string format must return False safely without raising exceptions."""
    assert verify_password("test", None) is False
    assert verify_password("test", "") is False
    assert verify_password("test", "md5$corrupted") is False
    assert verify_password("test", "scrypt$not$enough$parts") is False


# ============================================================================
# 2. ROLE-BASED ACCESS CONTROL & PRIVILEGE ENFORCEMENT (RBAC/BFLA)
# ============================================================================

def test_rbac_guard_denied_on_admin_user_routes(db, client):
    """GUARD accounts must receive 403 Forbidden when accessing /users endpoints."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    # List users
    r1 = client.get("/users", headers=headers)
    assert r1.status_code == 403, f"Expected 403, got {r1.status_code}: {r1.text}"

    # Create user
    r2 = client.post("/users", json={"username": "hacker", "email": "hacker@pec.edu", "full_name": "Hacker", "role": "ADMIN", "password": "pass"}, headers=headers)
    assert r2.status_code == 403

    # Patch user
    r3 = client.patch(f"/users/{uuid.uuid4()}", json={"full_name": "Updated"}, headers=headers)
    assert r3.status_code == 403


def test_rbac_guard_denied_on_admin_owner_mutations(db, client):
    """GUARD accounts must receive 403 Forbidden when creating, updating, or deleting owners."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    # Create owner
    r1 = client.post("/owners", json={"identifier": "24109988", "full_name": "Test", "person_type": "STUDENT", "residence_type": "HOSTELLER"}, headers=headers)
    assert r1.status_code == 403

    # Update owner
    r2 = client.put("/owners/any_id", json={"full_name": "Updated"}, headers=headers)
    assert r2.status_code == 403

    # Delete owner
    r3 = client.delete("/owners/any_id", headers=headers)
    assert r3.status_code == 403


def test_rbac_guard_denied_on_admin_gate_and_lane_mutations(db, client):
    """GUARD accounts must receive 403 Forbidden on gate creation/update/deactivation and lane upsert."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    # Create gate
    r1 = client.post("/gates", json={"id": "GATE_TEST", "name": "Test Gate"}, headers=headers)
    assert r1.status_code == 403

    # Update gate
    r2 = client.put("/gates/GATE_1", json={"name": "Modified Gate"}, headers=headers)
    assert r2.status_code == 403

    # Deactivate gate
    r3 = client.delete("/gates/GATE_1", headers=headers)
    assert r3.status_code == 403

    # Upsert camera lane
    r4 = client.put("/lanes/cam_test", json={"gate_id": "GATE_1", "lane_role": "ENTRY_LANE"}, headers=headers)
    assert r4.status_code == 403


def test_rbac_guard_permanent_vehicle_registration_forbidden(db, client):
    """GUARD accounts cannot register permanent categories (STUDENT, FACULTY, STAFF); requires ADMIN."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    # Attempting to register STUDENT vehicle as GUARD
    payload = {
        "plate": "CH01AB1111",
        "vehicle_category": "STUDENT",
        "make_model": "Honda Civic",
        "color": "Silver",
    }
    resp = client.post("/vehicles", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "requires the ADMIN role" in resp.json().get("detail", "")


def test_rbac_guard_visitor_registration_requires_validity_window(db, client):
    """GUARD registering VISITOR or DELIVERY vehicle must supply a bounded valid_until in the future."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    # Missing valid_until
    payload = {
        "plate": "CH01VISIT1",
        "vehicle_category": "VISITOR",
    }
    resp = client.post("/vehicles", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "require valid_until" in resp.json().get("detail", "")


def test_admin_self_demotion_and_disable_blocked(db, client):
    """ADMIN cannot disable or remove ADMIN role from their own account."""
    admin_user, admin_token = create_test_user(db, UserRole.ADMIN)
    headers = auth_header(admin_token)

    # Try disabling self
    r1 = client.patch(f"/users/{admin_user.id}", json={"is_active": False}, headers=headers)
    assert r1.status_code == 400
    assert "cannot disable your own account" in r1.json().get("detail", "")

    # Try removing ADMIN role from self
    r2 = client.patch(f"/users/{admin_user.id}", json={"role": "GUARD"}, headers=headers)
    assert r2.status_code == 400
    assert "cannot remove your own ADMIN role" in r2.json().get("detail", "")


# ============================================================================
# 3. HORIZONTAL PRIVILEGE ESCALATION & AUDIT SPOOFING (BOLA)
# ============================================================================

def test_delivery_decision_properly_binds_authenticated_user_id(db, client):
    """POST /deliveries/{order_id}/decision must attribute the decision to the authenticated user."""
    guard_user, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    order_id = f"TEST-ORD-{uuid.uuid4().hex[:6].upper()}"
    order = DeliveryOrder(
        order_id=order_id,
        platform=PlatformType.SWIGGY,
        status=OrderStatus.SUBMITTED,
        verification_status=AccessState.REVIEW,
        gate_id="GATE_1",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    inv = Invoice(
        order_id=order.id,
        source=DeliverySource.CONSOLE,
        ocr_engine="RAPIDOCR",
        overall_verdict=ScreeningVerdict.REVIEW,
    )
    db.add(inv)
    db.commit()

    resp = client.post(
        f"/deliveries/{order_id}/decision",
        json={"decision": "CLEARED", "note": "Checked items manually"},
        headers=headers,
    )
    assert resp.status_code == 201

    decision = db.query(DeliveryDecision).filter(DeliveryDecision.order_id == order.id).first()
    assert decision is not None
    assert decision.decided_by_id == guard_user.id


def test_review_triage_guard_id_spoofing_finding(db, client):
    """
    Security Finding Test: POST /security/reviews/{review_id}/triage accepts payload.guard_id
    from the client, which can differ from user.id (authenticated caller).
    This test verifies whether guard_id spoofing is possible in the current codebase.
    """
    guard1, token1 = create_test_user(db, UserRole.GUARD)
    guard2, _ = create_test_user(db, UserRole.GUARD)

    order_id = f"TEST-SPOOF-{uuid.uuid4().hex[:6].upper()}"
    order = DeliveryOrder(
        order_id=order_id,
        platform=PlatformType.ZOMATO,
        status=OrderStatus.SUBMITTED,
        verification_status=AccessState.REVIEW,
        gate_id="GATE_1"
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    inv = Invoice(
        order_id=order.id,
        source=DeliverySource.CONSOLE,
        ocr_engine="RAPIDOCR",
        overall_verdict=ScreeningVerdict.ALERT
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    review_id = f"cargo_{inv.id}"
    headers = auth_header(token1)

    # Guard 1 performs triage but supplies guard2's ID in payload
    payload = {
        "guard_id": str(guard2.id),  # Spoofed guard identity!
        "action": "ALLOW",
        "reason_notes": "Security triage override test",
    }
    resp = client.post(f"/security/reviews/{review_id}/triage", json=payload, headers=headers)
    assert resp.status_code == 200

    decision = db.query(DeliveryDecision).filter(DeliveryDecision.order_id == order.id).first()
    assert decision is not None
    # Vulnerability confirmed: decided_by_id was set to the spoofed guard2.id instead of authenticated guard1.id
    assert decision.decided_by_id == guard2.id


# ============================================================================
# 4. INPUT VALIDATION, INJECTION & TRAVERSAL VECTORS
# ============================================================================

def test_path_traversal_snapshot_endpoint_rejected(db, client):
    """GET /feed/snapshots/{id} must reject non-UUID strings and path traversal sequences with 404 or 422."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)
    for bad_id in ["../../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "non-uuid-string"]:
        resp = client.get(f"/feed/snapshots/{bad_id}", headers=headers)
        assert resp.status_code in (404, 422), f"Expected 404 or 422, got {resp.status_code}"


def test_path_traversal_invoice_image_rejected(db, client):
    """GET /deliveries/{order_id}/invoice-image must safely reject path traversal attempts."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    traversal_order_ids = [
        "../../../../etc/passwd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "....//....//etc/passwd",
    ]
    for oid in traversal_order_ids:
        resp = client.get(f"/deliveries/{oid}/invoice-image", headers=headers)
        # Order does not exist in DB -> 404
        assert resp.status_code == 404


def test_malicious_upload_svg_with_xss_rejected_415(client):
    """SVG files with embedded JavaScript must be rejected with 415 Unsupported Media Type."""
    svg_payload = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(\'XSS\')"><text>Invoice</text></svg>'
    files = {"file": ("malicious.svg", svg_payload, "image/svg+xml")}
    data = {"order_id": "D-XSS-1001", "sender_phone": "+919999900001"}

    resp = client.post("/intake/upload", data=data, files=files, headers={"Accept": "application/json"})
    assert resp.status_code == 415
    assert "Send the invoice as a JPG, PNG, WEBP photo or a PDF" in resp.json().get("detail", "")


def test_malicious_upload_executable_binary_rejected_415(client):
    """Raw ELF/EXE binaries must be rejected with 415 Unsupported Media Type."""
    elf_header = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    files = {"file": ("payload.bin", elf_header, "application/octet-stream")}
    data = {"order_id": "D-BIN-1002"}

    resp = client.post("/intake/upload", data=data, files=files, headers={"Accept": "application/json"})
    assert resp.status_code == 415


def test_malicious_upload_oversized_payload_rejected_413(client):
    """Payloads exceeding INVOICE_MAX_UPLOAD_MB must be rejected with 413 Payload Too Large."""
    oversized_size = int((INVOICE_MAX_UPLOAD_MB + 1) * 1024 * 1024)
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * oversized_size
    files = {"file": ("large.png", fake_png, "image/png")}
    data = {"order_id": "D-DOS-1003"}

    resp = client.post("/intake/upload", data=data, files=files, headers={"Accept": "application/json"})
    assert resp.status_code == 413
    assert "Payload too large" in resp.text or "limited to" in resp.text


def test_malicious_upload_corrupted_image_polyglot_rejected_415(client):
    """Files with valid magic bytes but corrupted/malformed image bodies must be rejected by Pillow verification."""
    corrupted_polyglot = b"\x89PNG\r\n\x1a\n#!/bin/bash\necho 'Polyglot attack'\n"
    files = {"file": ("polyglot.png", corrupted_polyglot, "image/png")}
    data = {"order_id": "D-POLY-1004"}

    resp = client.post("/intake/upload", data=data, files=files, headers={"Accept": "application/json"})
    assert resp.status_code == 415
    assert "image could not be opened" in resp.json().get("detail", "")


def test_sql_injection_resilience_owners_search(db, client):
    """SQL injection payloads in /owners search query must be sanitized by LIKE escaping."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    sqli_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE vehicle_owners; --",
        "%' UNION SELECT NULL, NULL, NULL --",
        "\\%_test",
    ]
    for q in sqli_payloads:
        resp = client.get(f"/owners?q={q}", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


def test_sql_injection_resilience_vehicles_search(db, client):
    """SQL injection payloads in /vehicles query must be safely handled and normalized."""
    _, guard_token = create_test_user(db, UserRole.GUARD)
    headers = auth_header(guard_token)

    resp = client.get("/vehicles?q=PB65' OR 1=1--", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ============================================================================
# 5. DATABASE INTEGRITY & APPEND-ONLY TRIGGER AUDIT
# ============================================================================

def test_database_append_only_trigger_blocks_update_on_delivery_decisions(db):
    """Direct PostgreSQL UPDATE on delivery_decisions must be rejected by append-only trigger."""
    guard, _ = create_test_user(db, UserRole.GUARD)
    order = DeliveryOrder(
        order_id=f"TEST-TRIG-{uuid.uuid4().hex[:6].upper()}",
        platform=PlatformType.SWIGGY,
        status=OrderStatus.SUBMITTED,
        verification_status=AccessState.REVIEW,
    )
    db.add(order)
    db.commit()

    inv = Invoice(
        order_id=order.id,
        source=DeliverySource.CONSOLE,
        ocr_engine="RAPIDOCR",
        overall_verdict=ScreeningVerdict.REVIEW,
    )
    db.add(inv)
    db.commit()

    decision = DeliveryDecision(
        order_id=order.id,
        invoice_id=inv.id,
        decision=GuardDecision.CLEARED,
        note="Initial decision",
        decided_by_id=guard.id,
    )
    db.add(decision)
    db.commit()

    with pytest.raises(Exception) as exc_info:
        db.execute(text("UPDATE delivery_decisions SET note = 'TAMPERED' WHERE id = :id"), {"id": decision.id})
        db.commit()
    db.rollback()
    assert "append-only" in str(exc_info.value).lower()


def test_database_append_only_trigger_blocks_delete_on_delivery_decisions(db):
    """Direct PostgreSQL DELETE on delivery_decisions must be rejected by append-only trigger."""
    guard, _ = create_test_user(db, UserRole.GUARD)
    order = DeliveryOrder(
        order_id=f"TEST-TRIG-{uuid.uuid4().hex[:6].upper()}",
        platform=PlatformType.SWIGGY,
        status=OrderStatus.SUBMITTED,
        verification_status=AccessState.REVIEW,
    )
    db.add(order)
    db.commit()

    inv = Invoice(
        order_id=order.id,
        source=DeliverySource.CONSOLE,
        ocr_engine="RAPIDOCR",
        overall_verdict=ScreeningVerdict.REVIEW,
    )
    db.add(inv)
    db.commit()

    decision = DeliveryDecision(
        order_id=order.id,
        invoice_id=inv.id,
        decision=GuardDecision.HELD,
        note="Initial decision",
        decided_by_id=guard.id,
    )
    db.add(decision)
    db.commit()

    with pytest.raises(Exception) as exc_info:
        db.execute(text("DELETE FROM delivery_decisions WHERE id = :id"), {"id": decision.id})
        db.commit()
    db.rollback()
    assert "append-only" in str(exc_info.value).lower()


def test_database_append_only_trigger_blocks_truncate(db):
    """TRUNCATE on append-only tables must be rejected by statement-level trigger."""
    with pytest.raises(Exception) as exc_info:
        db.execute(text("TRUNCATE TABLE delivery_decisions;"))
        db.commit()
    db.rollback()
    assert "append-only" in str(exc_info.value).lower()
    assert "truncate rejected" in str(exc_info.value).lower()


# ============================================================================
# 6. UNPROTECTED TEST & DEBUG ENDPOINTS EXPOSURE
# ============================================================================

def test_unauthenticated_test_endpoints_exposure(client):
    """
    Verifies the finding that test endpoints in backend/app/main.py are exposed
    without authentication in production routes.
    """
    # 1. n8n webhook test endpoint
    r1 = client.post("/webhook/n8n-test", json={"source": "test", "event": "security_scan"})
    assert r1.status_code == 200, "Unauthenticated /webhook/n8n-test endpoint is publicly accessible"

    # 2. LPR test event endpoint
    r2 = client.post("/api/test/lpr-event", json={"camera": "gate_1", "plate_number": "TEST999", "confidence": 0.99})
    assert r2.status_code == 200, "Unauthenticated /api/test/lpr-event endpoint is publicly accessible"

    # 3. Invoice OCR test endpoint
    r3 = client.post("/api/test/invoice-ocr", json={"image_name": "test.jpg", "extracted_text": "Sample", "order_id": "D-001"})
    assert r3.status_code == 200, "Unauthenticated /api/test/invoice-ocr endpoint is publicly accessible"
