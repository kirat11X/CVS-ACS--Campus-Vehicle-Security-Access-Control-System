"""
Comprehensive Edge Cases, Stress, and Resilience Tests for CVS-ACS.

Covers:
1. Malformed Plate Inputs & Normalization Stress:
   - Empty strings, whitespace-only, non-ASCII/Unicode, extreme lengths, missing state codes, special characters/injections.
   - Optical matcher confusion pairs (O/0, B/8, I/1, S/5, Z/2, G/6) and graceful similarity degradation.
2. Corrupted & Unusual Invoice Uploads:
   - 0-byte files, non-image files masquerading as PNG, corrupt image headers, oversized uploads.
   - Multi-page PDFs with missing totals, receipts with extreme currency amounts (> 1 crore).
   - Invoices with 0 line items and stress testing with 100+ line items.
3. Concurrency, Debounce & Observation Idempotency:
   - Simultaneous gate crossing events within MOVEMENT_DEBOUNCE_SECONDS.
   - Duplicate observation events with identical source_event_id.
   - Concurrent direction confirmation conflicts (409) and append-only correction logs.
4. Overstay Boundary Calculations:
   - Exact boundary behavior: 1.49 hours (no alert) vs 1.50/1.51 hours (HIGH severity alert).
   - Linked student immunity vs transient delivery alerts.
   - Idempotency over multiple query cycles.
5. Database Disconnect & Reconnect / MQTT Worker Resilience:
   - DB disconnect error handling in check_db_connection.
   - MQTT worker resilience during DB errors, malformed payloads, non-vehicle events, and unmapped cameras.
   - Disconnect and reconnect state transitions.
6. Transaction Integrity & Rollbacks:
   - Atomic rollback on partial member registration failure.
   - Atomic rollback on partial invoice creation failure.
   - Append-only enforcement on VehicleLinkEvent and ObservationResolution.
"""

import io
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import INVOICE_MAX_UPLOAD_MB, MOVEMENT_DEBOUNCE_SECONDS, UNLINKED_OVERSTAY_HOURS
from backend.app.db import check_db_connection
from backend.app.models.base import Base
from backend.app.models.delivery import DeliveryOrder, Invoice, InvoiceItem
from backend.app.models.enums import (
    GateDirection,
    LaneRole,
    LinkMethod,
    ObservationDirection,
    ObservationSource,
    ObservedVehicleType,
    PersonType,
    PlatformType,
    ResolutionOutcome,
    ScreeningVerdict,
    UserRole,
    VehicleCategory,
    VehicleStatus,
)
from backend.app.models.gate import EntryExitLog, Gate
from backend.app.models.identity import User, VehicleOwner
from backend.app.models.movement import CameraLane, VehicleLinkEvent
from backend.app.models.observation import ObservationEvent, ObservationFeedEvent, ObservationResolution
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.delivery import AlertItem
from backend.app.schemas.movement import InsideResponse, LinkedVehicle, MovementEntry, PresenceEntry
from backend.app.schemas.observation import GateSummary, ObservationCreate
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.alert_service import AlertService, alert_service
from backend.app.services.delivery_screening_service import DeliveryScreeningService
from backend.app.services.frigate_event_parser import FrigateEventParser
from backend.app.services.invoice_reader import ParsedInvoice, ParsedLine, parse_text, to_decimal
from backend.app.services.movement_service import MovementError, movement_service
from backend.app.services.observation_service import ObservationService
from backend.app.services.plate_normalizer import (
    ALL_VALID_STATES,
    format_plate_display,
    is_valid_indian_plate,
    normalize_plate,
)
from backend.app.services.plate_similarity import OCR_CONFUSION_PAIRS, plate_similarity, weighted_levenshtein
from backend.app.workers.frigate_mqtt_worker import FrigateMQTTWorker


# ==============================================================================
# In-Memory SQLite Fixtures for Isolated, Rapid, Network-Independent Resilience Testing
# ==============================================================================

_feed_id_seq = 0

@pytest.fixture(scope="function")
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_con, con_record):
        # Stub PostgreSQL functions in SQLite
        dbapi_con.create_function("pg_advisory_xact_lock", -1, lambda *args: 1)
        dbapi_con.create_function("hashtext", 1, lambda s: hash(s) % (2**31 - 1))

    @event.listens_for(ObservationFeedEvent, "before_insert")
    def set_feed_id(mapper, connection, target):
        global _feed_id_seq
        if target.id is None:
            _feed_id_seq += 1
            target.id = _feed_id_seq

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(sqlite_engine) -> Generator[Session, None, None]:
    connection = sqlite_engine.connect()
    session = Session(bind=connection)

    yield session

    session.close()
    connection.close()


