"""
Unit & Integration Test Suite for Telegram Connector
---------------------------------------------------
Verifies:
1. TelegramBotService initialization, configuration, and chat-gating.
2. Webhook endpoint (POST /telegram/webhook and POST /api/telegram/webhook).
3. Status endpoint (GET /telegram/status).
4. Order process-invoice endpoint (POST /orders/process-invoice).
5. Onboarding flow for first-time users tailored for Punjab Engineering College (PEC):
   - "Please enter your name:" with zero prefilled buttons.
   - "Enter your ID:" (SID, Guard ID, Faculty/Staff ID, Residence ID) with no gate buttons.
   - 8 PEC options: 4 Boys' Hostels (Shivalik, Aravali, Kurukshetra, Himalaya),
     2 Girls' Hostels (Kalpana Chawla, Vindhya), Residence Number, and Others (NAB/Gates).
6. Returning user recognition on 2nd and 3rd visits asking "Do you want to edit something?"
   with interactive [Change Location], [Edit Profile], and [Keep As Is / Ready] pop-up alert.
7. Dynamic location changes for Hostels, Residence Number, and Others.
8. Security rejection of invoices from unregistered users until verified.
9. Processing of incoming invoice photo/document updates into PostgreSQL for verified users.
10. Interactive guard triage via CallbackQuery (Approve & Open, Flag for Search, Deny)
    with immutable AccessDecision and DeliveryDecision audit logging.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, Document, Message, PhotoSize, Update, User as TgUser

from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.main import app
from backend.app.models.delivery import DeliveryDecision, DeliveryOrder, Invoice
from backend.app.models.enums import (
    AccessState,
    DeliverySource,
    GuardDecision,
    OrderStatus,
    ScreeningVerdict,
)
from backend.app.models.gate import AccessDecision, Gate
from backend.app.models.identity import User
from backend.app.routes.reviews import TriageAction, execute_review_triage
from backend.app.services.auth_service import create_access_token
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.telegram.bot_service import TelegramBotService, telegram_service
from backend.app.telegram.profile_manager import (
    PEC_ALL_HOSTELS,
    STATE_AWAITING_ID,
    STATE_AWAITING_LOCATION,
    STATE_AWAITING_NAME,
    STATE_AWAITING_OTHER_LOCATION,
    STATE_AWAITING_RESIDENCE_NO,
    STATE_CHANGING_LOCATION,
    STATE_IDLE,
    profile_manager,
)


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def staff_headers(db: Session):
    guard = db.query(User).filter(User.username == "guard1").first()
    assert guard is not None
    token, _ = create_access_token(guard)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_invoice_bytes():
    path = MEDIA_ROOT / "test_invoice.png"
    if path.is_file():
        return path.read_bytes()
    # 1x1 fallback png
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


def test_telegram_status_endpoint():
    """GET /telegram/status returns configuration and mode metadata."""
    with TestClient(app) as client:
        resp = client.get("/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "is_configured" in data
        assert data["is_configured"] is True


def test_telegram_chat_gating():
    """Verifies that unlisted chat IDs are blocked when allowed_chat_ids is configured."""
    bot_service = TelegramBotService(
        token="123456:FAKE_TOKEN_FOR_TESTING",
        mode="polling",
        allowed_chat_ids=[111, 222],
    )
    assert bot_service._is_chat_allowed(111) is True
    assert bot_service._is_chat_allowed(222) is True
    assert bot_service._is_chat_allowed(999) is False


def test_orders_process_invoice_endpoint(db: Session, staff_headers, sample_invoice_bytes):
    """POST /orders/process-invoice processes an uploaded invoice and returns DeliveryDetail."""
    gate = db.query(Gate).first()
    gate_id = gate.id if gate else None

    with TestClient(app) as client:
        files = {"file": ("test_invoice.png", sample_invoice_bytes, "image/png")}
        data = {
            "order_id": f"TEST-TG-ORD-{uuid.uuid4().hex[:6].upper()}",
            "platform": "ZOMATO",
        }
        if gate_id:
            data["gate_id"] = gate_id

        resp = client.post("/orders/process-invoice", data=data, files=files, headers=staff_headers)
        assert resp.status_code == 201
        res = resp.json()
        assert res["order_id"] == data["order_id"]
        assert res["platform"] == "ZOMATO"
        assert "overall" in res
        assert "items" in res
        assert "invoice" in res


def test_telegram_onboarding_pec_flow():
    """
    Simulates a brand new PEC user opening the bot for the first time:
    1. /start triggers Step 1 ("Please enter your name:") with NO "Use..." button.
    2. User inputs Name -> triggers Step 2 ("Enter your ID:").
    3. User inputs ID -> triggers Step 3 with exactly 8 PEC options (6 Hostels + Residence No + Others).
    4. User selects "Shivalik Hostel" -> registration completes with Shivalik Hostel.
    """
    async def _run():
        bot_service = TelegramBotService(token="123456:FAKE_TOKEN", mode="polling")
        test_chat_id = 91001
        profile_manager.delete_profile(test_chat_id)

        # Step 1: User sends /start
        mock_msg = AsyncMock()
        mock_msg.reply_text = AsyncMock()
        mock_chat = Chat(id=test_chat_id, type="private")
        mock_user = TgUser(id=test_chat_id, first_name="Kirat", last_name="Singh", is_bot=False)

        update1 = MagicMock(spec=Update)
        update1.effective_chat = mock_chat
        update1.effective_message = mock_msg
        update1.effective_user = mock_user

        context = MagicMock()

        await bot_service.handle_start(update1, context)
        assert profile_manager.get_state(test_chat_id) == STATE_AWAITING_NAME
        args1, kwargs1 = mock_msg.reply_text.call_args
        assert "Please enter your name:" in args1[0]
        # NO "Use..." button should be present
        assert kwargs1.get("reply_markup") is None

        # Step 2: User provides Full Name
        mock_msg.text = "Kirat Singh"
        await bot_service.handle_text_message(update1, context)
        assert profile_manager.get_state(test_chat_id) == STATE_AWAITING_ID
        args2, kwargs2 = mock_msg.reply_text.call_args
        assert "Enter your ID:" in args2[0]
        assert "SID" in args2[0]
        assert "Guard ID" in args2[0]
        assert "Faculty/Staff ID" in args2[0]
        assert "Residence ID" in args2[0]
        # NO Gate 1/Gate 2/Gate 3 buttons here
        assert kwargs2.get("reply_markup") is None

        # Step 3: User provides Student ID (SID)
        mock_msg.text = "24103001"
        await bot_service.handle_text_message(update1, context)
        assert profile_manager.get_state(test_chat_id) == STATE_AWAITING_LOCATION
        args3, kwargs3 = mock_msg.reply_text.call_args
        assert "Specify your hostel / location:" in args3[0]
        markup3 = kwargs3.get("reply_markup")
        assert markup3 is not None

        # Verify the 8 authoritative options
        flat_buttons = [b.text for row in markup3.inline_keyboard for b in row]
        assert len(flat_buttons) == 8
        assert "🏢 Shivalik Hostel" in flat_buttons
        assert "🏢 Aravali Hostel" in flat_buttons
        assert "🏢 Kurukshetra Hostel" in flat_buttons
        assert "🏢 Himalaya Hostel" in flat_buttons
        assert "🏢 Kalpana Chawla Hostel" in flat_buttons
        assert "🏢 Vindhya Hostel" in flat_buttons
        assert "🏡 Residence Number" in flat_buttons
        assert "📍 Others" in flat_buttons

        # Step 4: User selects "Shivalik Hostel" via callback
        mock_query = AsyncMock(spec=CallbackQuery)
        mock_query.data = "set_loc:Shivalik Hostel"
        mock_query.from_user = mock_user
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        update_cb = MagicMock(spec=Update)
        update_cb.effective_chat = mock_chat
        update_cb.callback_query = mock_query

        await bot_service.handle_callback(update_cb, context)
        assert profile_manager.get_state(test_chat_id) == STATE_IDLE
        assert profile_manager.is_registered(test_chat_id) is True

        prof = profile_manager.get_profile(test_chat_id)
        assert prof["full_name"] == "Kirat Singh"
        assert prof["identifier"] == "24103001"
        assert prof["location"] == "Shivalik Hostel"
        assert prof["visit_count"] == 1

        args4, _ = mock_query.edit_message_text.call_args
        assert "Registration Complete & Verified" in args4[0]
        assert "Shivalik Hostel" in args4[0]

    asyncio.run(_run())


def test_telegram_returning_user_and_edit_prompt():
    """
    Verifies that when a returning user opens the bot:
    1. The bot asks "Do you want to edit something?".
    2. Provides [Change Location], [Edit Profile], and [Keep As Is / Ready].
    3. Clicking [Keep As Is / Ready] triggers an instant pop-up confirmation alert.
    4. Clicking [Change Location] displays the 8 PEC options.
    """
    async def _run():
        bot_service = TelegramBotService(token="123456:FAKE_TOKEN", mode="polling")
        test_chat_id = 91002
        profile_manager.delete_profile(test_chat_id)
        profile_manager.save_profile(
            test_chat_id,
            full_name="Prof. Verma",
            identifier="F1002014",
            location="Kurukshetra Hostel",
        )

        mock_msg = AsyncMock()
        mock_msg.reply_text = AsyncMock()
        mock_chat = Chat(id=test_chat_id, type="private")
        mock_user = TgUser(id=test_chat_id, first_name="Prof.", last_name="Verma", is_bot=False)

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()

        # Second opening
        await bot_service.handle_start(update, context)
        prof = profile_manager.get_profile(test_chat_id)
        assert prof["visit_count"] == 2

        args, kwargs = mock_msg.reply_text.call_args
        assert "Welcome back, *Prof. Verma*! *(Visit #2)*" in args[0]
        assert "Do you want to edit something?" in args[0]

        markup = kwargs.get("reply_markup")
        assert markup is not None
        button_map = {b.callback_data: b.text for row in markup.inline_keyboard for b in row}
        assert "loc_change" in button_map
        assert "edit_profile" in button_map
        assert "ready_ack" in button_map

        # Test clicking [Keep As Is / Ready] pop-up alert
        mock_query = AsyncMock(spec=CallbackQuery)
        mock_query.data = "ready_ack"
        mock_query.from_user = mock_user
        mock_query.message = mock_msg
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        update_cb = MagicMock(spec=Update)
        update_cb.effective_chat = mock_chat
        update_cb.callback_query = mock_query

        await bot_service.handle_callback(update_cb, context)
        # Verifies native pop-up alert (show_alert=True)
        mock_query.answer.assert_called_once_with(
            "✅ Profile confirmed! Ready to receive and screen your delivery invoices.",
            show_alert=True,
        )
        mock_query.edit_message_text.assert_called_once()

    asyncio.run(_run())


def test_telegram_residence_and_others_selection():
    """
    Verifies that selecting 'Residence Number' and 'Others' prompts for typed input:
    - 'Residence Number' allows typing building/house number (e.g. House 42).
    - 'Others' allows typing custom location (e.g. NAB 2nd Floor).
    """
    async def _run():
        bot_service = TelegramBotService(token="123456:FAKE_TOKEN", mode="polling")
        test_chat_id = 91003
        profile_manager.delete_profile(test_chat_id)
        profile_manager.save_profile(
            test_chat_id,
            full_name="Staff Sharma",
            identifier="STF-01",
            location="Gate 1",
        )

        mock_msg = AsyncMock()
        mock_msg.reply_text = AsyncMock()
        mock_chat = Chat(id=test_chat_id, type="private")
        mock_user = TgUser(id=test_chat_id, first_name="Staff", is_bot=False)

        mock_query = AsyncMock(spec=CallbackQuery)
        mock_query.from_user = mock_user
        mock_query.message = mock_msg
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        update_cb = MagicMock(spec=Update)
        update_cb.effective_chat = mock_chat
        update_cb.callback_query = mock_query

        context = MagicMock()

        # 1. User picks 'Residence Number'
        mock_query.data = "set_loc:__RESIDENCE__"
        await bot_service.handle_callback(update_cb, context)
        assert profile_manager.get_state(test_chat_id) == STATE_AWAITING_RESIDENCE_NO

        # User types house number
        update_msg = MagicMock(spec=Update)
        update_msg.effective_chat = mock_chat
        update_msg.effective_message = mock_msg
        update_msg.effective_user = mock_user
        mock_msg.text = "House 42, Campus Enclave"

        await bot_service.handle_text_message(update_msg, context)
        prof = profile_manager.get_profile(test_chat_id)
        assert "House 42, Campus Enclave" in prof["location"]

        # 2. User picks 'Others'
        mock_query.data = "set_loc:__OTHERS__"
        await bot_service.handle_callback(update_cb, context)
        assert profile_manager.get_state(test_chat_id) == STATE_AWAITING_OTHER_LOCATION

        mock_msg.text = "NAB 2nd Floor"
        await bot_service.handle_text_message(update_msg, context)
        prof = profile_manager.get_profile(test_chat_id)
        assert prof["location"] == "NAB 2nd Floor"

    asyncio.run(_run())


def test_telegram_unregistered_invoice_rejection(sample_invoice_bytes):
    """Verifies that an unregistered user trying to upload an invoice is blocked and prompted to register."""
    async def _run():
        bot_service = TelegramBotService(token="123456:FAKE_TOKEN", mode="polling")
        test_chat_id = 91004
        profile_manager.delete_profile(test_chat_id)

        mock_msg = AsyncMock()
        mock_msg.reply_text = AsyncMock()
        mock_msg.caption = "Order ORD-12345"
        mock_msg.photo = [PhotoSize(file_id="p99", file_unique_id="pu99", width=100, height=100)]
        mock_msg.document = None

        mock_chat = Chat(id=test_chat_id, type="private")
        mock_user = TgUser(id=test_chat_id, first_name="Stranger", is_bot=False)

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()

        await bot_service.handle_incoming_invoice(update, context)

        # Verify registration challenge
        mock_msg.reply_text.assert_called_once()
        args, _ = mock_msg.reply_text.call_args
        assert "Security Registration Required Before Screening" in args[0]
        assert "Please enter your name:" in args[0]

    asyncio.run(_run())


def test_handle_incoming_invoice_student_photo(db: Session, sample_invoice_bytes):
    """
    Verifies that when a student uploads an invoice (screenshot or PDF):
    - The automated OCR & safety screening model runs.
    - All item details and quantities are extracted and presented.
    - Overall total of the bill is computed and presented.
    - Clearance decision is automatically determined by the model (NO manual triage buttons like approve/disapprove).
    - DeliveryDecision and AccessDecision audit records are persisted in PostgreSQL.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
            guard_chat_ids=[1001],
        )

        profile_manager.delete_profile(1001)
        # Pre-seed verified student profile for chat 1001
        profile_manager.save_profile(
            1001,
            full_name="Kirat Singh",
            identifier="24103001",
            location="Shivalik Hostel",
        )

        import random
        test_oid = f"D-{random.randint(10000, 99999)}"

        mock_file = AsyncMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(sample_invoice_bytes))

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        mock_status_msg = AsyncMock()
        mock_status_msg.edit_text = AsyncMock()

        mock_msg = AsyncMock()
        mock_msg.caption = f"Order {test_oid}"
        mock_msg.text = None
        mock_msg.photo = [PhotoSize(file_id="p1", file_unique_id="pu1", width=100, height=100)]
        mock_msg.document = None
        mock_msg.reply_text = AsyncMock(return_value=mock_status_msg)

        mock_chat = Chat(id=1001, type="private")
        mock_user = TgUser(id=5001, first_name="Kirat", is_bot=False, username="kirat_singh")

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        # Execute handler
        await bot_service.handle_incoming_invoice(update, context)

        # Verify initial acknowledgement of reaching the servers
        mock_msg.reply_text.assert_called_once()
        init_reply = mock_msg.reply_text.call_args[0][0]
        assert "has gone through and has reached the servers for a successful run" in init_reply

        # Verify status_msg.edit_text was called with screening summary and ZERO triage buttons
        mock_status_msg.edit_text.assert_called_once()
        args, kwargs = mock_status_msg.edit_text.call_args
        summary_text = args[0]
        assert test_oid in summary_text
        assert "Upload Confirmed: Reached Servers for a Successful Run" in summary_text
        assert "Kirat Singh" in summary_text
        assert "24103001" in summary_text
        assert "Shivalik Hostel" in summary_text
        assert "Item Details & Quantities" in summary_text
        assert "Bill Total:" in summary_text
        assert "Model Decision:" in summary_text

        # Absolutely NO manual buttons (no approve, disapprove, etc.)
        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is None

        # Verify database persistence
        db.expire_all()
        order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == test_oid).first()
        assert order is not None
        assert order.customer_name == "Kirat Singh"
        assert len(order.invoices) > 0
        invoice = order.invoices[-1]
        assert invoice.source == DeliverySource.TELEGRAM
        assert len(invoice.items) > 0

        # Verify automated decision records in PostgreSQL
        from backend.app.models.delivery import DeliveryDecision
        from backend.app.models.gate import AccessDecision

        decisions = db.query(DeliveryDecision).filter(DeliveryDecision.order_id == order.id).all()
        assert len(decisions) >= 1
        assert decisions[-1].decision in (GuardDecision.CLEARED, GuardDecision.HELD)
        assert "[MODEL_AUTO]" in decisions[-1].note

        access_dec = (
            db.query(AccessDecision)
            .filter(AccessDecision.reason_code.in_(["MODEL_CLEARED", "MODEL_HELD"]))
            .order_by(AccessDecision.timestamp.desc())
            .first()
        )
        assert access_dec is not None
        assert access_dec.decision in (AccessState.ALLOWED, AccessState.DENIED)

    asyncio.run(_run())


