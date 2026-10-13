import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin
from backend.app.models.enums import VehicleCategory, VehicleStatus, PlatformType

class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_plate = Column(String(30), nullable=False)
    normalized_plate = Column(String(30), unique=True, index=True, nullable=False)
    vehicle_category = Column(SQLEnum(VehicleCategory, name="vehicle_category_enum"), default=VehicleCategory.UNKNOWN, nullable=False, index=True)
    status = Column(SQLEnum(VehicleStatus, name="vehicle_status_enum"), default=VehicleStatus.ACTIVE, nullable=False, index=True)
    
    owner_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_owners.id"), nullable=True, index=True)
    visitor_id = Column(UUID(as_uuid=True), ForeignKey("visitors.id"), nullable=True, index=True)
    
    make_model = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    owner = relationship("VehicleOwner", back_populates="vehicles")
    visitor = relationship("Visitor", back_populates="vehicles")
    delivery_profile = relationship("DeliveryVehicle", back_populates="vehicle", uselist=False)
    entry_exit_logs = relationship("EntryExitLog", back_populates="vehicle")

class DeliveryVehicle(Base, TimestampMixin):
    __tablename__ = "delivery_vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id"), unique=True, nullable=False)
    platform = Column(SQLEnum(PlatformType, name="platform_type_enum"), default=PlatformType.OTHER, nullable=False)
    driver_name = Column(String(100), nullable=True)
    driver_phone = Column(String(20), nullable=True)
    is_verified = Column(Boolean, default=True, nullable=False)

    vehicle = relationship("Vehicle", back_populates="delivery_profile")