@pytest.fixture
def test_gate_and_lane(test_db) -> Gate:
    gate = Gate(id="GATE_RESILIENCE", name="Resilience Gate North")
    lane = CameraLane(camera_id="cam_resilience_1", gate_id="GATE_RESILIENCE", lane_role=LaneRole.ENTRY_LANE)
    test_db.add_all([gate, lane])
    test_db.commit()
    return gate


@pytest.fixture
def test_admin_user(test_db) -> User:
    user = User(
        username="admin_tester",
        email="admin_tester@campus.edu",
        full_name="Admin Tester",
        role="ADMIN",
        hashed_password="hashed_test_pass"
    )
    test_db.add(user)
    test_db.commit()
    return user


# ==============================================================================
# 1. MALFORMED PLATE INPUTS & NORMALIZATION STRESS
# ==============================================================================

class TestMalformedPlateInputs:
    """Stress tests across plate normalizer, display formatter, statutory validator, and optical matcher."""

    def test_plate_normalizer_empty_and_whitespace(self):
        assert normalize_plate("") == ""
        assert normalize_plate("   ") == ""
        assert normalize_plate("\t\n\r  ") == ""
        assert format_plate_display("") == ""
        assert not is_valid_indian_plate("")
        assert not is_valid_indian_plate("   ")

    def test_plate_normalizer_non_ascii_and_unicode(self):
        # Devanagari numerals are non-ASCII, so canonical filter strips them safely
        assert normalize_plate("PB65AB१२३४") == "PB65AB"
        # Emojis are stripped safely
        assert normalize_plate("PB65🚗AB1234🏁") == "PB65AB1234"
        # Accented Latin characters
        assert normalize_plate("PB-65-ÁB-1234") == "PB65B1234"
        # Arabic or RTL scripts
        assert normalize_plate("مرحبا123") == "123"
        # Null bytes embedded inside plate strings
        assert normalize_plate("PB65AB\x001234") == "PB65AB1234"

    def test_plate_normalizer_extreme_lengths(self):
        long_plate_50 = "A" * 50
        long_plate_1000 = "PB65AB1234" * 100
        # Normalization should handle extreme lengths without regex backtracking or memory issues
        norm_50 = normalize_plate(long_plate_50)
        norm_1000 = normalize_plate(long_plate_1000)
        assert len(norm_50) == 50
        assert len(norm_1000) == 1000
        assert not is_valid_indian_plate(norm_50)
        assert not is_valid_indian_plate(norm_1000)

    def test_plate_normalizer_special_characters_and_injections(self):
        # Special punctuation
        assert normalize_plate("@#$%^&*()_+=-~`{}[]|:;'<>,.?/") == ""
        # SQL injection attempts
        sql_inj = "'; DROP TABLE vehicles; --"
        norm_sql = normalize_plate(sql_inj)
        assert norm_sql == "DROPTABLEVEHICLES"
        assert not is_valid_indian_plate(norm_sql)
        # XSS injection attempts
        xss_payload = '<script>alert("XSS")</script>'
        norm_xss = normalize_plate(xss_payload)
        assert norm_xss == "SCRIPTALERTXSSSCRIPT"
        assert not is_valid_indian_plate(norm_xss)

    def test_indian_plate_statutory_validation_boundaries(self):
        # Missing state code
        assert not is_valid_indian_plate("65AB1234")
        assert not is_valid_indian_plate("1234")
        # Invalid state code (ZZ is not an Indian state/UT)
        assert not is_valid_indian_plate("ZZ01AB1234")
        # Valid state codes (PB, DL, CH, KA, MH)
        assert is_valid_indian_plate("PB65AB1234")
        assert is_valid_indian_plate("DL01AB1234")
        assert is_valid_indian_plate("CH01A0001")
        assert is_valid_indian_plate("KA011234")  # Karnataka allows blank series
        # Single digit RTO outside Delhi is invalid
        assert not is_valid_indian_plate("PB1AB1234")
        # Single digit RTO in Delhi is valid
        assert is_valid_indian_plate("DL1AB1234")
        # Forbidden characters in series ('I' and 'O' are disallowed to avoid 1/0 confusion)
        assert not is_valid_indian_plate("DL01IB1234")
        assert not is_valid_indian_plate("DL01OB1234")
        # Number 0000 is disallowed
        assert not is_valid_indian_plate("DL01AB0000")
        # Bharat Series: 22 BH 1234 AA
        assert is_valid_indian_plate("22BH1234AA")
        # BH series before 2021 is invalid (started in 2021)
        assert not is_valid_indian_plate("19BH1234AA")
        # Diplomatic format: 17 CD 1234
        assert is_valid_indian_plate("17CD1234")
        # Military format: 21A123456B
        assert is_valid_indian_plate("21A123456B")

    def test_plate_display_formatting_fallback(self):
        # Known valid patterns
        assert format_plate_display("PB65AB1234") == "PB 65 AB 1234"
        assert format_plate_display("22BH1234AA") == "22 BH 1234 AA"
        assert format_plate_display("KA011234") == "KA 01 1234"
        # Non-standard or malformed string falls back to clean normalized string without error
        assert format_plate_display("INVALID123XYZ") == "INVALID123XYZ"
        assert format_plate_display("A" * 60) == "A" * 60

    def test_optical_matcher_similarity_and_levenshtein(self):
        # Empty string handling
        assert plate_similarity("", "") == 1.0
        assert plate_similarity("DL01AB1234", "") == 0.0
        assert plate_similarity("", "DL01AB1234") == 0.0
        # Exact match
        assert plate_similarity("DL01AB1234", "dl01ab1234") == 1.0

        # OCR Confusion pairs: O vs 0, B vs 8, I vs 1
        # In weighted_levenshtein, OCR confusion penalty is 0.25 vs default 1.0
        dist_ocr_conf = weighted_levenshtein("DL01AB1234", "DLO1AB1234")
        dist_random_sub = weighted_levenshtein("DL01AB1234", "DLX1AB1234")
        assert dist_ocr_conf == 0.25
        assert dist_random_sub == 1.0
        # Similarity should be significantly higher for OCR confusion than random substitution
        sim_ocr = plate_similarity("DL01AB1234", "DLO1AB1234")
        sim_rand = plate_similarity("DL01AB1234", "DLX1AB1234")
        assert sim_ocr > sim_rand

        # Extreme length comparisons should not overflow or crash
        assert plate_similarity("A" * 200, "A" * 200) == 1.0
        assert plate_similarity("A" * 200, "B" * 200) == 0.0


