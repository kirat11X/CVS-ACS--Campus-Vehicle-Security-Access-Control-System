import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, Numeric, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import PlatformType, OrderStatus, AccessState

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

class Invoice(Base, TimestampMixin):
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

    order = relationship("DeliveryOrder", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    item_name = Column(String(150), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=True)
    total_price = Column(Numeric(10, 2), nullable=True)

    invoice = relationship("Invoice", back_populates="items")
