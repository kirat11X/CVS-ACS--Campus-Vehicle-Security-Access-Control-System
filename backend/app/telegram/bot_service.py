"""
Telegram Bot Service for Campus Vehicle Security & Access Control System
------------------------------------------------------------------------
Implements the Telegram Connector supporting:
  - Both Polling (TELEGRAM_MODE=polling) and Webhook (TELEGRAM_MODE=webhook)
  - Security onboarding tailored for Punjab Engineering College (PEC), Chandigarh:
      * Step 1: Clean prompt "Please enter your name:" (no prefilled buttons)
      * Step 2: "Enter your ID:" (SID for students, Guard ID for guards,
        Faculty/Staff ID for faculty/staff, Residence ID for campus residents)
      * Step 3: Specify your hostel / location across 8 authoritative options:
        - 4 Boys' Hostels: Shivalik, Aravali, Kurukshetra, Himalaya
        - 2 Girls' Hostels: Kalpana Chawla, Vindhya
        - 1 Residence Number option
        - 1 Others option (NAB, Gate 1, Gate 2, Gate 3, building numbers, etc.)
  - Returning user recognition with interactive "Do you want to edit something?" pop-up prompt
  - Dynamic location updates via [📍 Change Location], /changelocation, or chat
  - Incoming photo/document invoices downloaded via getFile and screened via
    delivery_screening_service (RapidOCR/Tesseract OCR + Indian grocery contraband policy)
  - Interactive InlineKeyboardMarkup (Approve & Open, Flag for Search, Deny, Change Location)
    wired to execute_review_triage with immutable PostgreSQL audit logging
  - Access gating by TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.app.config import (
    INVOICE_MAX_UPLOAD_MB,
    TELEGRAM_ALLOWED_CHAT_IDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GUARD_CHAT_IDS,
    TELEGRAM_MODE,
    TELEGRAM_WEBHOOK_SECRET,
)
from backend.app.db import SessionLocal
from backend.app.models.enums import DeliverySource, ScreeningVerdict
from backend.app.models.identity import User
from backend.app.services.delivery_screening_service import delivery_screening_service
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

logger = logging.getLogger("campus_security.telegram")

_ORDER_IN_TEXT = re.compile(
    r"(?:order\s*(?:id|no\.?|number)?\s*[:#]?\s*#?\s*|#)?\b([A-Z]{1,6}-?\d[A-Z0-9-]{2,})\b",
    re.IGNORECASE,
)

RESERVED_ORDER_KEYWORDS = {
    "DETAILS", "ORDER DETAILS", "SUMMARY", "INVOICE", "RECEIPT", "BILL",
    "ORDER", "ITEMS", "ITEM", "NONE", "NULL", "UNTITLED", "DATE", "STATUS"
}


def order_id_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _ORDER_IN_TEXT.search(text)
    if m:
        candidate = m.group(1).upper()
        if candidate in RESERVED_ORDER_KEYWORDS or not any(c.isdigit() for c in candidate):
            return None
        return candidate
    return None


async def send_post_registration_prompt(bot, chat_id: int) -> None:
    """Sends a clear follow-up message instructing the user they can upload delivery invoices."""
    text = (
        "📤 *You can send your invoices now!*\n\n"
        "Simply send a photo, mobile screenshot (e.g. Blinkit, Swiggy, Zepto, Zomato), "
        "or PDF of your delivery invoice directly in this chat.\n\n"
        "Our system will autonomously extract all items, quantities, and bill total "
        "for instant campus gate clearance."
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as exc:
        logger.debug("Could not send post-registration prompt: %s", exc)


def is_student_id(identifier: str) -> bool:
    """
    Returns True if identifier belongs to a student (SID), False otherwise.
    PEC Student IDs are standard numeric roll numbers (e.g. 24103001, 21104055)
    or explicitly prefixed with 'SID'.
    Non-student roles include Faculty ('F...', 'FAC...'), Staff ('STF...'),
    Security ('G...', 'GUARD...'), Campus Residents ('R...', 'HOUSE...', 'RES...'),
    or Gates ('GATE_...').
    """
    clean = (identifier or "").strip().upper()
    if not clean:
        return True

    # Explicit non-student prefixes
    if clean.startswith("F") and (len(clean) > 1 and (clean[1].isdigit() or clean.startswith("FAC"))):
        return False
    if clean.startswith("STF") or clean.startswith("STAFF"):
        return False
    if clean.startswith("G") and (len(clean) > 1 and (clean[1].isdigit() or clean.startswith("GUARD"))):
        return False
    if clean.startswith("R") and (len(clean) > 1 and (clean[1].isdigit() or clean.startswith("RES") or clean.startswith("HOUSE"))):
        return False
    if clean.startswith("GATE"):
        return False
    if any(prefix in clean for prefix in ("FACULTY", "RESIDENCE", "STAFF", "GUARD")):
        return False

    return True


def build_location_keyboard(prefix: str = "set_loc:") -> InlineKeyboardMarkup:
    """
    Builds the 8 authoritative Punjab Engineering College (PEC) location options:
    - 4 Boys' Hostels: Shivalik, Aravali, Kurukshetra, Himalaya
    - 2 Girls' Hostels: Kalpana Chawla, Vindhya
    - 1 Residence Number option
    - 1 Others option (NAB, Gate 1, Gate 2, Gate 3, building numbers, etc.)
    """
    rows = [
        [
            InlineKeyboardButton("🏢 Shivalik Hostel", callback_data=f"{prefix}Shivalik Hostel"),
            InlineKeyboardButton("🏢 Aravali Hostel", callback_data=f"{prefix}Aravali Hostel"),
        ],
        [
            InlineKeyboardButton("🏢 Kurukshetra Hostel", callback_data=f"{prefix}Kurukshetra Hostel"),
            InlineKeyboardButton("🏢 Himalaya Hostel", callback_data=f"{prefix}Himalaya Hostel"),
        ],
        [
            InlineKeyboardButton("🏢 Kalpana Chawla Hostel", callback_data=f"{prefix}Kalpana Chawla Hostel"),
            InlineKeyboardButton("🏢 Vindhya Hostel", callback_data=f"{prefix}Vindhya Hostel"),
        ],
        [
            InlineKeyboardButton("🏡 Residence Number", callback_data=f"{prefix}__RESIDENCE__"),
            InlineKeyboardButton("📍 Others", callback_data=f"{prefix}__OTHERS__"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


class TelegramBotService:
    def __init__(
        self,
        token: Optional[str] = None,
        mode: Optional[str] = None,
        allowed_chat_ids: Optional[List[int]] = None,
        guard_chat_ids: Optional[List[int]] = None,
    ) -> None:
        self.token: str = (token if token is not None else TELEGRAM_BOT_TOKEN).strip()
        self.mode: str = (mode if mode is not None else TELEGRAM_MODE).strip().lower()
        self.allowed_chat_ids: List[int] = (
            allowed_chat_ids if allowed_chat_ids is not None else list(TELEGRAM_ALLOWED_CHAT_IDS)
        )
        self.guard_chat_ids: List[int] = (
            guard_chat_ids if guard_chat_ids is not None else list(TELEGRAM_GUARD_CHAT_IDS)
        )
        self.application: Optional[Application] = None
        self._is_running: bool = False
        self._lock = asyncio.Lock()
        self._processed_update_ids: OrderedDict[int, float] = OrderedDict()
        self._processed_file_unique_ids: OrderedDict[str, float] = OrderedDict()

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _build_application(self) -> Application:
        if not self.is_configured:
            raise RuntimeError("TelegramBotService cannot build Application without TELEGRAM_BOT_TOKEN.")

        builder = (
            Application.builder()
            .token(self.token)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
        )
        app = builder.build()

        # Command Handlers
        app.add_handler(CommandHandler("start", self.handle_start))
        app.add_handler(CommandHandler("help", self.handle_help))
        app.add_handler(CommandHandler("status", self.handle_status))
        app.add_handler(CommandHandler("changelocation", self.handle_change_location))
        app.add_handler(CommandHandler("location", self.handle_change_location))
        app.add_handler(CommandHandler("edit", self.handle_edit_command))
        app.add_handler(CommandHandler("profile", self.handle_profile))

        # Text Message Handler (for step-by-step registration and custom location inputs)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

        # Media Invoice Handlers (Photos and Documents/PDFs)
        app.add_handler(
            MessageHandler(
                filters.PHOTO | filters.Document.ALL,
                self.handle_incoming_invoice,
            )
        )

        # Interactive Callback Query Handler (Triage & Location Selection)
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

    def _is_guard_chat(self, chat_id: int) -> bool:
        """
        Verifies if chat_id belongs to an authorized security guard.
        If guard_chat_ids is configured, chat_id must match.
        Otherwise, checks if the registered Telegram profile has a Guard identifier.
        """
        if self.guard_chat_ids:
            return chat_id in self.guard_chat_ids
        prof = profile_manager.get_profile(chat_id)
        if prof and profile_manager.is_registered(chat_id):
            ident = (prof.get("identifier") or "").upper()
            if ident.startswith(("GUARD", "GRD", "G_")):
                return True
        return False

    def _is_duplicate_update(self, update_id: Optional[int]) -> bool:
        """Returns True if update_id has already been processed within the LRU window."""
        if update_id is None:
            return False
        if update_id in self._processed_update_ids:
            return True
        self._processed_update_ids[update_id] = datetime.now(timezone.utc).timestamp()
        if len(self._processed_update_ids) > 10000:
            self._processed_update_ids.popitem(last=False)
        return False

    def _is_duplicate_file(self, file_unique_id: Optional[str]) -> bool:
        """Returns True if file_unique_id has already been processed within the LRU window."""
        if not file_unique_id:
            return False
        if file_unique_id in self._processed_file_unique_ids:
            return True
        self._processed_file_unique_ids[file_unique_id] = datetime.now(timezone.utc).timestamp()
        if len(self._processed_file_unique_ids) > 10000:
            self._processed_file_unique_ids.popitem(last=False)
        return False

    # ------------------------------------------------------------------
    # Command & Lifecycle Handlers
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

        msg = update.effective_message
        if not msg:
            return

        profile = profile_manager.get_profile(chat_id)

        # ------------------------------------------------------------------
        # 1. FIRST-TIME OPENING: Profile not registered
        # ------------------------------------------------------------------
        if not profile_manager.is_registered(chat_id):
            profile_manager.set_state(chat_id, STATE_AWAITING_NAME)
            text = (
                "🛡️ *Punjab Engineering College (PEC)*\n"
                "*Campus Gate Security & Delivery Intake*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Welcome to the PEC Chandigarh Access Control System.\n\n"
                "🔒 *Identity Registration Required*\n"
                "Please enter your name:"
            )
            # Pure clean prompt with NO prefilled "Use ..." button
            await msg.reply_text(text, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # 2. SUBSEQUENT OPENINGS (2nd, 3rd, etc.): Recognized user
        # ------------------------------------------------------------------
        visit_count = profile_manager.record_visit(chat_id)
        name = profile.get("full_name", "Member")
        identifier = profile.get("identifier", "UNKNOWN")
        location = profile.get("location", "Not Set")

        text = (
            f"🛡️ *Punjab Engineering College (PEC)*\n"
            f"*Gate Security & Delivery Intake*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome back, *{name}*! *(Visit #{visit_count})*\n\n"
            f"🆔 *Registered ID:* `{identifier}`\n"
            f"📍 *Current Location:* *{location}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 *Do you want to edit something?*\n"
            f"• Tap *Change Location* to update your hostel or campus building.\n"
            f"• Tap *Edit Profile* to change your name or ID.\n"
            f"• Or send your invoice photo / PDF directly to screen."
        )
        keyboard = [
            [
                InlineKeyboardButton("📍 Change Location", callback_data="loc_change"),
                InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile"),
            ],
            [
                InlineKeyboardButton("✅ Keep As Is / Ready", callback_data="ready_ack"),
            ],
        ]
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def handle_edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Command /edit to restart or adjust profile."""
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Unauthorized: Chat ID `{chat_id}` is not registered in TELEGRAM_ALLOWED_CHAT_IDS.",
                    parse_mode="Markdown",
                )
            return

        msg = update.effective_message
        if not msg:
            return

        profile_manager.set_state(chat_id, STATE_AWAITING_NAME)
        text = (
            "✏️ *Edit Security Profile*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Please enter your name:"
        )
        await msg.reply_text(text, parse_mode="Markdown")

    async def handle_change_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Explicit command to update current campus location."""
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            return

        msg = update.effective_message
        if not msg:
            return

        profile = profile_manager.get_profile(chat_id)
        if not profile or not profile_manager.is_registered(chat_id):
            await self.handle_start(update, context)
            return

        profile_manager.set_state(chat_id, STATE_CHANGING_LOCATION)
        text = (
            f"📍 *Update Campus Delivery Location*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *User:* *{profile.get('full_name')}*\n"
            f"🆔 *ID:* `{profile.get('identifier')}`\n"
            f"📍 *Current Location:* *{profile.get('location')}*\n\n"
            f"Please select your destination from the 8 options below:"
        )
        kb = build_location_keyboard(prefix="set_loc:")
        kb_rows = list(kb.inline_keyboard)
        kb_rows.append([InlineKeyboardButton("❌ Keep Current Location", callback_data="cancel_loc")])
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")

    async def handle_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Displays user's security profile and gives editing options."""
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Unauthorized: Chat ID `{chat_id}` is not registered in TELEGRAM_ALLOWED_CHAT_IDS.",
                    parse_mode="Markdown",
                )
            return

        msg = update.effective_message
        if not msg:
            return

        profile = profile_manager.get_profile(chat_id)
        if not profile or not profile_manager.is_registered(chat_id):
            await self.handle_start(update, context)
            return

        text = (
            f"👤 *Registered Security Profile*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Name:* *{profile.get('full_name')}*\n"
            f"• *ID:* `{profile.get('identifier')}`\n"
            f"• *Location:* *{profile.get('location')}*\n"
            f"• *Total Visits:* `{profile.get('visit_count', 1)}`\n"
            f"• *Status:* `ACTIVE & AUTHORIZED`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
            [InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile")],
        ])
        await msg.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.handle_start(update, context)

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        profile = profile_manager.get_profile(chat_id)
        prof_info = (
            f"• User: `{profile.get('full_name')}`\n"
            f"• ID: `{profile.get('identifier')}`\n"
            f"• Location: `{profile.get('location')}`\n"
            f"• Visits: `{profile.get('visit_count', 1)}`"
            if profile
            else "• Profile: `Unregistered`"
        )

        if update.effective_message:
            await update.effective_message.reply_text(
                f"✅ *Campus Bot Status*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Mode: `{self.mode.upper()}`\n"
                f"• Connected: `True`\n"
                f"{prof_info}",
                parse_mode="Markdown",
            )

    # ------------------------------------------------------------------
    # Conversational Text Message Handler
    # ------------------------------------------------------------------
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            return

        msg = update.effective_message
        if not msg or not msg.text:
            return

        raw_text = msg.text.strip()
        state = profile_manager.get_state(chat_id)
        tg_user = update.effective_user

        # ------------------------------------------------------------------
        # Step 1: User provides Name
        # ------------------------------------------------------------------
        if state == STATE_AWAITING_NAME:
            name = raw_text
            profile_manager.set_state(chat_id, STATE_AWAITING_ID, {"full_name": name})

            text = (
                f"👤 Name: *{name}*\n\n"
                f"👉 *Enter your ID:*\n"
                f"• *Students:* Student ID / SID (e.g. `24103001`)\n"
                f"• *Security Guards:* Guard ID (e.g. `GUARD_1` or Badge ID)\n"
                f"• *Faculty / Staff:* Faculty/Staff ID (e.g. `F1002014` or `STF-01`)\n"
                f"• *Campus Residents:* Residence ID (e.g. `R1042`)\n\n"
                f"Please type your ID below:"
            )
            # Pure clean text prompt with NO gate buttons
            await msg.reply_text(text, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # Step 2: User provides ID
        # ------------------------------------------------------------------
        if state == STATE_AWAITING_ID:
            identifier = raw_text.upper()
            profile_manager.set_state(chat_id, STATE_AWAITING_LOCATION, {"identifier": identifier})

            text = (
                f"🆔 ID: `{identifier}`\n\n"
                f"👉 *Specify your hostel / location:*\n"
                f"Please select your hostel or location from the 8 options below:"
            )
            kb = build_location_keyboard(prefix="set_loc:")
            await msg.reply_text(text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # Step 3: Location - Custom text typed directly
        # ------------------------------------------------------------------
        if state == STATE_AWAITING_LOCATION:
            location = raw_text
            draft = profile_manager.get_draft(chat_id)
            name = draft.get("full_name") or (tg_user.full_name if tg_user else "Member")
            identifier = draft.get("identifier") or "STUDENT"

            prof = profile_manager.save_profile(
                chat_id,
                full_name=name,
                identifier=identifier,
                location=location,
                username=tg_user.username if tg_user else None,
                user_id=tg_user.id if tg_user else None,
            )

            conf_text = (
                f"✅ *Registration Complete & Verified!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *Name:* *{prof['full_name']}*\n"
                f"🆔 *ID:* `{prof['identifier']}`\n"
                f"📍 *Location:* *{prof['location']}*\n\n"
                f"🛡️ *Security Status:* `ACTIVE & AUTHORIZED`\n\n"
                f"You can now send any food or parcel invoice (photo or document) to begin gate screening!"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
                [InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile")],
            ])
            await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
            await send_post_registration_prompt(context.bot, chat_id)
            return

        # ------------------------------------------------------------------
        # User typing Residence Number
        # ------------------------------------------------------------------
        if state == STATE_AWAITING_RESIDENCE_NO:
            residence_val = raw_text
            if not residence_val.lower().startswith("house") and not residence_val.lower().startswith("residence"):
                residence_loc = f"Residence: {residence_val}"
            else:
                residence_loc = residence_val

            draft = profile_manager.get_draft(chat_id)
            if draft.get("full_name") and draft.get("identifier"):
                # Finishing initial registration
                prof = profile_manager.save_profile(
                    chat_id,
                    full_name=draft["full_name"],
                    identifier=draft["identifier"],
                    location=residence_loc,
                    username=tg_user.username if tg_user else None,
                    user_id=tg_user.id if tg_user else None,
                )
                conf_text = (
                    f"✅ *Registration Complete & Verified!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *Name:* *{prof['full_name']}*\n"
                    f"🆔 *ID:* `{prof['identifier']}`\n"
                    f"📍 *Location:* *{prof['location']}*\n\n"
                    f"🛡️ *Security Status:* `ACTIVE & AUTHORIZED`\n\n"
                    f"You can now send any food or parcel invoice (photo or document) to begin gate screening!"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
                    [InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile")],
                ])
                await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
                await send_post_registration_prompt(context.bot, chat_id)
            else:
                # Updating location of existing profile
                prof = profile_manager.update_location(chat_id, residence_loc)
                name = prof.get("full_name", "Member") if prof else "Member"
                conf_text = (
                    f"✅ *Delivery Location Updated!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *User:* *{name}*\n"
                    f"📍 *New Destination:* *{residence_loc}*\n\n"
                    f"All subsequent delivery screenings will route to this destination."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location Again", callback_data="loc_change")],
                ])
                await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # User typing Others (NAB, Gate 1, Gate 2, Gate 3, building numbers)
        # ------------------------------------------------------------------
        if state == STATE_AWAITING_OTHER_LOCATION:
            other_loc = raw_text
            draft = profile_manager.get_draft(chat_id)
            if draft.get("full_name") and draft.get("identifier"):
                # Finishing initial registration
                prof = profile_manager.save_profile(
                    chat_id,
                    full_name=draft["full_name"],
                    identifier=draft["identifier"],
                    location=other_loc,
                    username=tg_user.username if tg_user else None,
                    user_id=tg_user.id if tg_user else None,
                )
                conf_text = (
                    f"✅ *Registration Complete & Verified!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *Name:* *{prof['full_name']}*\n"
                    f"🆔 *ID:* `{prof['identifier']}`\n"
                    f"📍 *Location:* *{prof['location']}*\n\n"
                    f"🛡️ *Security Status:* `ACTIVE & AUTHORIZED`\n\n"
                    f"You can now send any food or parcel invoice (photo or document) to begin gate screening!"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
                    [InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile")],
                ])
                await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
                await send_post_registration_prompt(context.bot, chat_id)
            else:
                # Updating location of existing profile
                prof = profile_manager.update_location(chat_id, other_loc)
                name = prof.get("full_name", "Member") if prof else "Member"
                conf_text = (
                    f"✅ *Delivery Location Updated!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *User:* *{name}*\n"
                    f"📍 *New Destination:* *{other_loc}*\n\n"
                    f"All subsequent delivery screenings will route to this destination."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location Again", callback_data="loc_change")],
                ])
                await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # Dynamic Location Update (Custom typed when in STATE_CHANGING_LOCATION)
        # ------------------------------------------------------------------
        if state == STATE_CHANGING_LOCATION:
            new_location = raw_text
            prof = profile_manager.update_location(chat_id, new_location)
            name = prof.get("full_name", "Member") if prof else "Member"

            conf_text = (
                f"✅ *Delivery Location Updated!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *User:* *{name}*\n"
                f"📍 *New Destination:* *{new_location}*\n\n"
                f"All subsequent delivery screenings will route to this destination."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Change Location Again", callback_data="loc_change")],
            ])
            await msg.reply_text(conf_text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # Idle State: Recognized user typing general text
        # ------------------------------------------------------------------
        lower_text = raw_text.lower()
        if "location" in lower_text or "change" in lower_text or "room" in lower_text or "hostel" in lower_text:
            await self.handle_change_location(update, context)
            return

        profile = profile_manager.get_profile(chat_id)
        if profile and profile_manager.is_registered(chat_id):
            text = (
                f"👋 Hello *{profile.get('full_name')}*!\n\n"
                f"🆔 *ID:* `{profile.get('identifier')}`\n"
                f"📍 *Current Location:* *{profile.get('location')}*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💬 *Do you want to edit something?*\n"
                f"• Tap *Change Location* to update your hostel or building.\n"
                f"• Tap *Edit Profile* to update your name or ID.\n"
                f"• Or send your invoice photo / PDF directly to begin screening."
            )
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📍 Change Location", callback_data="loc_change"),
                    InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile"),
                ],
                [
                    InlineKeyboardButton("✅ Keep As Is / Ready", callback_data="ready_ack"),
                ],
            ])
            await msg.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        else:
            await self.handle_start(update, context)

    # ------------------------------------------------------------------
    # Incoming Delivery Invoice Processing
    # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Security Verification: Ensure user profile is registered first
        # ------------------------------------------------------------------
        profile = profile_manager.get_profile(chat_id)
        if not profile or not profile_manager.is_registered(chat_id):
            profile_manager.set_state(chat_id, STATE_AWAITING_NAME)
            await message.reply_text(
                "⚠️ *Security Registration Required Before Screening*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "To ensure gate accountability and prevent unauthorized deliveries, "
                "invoices must be linked to a registered campus member.\n\n"
                "Please enter your name:",
                parse_mode="Markdown",
            )
            return

        # Check update_id deduplication
        if update.update_id is not None and self._is_duplicate_update(update.update_id):
            logger.info("Duplicate invoice update_id %s received, skipping.", update.update_id)
            return

        # Identify photo or document
        file_id: Optional[str] = None
        file_unique_id: Optional[str] = None
        file_size: Optional[int] = None
        is_unsupported_doc = False

        if message.photo:
            best_photo = message.photo[-1]
            file_id = best_photo.file_id
            file_unique_id = getattr(best_photo, "file_unique_id", None)
            file_size = getattr(best_photo, "file_size", None)
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
                file_unique_id = getattr(doc, "file_unique_id", None)
                file_size = getattr(doc, "file_size", None)
            else:
                is_unsupported_doc = True

        if is_unsupported_doc:
            await message.reply_text(
                "❌ *Unsupported Document Format*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Please upload a valid invoice photo (JPG, PNG, WEBP) or PDF document.",
                parse_mode="Markdown",
            )
            return

        if not file_id:
            await message.reply_text(
                "❌ *Unsupported File*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Please send an image photo, screenshot, or PDF of your delivery invoice.",
                parse_mode="Markdown",
            )
            return

        # 10 MB cap before downloading
        MAX_INVOICE_BYTES = int(INVOICE_MAX_UPLOAD_MB * 1024 * 1024)
        if isinstance(file_size, int) and file_size > MAX_INVOICE_BYTES:
            logger.warning("Incoming file size %s exceeds %s MB limit for chat %s", file_size, INVOICE_MAX_UPLOAD_MB, chat_id)
            await message.reply_text(
                f"❌ *File Too Large*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"The maximum allowed invoice size is {int(INVOICE_MAX_UPLOAD_MB)} MB. Please upload a smaller or compressed file.",
                parse_mode="Markdown",
            )
            return

        # Deduplication on file_unique_id
        if file_unique_id and self._is_duplicate_file(file_unique_id):
            logger.warning("Duplicate invoice file_unique_id %s from chat %s rejected.", file_unique_id, chat_id)
            await message.reply_text(
                "⚠️ *Duplicate Invoice Detected*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "This exact invoice file has already been received and processed by our servers.",
                parse_mode="Markdown",
            )
            return

        sender_name = profile.get("full_name", "Member")
        sender_id = profile.get("identifier", "STUDENT")
        user_location = profile.get("location", "Campus")
        is_student = is_student_id(sender_id)

        status_msg = await message.reply_text(
            "📤 Your invoice has gone through and has reached the servers for a successful run. Processing details..."
        )

        try:
            tg_file = await context.bot.get_file(file_id)
            tg_size = getattr(tg_file, "file_size", None)
            if isinstance(tg_size, int) and tg_size > MAX_INVOICE_BYTES:
                await status_msg.edit_text(
                    f"❌ File too large: Download size exceeds {int(INVOICE_MAX_UPLOAD_MB)} MB limit."
                )
                return

            file_bytes = await tg_file.download_as_bytearray()
            raw_bytes = bytes(file_bytes)
            if len(raw_bytes) > MAX_INVOICE_BYTES:
                await status_msg.edit_text(
                    f"❌ File too large: File size ({len(raw_bytes)/(1024*1024):.1f} MB) exceeds {int(INVOICE_MAX_UPLOAD_MB)} MB limit."
                )
                return

            caption = message.caption or message.text or ""
            extracted_oid = order_id_from_text(caption)

            # Route gate according to identifier or location
            assigned_gate: Optional[str] = None
            loc_upper = user_location.upper()
            if sender_id.startswith("GATE_") or sender_id in ("GATE1", "GATE2", "GATE3", "GATE 1", "GATE 2", "GATE 3"):
                assigned_gate = sender_id.replace(" ", "_")
            elif "GATE 1" in loc_upper or "GATE_1" in loc_upper or "GATE1" in loc_upper:
                assigned_gate = "GATE_1"
            elif "GATE 2" in loc_upper or "GATE_2" in loc_upper or "GATE2" in loc_upper:
                assigned_gate = "GATE_2"
            elif "GATE 3" in loc_upper or "GATE_3" in loc_upper or "GATE3" in loc_upper:
                assigned_gate = "GATE_3"
            elif any(h in user_location for h in PEC_ALL_HOSTELS):
                # PEC hostels (Shivalik, Aravali, Kurukshetra, Himalaya, Kalpana Chawla, Vindhya) are near Gate 3
                assigned_gate = "GATE_3"

            sender_tag = f"{sender_name} ({sender_id}) · {user_location}"[:50]

            db = SessionLocal()
            try:
                from backend.app.models.delivery import DeliveryDecision, DeliveryOrder, Invoice
                from backend.app.models.enums import AccessState, GuardDecision, OrderStatus, PlatformType
                from backend.app.models.gate import AccessDecision
                from backend.app.models.identity import VehicleOwner

                owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == sender_id).first()
                cust_id = owner.id if owner else None

                # Resolve default guard user for system audit logging
                guard = db.query(User).filter(User.username == "guard1").first()
                if not guard:
                    guard = db.query(User).filter(User.role == "GUARD").first()
                if not guard:
                    guard = db.query(User).first()
                guard_id = guard.id if guard else uuid.uuid4()
                now = datetime.now(timezone.utc)

                if is_student:
                    # ----------------------------------------------------------
                    # Student ID: Run automated OCR & cargo screening model
                    # ----------------------------------------------------------
                    try:
                        invoice = await asyncio.wait_for(
                            asyncio.to_thread(
                                delivery_screening_service.process,
                                db,
                                order_id=extracted_oid,
                                content=raw_bytes,
                                source=DeliverySource.TELEGRAM,
                                sender=sender_tag,
                                gate_id=assigned_gate,
                                platform=None,
                                user_id=None,
                                customer_name=sender_name,
                                customer_id=cust_id,
                            ),
                            timeout=30.0,
                        )
                    except asyncio.TimeoutError:
                        logger.error("Invoice screening timed out after 30s for chat %s", chat_id)
                        await status_msg.edit_text(
                            "⏱️ *Processing Timeout*\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "Invoice screening timed out on the server. Please try submitting again or upload a clearer screenshot.",
                            parse_mode="Markdown",
                        )
                        return
                    except Exception as proc_exc:
                        # If no order ID was given and none could be read, auto-generate fallback ID
                        if "No order ID was given" in str(proc_exc):
                            fallback_oid = f"TG-{uuid.uuid4().hex[:8].upper()}"
                            try:
                                invoice = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        delivery_screening_service.process,
                                        db,
                                        order_id=fallback_oid,
                                        content=raw_bytes,
                                        source=DeliverySource.TELEGRAM,
                                        sender=sender_tag,
                                        gate_id=assigned_gate,
                                        platform=None,
                                        user_id=None,
                                        customer_name=sender_name,
                                        customer_id=cust_id,
                                    ),
                                    timeout=30.0,
                                )
                            except asyncio.TimeoutError:
                                logger.error("Fallback invoice screening timed out after 30s for chat %s", chat_id)
                                await status_msg.edit_text(
                                    "⏱️ *Processing Timeout*\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    "Invoice screening timed out on the server. Please try submitting again or upload a clearer screenshot.",
                                    parse_mode="Markdown",
                                )
                                return
                        else:
                            raise proc_exc

                    order = invoice.order
                    oid = order.order_id
                    vendor = invoice.vendor or (order.restaurant if hasattr(order, "restaurant") else None) or order.platform.value
                    if not vendor or vendor.upper() in ("OTHER", "UNKNOWN", "NONE"):
                        vendor = "Blinkit" if "blinkit" in (invoice.raw_ocr_text or "").lower() or "delivered" in (invoice.raw_ocr_text or "").lower() else "Store / Quick Commerce"
                    total = float(invoice.total_amount or invoice.computed_total or 0.0)
                    is_allowed = (invoice.overall_verdict == ScreeningVerdict.ALLOW)

                    # Automated model decisions - zero manual triage buttons
                    auto_decision = GuardDecision.CLEARED if is_allowed else GuardDecision.HELD
                    access_state = AccessState.ALLOWED if is_allowed else AccessState.DENIED
                    decision_label = (
                        "✅ *AUTO-APPROVED & CLEARED*"
                        if is_allowed
                        else "⚠️ *FLAGGED FOR GATE PHYSICAL SEARCH*"
                    )
                    decision_note = (
                        "Automated model clearance: Verified zero contraband & clean invoice."
                        if is_allowed
                        else f"Automated model screening: Flagged risk ({invoice.overall_verdict.value if invoice.overall_verdict else 'REVIEW'})."
                    )

                    # 1. Record DeliveryDecision in PostgreSQL
                    deliv_decision = DeliveryDecision(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        invoice_id=invoice.id,
                        decision=auto_decision,
                        note=f"[MODEL_AUTO] {decision_note}",
                        decided_by_id=guard_id,
                        decided_at=now,
                    )
                    db.add(deliv_decision)

                    # 2. Record AccessDecision audit record in PostgreSQL
                    plate_str = order.delivery_vehicle_plate or "DELIVERY"
                    gate_id_val = assigned_gate or invoice.gate_id or "GATE_3"
                    access_audit = AccessDecision(
                        id=uuid.uuid4(),
                        plate=plate_str,
                        normalized_plate=plate_str,
                        gate_id=gate_id_val,
                        decision=access_state,
                        reason_code=f"MODEL_{auto_decision.value}",
                        reason=decision_note,
                        confidence=float(invoice.confidence or 1.0),
                        context_data={
                            "screening_source": "TELEGRAM_AUTO_MODEL",
                            "order_id": order.order_id,
                            "student_id": sender_id,
                            "student_name": sender_name,
                            "location": user_location,
                            "restaurant": order.restaurant,
                            "platform": order.platform.value if order.platform else "OTHER",
                            "verdict": invoice.overall_verdict.value if invoice.overall_verdict else "UNKNOWN",
                            "total_amount": total,
                            "items_count": len(invoice.items),
                        },
                        timestamp=now,
                    )
                    db.add(access_audit)

                    # 3. Synchronize DeliveryOrder status
                    order.verification_status = access_state
                    order.status = OrderStatus.OCR_PROCESSED if is_allowed else OrderStatus.REVIEW
                    db.commit()

                    # Extract all item details and quantities
                    item_lines = []
                    for idx, item in enumerate(invoice.items, start=1):
                        qty = item.quantity if (item.quantity is not None and item.quantity > 0) else 1
                        price_val = float(item.total_price or 0.0)
                        price_str = f" — ₹{price_val:,.2f}" if price_val > 0 else ""
                        item_lines.append(f"{idx}. *{item.item_name}* (Qty: *{qty}*){price_str}")

                    if not item_lines:
                        item_lines.append("• _Items verified by cargo screening model_")

                    items_summary = "\n".join(item_lines)
                    match_str = " (Verified)" if invoice.totals_match else ""

                    display_oid = (
                        "Untitled"
                        if (oid.startswith("TG-") or oid.startswith("UNTITLED-") or oid.upper() in RESERVED_ORDER_KEYWORDS)
                        else oid
                    )

                    place_name = order.restaurant or invoice.vendor or "Store / Merchant"
                    plat_val = order.platform.value if order.platform else "Quick Commerce"
                    if plat_val.upper() == "OTHER":
                        plat_val = "Quick Commerce"

                    if order.restaurant and order.restaurant.upper() != plat_val.upper():
                        merchant_info = f"🍽️ *Ordered From:* *{order.restaurant}* (via {plat_val.title()})\n"
                    else:
                        merchant_info = f"🏪 *Ordered From:* *{place_name}*\n"

                    text = (
                        f"✅ *Upload Confirmed: Reached Servers for a Successful Run*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 *Student:* *{sender_name}* (`{sender_id}`)\n"
                        f"📍 *Hostel:* *{user_location}*\n"
                        f"🆔 *Order ID:* `{display_oid}`\n"
                        f"{merchant_info}\n"
                        f"📋 *Item Details & Quantities:*\n"
                        f"{items_summary}\n\n"
                        f"💰 *Bill Total:* *₹{total:,.2f}*{match_str}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🛡️ *Model Decision:* {decision_label}\n"
                        f"ℹ️ _{decision_note}_"
                    )

                else:
                    # ----------------------------------------------------------
                    # Faculty / Residence / Staff ID: Model is NOT run; Direct Auto-Clearance
                    # ----------------------------------------------------------
                    image_rel, preview_rel = delivery_screening_service.store_upload(raw_bytes)
                    oid = extracted_oid or f"TG-FAC-{uuid.uuid4().hex[:8].upper()}"
                    gate_id_val = assigned_gate or "GATE_1"

                    order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == oid).first()
                    if not order:
                        order = DeliveryOrder(
                            order_id=oid,
                            platform=PlatformType.OTHER,
                            gate_id=gate_id_val,
                            customer_name=sender_name,
                            customer_id=cust_id,
                            status=OrderStatus.OCR_PROCESSED,
                            verification_status=AccessState.ALLOWED,
                        )
                        db.add(order)
                        db.flush()
                    else:
                        order.customer_name = sender_name
                        if cust_id:
                            order.customer_id = cust_id
                        order.status = OrderStatus.OCR_PROCESSED
                        order.verification_status = AccessState.ALLOWED

                    invoice = Invoice(
                        order_id=order.id,
                        image_path=image_rel,
                        preview_path=preview_rel,
                        source=DeliverySource.TELEGRAM,
                        sender=sender_tag,
                        gate_id=gate_id_val,
                        overall_verdict=ScreeningVerdict.ALLOW,
                        reply_text="Faculty / Campus Resident direct gate pass. Cargo model screening exempted.",
                        created_by_id=guard_id,
                    )
                    db.add(invoice)
                    db.flush()

                    deliv_decision = DeliveryDecision(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        invoice_id=invoice.id,
                        decision=GuardDecision.CLEARED,
                        note="Exempted: Faculty / Campus Resident auto-clearance (model screening bypassed).",
                        decided_by_id=guard_id,
                        decided_at=now,
                    )
                    db.add(deliv_decision)

                    access_audit = AccessDecision(
                        id=uuid.uuid4(),
                        plate=order.delivery_vehicle_plate or "DELIVERY",
                        normalized_plate=order.delivery_vehicle_plate or "DELIVERY",
                        gate_id=gate_id_val,
                        decision=AccessState.ALLOWED,
                        reason_code="EXEMPT_FACULTY_RESIDENT",
                        reason="Faculty / Campus Resident delivery auto-approved without cargo screening model.",
                        confidence=1.0,
                        context_data={
                            "screening_source": "TELEGRAM_FACULTY_RESIDENT_EXEMPT",
                            "order_id": order.order_id,
                            "customer_name": sender_name,
                            "identifier": sender_id,
                            "location": user_location,
                        },
                        timestamp=now,
                    )
                    db.add(access_audit)
                    db.commit()

                    display_oid = (
                        "Untitled"
                        if (oid.startswith("TG-") or oid.startswith("UNTITLED-") or oid.upper() in RESERVED_ORDER_KEYWORDS)
                        else oid
                    )

                    place_name = order.restaurant or invoice.vendor or "Store / Merchant"
                    plat_val = order.platform.value if order.platform else "Direct Delivery"
                    if plat_val.upper() == "OTHER":
                        plat_val = "Direct Delivery"

                    if order.restaurant and order.restaurant.upper() != plat_val.upper():
                        merchant_info = f"🍽️ *Ordered From:* *{order.restaurant}* (via {plat_val.title()})\n"
                    else:
                        merchant_info = f"🏪 *Ordered From:* *{place_name}*\n"

                    text = (
                        f"✅ *Upload Confirmed: Reached Servers for a Successful Run*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 *Recipient:* *{sender_name}* (`{sender_id}`)\n"
                        f"📍 *Campus Destination:* *{user_location}*\n"
                        f"🆔 *Order ID:* `{display_oid}`\n"
                        f"{merchant_info}\n"
                        f"🛡️ *Model Status:* ⚡ *EXEMPT (Faculty / Resident)*\n"
                        f"✅ *Clearance:* *AUTO-APPROVED & CLEARED FOR GATE ENTRY*\n\n"
                        f"ℹ️ _Contraband screening model is only enforced for student deliveries. Faculty, staff, and campus residential deliveries are cleared automatically._"
                    )

                # Send response with NO manual approval/disapproval buttons
                await status_msg.edit_text(text, reply_markup=None, parse_mode="Markdown")
            finally:
                db.close()
        except Exception as exc:
            logger.exception("Error processing invoice from Telegram: %s", exc)
            await status_msg.edit_text(f"❌ Failed to process invoice: {str(exc)}")

    # ------------------------------------------------------------------
    # Callback Query Router (Triage, Onboarding, Location Updates)
    # ------------------------------------------------------------------
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._is_chat_allowed(chat_id):
            await query.answer("⛔ Unauthorized chat.", show_alert=True)
            return

        data = query.data or ""

        # ------------------------------------------------------------------
        # 1. Returning User: Profile Confirmation Pop-up
        # ------------------------------------------------------------------
        if data == "ready_ack":
            await query.answer("✅ Profile confirmed! Ready to receive and screen your delivery invoices.", show_alert=True)
            profile = profile_manager.get_profile(chat_id)
            name = profile.get("full_name", "Member") if profile else "Member"
            ident = profile.get("identifier", "ID") if profile else "ID"
            loc = profile.get("location", "PEC Campus") if profile else "PEC Campus"
            text = (
                f"✅ *Profile Confirmed & Ready*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• *User:* *{name}* (`{ident}`)\n"
                f"• *Destination:* *{loc}*\n\n"
                f"📸 Send your delivery invoice photo or document anytime!"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # 2. Location Change Trigger
        # ------------------------------------------------------------------
        if data == "loc_change":
            await query.answer()
            profile = profile_manager.get_profile(chat_id)
            if not profile or not profile_manager.is_registered(chat_id):
                profile_manager.set_state(chat_id, STATE_AWAITING_NAME)
                await query.edit_message_text("👉 Please enter your name:", parse_mode="Markdown")
                return

            profile_manager.set_state(chat_id, STATE_CHANGING_LOCATION)
            text = (
                f"📍 *Update Campus Delivery Location*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *User:* *{profile.get('full_name')}*\n"
                f"🆔 *ID:* `{profile.get('identifier')}`\n"
                f"📍 *Current Location:* *{profile.get('location')}*\n\n"
                f"Please select your destination from the 8 options below:"
            )
            kb = build_location_keyboard(prefix="set_loc:")
            kb_rows = list(kb.inline_keyboard)
            kb_rows.append([InlineKeyboardButton("❌ Keep Current Location", callback_data="cancel_loc")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # 3. Location Selection from 8 options
        # ------------------------------------------------------------------
        if data.startswith("set_loc:"):
            target_loc = data[len("set_loc:"):]

            # Option 7: Residence Number
            if target_loc == "__RESIDENCE__":
                await query.answer()
                profile_manager.set_state(chat_id, STATE_AWAITING_RESIDENCE_NO)
                prompt_text = (
                    "🏡 *Enter your Residence Number:*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Please type your residence or house number below:\n"
                    "_(Example: House 42, Campus Enclave or Type-IV Quarter 15)_"
                )
                await query.edit_message_text(prompt_text, parse_mode="Markdown")
                return

            # Option 8: Others (NAB, Gate 1, Gate 2, Gate 3, building numbers)
            if target_loc == "__OTHERS__":
                await query.answer()
                profile_manager.set_state(chat_id, STATE_AWAITING_OTHER_LOCATION)
                prompt_text = (
                    "📍 *Enter your Location:*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Please type your building, facility, or gate below:\n"
                    "_(Example: NAB, Gate 1, Gate 2, Gate 3, Admin Block, Workshop)_"
                )
                await query.edit_message_text(prompt_text, parse_mode="Markdown")
                return

            # Options 1-6: One of the 6 PEC Hostels
            await query.answer(f"Selected {target_loc}!")
            state = profile_manager.get_state(chat_id)

            if state == STATE_AWAITING_LOCATION:
                # Completing initial registration
                draft = profile_manager.get_draft(chat_id)
                name = draft.get("full_name") or (query.from_user.full_name if query.from_user else "Member")
                identifier = draft.get("identifier") or "STUDENT"
                prof = profile_manager.save_profile(
                    chat_id,
                    full_name=name,
                    identifier=identifier,
                    location=target_loc,
                    username=query.from_user.username if query.from_user else None,
                    user_id=query.from_user.id if query.from_user else None,
                )
                conf_text = (
                    f"✅ *Registration Complete & Verified!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *Name:* *{prof['full_name']}*\n"
                    f"🆔 *ID:* `{prof['identifier']}`\n"
                    f"📍 *Location:* *{prof['location']}*\n\n"
                    f"🛡️ *Security Status:* `ACTIVE & AUTHORIZED`\n\n"
                    f"You can now send any food or parcel invoice (photo or document) to begin gate screening!"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location", callback_data="loc_change")],
                    [InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile")],
                ])
                await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="Markdown")
                await send_post_registration_prompt(context.bot, chat_id)
            else:
                # Dynamic update of existing profile
                prof = profile_manager.update_location(chat_id, target_loc)
                name = prof.get("full_name", "Member") if prof else "Member"
                conf_text = (
                    f"✅ *Delivery Location Updated!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *User:* *{name}*\n"
                    f"📍 *New Destination:* *{target_loc}*\n\n"
                    f"All subsequent delivery screenings will route to this destination."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📍 Change Location Again", callback_data="loc_change")],
                ])
                await query.edit_message_text(conf_text, reply_markup=kb, parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # 4. Profile Editing Trigger
        # ------------------------------------------------------------------
        if data == "edit_profile":
            await query.answer("✏️ Editing profile...", show_alert=False)
            profile_manager.set_state(chat_id, STATE_AWAITING_NAME)
            await query.edit_message_text(
                "✏️ *Edit Security Profile*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Please enter your name:",
                parse_mode="Markdown",
            )
            return

        # ------------------------------------------------------------------
        # 5. Cancel Location Change
        # ------------------------------------------------------------------
        if data == "cancel_loc":
            await query.answer("Location update cancelled.")
            profile_manager.clear_state(chat_id)
            profile = profile_manager.get_profile(chat_id)
            loc = profile.get("location", "Campus") if profile else "Campus"
            await query.edit_message_text(f"👌 Location update cancelled. Kept current location: *{loc}*", parse_mode="Markdown")
            return

        # ------------------------------------------------------------------
        # 6. Interactive Guard Triage Callback Handler
        # ------------------------------------------------------------------
        if not data.startswith("triage:"):
            await query.answer()
            return

        # Enforce Guard role: reject non-guard chat_ids with an alert
        if not self._is_guard_chat(chat_id):
            logger.warning("Unauthorized triage callback attempt by non-guard chat_id %s", chat_id)
            await query.answer("Unauthorized: Guard role required", show_alert=True)
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
            prof = profile_manager.get_profile(chat_id)
            guard = None
            if prof:
                guard = db.query(User).filter(User.username == prof.get("identifier")).first()
            if not guard:
                guard = db.query(User).filter(User.role == "GUARD").first()
            if not guard:
                guard = db.query(User).filter(User.username == "guard1").first()
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
            if update.update_id is not None and self._is_duplicate_update(update.update_id):
                logger.info("Ignoring duplicate webhook update_id %s", update.update_id)
                return True
            await self.application.process_update(update)
            return True
        return False


telegram_service = TelegramBotService()
