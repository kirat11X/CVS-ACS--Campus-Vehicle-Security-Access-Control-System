import uuid
from sqlalchemy import BigInteger, Column, String, Boolean, DateTime, ForeignKey, Integer, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import PersonType, ResidenceType

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(30), default="GUARD", nullable=False)  # ADMIN, GUARD, SUPERVISOR
    hashed_password = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    assigned_alerts = relationship("SecurityAlert", foreign_keys="SecurityAlert.assigned_to_id", back_populates="assigned_to")
    reviewed_alerts = relationship("SecurityAlert", foreign_keys="SecurityAlert.reviewed_by_id", back_populates="reviewed_by")

class VehicleOwner(Base, TimestampMixin):
    __tablename__ = "vehicle_owners"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier = Column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )  # Institutional ID: Student (8 digits, e.g. 24103042), Faculty (F + 7 digits, e.g. F1234567), Resident (R + 4-digit house no, e.g. R1042)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), index=True, nullable=True)
    phone = Column(String(20), index=True, nullable=True)
    
    person_type = Column(SQLEnum(PersonType, name="person_type_enum"), default=PersonType.STUDENT, nullable=False, index=True)
    residence_type = Column(SQLEnum(ResidenceType, name="residence_type_enum"), default=ResidenceType.UNKNOWN, nullable=False, index=True)
    residence = Column(String(100), nullable=True)  # e.g. BH-4, Faculty Enclave Qtr 12
    department = Column(String(100), nullable=True)  # e.g. Computer Science & Engineering
    
    owner_type = Column(String(30), nullable=True)  # Retained for backward compatibility
    department_or_hostel = Column(String(100), nullable=True)
    status = Column(String(20), default="ACTIVE", nullable=False)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    vehicles = relationship("Vehicle", back_populates="owner")
    visitors_hosted = relationship("Visitor", back_populates="host_owner")
    orders = relationship("DeliveryOrder", back_populates="customer")

class Visitor(Base, TimestampMixin):
    __tablename__ = "visitors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visitor_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    purpose = Column(Text, nullable=True)
    host_owner_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_owners.id"), nullable=True)
    allowed_gate_id = Column(String(20), ForeignKey("gates.id"), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False)

    host_owner = relationship("VehicleOwner", back_populates="visitors_hosted")
    allowed_gate = relationship("Gate", back_populates="visitors_allowed")
    vehicles = relationship("Vehicle", back_populates="visitor")


class TelegramUser(Base, TimestampMixin):
    __tablename__ = "telegram_users"

    chat_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, nullable=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(100), nullable=False)
    identifier = Column(String(50), nullable=False, index=True)
    location = Column(String(150), nullable=False)
    visit_count = Column(Integer, default=1, nullable=False)

