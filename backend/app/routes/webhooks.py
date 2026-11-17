import hashlib
import hmac
import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.app.config import INVOICE_MAX_UPLOAD_MB, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
from backend.app.dependencies import get_db
from backend.app.models.enums import DeliverySource
from backend.app.routes.intake import screen_and_reply
from backend.app.whatsapp import get_whatsapp_provider

router = APIRouter(prefix="/webhooks", tags=["WhatsApp"])

# "Order D-20481", "#D-20481", "order id: ORD-2026-9821", or a bare "D-20481"
_ORDER_IN_TEXT = re.compile(r"(?:order\s*(?:id|no\.?|number)?\s*[:#]?\s*#?\s*|#)?\b([A-Z]{1,6}-?\d[A-Z0-9-]{2,})\b", re.IGNORECASE)

def order_id_from_text(text: Optional[str]) -> Optional[str]:
    m = _ORDER_IN_TEXT.search(text or "")
    return m.group(1).upper() if m else None

@router.get("/whatsapp", response_class=PlainTextResponse)
def verify_subscription(
    mode: Optional[str] = Query(None, alias="hub.mode"),
    token: Optional[str] = Query(None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta webhook subscription handshake (needs WHATSAPP_VERIFY_TOKEN)."""
    if mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and token and hmac.compare_digest(token, WHATSAPP_VERIFY_TOKEN):
        return challenge or ""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed.")

@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Provider-agnostic inbound chat message (n8n can forward here). The configured provider parses
    the payload; an attached invoice (Meta media id, or inline media_base64 for local / mock) is
    screened and the reply goes back through the same provider. Arbitrary media URLs are not fetched.
    """
    raw = await request.body()
    if len(raw) > INVOICE_MAX_UPLOAD_MB * 1.4 * 1024 * 1024:  # base64 overhead
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large.")
    provider = get_whatsapp_provider()
    if provider.name == "meta" and WHATSAPP_APP_SECRET:
        expected = "sha256=" + hmac.new(WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bad signature.")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object.")

    message = provider.parse_incoming_webhook(payload)
    if not message:
        return {"status": "ignored", "provider": provider.name}  # e.g. delivery receipts
    sender = message.get("sender")
    order_id = order_id_from_text(message.get("text"))
    media = await run_in_threadpool(provider.fetch_media, message)
    if not media:
        reply = "Please send a photo of the invoice together with the order ID (e.g. D-20481)."
        provider.send_message(sender or "", reply)
        return {"status": "needs_invoice", "provider": provider.name, "reply_text": reply}

    content, _ = media
    try:
        detail = await run_in_threadpool(
            screen_and_reply, db, order_id=order_id, content=content, source=DeliverySource.WHATSAPP,
            sender=sender, gate_id=payload.get("gate_id") if isinstance(payload.get("gate_id"), str) else None,
        )
    except HTTPException as exc:
        reply = str(exc.detail)
        provider.send_message(sender or "", reply)
        return {"status": "rejected", "provider": provider.name, "reply_text": reply}
    return {
        "status": "screened",
        "provider": provider.name,
        "order_id": detail.order_id,
        "overall": detail.overall.value,
        "reply_text": detail.reply_text,
    }
