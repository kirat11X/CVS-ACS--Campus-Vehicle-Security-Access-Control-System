from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from backend.app.models.enums import DeliverySource, GuardDecision, ScreeningVerdict

class DecisionRecord(BaseModel):
    decision: GuardDecision
    note: Optional[str] = None
    by: str = Field(..., description="Full name of the guard who decided")
    at: datetime

class DeliverySummary(BaseModel):
    """One screened delivery (its latest invoice). Context for the guard; nothing is blocked automatically."""
    order_id: str
    platform: str
    gate_id: Optional[str] = None
    source: DeliverySource
    sender: Optional[str] = None
    received_at: datetime
    line_count: int
    review_count: int
    alert_count: int
    overall: ScreeningVerdict
    totals_match: Optional[bool] = None
    total_amount: Optional[float] = None
    latest_decision: Optional[DecisionRecord] = None
    reply_text: str

class InvoiceInfo(BaseModel):
    image_url: str = Field(..., description="GET with the bearer token (same as /feed/snapshots)")
    ocr_engine: Optional[str] = None
    ocr_confidence: Optional[float] = None
    raw_ocr_text: str = ""
    vendor: Optional[str] = None
    subtotal: Optional[float] = None
    delivery_fee: Optional[float] = None
    total: Optional[float] = None
    computed_total: Optional[float] = None

class DeliveryItem(BaseModel):
    line_no: int
    item_name: str
    quantity: Optional[int] = None
    amount: Optional[float] = None
    category: str
    category_label: str
    reason_code: str
    verdict: ScreeningVerdict
    confidence: Optional[float] = None

class DeliveryDetail(DeliverySummary):
    invoice: InvoiceInfo
    items: List[DeliveryItem]
    decisions: List[DecisionRecord]

class DecisionCreate(BaseModel):
    decision: GuardDecision
    note: Optional[str] = Field(None, max_length=1000)

class AlertItem(BaseModel):
    """Something that needs a guard's attention. Not a threat label and not an access decision."""
    kind: Literal["PLATE_REVIEW", "PLATE_UNLINKED", "DELIVERY_REVIEW", "DELIVERY_ALERT", "OVERSTAY_UNLINKED"]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    title: str
    detail: str
    ref: str = Field(..., description="Plate or order_id")
    gate_id: Optional[str] = None
    at: datetime

class WhatsAppStatus(BaseModel):
    provider: Literal["local", "mock", "meta"]
    available: bool
    intake_url: str
    outbox_count: int