# ==============================================================================
# 2. CORRUPTED & UNUSUAL INVOICE UPLOADS
# ==============================================================================

class TestCorruptedAndUnusualInvoiceUploads:
    """Stress tests for file intake validation, corrupted headers, and unusual invoice layouts."""

    @pytest.fixture
    def screening_service(self):
        return DeliveryScreeningService()

    def test_invoice_upload_zero_byte_file(self, screening_service):
        with pytest.raises(HTTPException) as exc_info:
            screening_service.store_upload(b"")
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.detail.lower()

    def test_invoice_upload_non_image_file_renamed_as_png(self, screening_service):
        plain_text_payload = b"Hello, this is a plain text file pretending to be an invoice."
        with pytest.raises(HTTPException) as exc_info:
            screening_service.store_upload(plain_text_payload)
        assert exc_info.value.status_code == 415
        assert "Send the invoice as a JPG, PNG, WEBP photo or a PDF" in exc_info.value.detail

    def test_invoice_upload_corrupted_image_magic_bytes(self, screening_service):
        # Starts with PNG magic header but has corrupted invalid body
        corrupt_png_payload = b"\x89PNG\r\n\x1a\nCorruptRandomGarbageBody12345"
        with pytest.raises(HTTPException) as exc_info:
            screening_service.store_upload(corrupt_png_payload)
        assert exc_info.value.status_code == 415
        assert "The image could not be opened" in exc_info.value.detail

    def test_invoice_upload_oversized_payload(self, screening_service):
        # INVOICE_MAX_UPLOAD_MB is 10 MB
        oversized_bytes = b"0" * int((INVOICE_MAX_UPLOAD_MB + 1) * 1024 * 1024)
        with pytest.raises(HTTPException) as exc_info:
            screening_service.store_upload(oversized_bytes)
        assert exc_info.value.status_code == 413
        assert "limited to" in exc_info.value.detail

    def test_invoice_pdf_corrupt_header(self, screening_service):
        invalid_pdf_data = b"NOT_A_PDF_HEADER_DATA"
        with pytest.raises(HTTPException) as exc_info:
            screening_service.store_upload(invalid_pdf_data)
        assert exc_info.value.status_code == 415

    def test_invoice_screening_multi_page_missing_total(self, screening_service):
        # Multi-page invoice where total was on page 2 and missing from page 1 read
        text_missing_total = """
        Campus Canteen
        Order ID: ORD-MISSING-01
        Items                  Qty    Amount
        1  Paneer Butter Masala 1     240.00
        2  Garlic Naan          3     150.00
        """
        parsed = parse_text(text_missing_total)
        result = screening_service.screen(parsed, "ORD-MISSING-01")

        assert parsed.total is None
        assert result.totals_match is None
        # Rule: When total cannot be confirmed, overall verdict is at least REVIEW
        assert result.overall == ScreeningVerdict.REVIEW
        reply = screening_service.reply_text("ORD-MISSING-01", result)
        assert "No invoice total could be read" in reply

    def test_invoice_extreme_currency_amounts(self, screening_service):
        # Invoices with amounts > 1 crore (e.g. ₹15,000,000.00 and ₹50,000,000.00)
        text_extreme_currency = """
        Institutional Procurement Dept
        Order ID: ORD-EXTREME-01
        Items                         Qty    Amount
        1  Industrial Lab Equipment    1  15000000.00
        2  Enterprise Server Rack      2  35000000.00
        Subtotal                          50000000.00
        Total                             50000000.00
        """
        parsed = parse_text(text_extreme_currency)
        assert len(parsed.lines) == 2
        assert parsed.lines[0].amount == Decimal("15000000.00")
        assert parsed.total == Decimal("50000000.00")

        result = screening_service.screen(parsed, "ORD-EXTREME-01")
        assert result.computed_total == Decimal("50000000.00")
        assert result.totals_match is True
        # Unknown/procurement items default to REVIEW
        assert result.overall == ScreeningVerdict.REVIEW

    def test_invoice_zero_line_items_graceful_degradation(self, screening_service):
        # Blank or unreadable invoice with header only
        text_zero_items = """
        Vendor Header Only
        Order ID: ORD-ZERO-01
        Thank you for your visit!
        """
        parsed = parse_text(text_zero_items)
        assert len(parsed.lines) == 0

        result = screening_service.screen(parsed, "ORD-ZERO-01")
        assert result.overall == ScreeningVerdict.REVIEW
        reply = screening_service.reply_text("ORD-ZERO-01", result)
        assert "no item lines could be read" in reply.lower()

    def test_invoice_stress_100_plus_line_items(self, screening_service):
        # Large multi-item invoice with 120 items
        item_count = 120
        raw_rows = ["Mega Campus Superstore", "Order ID: ORD-CENTURY-120"]
        for i in range(1, item_count + 1):
            raw_rows.append(f"{i}  Burger  1  50.00")
        expected_total = item_count * 50
        raw_rows.append(f"Subtotal {expected_total:.2f}")
        raw_rows.append(f"Total {expected_total:.2f}")

        parsed = parse_text("\n".join(raw_rows))
        assert len(parsed.lines) == item_count
        assert parsed.total == Decimal(f"{expected_total:.2f}")

        result = screening_service.screen(parsed, "ORD-CENTURY-120")
        assert result.computed_total == Decimal(f"{expected_total:.2f}")
        assert result.totals_match is True
        # All items are burgers (FOOD_OK), so entire 120-item order is ALLOWed
        assert result.overall == ScreeningVerdict.ALLOW
        assert "all 120 lines look fine" in screening_service.reply_text("ORD-CENTURY-120", result).lower()


