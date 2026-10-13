from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class WhatsAppProvider(ABC):
    """
    Abstract WhatsApp provider interface.
    Allows swapping between local mock and Meta WhatsApp Cloud API / Twilio in production.
    """

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
            "media_type": "..."
        }
        """
        pass
