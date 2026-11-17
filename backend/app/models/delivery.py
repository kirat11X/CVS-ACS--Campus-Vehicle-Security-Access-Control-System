import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text, Numeric, Integer, Enum as SQLEnum, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import PlatformType, OrderStatus, AccessState, ScreeningVerdict, GuardDecision, DeliverySource

class DeliveryOrder(Base, TimestampMixin):
    __tablename__ = "delivery_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), unique=True, index=True, nullable=False)  # e.g. ORD-2026-9821
    platform = Column(SQLEnum(PlatformType, name="order_platform_enum"), default=PlatformType.ZOMATO, nullable=False, index=True)

    customer_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_owners.id"), nullable=True, index=True)
    customer_name = Column(String(100), nullable=True)
    restaurant = Column(String(150), nullable=True)

    delivery_vehicle_plate = Column(String(30), nullable=True, index=True)
    delivery_agent_name = Column(String(100), nullable=True)
    delivery_agent_phone = Column(String(20), nullable=True)

    order_timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    status = Column(SQLEnum(OrderStatus, name="order_status_enum"), default=OrderStatus.SUBMITTED, nullable=False, index=True)
    verification_status = Column(SQLEnum(AccessState, name="order_access_state_enum"), default=AccessState.REVIEW, nullable=False)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=True)

    customer = relationship("VehicleOwner", back_populates="orders")
    gate = relationship("Gate", back_populates="delivery_orders")
    invoices = relationship("Invoice", back_populates="order")
    decisions = relationship("DeliveryDecision", back_populates="order", order_by="DeliveryDecision.decided_at")

class Invoice(Base, TimestampMixin):
    """
    One received invoice document. A rider may send the same order again; every submission
    is a new row (history kept), and the latest one is the order's current screening.
    """
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("delivery_orders.id"), nullable=True, index=True)
    image_path = Column(String(255), nullable=True)
    raw_ocr_text = Column(Text, nullable=True)
    confidence = Column(Float, default=1.0, nullable=False)
    vendor = Column(String(100), nullable=True)
    subtotal = Column(Numeric(10, 2), nullable=True)
    tax = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)

    # Phase 7: delivery screening. All nullable: pre-Phase-7 rows were never screened.
    source = Column(SQLEnum(DeliverySource, name="delivery_source_enum"), nullable=True, index=True)
    sender = Column(String(50), nullable=True)  # rider phone / chat sender, as given
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=True)
    preview_path = Column(String(255), nullable=True)  # PNG of page 1 when the upload is a PDF
    ocr_engine = Column(String(30), nullable=True)  # RAPIDOCR or TESSERACT
    delivery_fee = Column(Numeric(10, 2), nullable=True)
    computed_total = Column(Numeric(10, 2), nullable=True)  # sum of line amounts + delivery fee (+ tax)
    totals_match = Column(Boolean, nullable=True)  # None when the invoice printed no total to check
    overall_verdict = Column(SQLEnum(ScreeningVerdict, name="screening_verdict_enum"), nullable=True, index=True)
    reply_text = Column(Text, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    order = relationship("DeliveryOrder", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.line_no")

class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    item_name = Column(String(150), nullable=False)
    quantity = Column(Integer, nullable=True)  # None when OCR could not read it (no default: never guessed)
    unit_price = Column(Numeric(10, 2), nullable=True)
    total_price = Column(Numeric(10, 2), nullable=True)

    # Phase 7: deterministic screening of the line (policy table, not ML)
    line_no = Column(Integer, nullable=True)
    category = Column(String(30), nullable=True)
    reason_code = Column(String(40), nullable=True)
    verdict = Column(SQLEnum(ScreeningVerdict, name="screening_verdict_enum"), nullable=True)
    confidence = Column(Float, nullable=True)  # OCR confidence of the line, if the engine gave one

    invoice = relationship("Invoice", back_populates="items")

class DeliveryDecision(Base):
    """
    Append-only record of what a guard decided about a screened delivery. The guard
    decides; the screening only proposes. A new decision is a new row.
    """
    __tablename__ = "delivery_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("delivery_orders.id"), nullable=False, index=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    decision = Column(SQLEnum(GuardDecision, name="guard_decision_enum"), nullable=False)
    note = Column(Text, nullable=True)
    decided_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    decided_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    order = relationship("DeliveryOrder", back_populates="decisions")
    invoice = relationship("Invoice")
    decided_by = relationship("User", foreign_keys=[decided_by_id])

@event.listens_for(DeliveryDecision, "before_update")
def _reject_decision_update(mapper, connection, target):
    raise ValueError("delivery_decisions is append-only.")

@event.listens_for(DeliveryDecision, "before_delete")
def _reject_decision_delete(mapper, connection, target):
    raise ValueError("delivery_decisions is append-only.")
