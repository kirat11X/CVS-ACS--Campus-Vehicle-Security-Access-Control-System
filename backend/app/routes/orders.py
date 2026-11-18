from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.app.config import INVOICE_MAX_UPLOAD_MB
from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.enums import DeliverySource
from backend.app.schemas.delivery import DeliveryDetail
from backend.app.services.delivery_screening_service import delivery_screening_service

router = APIRouter(tags=["Orders & Delivery Screening"])


async def read_upload(file: UploadFile) -> bytes:
    """Reads at most the size limit + 1 byte so oversized uploads are rejected without buffering."""
    return await file.read(int(INVOICE_MAX_UPLOAD_MB * 1024 * 1024) + 1)


@router.post("/orders/process-invoice", response_model=DeliveryDetail, status_code=status.HTTP_201_CREATED)
@router.post("/api/orders/process-invoice", response_model=DeliveryDetail, status_code=status.HTTP_201_CREATED)
async def process_order_invoice(
    file: UploadFile = File(..., description="Invoice photo (JPG / PNG / WEBP) or PDF"),
    order_id: Optional[str] = Form(None, max_length=50, description="Order ID printed on the invoice"),
    gate_id: Optional[str] = Form(None, max_length=30, description="Arrival campus gate ID"),
    platform: Optional[str] = Form(None, max_length=20, description="Delivery platform (ZOMATO, SWIGGY, BLINKIT, etc.)"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
) -> DeliveryDetail:
    """
    Standard Order Invoice Screening entrypoint (Track B OCR + Track C 3-tier screening).
    Accepts invoice photo or PDF, executes deterministic item categorization and contraband
    screening against the 3,414-item taxonomy, persists records in PostgreSQL, and returns
    full delivery screening detail.
    """
    content = await read_upload(file)

    def work():
        invoice = delivery_screening_service.process(
            db,
            order_id=order_id,
            content=content,
            source=DeliverySource.CONSOLE,
            sender=user.username,
            gate_id=gate_id,
            platform=platform,
            user_id=user.id,
        )
        return delivery_screening_service.detail(db, invoice.order.order_id)

    return await run_in_threadpool(work)
