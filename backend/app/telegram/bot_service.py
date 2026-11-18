"""
Telegram Bot Service for Campus Vehicle Security & Access Control System
------------------------------------------------------------------------
Implements the Telegram Connector supporting:
  - Both Polling (TELEGRAM_MODE=polling) and Webhook (TELEGRAM_MODE=webhook)
  - Incoming photo/document invoices downloaded via getFile and processed
    via delivery_screening_service (Track B OCR + Track C 3-tier screening)
  - Interactive InlineKeyboardMarkup (Approve & Open, Flag for Search, Deny)
    wired to execute_review_triage with immutable PostgreSQL audit logging
  - Access gating by TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.app.config import (
    TELEGRAM_ALLOWED_CHAT_IDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_MODE,
    TELEGRAM_WEBHOOK_SECRET,
)
import re
from backend.app.db import SessionLocal
from backend.app.models.enums import DeliverySource, ScreeningVerdict
from backend.app.models.identity import User
from backend.app.services.delivery_screening_service import delivery_screening_service

logger = logging.getLogger("campus_security.telegram")

_ORDER_IN_TEXT = re.compile(r"(?:order\s*(?:id|no\.?|number)?\s*[:#]?\s*#?\s*|#)?\b([A-Z]{1,6}-?\d[A-Z0-9-]{2,})\b", re.IGNORECASE)

def order_id_from_text(text: Optional[str]) -> Optional[str]:
    m = _ORDER_IN_TEXT.search(text or "")
    return m.group(1).upper() if m else None


class TelegramBotService:
    def __init__(
        self,
        token: Optional[str] = None,
        mode: Optional[str] = None,
        allowed_chat_ids: Optional[List[int]] = None,
    ) -> None:
        self.token: str = (token if token is not None else TELEGRAM_BOT_TOKEN).strip()
        self.mode: str = (mode if mode is not None else TELEGRAM_MODE).strip().lower()
        self.allowed_chat_ids: List[int] = (
            allowed_chat_ids if allowed_chat_ids is not None else TELEGRAM_ALLOWED_CHAT_IDS
        )
        self.application: Optional[Application] = None
        self._is_running: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _build_application(self) -> Application:
        if not self.is_configured:
            raise RuntimeError("TelegramBotService cannot build Application without TELEGRAM_BOT_TOKEN.")

        builder = Application.builder().token(self.token)
        app = builder.build()

        # Command Handlers
        app.add_handler(CommandHandler("start", self.handle_start))
        app.add_handler(CommandHandler("help", self.handle_help))
        app.add_handler(CommandHandler("status", self.handle_status))

        # Media Invoice Handlers (Photos and Documents/PDFs)
        app.add_handler(
            MessageHandler(
                filters.PHOTO | filters.Document.ALL,
                self.handle_incoming_invoice,
            )
        )

        # Interactive Guard Triage Callback Handler
        app.add_handler(CallbackQueryHandler(self.handle_callback))

        return app

    async def start(self) -> None:
        """Initializes and starts the bot application (starts polling if in polling mode)."""
        async with self._lock:
            if self._is_running or not self.is_configured:
                return

            try:
                self.application = self._build_application()
                await self.application.initialize()
                await self.application.start()

                if self.mode == "polling":
                    logger.info("Starting Telegram bot updater polling for @KritanshCampusbot...")
                    await self.application.updater.start_polling(drop_pending_updates=True)
                    logger.info("Telegram bot polling started successfully.")
                else:
                    logger.info("Telegram bot initialized in webhook mode (ready for POST /api/telegram/webhook).")

                self._is_running = True
            except Exception as exc:
                logger.error("Failed to start TelegramBotService: %s", exc)
                # Keep server booting even if Telegram API is unreachable in isolated networks
                self._is_running = False

    async def stop(self) -> None:
        """Cleanly stops polling and shuts down the bot application."""
        async with self._lock:
            if not self._is_running or not self.application:
                return

            try:
                logger.info("Stopping TelegramBotService...")
                if self.mode == "polling" and self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                if self.application.running:
                    await self.application.stop()
                await self.application.shutdown()
                logger.info("TelegramBotService shutdown complete.")
            except Exception as exc:
                logger.warning("Error stopping TelegramBotService: %s", exc)
            finally:
                self._is_running = False

    def _is_chat_allowed(self, chat_id: int) -> bool:
        if not self.allowed_chat_ids:
            return True
        return chat_id in self.allowed_chat_ids

    # ------------------------------------------------------------------
    # Message Handlers
    # ------------------------------------------------------------------
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Unauthorized: Chat ID `{chat_id}` is not registered in TELEGRAM_ALLOWED_CHAT_IDS.",
                    parse_mode="Markdown",
                )
            return

        text = (
            "🛡️ *Campus Gate Security & Delivery Intake Bot*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Welcome to the PEC Campus Access Control System.\n\n"
            "• *Guards & Riders:* Send an invoice photo or PDF (with order ID in the caption or invoice)\n"
            "• *Automated OCR:* RapidOCR / Tesseract runs instant extraction and arithmetic reconciliation\n"
            "• *Screening:* 3,414-item Indian quick-commerce policy checks for contraband or restricted goods\n"
            "• *Interactive Gate Triage:* Guards can approve or flag deliveries with 1-click inline buttons\n\n"
            "Send an invoice photo or document now to begin screening."
        )
        if update.effective_message:
            await update.effective_message.reply_text(text, parse_mode="Markdown")

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.handle_start(update, context)

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(
                f"✅ *Campus Bot Status*\n"
                f"• Mode: `{self.mode.upper()}`\n"
                f"• Allowed Chats: `{self.allowed_chat_ids or 'All (Unrestricted)'}`\n"
                f"• Connected: `True`",
                parse_mode="Markdown",
            )

    async def handle_incoming_invoice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message:
            return

        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            logger.warning("Invoice upload from unauthorized Telegram chat %s rejected.", chat_id)
            await message.reply_text(
                f"⛔ Access denied: Chat ID `{chat_id}` is not permitted for campus gate screening.",
                parse_mode="Markdown",
            )
            return

        # Identify photo or document
        file_id: Optional[str] = None
        if message.photo:
            file_id = message.photo[-1].file_id  # Highest resolution
        elif message.document:
            doc = message.document
            mime = (doc.mime_type or "").lower()
            fname = (doc.file_name or "").lower()
            if (
                mime.startswith("image/")
                or mime == "application/pdf"
                or fname.endswith((".jpg", ".jpeg", ".png", ".webp", ".pdf"))
            ):
                file_id = doc.file_id

        if not file_id:
            return

        status_msg = await message.reply_text("🔍 Downloading invoice and running automated OCR & safety screening...")

        try:
            tg_file = await context.bot.get_file(file_id)
            file_bytes = await tg_file.download_as_bytearray()
            raw_bytes = bytes(file_bytes)

            caption = message.caption or message.text or ""
            extracted_oid = order_id_from_text(caption)

            sender_user = update.effective_user
            if sender_user and sender_user.username:
                sender_handle = f"@{sender_user.username}"
            elif sender_user:
                sender_handle = f"{sender_user.full_name} ({sender_user.id})"
            else:
                sender_handle = str(chat_id)

            db = SessionLocal()
            try:
                try:
                    invoice = delivery_screening_service.process(
                        db,
                        order_id=extracted_oid,
                        content=raw_bytes,
                        source=DeliverySource.TELEGRAM,
                        sender=sender_handle[:50],
                        gate_id=None,
                        platform=None,
                        user_id=None,
                    )
                except Exception as proc_exc:
                    # If no order ID was given and none could be read, auto-generate fallback ID
                    if "No order ID was given" in str(proc_exc):
                        fallback_oid = f"TG-{uuid.uuid4().hex[:8].upper()}"
                        invoice = delivery_screening_service.process(
                            db,
                            order_id=fallback_oid,
                            content=raw_bytes,
                            source=DeliverySource.TELEGRAM,
                            sender=sender_handle[:50],
                            gate_id=None,
                            platform=None,
                            user_id=None,
                        )
                    else:
                        raise proc_exc

                order = invoice.order
                oid = order.order_id
                vendor = invoice.vendor or order.platform.value
                total = float(invoice.total_amount or 0.0)
                verdict = invoice.overall_verdict.value if invoice.overall_verdict else "REVIEW"
                totals_match = invoice.totals_match

                # Format breakdown
                item_lines = []
                for item in invoice.items[:8]:
                    badge = (
                        "✅"
                        if item.verdict == ScreeningVerdict.ALLOW
                        else ("⚠️" if item.verdict == ScreeningVerdict.REVIEW else "🚨")
                    )
                    item_lines.append(
                        f"{badge} {item.item_name} (x{item.quantity or 1}): ₹{float(item.total_price or 0.0):.2f} "
                        f"[{item.category or 'UNKNOWN'}]"
                    )
                if len(invoice.items) > 8:
                    item_lines.append(f"  ...and {len(invoice.items) - 8} more item(s)")

                items_summary = "\n".join(item_lines) if item_lines else "No individual items extracted"
                verdict_emoji = "✅" if verdict == "ALLOW" else ("⚠️" if verdict == "REVIEW" else "🚨")
                match_str = "Verified" if totals_match else "Arithmetic Unverified"

                text = (
                    f"📦 *Delivery Cargo Screening*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"*Order ID:* `{oid}`\n"
                    f"*Vendor / Platform:* {vendor}\n"
                    f"*Total Amount:* ₹{total:,.2f} ({match_str})\n"
                    f"*Overall Verdict:* {verdict_emoji} *{verdict}*\n\n"
                    f"*Items Breakdown:*\n{items_summary}\n\n"
                    f"🛡️ *Guard Action Required:*\n"
                    f"Please select campus gate clearance action:"
                )

                review_id = f"cargo_{invoice.id}"
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Approve & Open", callback_data=f"triage:ALLOW:{review_id}"),
                        InlineKeyboardButton("⚠️ Flag for Search", callback_data=f"triage:OVERRIDE:{review_id}"),
                        InlineKeyboardButton("⛔ Deny", callback_data=f"triage:REJECT:{review_id}"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            finally:
                db.close()
        except Exception as exc:
            logger.exception("Error processing invoice from Telegram: %s", exc)
            await status_msg.edit_text(f"❌ Failed to screen invoice: {str(exc)}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            await query.answer("⛔ Unauthorized chat.", show_alert=True)
            return

        data = query.data or ""
        if not data.startswith("triage:"):
            await query.answer()
            return

        parts = data.split(":", 2)
        if len(parts) != 3:
            await query.answer("Invalid callback data.", show_alert=True)
            return

        from backend.app.routes.reviews import TriageAction, execute_review_triage

        _, action_str, review_id = parts
        try:
            action = TriageAction(action_str)
        except ValueError:
            await query.answer(f"Unknown action: {action_str}", show_alert=True)
            return

        db = SessionLocal()
        try:
            guard = db.query(User).filter(User.username == "guard1").first()
            if not guard:
                guard = db.query(User).filter(User.role == "GUARD").first()
            if not guard:
                guard = db.query(User).first()

            guard_user_id = guard.id if guard else uuid.uuid4()
            tg_user = query.from_user
            officer_name = f"@{tg_user.username}" if tg_user and tg_user.username else (tg_user.full_name if tg_user else "Guard")

            note = f"Triage via Telegram by {officer_name} (chat {chat_id})"
            res = execute_review_triage(
                db,
                review_id=review_id,
                action=action,
                guard_id=guard_user_id,
                reason_notes=note,
            )

            action_labels = {
                TriageAction.ALLOW: "✅ APPROVED & CLEARED",
                TriageAction.OVERRIDE: "⚠️ FLAGGED FOR PHYSICAL SEARCH",
                TriageAction.REJECT: "⛔ DENIED & TURNED AWAY",
            }
            label = action_labels.get(action, action.value)

            await query.answer(f"Recorded: {label}")

            now_str = datetime.now(timezone.utc).strftime("%I:%M %p UTC")
            base_text = query.message.text if query.message else "Cargo Review"
            updated_text = (
                base_text
                + f"\n\n━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ *Decision Recorded:* {label}\n"
                f"👮 *Officer:* {officer_name}\n"
                f"⏱️ *Timestamp:* {now_str}\n"
                f"🆔 *Audit ID:* `{res.audit_id}`"
            )
            await query.edit_message_text(updated_text, parse_mode="Markdown")
        except Exception as exc:
            logger.exception("Error executing triage callback: %s", exc)
            await query.answer(f"Error: {str(exc)}", show_alert=True)
        finally:
            db.close()

    async def process_webhook_update(self, raw_data: dict, secret_token: Optional[str] = None) -> bool:
        """Processes an incoming Telegram Update JSON payload received via webhook."""
        if TELEGRAM_WEBHOOK_SECRET and secret_token != TELEGRAM_WEBHOOK_SECRET:
            raise PermissionError("Invalid Telegram webhook secret token.")

        if not self.application:
            self.application = self._build_application()
            await self.application.initialize()

        update = Update.de_json(raw_data, self.application.bot)
        if update:
            await self.application.process_update(update)
            return True
        return False


telegram_service = TelegramBotService()
