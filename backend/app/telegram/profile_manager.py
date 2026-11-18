"""
Telegram User Profile & Onboarding State Manager
------------------------------------------------
Persists verified Telegram user profiles (name, ID, location, visit count)
both to persistent JSON and directly to the PostgreSQL database (telegram_users
and vehicle_owners tables), ensuring full institutional visibility, analytics,
and relational linking.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("campus_security.telegram.profiles")

# Onboarding conversation states
STATE_IDLE = "IDLE"
STATE_AWAITING_NAME = "AWAITING_NAME"
STATE_AWAITING_ID = "AWAITING_ID"
STATE_AWAITING_LOCATION = "AWAITING_LOCATION"
STATE_AWAITING_RESIDENCE_NO = "AWAITING_RESIDENCE_NO"
STATE_AWAITING_OTHER_LOCATION = "AWAITING_OTHER_LOCATION"
STATE_CHANGING_LOCATION = "CHANGING_LOCATION"

# Authoritative PEC Chandigarh Hostels (4 Boys' Hostels + 2 Girls' Hostels)
PEC_BOYS_HOSTELS: List[str] = [
    "Shivalik Hostel",
    "Aravali Hostel",
    "Kurukshetra Hostel",
    "Himalaya Hostel",
]

PEC_GIRLS_HOSTELS: List[str] = [
    "Kalpana Chawla Hostel",
    "Vindhya Hostel",
]

PEC_ALL_HOSTELS: List[str] = PEC_BOYS_HOSTELS + PEC_GIRLS_HOSTELS


class TelegramProfileManager:
    """Thread-safe, dual-persisted repository (PostgreSQL + JSON backup) for Telegram credentials & locations."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            storage_path = repo_root / "data" / "telegram_profiles.json"

        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()
        self._profiles: Dict[int, Dict[str, Any]] = {}
        self._states: Dict[int, str] = {}
        self._drafts: Dict[int, Dict[str, Any]] = {}

        self._load()

    def _load(self) -> None:
        """Loads profiles from JSON storage and syncs from PostgreSQL as the authoritative source of truth."""
        with self._lock:
            # 1. Load profiles from JSON backup if available
            if self.storage_path.is_file():
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                        self._profiles = {int(k): v for k, v in raw.items()}
                    logger.info("Loaded %d Telegram user profiles from %s", len(self._profiles), self.storage_path)
                except Exception as exc:
                    logger.warning("Failed to parse Telegram profiles file %s: %s", self.storage_path, exc)
                    self._profiles = {}

            # 2. Always query PostgreSQL telegram_users table as the authoritative source of truth
            try:
                from backend.app.db import SessionLocal
                from backend.app.models.identity import TelegramUser
                with SessionLocal() as db:
                    rows = db.query(TelegramUser).all()
                    db_synced = False
                    for r in rows:
                        self._profiles[r.chat_id] = {
                            "chat_id": r.chat_id,
                            "user_id": r.user_id or r.chat_id,
                            "username": r.username or "",
                            "full_name": r.full_name,
                            "identifier": r.identifier,
                            "location": r.location,
                            "visit_count": r.visit_count,
                            "created_at": r.created_at.isoformat() if r.created_at else "",
                            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                        }
                        db_synced = True
                    if rows:
                        logger.info("Synced %d Telegram user profiles from authoritative PostgreSQL database", len(rows))
                    if db_synced:
                        self._save()
            except Exception as db_exc:
                logger.debug("Could not query telegram_users from PostgreSQL on startup: %s", db_exc)

    def _save(self) -> None:
        """Atomically saves profiles to disk."""
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                temp_dir = self.storage_path.parent
                with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
                    json.dump(self._profiles, tf, indent=2)
                    temp_name = tf.name
                os.replace(temp_name, self.storage_path)
            except Exception as exc:
                logger.error("Failed to write Telegram profiles file %s: %s", self.storage_path, exc)

    def sync_to_db(
        self,
        chat_id: int,
        *,
        full_name: str,
        identifier: str,
        location: str,
        visit_count: int = 1,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> None:
        """
        Synchronizes the Telegram user to PostgreSQL:
        1. Persists to the dedicated `telegram_users` table.
        2. Upserts into `vehicle_owners` (institutional members table) so the person's
           Name, ID, and Venue/Hostel are fully visible across the platform and queries.
        """
        try:
            from backend.app.db import SessionLocal
            from backend.app.models.identity import TelegramUser, VehicleOwner
            from backend.app.models.enums import PersonType, ResidenceType

            with SessionLocal() as db:
                # 1. Upsert telegram_users table
                tg_user = db.query(TelegramUser).filter(TelegramUser.chat_id == chat_id).first()
                if not tg_user:
                    tg_user = TelegramUser(
                        chat_id=chat_id,
                        user_id=user_id,
                        username=username,
                        full_name=full_name,
                        identifier=identifier,
                        location=location,
                        visit_count=visit_count,
                    )
                    db.add(tg_user)
                else:
                    tg_user.full_name = full_name
                    tg_user.identifier = identifier
                    tg_user.location = location
                    tg_user.visit_count = visit_count
                    if username:
                        tg_user.username = username
                    if user_id:
                        tg_user.user_id = user_id

                # 2. Upsert vehicle_owners table in PostgreSQL
                owner = db.query(VehicleOwner).filter(VehicleOwner.identifier == identifier).first()

                res_type = ResidenceType.OFF_CAMPUS
                if any(h in location for h in PEC_ALL_HOSTELS) or "hostel" in location.lower():
                    res_type = ResidenceType.HOSTELLER
                elif "house" in location.lower() or "residence" in location.lower() or "flat" in location.lower() or "enclave" in location.lower():
                    res_type = ResidenceType.CAMPUS_RESIDENT

                p_type = PersonType.STUDENT
                if identifier.startswith("F"):
                    p_type = PersonType.FACULTY
                elif identifier.startswith("STF") or identifier.startswith("G"):
                    p_type = PersonType.STAFF
                elif identifier.startswith("R") and identifier[1:].isdigit():
                    p_type = PersonType.RESIDENT

                if not owner:
                    owner = VehicleOwner(
                        identifier=identifier,
                        full_name=full_name,
                        residence=location,
                        department_or_hostel=location,
                        residence_type=res_type,
                        person_type=p_type,
                        status="ACTIVE",
                    )
                    db.add(owner)
                else:
                    owner.full_name = full_name
                    owner.residence = location
                    owner.department_or_hostel = location
                    owner.residence_type = res_type

                db.commit()
                logger.info(
                    "Successfully synced Telegram user & VehicleOwner to PostgreSQL: %s (ID: %s, Venue: %s)",
                    full_name,
                    identifier,
                    location,
                )
        except Exception as exc:
            logger.warning("Failed to sync Telegram profile to PostgreSQL: %s", exc)

    # ------------------------------------------------------------------
    # Profile Access & Mutation
    # ------------------------------------------------------------------
    def get_profile(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Returns the registered profile for chat_id, or None if unverified."""
        with self._lock:
            p = self._profiles.get(chat_id)
            return dict(p) if p else None

    def is_registered(self, chat_id: int) -> bool:
        """Checks if the user has completed name, ID, and location registration."""
        p = self.get_profile(chat_id)
        if not p:
            return False
        return bool(p.get("full_name") and p.get("identifier") and p.get("location"))

    def record_visit(self, chat_id: int) -> int:
        """Increments and returns the user's visit counter, saving to disk and PostgreSQL."""
        with self._lock:
            p = self._profiles.get(chat_id)
            if not p:
                return 1
            p["visit_count"] = p.get("visit_count", 1) + 1
            p["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            snapshot = dict(p)

        # Sync to PostgreSQL
        self.sync_to_db(
            chat_id,
            full_name=snapshot["full_name"],
            identifier=snapshot["identifier"],
            location=snapshot["location"],
            visit_count=snapshot["visit_count"],
            username=snapshot.get("username"),
            user_id=snapshot.get("user_id"),
        )
        return snapshot["visit_count"]

    def save_profile(
        self,
        chat_id: int,
        *,
        full_name: str,
        identifier: str,
        location: str,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Saves a complete user profile to memory, JSON file, and PostgreSQL."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = self._profiles.get(chat_id, {})
            visit_count = existing.get("visit_count", 1)

            profile: Dict[str, Any] = {
                "chat_id": chat_id,
                "user_id": user_id or existing.get("user_id") or chat_id,
                "username": username or existing.get("username") or "",
                "full_name": full_name.strip(),
                "identifier": identifier.strip().upper(),
                "location": location.strip(),
                "visit_count": visit_count,
                "created_at": existing.get("created_at", now_str),
                "updated_at": now_str,
            }

            self._profiles[chat_id] = profile
            self._save()
            self._states.pop(chat_id, None)
            self._drafts.pop(chat_id, None)
            snapshot = dict(profile)

        # Sync to PostgreSQL (telegram_users + vehicle_owners)
        self.sync_to_db(
            chat_id,
            full_name=snapshot["full_name"],
            identifier=snapshot["identifier"],
            location=snapshot["location"],
            visit_count=visit_count,
            username=snapshot["username"],
            user_id=snapshot["user_id"],
        )
        return snapshot

    def update_location(self, chat_id: int, new_location: str) -> Optional[Dict[str, Any]]:
        """Updates the user's campus location and persists to memory, JSON, and PostgreSQL."""
        with self._lock:
            p = self._profiles.get(chat_id)
            if not p:
                return None
            p["location"] = new_location.strip()
            p["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            self._states.pop(chat_id, None)
            self._drafts.pop(chat_id, None)
            snapshot = dict(p)

        # Sync to PostgreSQL
        self.sync_to_db(
            chat_id,
            full_name=snapshot["full_name"],
            identifier=snapshot["identifier"],
            location=snapshot["location"],
            visit_count=snapshot.get("visit_count", 1),
            username=snapshot.get("username"),
            user_id=snapshot.get("user_id"),
        )
        return snapshot

    def delete_profile(self, chat_id: int) -> bool:
        """Deletes a profile from memory, JSON, and PostgreSQL."""
        deleted = False
        with self._lock:
            if chat_id in self._profiles:
                del self._profiles[chat_id]
                self._save()
                deleted = True
            self._states.pop(chat_id, None)
            self._drafts.pop(chat_id, None)

        try:
            from backend.app.db import SessionLocal
            from backend.app.models.identity import TelegramUser
            with SessionLocal() as db:
                row = db.query(TelegramUser).filter(TelegramUser.chat_id == chat_id).first()
                if row:
                    db.delete(row)
                    db.commit()
                    deleted = True
        except Exception as exc:
            logger.debug("Failed deleting from telegram_users table: %s", exc)

        return deleted

    # ------------------------------------------------------------------
    # Onboarding State Machine
    # ------------------------------------------------------------------
    def get_state(self, chat_id: int) -> str:
        """Returns the current conversational onboarding state for chat_id."""
        with self._lock:
            return self._states.get(chat_id, STATE_IDLE)

    def set_state(self, chat_id: int, state: str, draft_data: Optional[Dict[str, Any]] = None) -> None:
        """Sets the conversational state and merges draft onboarding data."""
        with self._lock:
            self._states[chat_id] = state
            if draft_data:
                curr = self._drafts.setdefault(chat_id, {})
                curr.update(draft_data)

    def get_draft(self, chat_id: int) -> Dict[str, Any]:
        """Returns current draft data accumulated during onboarding."""
        with self._lock:
            return dict(self._drafts.setdefault(chat_id, {}))

    def clear_state(self, chat_id: int) -> None:
        """Resets the state to IDLE and wipes draft onboarding data."""
        with self._lock:
            self._states.pop(chat_id, None)
            self._drafts.pop(chat_id, None)


profile_manager = TelegramProfileManager()