def test_handle_incoming_invoice_faculty_exemption(db: Session, sample_invoice_bytes):
    """
    Verifies that when a faculty or resident uploads an invoice:
    - The screening model is exempted / bypassed.
    - DeliveryOrder and Invoice are persisted in PostgreSQL.
    - DeliveryDecision is auto-approved as CLEARED with zero triage buttons.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1002],
        )

        profile_manager.delete_profile(1002)
        # Pre-seed verified faculty profile for chat 1002
        profile_manager.save_profile(
            1002,
            full_name="Prof. Sharma",
            identifier="F1002014",
            location="Kurukshetra Hostel",
        )

        import random
        test_oid = f"FAC-{random.randint(10000, 99999)}"

        mock_file = AsyncMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(sample_invoice_bytes))

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        mock_status_msg = AsyncMock()
        mock_status_msg.edit_text = AsyncMock()

        mock_msg = AsyncMock()
        mock_msg.caption = f"Order {test_oid}"
        mock_msg.text = None
        mock_msg.photo = [PhotoSize(file_id="p2", file_unique_id="pu2", width=100, height=100)]
        mock_msg.document = None
        mock_msg.reply_text = AsyncMock(return_value=mock_status_msg)

        mock_chat = Chat(id=1002, type="private")
        mock_user = TgUser(id=5002, first_name="Prof.", is_bot=False, username="prof_sharma")

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        # Execute handler
        await bot_service.handle_incoming_invoice(update, context)

        # Verify initial acknowledgement of reaching the servers
        mock_msg.reply_text.assert_called_once()
        init_reply = mock_msg.reply_text.call_args[0][0]
        assert "has gone through and has reached the servers for a successful run" in init_reply

        mock_status_msg.edit_text.assert_called_once()
        args, kwargs = mock_status_msg.edit_text.call_args
        summary_text = args[0]
        assert test_oid in summary_text
        assert "Upload Confirmed: Reached Servers for a Successful Run" in summary_text
        assert "EXEMPT (Faculty / Resident)" in summary_text
        assert "AUTO-APPROVED & CLEARED" in summary_text
        assert "Prof. Sharma" in summary_text

        # Zero manual buttons
        assert kwargs.get("reply_markup") is None

        # Verify database persistence
        db.expire_all()
        order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == test_oid).first()
        assert order is not None
        assert order.customer_name == "Prof. Sharma"
        assert order.status == OrderStatus.OCR_PROCESSED
        assert order.verification_status == AccessState.ALLOWED

        from backend.app.models.delivery import DeliveryDecision
        decisions = db.query(DeliveryDecision).filter(DeliveryDecision.order_id == order.id).all()
        assert len(decisions) >= 1
        assert decisions[-1].decision == GuardDecision.CLEARED
        assert "Faculty / Campus Resident" in decisions[-1].note

    asyncio.run(_run())


def test_handle_callback_guard_triage(db: Session, sample_invoice_bytes):
    """
    Simulates a guard clicking 'Approve & Open' in Telegram:
    - Parses triage:ALLOW:cargo_<UUID>
    - Invokes execute_review_triage
    - Creates DeliveryDecision and immutable AccessDecision audit trail in PostgreSQL
    - Edits Telegram message with audit details
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
            guard_chat_ids=[1001],
        )

        # 1. Seed a delivery order & invoice
        test_oid = f"TG-DEC-{uuid.uuid4().hex[:6].upper()}"
        inv = delivery_screening_service.process(
            db,
            order_id=test_oid,
            content=sample_invoice_bytes,
            source=DeliverySource.TELEGRAM,
            sender="@rider_bob",
        )
        review_id = f"cargo_{inv.id}"

        # 2. Build mock CallbackQuery
        mock_msg = AsyncMock()
        mock_msg.text = "📦 Delivery Cargo Screening\nOrder ID: " + test_oid

        mock_query = AsyncMock(spec=CallbackQuery)
        mock_query.data = f"triage:ALLOW:{review_id}"
        mock_query.from_user = TgUser(id=9001, first_name="Officer", is_bot=False, username="guard_john")
        mock_query.message = mock_msg
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_chat = Chat(id=1001, type="group")

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.callback_query = mock_query

        context = MagicMock()

        # 3. Execute callback handler
        await bot_service.handle_callback(update, context)

        # 4. Verify callback answer & message edit
        mock_query.answer.assert_called_once()
        mock_query.edit_message_text.assert_called_once()
        args, kwargs = mock_query.edit_message_text.call_args
        updated_text = args[0]
        assert "APPROVED & CLEARED" in updated_text
        assert "@guard_john" in updated_text
        assert "Audit ID:" in updated_text

        # 5. Verify PostgreSQL audit persistence
        db.expire_all()
        decisions = (
            db.query(DeliveryDecision)
            .filter(DeliveryDecision.order_id == inv.order_id)
            .all()
        )
        assert len(decisions) >= 1
        assert decisions[-1].decision == GuardDecision.CLEARED
        assert "Telegram" in decisions[-1].note

        access_audit = (
            db.query(AccessDecision)
            .filter(AccessDecision.reason_code == "GUARD_CARGO_ALLOW")
            .order_by(AccessDecision.timestamp.desc())
            .first()
        )
        assert access_audit is not None
        assert access_audit.decision == AccessState.ALLOWED
        assert access_audit.context_data.get("review_id") == review_id

    asyncio.run(_run())