# ==============================================================================
# 3. CONCURRENCY, DEBOUNCE & OBSERVATION IDEMPOTENCY
# ==============================================================================

class TestConcurrencyAndDebounce:
    """Stress tests for simultaneous crossings, debounce windows, duplicate events, and direction conflict resolution."""

    def test_simultaneous_gate_crossing_within_debounce_window(self, test_db, test_gate_and_lane):
        now = datetime.now(timezone.utc)
        gate_id = test_gate_and_lane.id

        # First observation at t=0s
        obs_1 = ObservationEvent(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="evt_debounce_1",
            raw_plate="DL01AB1111",
            normalized_plate="DL01AB1111",
            observed_at=now,
            direction=ObservationDirection.UNKNOWN
        )
        test_db.add(obs_1)
        test_db.commit()

        mov_1 = movement_service.on_observation(test_db, obs_1)
        test_db.commit()
        assert mov_1 is not None, "Initial crossing must create a movement record"
        assert mov_1.direction == GateDirection.ENTRY

        # Second observation at t=15s (within MOVEMENT_DEBOUNCE_SECONDS = 60s) for SAME plate, gate, direction
        obs_2 = ObservationEvent(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="evt_debounce_2",
            raw_plate="DL01AB1111",
            normalized_plate="DL01AB1111",
            observed_at=now + timedelta(seconds=15),
            direction=ObservationDirection.UNKNOWN
        )
        test_db.add(obs_2)
        test_db.commit()

        mov_2 = movement_service.on_observation(test_db, obs_2)
        test_db.commit()
        assert mov_2 is None, "Simultaneous observation within debounce window must be suppressed"

        # Third observation at t=75s (> MOVEMENT_DEBOUNCE_SECONDS = 60s)
        obs_3 = ObservationEvent(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="evt_debounce_3",
            raw_plate="DL01AB1111",
            normalized_plate="DL01AB1111",
            observed_at=now + timedelta(seconds=75),
            direction=ObservationDirection.UNKNOWN
        )
        test_db.add(obs_3)
        test_db.commit()

        mov_3 = movement_service.on_observation(test_db, obs_3)
        test_db.commit()
        assert mov_3 is not None, "Observation after debounce window expiration must create a movement record"
        assert mov_3.id != mov_1.id

    def test_duplicate_observation_event_idempotency(self, test_db, test_gate_and_lane):
        gate_id = test_gate_and_lane.id

        # First event payload
        c1 = ObservationCreate(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="frigate_idem_unique_99",
            raw_plate="PB65AB9999",
            plate_confidence=0.72,
            vehicle_type=ObservedVehicleType.CAR
        )
        obs1 = ObservationService.create_or_update_observation(test_db, c1)

        # Duplicate event with same source_event_id and refined OCR confidence
        c2 = ObservationCreate(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="frigate_idem_unique_99",
            raw_plate="PB65AB9999",
            plate_confidence=0.96,
            vehicle_type=ObservedVehicleType.CAR
        )
        obs2 = ObservationService.create_or_update_observation(test_db, c2)

        # Observations must be identical row (idempotent upsert), not duplicate entries
        assert obs1.id == obs2.id
        assert obs2.plate_confidence == 0.96

        count = (
            test_db.query(ObservationEvent)
            .filter_by(source_event_id="frigate_idem_unique_99")
            .count()
        )
        assert count == 1, "Duplicate source_event_id must not create duplicate database rows"

    def test_concurrent_direction_confirmation_and_correction(self, test_db, test_gate_and_lane, test_admin_user):
        gate_id = test_gate_and_lane.id
        now = datetime.now(timezone.utc)

        obs = ObservationEvent(
            gate_id=gate_id,
            camera_id="cam_resilience_1",
            source=ObservationSource.FRIGATE,
            source_event_id="evt_dir_conflict",
            raw_plate="HR26DK5555",
            normalized_plate="HR26DK5555",
            observed_at=now,
            direction=ObservationDirection.UNKNOWN
        )
        test_db.add(obs)
        test_db.commit()

        # Ingestion creates movement via camera lane role
        root_mov = movement_service.on_observation(test_db, obs)
        test_db.commit()
        assert root_mov is not None

        # Guard attempting confirm_direction on an observation that already has a movement must get 409
        with pytest.raises(MovementError) as exc_409:
            movement_service.confirm_direction(test_db, obs.id, "EXIT", "Confirmed exit", test_admin_user.id)
        assert exc_409.value.status_code == 409
        assert "already has a movement record" in exc_409.value.detail

        # Correcting direction via append-only correction row
        corrected = movement_service.correct(
            test_db, root_mov.id, direction="EXIT", plate=None, note="Guard correction", user_id=test_admin_user.id
        )
        assert corrected.effective.direction == GateDirection.EXIT

        # No-op correction must be rejected with 400
        with pytest.raises(MovementError) as exc_noop:
            movement_service.correct(
                test_db, root_mov.id, direction="EXIT", plate=None, note="No-op", user_id=test_admin_user.id
            )
        assert exc_noop.value.status_code == 400

        # Blank/empty plate in correction must be rejected with 400
        with pytest.raises(MovementError) as exc_blank:
            movement_service.correct(
                test_db, root_mov.id, direction=None, plate="   ", note="Blank plate", user_id=test_admin_user.id
            )
        assert exc_blank.value.status_code == 400


