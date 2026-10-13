import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import LaneRole, LinkMethod

class CameraLane(Base, TimestampMixin):
    """
    Administrator-declared role of a camera at a gate. Direction is derived only
    from this declaration (or a guard's confirmation), never from a camera's name.
    For BIDIRECTIONAL lanes, direction needs both zone names and Frigate's
    entered_zones order: outside_zone then inside_zone = ENTRY, reverse = EXIT.
    """
    __tablename__ = "camera_lanes"

    camera_id = Column(String(50), primary_key=True)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=False, index=True)
    lane_role = Column(SQLEnum(LaneRole, name="lane_role_enum"), nullable=False)
    outside_zone = Column(String(64), nullable=True)
    inside_zone = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    updated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    gate = relationship("Gate")

class VehicleLinkEvent(Base):
    """
    Append-only record that a person asserted a vehicle belongs to an owner.
    A link is a human assertion, not proof of identity. No ID images are stored.
    """
    __tablename__ = "vehicle_link_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_owners.id"), nullable=False, index=True)
    method = Column(SQLEnum(LinkMethod, name="link_method_enum"), nullable=False)
    evidence_note = Column(Text, nullable=False)
    linked_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    linked_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    vehicle = relationship("Vehicle")
    owner = relationship("VehicleOwner")
    linked_by = relationship("User", foreign_keys=[linked_by_id])

@event.listens_for(VehicleLinkEvent, "before_update")
def _reject_link_update(mapper, connection, target):
    raise ValueError("vehicle_link_events is append-only.")

@event.listens_for(VehicleLinkEvent, "before_delete")
def _reject_link_delete(mapper, connection, target):
    raise ValueError("vehicle_link_events is append-only.")
