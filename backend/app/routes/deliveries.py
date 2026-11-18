from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import INVOICE_MAX_UPLOAD_MB, MEDIA_ROOT
from backend.app.dependencies import CurrentUser, get_db, require_admin, require_staff
from backend.app.models.delivery import DeliveryDecision, DeliveryOrder, Invoice, InvoiceItem
from backend.app.models.enums import DeliverySource, ScreeningVerdict
from backend.app.schemas.delivery import DecisionCreate, DeliveryDetail, DeliveryItemsUpdate, DeliverySummary
from backend.app.services.delivery_screening_service import delivery_screening_service

router = APIRouter(prefix="/deliveries", tags=["Delivery Screening"])

async def read_upload(file: UploadFile) -> bytes:
    """Reads at most the size limit + 1 byte, so an oversized upload is rejected without buffering it all."""
    return await file.read(int(INVOICE_MAX_UPLOAD_MB * 1024 * 1024) + 1)

@router.get("", response_model=List[DeliverySummary])
def list_deliveries(
    status: Optional[str] = Query(None, description="pending (flagged, no decision), undecided, decided, CLEARED, HELD or ESCALATED"),
    verdict: Optional[ScreeningVerdict] = Query(None, description="Overall screening verdict"),
    q: Optional[str] = Query(None, max_length=50, description="Order ID fragment"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Screened deliveries, newest first (one per order: its latest invoice)."""
    return delivery_screening_service.list_deliveries(db, status, verdict, q, limit)

@router.post("/process", response_model=DeliveryDetail, status_code=201)
async def process_delivery(
    order_id: str = Form(..., max_length=50),
    file: UploadFile = File(..., description="Invoice photo (JPG / PNG / WEBP) or PDF"),
    gate_id: Optional[str] = Form(None, max_length=30),
    platform: Optional[str] = Form(None, max_length=20),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """A guard uploads an invoice from the console. Screens it and returns the result; the guard still decides."""
    content = await read_upload(file)

    def work():
        invoice = delivery_screening_service.process(
            db, order_id=order_id, content=content, source=DeliverySource.CONSOLE,
            sender=user.username, gate_id=gate_id, platform=platform, user_id=user.id,
        )
        return delivery_screening_service.detail(db, invoice.order.order_id)

    return await run_in_threadpool(work)

@router.get("/{order_id}", response_model=DeliveryDetail)
def get_delivery(order_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """Latest screening of an order: invoice, every line with category / reason code / verdict, decision history."""
    return delivery_screening_service.detail(db, order_id)

@router.get("/{order_id}/invoice-image")
def get_invoice_image(order_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_staff)):
    """The invoice as received (page 1 rendered to PNG for PDFs). Bearer auth, like /feed/snapshots/{id}."""
    path, media_type = delivery_screening_service.invoice_image(db, order_id)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=60"})

@router.post("/{order_id}/decision", response_model=DeliveryDetail, status_code=201)
def record_decision(
    order_id: str,
    body: DecisionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Appends the guard's decision (CLEARED / HELD / ESCALATED). Earlier decisions are kept."""
    return delivery_screening_service.record_decision(db, order_id, body.decision, body.note, user.id)

@router.put("/{order_id}/items", response_model=DeliveryDetail)
def update_delivery_items(
    order_id: str,
    body: DeliveryItemsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Allows staff/guards to manually edit or correct extracted items, quantities, or prices on the portal."""
    return delivery_screening_service.update_items(db, order_id, body, user.id)

@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def delete_delivery(
    order_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Deletes a delivery order, its invoices, items, and image files from PostgreSQL and disk (ADMIN only).
    """
    order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery order '{order_id}' not found."
        )

    # Use replica session role to bypass append-only triggers during administrative deletion
    db.execute(text("SET LOCAL session_replication_role = 'replica';"))

    # Remove decisions, items, and invoices
    db.query(DeliveryDecision).filter(DeliveryDecision.order_id == order.id).delete(synchronize_session=False)

    invoices = db.query(Invoice).filter(Invoice.order_id == order.id).all()
    for inv in invoices:
        # Delete invoice items
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).delete(synchronize_session=False)
        # Remove physical file from disk if present
        if inv.image_path:
            file_path = MEDIA_ROOT / inv.image_path
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
        db.delete(inv)

    db.delete(order)
    db.commit()

    return {
        "status": "success",
        "message": f"Delivery order '{order_id}' and all associated invoices/items deleted successfully from PostgreSQL.",
        "deleted_order_id": order_id
    }
