import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import GateStatus, GateDirection, AccessState, AlertSeverity, AlertStatus, DirectionMethod, LogPlateSource

class Gate(Base, TimestampMixin):
    __tablename__ = "gates"

    id = Column(String(30), primary_key=True)  # GATE_1, GATE_2, GATE_3
    name = Column(String(100), nullable=False)
    location = Column(String(200), nullable=True)
    status = Column(SQLEnum(GateStatus, name="gate_status_enum"), default=GateStatus.ACTIVE, nullable=False)
    camera_id = Column(String(50), nullable=True)  # Mapping to Frigate camera ID, e.g. "gate_cam"
    direction_capability = Column(String(20), default="BIDIRECTIONAL", nullable=False)

    visitors_allowed = relationship("Visitor", back_populates="allowed_gate")
    access_decisions = relationship("AccessDecision", back_populates="gate")
    entry_exit_logs = relationship("EntryExitLog", back_populates="gate")
    delivery_orders = relationship("DeliveryOrder", back_populates="gate")
    observations = relationship("ObservationEvent", back_populates="gate")

class AccessDecision(Base):
    __tablename__ = "access_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate = Column(String(30), nullable=False)
    normalized_plate = Column(String(30), index=True, nullable=False)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=False, index=True)
    decision = Column(SQLEnum(AccessState, name="access_state_enum"), nullable=False, index=True)
    reason_code = Column(String(50), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    context_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    gate = relationship("Gate", back_populates="access_decisions")
    entry_exit_logs = relationship("EntryExitLog", back_populates="access_decision")

class EntryExitLog(Base, TimestampMixin):
    """
    Gate crossing journal. Phase 6 movement records (direction_method set) are
    append-only: a movement is a root row (observation_id set) plus correction rows
    (correction_of_id -> root). The latest row of a chain is the effective view.
    Movement records carry no access decision (decision/reason_code stay NULL).
    """
    __tablename__ = "entry_exit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True, index=True)
    plate = Column(String(30), nullable=True)
    normalized_plate = Column(String(30), index=True, nullable=True)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=False, index=True)
    direction = Column(SQLEnum(GateDirection, name="gate_direction_enum"), default=GateDirection.ENTRY, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    confidence = Column(Float, default=1.0, nullable=True)  # plate-read confidence snapshot
    decision = Column(SQLEnum(AccessState, name="log_access_state_enum"), nullable=True, index=True)
    reason_code = Column(String(50), nullable=True)
    frigate_event_id = Column(String(100), nullable=True, index=True)
    decision_id = Column(UUID(as_uuid=True), ForeignKey("access_decisions.id"), nullable=True)

    # Phase 6 movement provenance
    observation_id = Column(UUID(as_uuid=True), ForeignKey("observation_events.id"), nullable=True, unique=True)  # root rows only
    correction_of_id = Column(UUID(as_uuid=True), ForeignKey("entry_exit_logs.id"), nullable=True, index=True)  # always the root
    direction_method = Column(SQLEnum(DirectionMethod, name="direction_method_enum"), nullable=True, index=True)
    direction_confidence = Column(Float, nullable=True)
    direction_evidence = Column(JSON, nullable=True)
    plate_source = Column(SQLEnum(LogPlateSource, name="log_plate_source_enum"), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)

    gate = relationship("Gate", back_populates="entry_exit_logs")
    vehicle = relationship("Vehicle", back_populates="entry_exit_logs")
    access_decision = relationship("AccessDecision", back_populates="entry_exit_logs")
    security_alerts = relationship("SecurityAlert", back_populates="log")
    observation = relationship("ObservationEvent")
    created_by = relationship("User", foreign_keys=[created_by_id])

@event.listens_for(EntryExitLog, "before_update")
def _reject_movement_update(mapper, connection, target):
    if target.direction_method is not None:
        raise ValueError("Movement records are append-only; add a correction row instead.")

@event.listens_for(EntryExitLog, "before_delete")
def _reject_movement_delete(mapper, connection, target):
    if target.direction_method is not None:
        raise ValueError("Movement records are append-only; they cannot be deleted.")

class SecurityAlert(Base, TimestampMixin):
    __tablename__ = "security_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=True, index=True)
    log_id = Column(UUID(as_uuid=True), ForeignKey("entry_exit_logs.id"), nullable=True, index=True)
    severity = Column(SQLEnum(AlertSeverity, name="alert_severity_enum"), default=AlertSeverity.MEDIUM, nullable=False, index=True)
    status = Column(SQLEnum(AlertStatus, name="alert_status_enum"), default=AlertStatus.PENDING, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    assigned_to_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    log = relationship("EntryExitLog", back_populates="security_alerts")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id], back_populates="assigned_alerts")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id], back_populates="reviewed_alerts")