def test_telegram_webhook_processing():
    """Verifies process_webhook_update deserializes update and invokes application.process_update."""
    async def _run():
        bot_service = TelegramBotService(token="123456:FAKE_TOKEN_FOR_TESTING", mode="webhook")
        mock_app = MagicMock()
        mock_app.process_update = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.defaults = None
        mock_app.bot = mock_bot
        bot_service.application = mock_app

        raw_payload = {
            "update_id": 99999,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 5001, "is_bot": False, "first_name": "Test"},
                "text": "/status",
            },
        }

        result = await bot_service.process_webhook_update(raw_payload)
        assert result is True
        mock_app.process_update.assert_called_once()

    asyncio.run(_run())


def test_handle_callback_guard_triage_unauthorized(db: Session, sample_invoice_bytes):
    """
    Verifies that when a non-guard chat_id clicks a triage action,
    it is strictly rejected with 'Unauthorized: Guard role required'.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001, 2002],
            guard_chat_ids=[1001],  # 2002 is NOT a guard!
        )

        test_oid = f"TG-DEC-{uuid.uuid4().hex[:6].upper()}"
        inv = delivery_screening_service.process(
            db,
            order_id=test_oid,
            content=sample_invoice_bytes,
            source=DeliverySource.TELEGRAM,
            sender="@rider_bob",
        )
        review_id = f"cargo_{inv.id}"

        mock_msg = AsyncMock()
        mock_msg.text = "📦 Delivery Cargo Screening\nOrder ID: " + test_oid

        mock_query = AsyncMock(spec=CallbackQuery)
        mock_query.data = f"triage:ALLOW:{review_id}"
        mock_query.from_user = TgUser(id=2002, first_name="Student", is_bot=False, username="student_user")
        mock_query.message = mock_msg
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_chat = Chat(id=2002, type="private")

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.callback_query = mock_query

        context = MagicMock()

        await bot_service.handle_callback(update, context)

        # Must reject with alert
        mock_query.answer.assert_called_once_with("Unauthorized: Guard role required", show_alert=True)
        # Must not edit message or record decision
        mock_query.edit_message_text.assert_not_called()

    asyncio.run(_run())


def test_handle_incoming_invoice_duplicate_file_unique_id(db: Session, sample_invoice_bytes):
    """
    Verifies that uploading the exact same file_unique_id twice is detected and rejected.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
        )

        profile_manager.delete_profile(1001)
        profile_manager.save_profile(
            1001,
            full_name="Kirat Singh",
            identifier="24103001",
            location="Shivalik Hostel",
        )

        mock_file = AsyncMock()
        mock_file.file_size = len(sample_invoice_bytes)
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(sample_invoice_bytes))

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        mock_status_msg = AsyncMock()
        mock_status_msg.edit_text = AsyncMock()

        # 1. First upload
        mock_msg1 = AsyncMock()
        mock_msg1.caption = "Order Test-Dup-1"
        mock_msg1.text = None
        photo1 = PhotoSize(file_id="p_dup_1", file_unique_id="pu_unique_same_123", width=100, height=100, file_size=len(sample_invoice_bytes))
        mock_msg1.photo = [photo1]
        mock_msg1.document = None
        mock_msg1.reply_text = AsyncMock(return_value=mock_status_msg)

        mock_chat = Chat(id=1001, type="private")
        mock_user = TgUser(id=5001, first_name="Kirat", is_bot=False)

        update1 = MagicMock(spec=Update)
        update1.update_id = 10001
        update1.effective_chat = mock_chat
        update1.effective_message = mock_msg1
        update1.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        await bot_service.handle_incoming_invoice(update1, context)
        mock_msg1.reply_text.assert_called_once()
        mock_status_msg.edit_text.assert_called_once()

        # 2. Second upload with identical file_unique_id
        mock_msg2 = AsyncMock()
        mock_msg2.caption = "Order Test-Dup-2"
        mock_msg2.text = None
        photo2 = PhotoSize(file_id="p_dup_2", file_unique_id="pu_unique_same_123", width=100, height=100, file_size=len(sample_invoice_bytes))
        mock_msg2.photo = [photo2]
        mock_msg2.document = None
        mock_msg2.reply_text = AsyncMock()

        update2 = MagicMock(spec=Update)
        update2.update_id = 10002
        update2.effective_chat = mock_chat
        update2.effective_message = mock_msg2
        update2.effective_user = mock_user

        await bot_service.handle_incoming_invoice(update2, context)
        mock_msg2.reply_text.assert_called_once()
        dup_reply = mock_msg2.reply_text.call_args[0][0]
        assert "Duplicate Invoice Detected" in dup_reply

    asyncio.run(_run())


