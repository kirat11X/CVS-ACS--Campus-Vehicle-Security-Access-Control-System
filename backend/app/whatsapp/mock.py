import uuid
import time
from typing import Dict, Any, Optional, List
from backend.app.whatsapp.base import WhatsAppProvider

class MockWhatsAppProvider(WhatsAppProvider):
    """
    Local mock implementation of WhatsAppProvider for offline development and testing.
    """

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.received_webhooks: List[Dict[str, Any]] = []

    def is_available(self) -> bool:
        # Mock provider is always available locally
        return True

    def send_message(self, to_phone: str, text: str) -> Dict[str, Any]:
        msg_id = f"mock_msg_{uuid.uuid4().hex[:8]}"
        record = {
            "id": msg_id,
            "to": to_phone,
            "text": text,
            "timestamp": time.time(),
            "status": "delivered"
        }
        self.sent_messages.append(record)
        return record

    def parse_incoming_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.received_webhooks.append(payload)
        # Handle simple mock webhook payload or Meta-like simulation
        sender = payload.get("sender") or payload.get("from") or "mock_user"
        message_id = payload.get("id") or f"msg_{uuid.uuid4().hex[:8]}"
        text = payload.get("text") or payload.get("body") or ""
        media_url = payload.get("media_url") or payload.get("image_url")
        media_type = payload.get("media_type", "image" if media_url else "text")

        return {
            "sender": sender,
            "message_id": message_id,
            "text": text,
            "media_url": media_url,
            "media_type": media_type
        }

mock_whatsapp = MockWhatsAppProvider()
