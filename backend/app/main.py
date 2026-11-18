import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional

from backend.app.db import check_db_connection
from backend.app.dependencies import CurrentUser, require_admin
from backend.app.mqtt import mqtt_manager
from backend.app.workers.frigate_mqtt_worker import frigate_worker
from backend.app.config import AUTH_SECRET_KEY_IS_EPHEMERAL, CORS_ALLOW_ORIGINS
from backend.app.routes import (
    vehicles_router,
    gates_router,
    observations_router,
    auth_router,
    owners_router,
    feed_router,
    resolutions_router,
    lanes_router,
    movements_router,
    presence_router,
    dashboard_router,
    users_router,
    deliveries_router,
    intake_router,
    webhooks_router,
    system_router,
    reviews_router,
    telegram_router,
    orders_router,
)
from backend.app.telegram import telegram_service
from backend.app.whatsapp import get_whatsapp_provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("campus_security")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if AUTH_SECRET_KEY_IS_EPHEMERAL:
        logger.warning("AUTH_SECRET_KEY is not set; using a per-process key. Tokens will not survive a restart.")
    logger.info("Initializing background services...")
    mqtt_manager.start()
    frigate_worker.start()
    if telegram_service.is_configured:
        await telegram_service.start()
    yield
    # Shutdown
    logger.info("Stopping background services...")
    if telegram_service.is_configured:
        await telegram_service.stop()
    frigate_worker.stop()
    mqtt_manager.stop()

app = FastAPI(
    title="Campus Vehicle Security & Access Control System",
    version="0.7.0",
    description="Authoritative campus vehicle security, intelligence, and observation management API.",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Delivery Screening", "description": "Phase 7: invoice OCR, deterministic per-line policy (ALLOW / REVIEW / ALERT), append-only guard decisions."},
        {"name": "Delivery Intake", "description": "Phase 7: public LAN page riders use to send an invoice while the WhatsApp Business API is unavailable."},
        {"name": "WhatsApp", "description": "Phase 7: provider-agnostic chat webhook (local intake / mock / Meta Cloud API)."},
        {"name": "Telegram Connector", "description": "Stage 1: Interactive Telegram bot connector: polling/webhook, invoice screening, inline gate triage."},
        {"name": "Orders & Delivery Screening", "description": "Standard invoice intake and multi-platform order verification."},
        {"name": "Alerts & System", "description": "Phase 7: unified needs-attention list and chat provider status."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Last-Event-ID"],
    max_age=600,
)

app.include_router(vehicles_router)
app.include_router(gates_router)
app.include_router(observations_router)
app.include_router(auth_router)
app.include_router(owners_router)
app.include_router(feed_router)
app.include_router(resolutions_router)
app.include_router(lanes_router)
app.include_router(movements_router)
app.include_router(presence_router)
app.include_router(dashboard_router)
app.include_router(users_router)
app.include_router(deliveries_router)
app.include_router(intake_router)
app.include_router(webhooks_router)
app.include_router(system_router)
app.include_router(reviews_router)
app.include_router(telegram_router)
app.include_router(orders_router)

class WebhookTestPayload(BaseModel):
    source: str
    event: str
    data: Optional[Dict[str, Any]] = None

@app.get("/health")
def get_health():
    return {"status": "ok"}

@app.get("/health/db")
def get_health_db():
    res = check_db_connection()
    if res.get("status") != "ok":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=res
        )
    return res

@app.get("/health/mqtt")
def get_health_mqtt():
    res = mqtt_manager.check_connection()
    if res.get("status") != "ok":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=res
        )
    return res

@app.get("/health/all")
def get_health_all():
    db_status = check_db_connection()
    mqtt_status = mqtt_manager.check_connection()
    worker_stats = frigate_worker.get_stats()
    overall = (db_status.get("status") == "ok") and (mqtt_status.get("status") == "ok")
    whatsapp_provider = get_whatsapp_provider()
    return {
        "status": "ok" if overall else "degraded",
        "database": db_status,
        "mqtt": mqtt_status,
        "frigate_worker": worker_stats,
        "whatsapp": {"provider": whatsapp_provider.name, "available": whatsapp_provider.is_available()},
    }

@app.get("/api/workers/frigate-worker")
def get_frigate_worker_status():
    return frigate_worker.get_stats()

@app.post("/webhook/n8n-test")
def receive_n8n_test_webhook(payload: WebhookTestPayload):
    logger.info(f"Received n8n test webhook: source={payload.source} event={payload.event}")
    # Record in database for E2E verification
    try:
        from backend.app.db import SessionLocal, HealthCheckRecord
        db = SessionLocal()
        db.add(HealthCheckRecord(component="n8n_webhook_pipeline", status="PASS"))
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"Could not log n8n event to db: {e}")

    return {
        "status": "success",
        "received_source": payload.source,
        "received_event": payload.event,
        "message": "n8n to FastAPI webhook verified"
    }

class LPREventPayload(BaseModel):
    camera: str
    plate_number: str
    confidence: float
    source: Optional[str] = "frigate_lpr"

@app.post("/api/test/lpr-event")
def receive_lpr_event(payload: LPREventPayload):
    logger.info(f"Received LPR test event from camera '{payload.camera}'")
    from backend.app.db import SessionLocal, HealthCheckRecord
    db = SessionLocal()
    rec = HealthCheckRecord(
        component="lpr_pipeline",
        status=f"PASS: {payload.plate_number}"
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    rec_id = rec.id
    db.close()
    return {
        "status": "success",
        "message": f"Plate {payload.plate_number} recorded in database",
        "record_id": rec_id
    }

class InvoiceOCRTestPayload(BaseModel):
    image_name: str
    extracted_text: str
    order_id: Optional[str] = None

@app.post("/api/test/invoice-ocr")
def receive_invoice_ocr(payload: InvoiceOCRTestPayload):
    logger.info(f"Received Invoice OCR result: order_id={payload.order_id}")
    from backend.app.db import SessionLocal, HealthCheckRecord
    db = SessionLocal()
    rec = HealthCheckRecord(
        component="invoice_ocr_pipeline",
        status=f"PASS: {payload.order_id or 'verified'}"
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    rec_id = rec.id
    db.close()
    return {
        "status": "success",
        "message": f"Invoice {payload.order_id} recorded in database",
        "record_id": rec_id
    }

@app.get("/api/events/frigate")
def get_frigate_events(user: CurrentUser = Depends(require_admin)):
    """Last raw frigate/# messages (plate reads, snapshot payloads): ADMIN only."""
    return {"events": mqtt_manager.last_events}