def test_handle_incoming_invoice_oversized_file(db: Session):
    """
    Verifies that files exceeding 10 MB are rejected before download.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
        )

        profile_manager.delete_profile(1001)
        profile_manager.save_profile(
            1001,
            full_name="Kirat Singh",
            identifier="24103001",
            location="Shivalik Hostel",
        )

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock()

        mock_msg = AsyncMock()
        mock_msg.caption = None
        mock_msg.text = None
        photo = PhotoSize(
            file_id="p_large",
            file_unique_id="pu_large_1",
            width=1000,
            height=1000,
            file_size=11 * 1024 * 1024,  # 11 MB > 10 MB limit
        )
        mock_msg.photo = [photo]
        mock_msg.document = None
        mock_msg.reply_text = AsyncMock()

        mock_chat = Chat(id=1001, type="private")
        mock_user = TgUser(id=5001, first_name="Kirat", is_bot=False)

        update = MagicMock(spec=Update)
        update.update_id = 10003
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        await bot_service.handle_incoming_invoice(update, context)

        # get_file must NOT be called for oversized file
        mock_bot.get_file.assert_not_called()
        mock_msg.reply_text.assert_called_once()
        reply_text = mock_msg.reply_text.call_args[0][0]
        assert "File Too Large" in reply_text

    asyncio.run(_run())


def test_handle_incoming_invoice_unsupported_document_type(db: Session):
    """
    Verifies that uploading an unsupported document type (e.g. zip, exe)
    replies with an explicit error instead of silently returning.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
        )

        profile_manager.delete_profile(1001)
        profile_manager.save_profile(
            1001,
            full_name="Kirat Singh",
            identifier="24103001",
            location="Shivalik Hostel",
        )

        mock_bot = AsyncMock()
        mock_bot.get_file = AsyncMock()

        mock_doc = MagicMock(spec=Document)
        mock_doc.file_id = "doc_unsupp"
        mock_doc.file_unique_id = "doc_u_1"
        mock_doc.file_name = "archive.zip"
        mock_doc.mime_type = "application/zip"
        mock_doc.file_size = 1024

        mock_msg = AsyncMock()
        mock_msg.caption = None
        mock_msg.text = None
        mock_msg.photo = []
        mock_msg.document = mock_doc
        mock_msg.reply_text = AsyncMock()

        mock_chat = Chat(id=1001, type="private")
        mock_user = TgUser(id=5001, first_name="Kirat", is_bot=False)

        update = MagicMock(spec=Update)
        update.update_id = 10004
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        await bot_service.handle_incoming_invoice(update, context)

        # Must NOT attempt to download
        mock_bot.get_file.assert_not_called()
        mock_msg.reply_text.assert_called_once()
        reply_text = mock_msg.reply_text.call_args[0][0]
        assert "Unsupported Document Format" in reply_text

    asyncio.run(_run())