# ==============================================================================
# 4. OVERSTAY BOUNDARY CALCULATIONS
# ==============================================================================

class TestOverstayBoundaryCalculations:
    """Stress tests for exact boundary thresholds: 1.49h vs 1.50h vs 1.51h, linkage immunity, and idempotency."""

    @pytest.fixture
    def alert_svc(self):
        return AlertService()

    def _make_presence_entry(self, plate: str, hours_ago: float, linked: bool = False, category: str = "UNKNOWN", owner=None):
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=hours_ago)
        return PresenceEntry(
            subject=plate,
            status="INSIDE",
            normalized_plate=plate,
            linked=linked,
            vehicle=LinkedVehicle(
                id=uuid.uuid4(), plate=plate, raw_plate=plate, category=category, status="ACTIVE", is_active=True, registry_status="ACTIVE"
            ) if linked else None,
            owner=owner,
            inside_since=entry_time,
            last_movement=MovementEntry(
                id=uuid.uuid4(),
                gate=GateSummary(id="GATE_NORTH", name="North Gate"),
                timestamp=entry_time,
                direction="ENTRY",
                direction_method="CAMERA_ROLE",
                plate=plate,
                normalized_plate=plate,
                linked=linked,
            )
        )

    def test_overstay_boundary_exactly_149_vs_150_vs_151_hours(self, alert_svc):
        # 1.49 hours inside (< 1.5h threshold): MUST NOT trigger alert
        e_149 = self._make_presence_entry("DL01AB1490", hours_ago=1.49, linked=False)
        # 1.50 hours inside (== 1.5h threshold): MUST trigger alert (>= threshold)
        e_150 = self._make_presence_entry("DL01AB1500", hours_ago=1.50, linked=False)
        # 1.51 hours inside (> 1.5h threshold): MUST trigger alert
        e_151 = self._make_presence_entry("DL01AB1510", hours_ago=1.51, linked=False)

        mock_db = MagicMock()
        with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
            mock_inside.return_value = InsideResponse(
                total=3, items=[e_149, e_150, e_151], unattributed_entries=[]
            )
            alerts = alert_svc.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

        alert_plates = [a.ref for a in alerts]
        assert "DL01AB1490" not in alert_plates, "1.49 hours must not cross the 1.5h threshold"
        assert "DL01AB1500" in alert_plates, "1.50 hours must trigger an alert"
        assert "DL01AB1510" in alert_plates, "1.51 hours must trigger an alert"

        # Check alert properties
        a_151 = next(a for a in alerts if a.ref == "DL01AB1510")
        assert a_151.kind == "OVERSTAY_UNLINKED"
        assert a_151.severity == "HIGH"
        assert "GATE_NORTH" in a_151.detail

    def test_linked_student_immunity_from_unlinked_overstay(self, alert_svc):
        # Registered student vehicle inside for 5 hours must NOT trigger an unlinked overstay alert
        student_owner = OwnerContextResponse(
            id=str(uuid.uuid4()),
            institutional_id="24103042",
            name="Regular Student",
            person_type="STUDENT",
            status="ACTIVE"
        )
        student_entry = self._make_presence_entry(
            "CH01AB3333", hours_ago=5.0, linked=True, category="STUDENT", owner=student_owner
        )

        mock_db = MagicMock()
        with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
            mock_inside.return_value = InsideResponse(total=1, items=[student_entry], unattributed_entries=[])
            alerts = alert_svc.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

        assert len(alerts) == 0, "Linked student vehicles must be immune from unlinked overstay alerts"

    def test_transient_delivery_overstay_triggers(self, alert_svc):
        # Transient delivery vehicle inside for 2.0 hours (> 1.5h threshold) must trigger alert even if linked
        delivery_entry = self._make_presence_entry(
            "DL01DL8888", hours_ago=2.0, linked=True, category="DELIVERY"
        )

        mock_db = MagicMock()
        with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
            mock_inside.return_value = InsideResponse(total=1, items=[delivery_entry], unattributed_entries=[])
            alerts = alert_svc.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

        assert len(alerts) == 1
        assert "Delivery vehicle" in alerts[0].title
        assert alerts[0].severity == "HIGH"

    def test_overstay_alerts_idempotent_multiple_calls(self, alert_svc):
        entry = self._make_presence_entry("PB65AB9999", hours_ago=2.2, linked=False)
        mock_db = MagicMock()

        with patch("backend.app.services.alert_service.movement_service.inside") as mock_inside:
            mock_inside.return_value = InsideResponse(total=1, items=[entry], unattributed_entries=[])
            alerts_run_1 = alert_svc.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)
            alerts_run_2 = alert_svc.unlinked_overstay_alerts(mock_db, threshold_hours=1.5)

        assert len(alerts_run_1) == len(alerts_run_2) == 1
        assert alerts_run_1[0].ref == alerts_run_2[0].ref == "PB65AB9999"


