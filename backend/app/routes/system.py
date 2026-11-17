import socket
from typing import List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.app.config import INTAKE_PUBLIC_URL
from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.schemas.delivery import AlertItem, WhatsAppStatus
from backend.app.services.alert_service import alert_service
from backend.app.whatsapp import get_whatsapp_provider

router = APIRouter(tags=["Alerts & System"])

def lan_address() -> str:
    """This host's LAN address (the interface with the default route). No packet is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1; connect() on UDP only picks a route
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"

def intake_url(request: Request) -> str:
    """INTAKE_PUBLIC_URL, else http://<LAN address>:<port>/intake for phones on the same network."""
    if INTAKE_PUBLIC_URL:
        return INTAKE_PUBLIC_URL
    port = request.url.port or 8000
    return f"http://{lan_address()}:{port}/intake"

@router.get("/alerts", response_model=List[AlertItem])
def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Everything that needs a guard's attention, most severe first: plates that need review or are
    not in the registry (newest sighting per plate, unresolved), and delivery lines screened
    REVIEW / ALERT without a guard decision. Prompts to look, never access decisions.
    """
    return alert_service.alerts(db, limit=limit)

@router.get("/system/whatsapp", response_model=WhatsAppStatus)
def get_whatsapp_status(request: Request, user: CurrentUser = Depends(require_staff)):
    """Which chat provider is active. 'local' = LAN intake page, used until the WhatsApp Business API exists."""
    provider = get_whatsapp_provider()
    return WhatsAppStatus(
        provider=provider.name,
        available=provider.is_available(),
        intake_url=intake_url(request),
        outbox_count=provider.outbox_count(),
    )
