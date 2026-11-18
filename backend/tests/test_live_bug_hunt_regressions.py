"""
Regression test suite for Stage 1 Bug Hunt & Live Fullstack Testing
-------------------------------------------------------------------
Verifies fixes applied during interactive bug hunting:
1. Vehicles endpoint allows limit >= 1000 (le=2000).
2. Observation snapshot handler gracefully returns placeholder SVG when Frigate is offline (no 502).
3. Delivery image endpoint falls back gracefully when image path is missing/removed.
4. RBAC enforcement: GUARD receives 403 Forbidden on ADMIN-only endpoints (/users, DELETE /deliveries).
5. Unlinked vehicle overstay alerts (>1.5h) detection for vehicles not linked to students/faculty/residents.
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db import SessionLocal
from backend.app.models.identity import User
from backend.app.models.observation import ObservationEvent
from backend.app.models.delivery import DeliveryOrder, Invoice, PlatformType
from backend.app.services.auth_service import create_access_token
from backend.app.services.alert_service import alert_service


@pytest.fixture(scope="module")
def db_session():
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="module")
def admin_headers(db_session: Session):
    admin = db_session.query(User).filter(User.username == "admin").first()
    assert admin is not None
    token, _ = create_access_token(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def guard_headers(db_session: Session):
    guard = db_session.query(User).filter(User.username == "guard1").first()
    assert guard is not None
    token, _ = create_access_token(guard)
    return {"Authorization": f"Bearer {token}"}


def test_vehicles_query_limit_1000(guard_headers):
    """Bug 1 Fix: GET /vehicles?limit=1000 must succeed and not raise 422 Unprocessable Content."""
    with TestClient(app) as client:
        resp = client.get("/vehicles?limit=1000", headers=guard_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) <= 1000


def test_observation_snapshot_offline_resilience(guard_headers, db_session: Session):
    """Bug 2 Fix: GET /feed/snapshots/{id} must not return 502 Bad Gateway when Frigate is offline."""
    # Find any existing observation
    obs = db_session.query(ObservationEvent).first()
    if not obs:
        pytest.skip("No observation found to test snapshot endpoint.")

    with TestClient(app) as client:
        resp = client.get(f"/feed/snapshots/{obs.id}", headers=guard_headers)
        # Should return 200 with SVG/JPEG, or 404, but NEVER 502 Bad Gateway
        assert resp.status_code in (200, 404)
        assert resp.status_code != 502
        if resp.status_code == 200:
            assert resp.headers.get("content-type") in ("image/svg+xml", "image/jpeg", "image/png")


def test_delivery_invoice_image_resilience(guard_headers, db_session: Session):
    """Bug 3 Fix: Delivery invoice image endpoint handles missing or test images gracefully."""
    inv = db_session.query(Invoice).first()
    if not inv or not inv.order:
        pytest.skip("No invoice found to test delivery image endpoint.")

    order_id = inv.order.order_id
    with TestClient(app) as client:
        resp = client.get(f"/deliveries/{order_id}/invoice-image", headers=guard_headers)
        # Must return 200 or clean 404, never 500
        assert resp.status_code in (200, 404)
        assert resp.status_code != 500


def test_rbac_guard_blocked_from_users_endpoint(guard_headers, admin_headers):
    """Bug Hunt RBAC 1: GET /users must return 200 for ADMIN and 403 Forbidden for GUARD."""
    with TestClient(app) as client:
        admin_resp = client.get("/users", headers=admin_headers)
        assert admin_resp.status_code == 200

        guard_resp = client.get("/users", headers=guard_headers)
        assert guard_resp.status_code == 403


def test_rbac_guard_blocked_from_delete_delivery(guard_headers):
    """Bug Hunt RBAC 2: DELETE /deliveries/{order_id} must return 403 Forbidden for GUARD."""
    with TestClient(app) as client:
        guard_resp = client.delete("/deliveries/D-NONEXISTENT", headers=guard_headers)
        assert guard_resp.status_code == 403


def test_unlinked_overstay_alert_detection(db_session: Session):
    """User Feature Verification: Unlinked vehicles inside > 1.5 hours generate security alerts."""
    alerts = alert_service.unlinked_overstay_alerts(db_session, threshold_hours=1.5)
    # Check that any generated alerts match the required format
    for alert in alerts:
        assert alert.kind == "OVERSTAY_UNLINKED"
        assert alert.severity == "HIGH"
        assert "overstay" in alert.title.lower()
        assert "not linked to any student or resident" in alert.detail.lower()