# ==============================================================================
# 5. DATABASE DISCONNECT & RECONNECT / MQTT WORKER RESILIENCE
# ==============================================================================

class TestDatabaseDisconnectAndMQTTWorkerResilience:
    """Stress tests verifying system resilience when DB or MQTT connections fail."""

    def test_db_disconnect_check_db_connection_resilience(self):
        # Simulate PostgreSQL connection failure (e.g. server down or pool exhausted)
        with patch("backend.app.db.engine.connect", side_effect=OperationalError("Connection refused", None, None)):
            res = check_db_connection()
            assert res["status"] == "error"
            assert "Connection refused" in res["detail"]

    def test_mqtt_worker_database_failure_resilience(self):
        worker = FrigateMQTTWorker()
        mock_db = MagicMock()
        # Simulate database session crash during flush/commit
        mock_db.flush.side_effect = OperationalError("Database dropped connection", None, None)

        payload = {
            "after": {
                "id": "evt_crash_sim",
                "camera": "cam_resilience_1",
                "label": "car",
                "license_plate": "DL01AB9999"
            }
        }

        with patch.object(FrigateEventParser, "resolve_camera_to_gate", return_value=Gate(id="GATE_1")):
            obs = worker.process_payload(payload, db=mock_db)

        # Worker must catch error, rollback session, update error stats, and return None without crashing
        assert obs is None
        mock_db.rollback.assert_called_once()
        assert worker.stats["errors"] == 1

    def test_mqtt_worker_malformed_json_payload(self):
        worker = FrigateMQTTWorker()
        obs = worker.process_payload("INVALID_NOT_JSON{{{")
        assert obs is None
        assert worker.stats["malformed_payloads"] == 1

    def test_mqtt_worker_non_vehicle_event_ignored(self):
        worker = FrigateMQTTWorker()
        mock_db = MagicMock()
        payload = {
            "after": {
                "id": "evt_pedestrian",
                "camera": "cam_resilience_1",
                "label": "person",
            }
        }
        obs = worker.process_payload(payload, db=mock_db)
        assert obs is None
        assert worker.stats["non_vehicle_events"] == 1

    def test_mqtt_worker_unmapped_camera_handled(self):
        worker = FrigateMQTTWorker()
        mock_db = MagicMock()
        payload = {
            "after": {
                "id": "evt_unmapped",
                "camera": "cam_unknown_999",
                "label": "car",
            }
        }
        with patch.object(FrigateEventParser, "resolve_camera_to_gate", return_value=None):
            obs = worker.process_payload(payload, db=mock_db)
        assert obs is None
        assert worker.stats["unmapped_cameras"] == 1

    def test_mqtt_worker_disconnect_reconnect_callbacks(self):
        worker = FrigateMQTTWorker()
        worker._setup_client()

        # Simulate disconnect event
        worker._on_disconnect(client=MagicMock(), userdata=None, disconnect_flags=None, reason_code=7)
        assert not worker.is_connected()

        # Simulate connect event
        mock_client = MagicMock()
        worker._on_connect(client=mock_client, userdata=None, flags=None, rc=0)
        assert worker.is_connected()
        mock_client.subscribe.assert_called_with("frigate/events")


