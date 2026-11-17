from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

class WhatsAppProvider(ABC):
    """
    Abstract WhatsApp provider interface.
    Allows swapping between the LAN intake (local), the in-memory mock and the
    Meta WhatsApp Cloud API without touching the delivery screening code.
    """

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider credentials and network connectivity are operational."""
        pass

    @abstractmethod
    def send_message(self, to_phone: str, text: str) -> Dict[str, Any]:
        """Send a plain text message to a user."""
        pass

    @abstractmethod
    def parse_incoming_webhook(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse raw webhook payload into a normalized format:
        {
            "sender": "...",
            "message_id": "...",
            "text": "...",
            "media_url": "...",
            "media_type": "...",
            "media_id": "...",        # provider media handle (Meta), optional
            "media_base64": "...",    # inline file content (n8n forwarding), optional
            "media_mime": "...",      # optional
            "filename": "..."         # optional
        }
        """
        pass

    def fetch_media(self, message: Dict[str, Any]) -> Optional[Tuple[bytes, Optional[str]]]:
        """
        Returns (content, mime type) of a parsed message's attachment, or None. The default
        accepts inline base64 only: arbitrary media URLs are not fetched from a public webhook.
        """
        import base64
        import binascii
        data = message.get("media_base64")
        if not data:
            return None
        try:
            return base64.b64decode(data, validate=False), message.get("media_mime")
        except (binascii.Error, ValueError):
            return None

    def outbox_count(self) -> int:
        """Replies sent (or stored for display) since this provider was created."""
        return 0
