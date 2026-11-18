import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_MODE,
    TELEGRAM_WEBHOOK_SECRET,
)
from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.identity import TelegramUser
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
    Enforces mandatory TELEGRAM_WEBHOOK_SECRET validation when TELEGRAM_MODE=webhook.
    Routes update through TelegramBotService.
    """
    if TELEGRAM_MODE == "webhook":
        if not TELEGRAM_WEBHOOK_SECRET:
            logger.error("TELEGRAM_MODE is webhook but TELEGRAM_WEBHOOK_SECRET is not configured.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="TELEGRAM_WEBHOOK_SECRET must be configured when TELEGRAM_MODE=webhook.",
            )
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing X-Telegram-Bot-Api-Secret-Token header.",
            )
    elif TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid X-Telegram-Bot-Api-Secret-Token header.",
        )

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
        "guard_chat_ids": telegram_service.guard_chat_ids,
    }


@router.get("/telegram/users", status_code=status.HTTP_200_OK)
@router.get("/api/telegram/users", status_code=status.HTTP_200_OK)
def list_telegram_users(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
) -> Dict[str, Any]:
    """
    Returns all verified Telegram users and their venue/hostel destinations stored in PostgreSQL.
    Requires Staff or Admin Bearer Authentication.
    """
    users = db.query(TelegramUser).order_by(TelegramUser.updated_at.desc()).all()
    return {
        "count": len(users),
        "users": [
            {
                "chat_id": u.chat_id,
                "user_id": u.user_id,
                "username": u.username,
                "full_name": u.full_name,
                "identifier": u.identifier,
                "location": u.location,
                "visit_count": u.visit_count,
                "updated_at": u.updated_at.isoformat() if u.updated_at else None,
            }
            for u in users
        ],
    }