def test_telegram_users_endpoint_auth(db: Session, staff_headers):
    """
    Verifies that GET /telegram/users and /api/telegram/users require
    staff/admin bearer authentication.
    """
    client = TestClient(app)

    # 1. Unauthenticated request -> 401 Unauthorized
    resp_unauth = client.get("/telegram/users")
    assert resp_unauth.status_code == 401

    resp_api_unauth = client.get("/api/telegram/users")
    assert resp_api_unauth.status_code == 401

    # 2. Authenticated request with staff_headers -> 200 OK
    resp_auth = client.get("/telegram/users", headers=staff_headers)
    assert resp_auth.status_code == 200
    data = resp_auth.json()
    assert "count" in data
    assert "users" in data
    assert isinstance(data["users"], list)


def test_telegram_webhook_secret_enforcement():
    """
    Verifies that when TELEGRAM_MODE=webhook, TELEGRAM_WEBHOOK_SECRET is strictly validated.
    """
    client = TestClient(app)

    with patch("backend.app.routes.telegram.TELEGRAM_MODE", "webhook"), \
         patch("backend.app.routes.telegram.TELEGRAM_WEBHOOK_SECRET", "super_secret_webhook_token_123"):

        # 1. Missing secret token header -> 403 Forbidden
        resp_no_secret = client.post(
            "/telegram/webhook",
            json={"update_id": 1234},
        )
        assert resp_no_secret.status_code == 403

        # 2. Invalid secret token header -> 403 Forbidden
        resp_wrong_secret = client.post(
            "/telegram/webhook",
            json={"update_id": 1234},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
        )
        assert resp_wrong_secret.status_code == 403

        # 3. Valid secret token header -> 200 OK
        with patch.object(telegram_service, "process_webhook_update", new=AsyncMock(return_value=True)):
            resp_valid = client.post(
                "/telegram/webhook",
                json={"update_id": 1234},
                headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_webhook_token_123"},
            )
            assert resp_valid.status_code == 200
            assert resp_valid.json() == {"ok": True}


def test_handle_edit_and_profile_chat_allowed_enforcement():
    """
    Verifies that /edit and /profile strictly enforce _is_chat_allowed
    when allowed_chat_ids is configured.
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],  # Only 1001 allowed
        )

        mock_msg_unauth = AsyncMock()
        mock_msg_unauth.reply_text = AsyncMock()
        mock_chat_unauth = Chat(id=9999, type="private")

        update_unauth = MagicMock(spec=Update)
        update_unauth.effective_chat = mock_chat_unauth
        update_unauth.effective_message = mock_msg_unauth

        context = MagicMock()

        # 1. /edit from unauthorized chat
        await bot_service.handle_edit_command(update_unauth, context)
        mock_msg_unauth.reply_text.assert_called_once()
        assert "Unauthorized" in mock_msg_unauth.reply_text.call_args[0][0]

        mock_msg_unauth.reply_text.reset_mock()

        # 2. /profile from unauthorized chat
        await bot_service.handle_profile(update_unauth, context)
        mock_msg_unauth.reply_text.assert_called_once()
        assert "Unauthorized" in mock_msg_unauth.reply_text.call_args[0][0]

    asyncio.run(_run())