# ==============================================================================
# 6. TRANSACTION INTEGRITY & ROLLBACKS
# ==============================================================================

class TestTransactionIntegrityAndRollbacks:
    """Tests guaranteeing partial failures cleanly roll back and append-only constraints are enforced."""

    def test_transaction_rollback_partial_member_registration(self, test_db, test_admin_user):
        admin_id = test_admin_user.id

        # Attempt atomic registration of member + 2 vehicles where 2nd vehicle fails unique plate constraint
        try:
            with test_db.begin_nested():
                owner = VehicleOwner(
                    identifier="24109999",
                    full_name="Atomic Rollback Student",
                    person_type=PersonType.STUDENT,
                    status="ACTIVE",
                    created_by_id=admin_id
                )
                test_db.add(owner)
                test_db.flush()

                v1 = Vehicle(
                    raw_plate="DL01AB7771",
                    normalized_plate="DL01AB7771",
                    owner_id=owner.id,
                    vehicle_category=VehicleCategory.STUDENT,
                    status=VehicleStatus.ACTIVE
                )
                test_db.add(v1)
                test_db.flush()

                # Duplicate normalized plate causes IntegrityError
                v2 = Vehicle(
                    raw_plate="DL01AB7771",
                    normalized_plate="DL01AB7771",
                    owner_id=owner.id,
                    vehicle_category=VehicleCategory.STUDENT,
                    status=VehicleStatus.ACTIVE
                )
                test_db.add(v2)
                test_db.flush()
        except IntegrityError:
            test_db.rollback()

        # Verify that atomic rollback prevented partial registration: neither the owner nor v1 exist
        persisted_owner = test_db.query(VehicleOwner).filter_by(identifier="24109999").first()
        persisted_v1 = test_db.query(Vehicle).filter_by(normalized_plate="DL01AB7771").first()
        assert persisted_owner is None, "Rollback must remove orphaned owner record"
        assert persisted_v1 is None, "Rollback must remove orphaned vehicle record"

    def test_transaction_rollback_partial_invoice_creation(self, test_db):
        # Attempt invoice creation where an item causes failure
        try:
            with test_db.begin_nested():
                order = DeliveryOrder(
                    order_id="ORD-ATOMIC-FAIL",
                    platform=PlatformType.ZOMATO
                )
                test_db.add(order)
                test_db.flush()

                inv = Invoice(
                    order_id=order.id,
                    vendor="Atomic Food",
                    total_amount=Decimal("500.00")
                )
                test_db.add(inv)
                test_db.flush()

                # Simulate a database constraint failure or invalid data
                item_bad = InvoiceItem(
                    invoice_id=inv.id,
                    item_name="Valid Food",
                    total_price=Decimal("500.00")
                )
                test_db.add(item_bad)
                test_db.flush()

                # Force an explicit failure / rollback
                raise RuntimeError("Simulated mid-transaction failure during item processing")
        except RuntimeError:
            test_db.rollback()

        # Ensure no orphaned invoice or delivery order remains
        persisted_order = test_db.query(DeliveryOrder).filter_by(order_id="ORD-ATOMIC-FAIL").first()
        persisted_invoice = test_db.query(Invoice).filter_by(vendor="Atomic Food").first()
        assert persisted_order is None
        assert persisted_invoice is None

    def test_append_only_integrity_vehicle_link_events(self, test_db, test_admin_user):
        owner = VehicleOwner(
            identifier="24103055", full_name="Student Links", person_type=PersonType.STUDENT, status="ACTIVE", created_by_id=test_admin_user.id
        )
        veh = Vehicle(
            raw_plate="DL01AB4444", normalized_plate="DL01AB4444", vehicle_category=VehicleCategory.STUDENT, status=VehicleStatus.ACTIVE
        )
        test_db.add_all([owner, veh])
        test_db.commit()

        link = VehicleLinkEvent(
            vehicle_id=veh.id,
            owner_id=owner.id,
            method=LinkMethod.ADMIN,
            evidence_note="Original verified assertion",
            linked_by_id=test_admin_user.id
        )
        test_db.add(link)
        test_db.commit()

        # Update must be rejected
        with pytest.raises(ValueError) as exc_update:
            link.evidence_note = "Tampered Note"
            test_db.flush()
        test_db.rollback()
        assert "append-only" in str(exc_update.value)

        # Delete must be rejected
        link = test_db.query(VehicleLinkEvent).filter_by(id=link.id).one()
        with pytest.raises(ValueError) as exc_delete:
            test_db.delete(link)
            test_db.flush()
        test_db.rollback()
        assert "append-only" in str(exc_delete.value)

    def test_append_only_integrity_observation_resolutions(self, test_db, test_admin_user, test_gate_and_lane):
        obs = ObservationEvent(
            gate_id=test_gate_and_lane.id,
            source=ObservationSource.MANUAL,
            raw_plate="DL01AB8888",
            normalized_plate="DL01AB8888"
        )
        test_db.add(obs)
        test_db.commit()

        res = ObservationResolution(
            observation_id=obs.id,
            outcome=ResolutionOutcome.NONE_OF_THESE,
            chosen_vehicle_id=None,
            created_by_id=test_admin_user.id
        )
        test_db.add(res)
        test_db.commit()

        # Update must be rejected
        with pytest.raises(ValueError) as exc_update:
            res.note = "Tampered note"
            test_db.flush()
        test_db.rollback()
        assert "append-only" in str(exc_update.value)

        # Delete must be rejected
        res = test_db.query(ObservationResolution).filter_by(id=res.id).one()
        with pytest.raises(ValueError) as exc_delete:
            test_db.delete(res)
            test_db.flush()
        test_db.rollback()
        assert "append-only" in str(exc_delete.value)
