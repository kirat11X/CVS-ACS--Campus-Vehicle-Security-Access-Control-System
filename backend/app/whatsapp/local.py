import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.config import MEDIA_ROOT
from backend.app.whatsapp.mock import MockWhatsAppProvider

logger = logging.getLogger("campus_security.whatsapp")

class LocalIntakeProvider(MockWhatsAppProvider):
    """
    Default provider while the WhatsApp Business API is not available.

    Riders (or the guard) open the LAN intake page (GET /intake) on a phone and upload the
    invoice there; the reply that would have gone back on chat is shown on the result page
    and appended to an outbox file (media/whatsapp_outbox/outbox.jsonl) so it stays visible.
    Webhook payloads use the same simple format as the mock (n8n can forward them).
    """

    name = "local"

    def __init__(self, outbox_path: Optional[Path] = None):
        super().__init__()
        self.outbox_path = outbox_path or (MEDIA_ROOT / "whatsapp_outbox" / "outbox.jsonl")
        self._lock = threading.Lock()
        self._count = self._count_existing()

    def _count_existing(self) -> int:
        try:
            with open(self.outbox_path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except FileNotFoundError:
            return 0
        except OSError as exc:
            logger.warning("Cannot read WhatsApp outbox %s: %s", self.outbox_path, exc)
            return 0

    def send_message(self, to_phone: str, text: str) -> Dict[str, Any]:
        record = {
            "id": f"local_msg_{uuid.uuid4().hex[:8]}",
            "to": to_phone or "",
            "text": text,
            "timestamp": time.time(),
            "status": "stored",  # shown on the intake result page; nothing leaves the LAN
        }
        with self._lock:
            self.sent_messages.append(record)
            del self.sent_messages[:-200]  # keep the in-memory tail small
            try:
                self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.outbox_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError as exc:
                logger.warning("Cannot append to WhatsApp outbox %s: %s", self.outbox_path, exc)
            self._count += 1
        return record

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(reversed(self.sent_messages[-limit:]))

    def outbox_count(self) -> int:
        return self._count


# Canonical naming alias
LocalIntakeWhatsAppProvider = LocalIntakeProvider
