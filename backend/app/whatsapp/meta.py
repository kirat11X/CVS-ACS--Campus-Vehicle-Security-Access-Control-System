import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from backend.app.config import WHATSAPP_GRAPH_VERSION, WHATSAPP_PHONE_ID, WHATSAPP_TOKEN
from backend.app.whatsapp.base import WhatsAppProvider

logger = logging.getLogger("campus_security.whatsapp")

_PLACEHOLDER_PREFIXES = ("mock", "change-me", "your_", "<")

def _configured(value: str) -> bool:
    return bool(value) and not value.strip().lower().startswith(_PLACEHOLDER_PREFIXES)

class MetaCloudWhatsAppProvider(WhatsAppProvider):
    """
    WhatsApp Cloud API (Meta Graph) provider, for when a Business account exists.
    Reads WHATSAPP_TOKEN / WHATSAPP_PHONE_ID (older names WHATSAPP_API_TOKEN /
    WHATSAPP_PHONE_NUMBER_ID also accepted) and reports unavailable while they are missing
    or still placeholders. Not exercised against the real API yet: treat as a stub.
    """

    name = "meta"

    def __init__(self, token: str = WHATSAPP_TOKEN, phone_id: str = WHATSAPP_PHONE_ID, graph_version: str = WHATSAPP_GRAPH_VERSION):
        self.token = token
        self.phone_id = phone_id
        self.base = f"https://graph.facebook.com/{graph_version}"
        self._sent = 0

    def is_available(self) -> bool:
        return _configured(self.token) and _configured(self.phone_id)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def send_message(self, to_phone: str, text: str) -> Dict[str, Any]:
        if not self.is_available():
            return {"status": "not_sent", "reason": "WHATSAPP_TOKEN / WHATSAPP_PHONE_ID not configured", "to": to_phone, "text": text}
        body = {"messaging_product": "whatsapp", "to": to_phone, "type": "text", "text": {"body": text}}
        try:
            resp = httpx.post(f"{self.base}/{self.phone_id}/messages", json=body, headers=self._headers(), timeout=10.0)
        except httpx.HTTPError as exc:
            logger.warning("WhatsApp Cloud API send failed: %s", exc)
            return {"status": "failed", "reason": str(exc), "to": to_phone, "text": text}
        if resp.status_code >= 400:
            return {"status": "failed", "reason": resp.text[:300], "to": to_phone, "text": text}
        self._sent += 1
        ids = [m.get("id") for m in resp.json().get("messages", [])]
        return {"status": "sent", "id": ids[0] if ids else None, "to": to_phone, "text": text}

    def parse_incoming_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """entry[].changes[].value.messages[0] of a Cloud API notification; None for status callbacks."""
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            msg = value["messages"][0]
        except (KeyError, IndexError, TypeError):
            return None
        kind = msg.get("type", "text")
        media = msg.get(kind) if kind in ("image", "document") else None
        text = (msg.get("text") or {}).get("body") or (media or {}).get("caption") or ""
        return {
            "sender": msg.get("from"),
            "message_id": msg.get("id"),
            "text": text,
            "media_url": None,
            "media_type": kind,
            "media_id": (media or {}).get("id"),
            "media_mime": (media or {}).get("mime_type"),
            "filename": (media or {}).get("filename"),
        }

    def fetch_media(self, message: Dict[str, Any]) -> Optional[Tuple[bytes, Optional[str]]]:
        media_id = message.get("media_id")
        if not media_id or not self.is_available():
            return super().fetch_media(message)
        try:
            meta = httpx.get(f"{self.base}/{media_id}", headers=self._headers(), timeout=10.0)
            meta.raise_for_status()
            url = meta.json().get("url")
            if not url:
                return None
            content = httpx.get(url, headers=self._headers(), timeout=20.0)
            content.raise_for_status()
            return content.content, content.headers.get("content-type") or message.get("media_mime")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("WhatsApp Cloud API media download failed: %s", exc)
            return None

    def outbox_count(self) -> int:
        return self._sent


# Canonical naming alias
CloudAPIWhatsAppProvider = MetaCloudWhatsAppProvider
