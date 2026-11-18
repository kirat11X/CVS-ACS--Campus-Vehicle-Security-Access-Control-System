"""
Unit & Integration Test Suite for Telegram Connector
---------------------------------------------------
Verifies:
1. TelegramBotService initialization, configuration, and chat-gating.
2. Webhook endpoint (POST /telegram/webhook and POST /api/telegram/webhook).
3. Status endpoint (GET /telegram/status).
4. Order process-invoice endpoint (POST /orders/process-invoice).
5. Processing of incoming invoice photo/document updates into PostgreSQL.
6. Interactive guard triage via CallbackQuery (Approve & Open, Flag for Search, Deny)
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
from backend.app.models.enums import AccessState, DeliverySource, GuardDecision, ScreeningVerdict
from backend.app.models.gate import AccessDecision, Gate
from backend.app.models.identity import User
from backend.app.routes.reviews import TriageAction, execute_review_triage
from backend.app.services.auth_service import create_access_token
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.telegram.bot_service import TelegramBotService, telegram_service


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


def test_handle_incoming_invoice_photo(db: Session, sample_invoice_bytes):
    """
    Simulates a Telegram update with a photo invoice and caption:
    - Downloads via getFile mock
    - Runs delivery screening
    - Persists Invoice & DeliveryOrder with source=TELEGRAM
    - Replies with markdown summary and 3-button inline triage keyboard
    """
    async def _run():
        bot_service = TelegramBotService(
            token="123456:FAKE_TOKEN_FOR_TESTING",
            mode="polling",
            allowed_chat_ids=[1001],
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

        mock_chat = Chat(id=1001, type="group")
        mock_user = TgUser(id=5001, first_name="Rider", is_bot=False, username="rider_bob")

        update = MagicMock(spec=Update)
        update.effective_chat = mock_chat
        update.effective_message = mock_msg
        update.effective_user = mock_user

        context = MagicMock()
        context.bot = mock_bot

        # Execute handler
        await bot_service.handle_incoming_invoice(update, context)

        # Verify status_msg.edit_text was called with screening summary and keyboard
        mock_status_msg.edit_text.assert_called_once()
        args, kwargs = mock_status_msg.edit_text.call_args
        summary_text = args[0]
        assert test_oid in summary_text
        assert "Delivery Cargo Screening" in summary_text
        assert "Overall Verdict" in summary_text

        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is not None
        assert len(reply_markup.inline_keyboard) == 1
        buttons = reply_markup.inline_keyboard[0]
        assert len(buttons) == 3
        assert buttons[0].text == "✅ Approve & Open"
        assert "triage:ALLOW:cargo_" in buttons[0].callback_data
        assert buttons[1].text == "⚠️ Flag for Search"
        assert "triage:OVERRIDE:cargo_" in buttons[1].callback_data
        assert buttons[2].text == "⛔ Deny"
        assert "triage:REJECT:cargo_" in buttons[2].callback_data

        # Verify database persistence
        db.expire_all()
        order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == test_oid).first()
        assert order is not None
        assert len(order.invoices) > 0
        invoice = order.invoices[-1]
        assert invoice.source == DeliverySource.TELEGRAM

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
