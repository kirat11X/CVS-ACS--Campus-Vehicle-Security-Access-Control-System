import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status

from backend.app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_MODE
from backend.app.telegram.bot_service import telegram_service

logger = logging.getLogger("campus_security.telegram.routes")

router = APIRouter(tags=["Telegram Connector"])


@router.post("/telegram/webhook", status_code=status.HTTP_200_OK)
@router.post("/api/telegram/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> Dict[str, Any]:
    """
    Receives incoming webhook updates from Telegram's Bot API (TELEGRAM_MODE=webhook).
    Validates optional secret token header and routes update through TelegramBotService.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Malformed JSON in Telegram webhook: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload.")

    try:
        success = await telegram_service.process_webhook_update(
            body,
            secret_token=x_telegram_bot_api_secret_token,
        )
        return {"ok": success}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        logger.exception("Error processing Telegram webhook: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Webhook error: {str(exc)}")


@router.get("/telegram/status", status_code=status.HTTP_200_OK)
@router.get("/api/telegram/status", status_code=status.HTTP_200_OK)
def telegram_status() -> Dict[str, Any]:
    """Returns runtime health and configuration metadata for the Telegram Bot Connector."""
    return {
        "status": "online" if telegram_service.is_running else ("configured" if telegram_service.is_configured else "disabled"),
        "mode": telegram_service.mode,
        "is_configured": telegram_service.is_configured,
        "is_running": telegram_service.is_running,
        "allowed_chat_ids": telegram_service.allowed_chat_ids,
    }
