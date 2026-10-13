import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, JSON, Text, BigInteger, CheckConstraint, Enum as SQLEnum, Index, event, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now
from backend.app.models.enums import ObservationSource, ObservedVehicleType, ObservationDirection, ResolutionOutcome, FeedEventKind

class ObservationEvent(Base, TimestampMixin):
    __tablename__ = "observation_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gate_id = Column(String(30), ForeignKey("gates.id"), nullable=False, index=True)
    camera_id = Column(String(50), nullable=True)
    observed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    source = Column(SQLEnum(ObservationSource, name="observation_source_enum"), default=ObservationSource.FRIGATE, nullable=False)
    source_event_id = Column(String(100), nullable=True, index=True)
    raw_plate = Column(String(30), nullable=True)
    normalized_plate = Column(String(30), nullable=True, index=True)
    plate_confidence = Column(Float, nullable=True)
    vehicle_type = Column(SQLEnum(ObservedVehicleType, name="observed_vehicle_type_enum"), default=ObservedVehicleType.UNKNOWN, nullable=False)
    vehicle_confidence = Column(Float, nullable=True)
    direction = Column(SQLEnum(ObservationDirection, name="observation_direction_enum"), default=ObservationDirection.UNKNOWN, nullable=False)
    metadata_payload = Column(JSON, nullable=True)

    # Set only for MANUAL observations entered by a guard
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)

    gate = relationship("Gate", back_populates="observations")
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        # One observation per sensor event: refinements of a source_event_id update this row.
        Index("ix_observation_events_source_event", "source", "source_event_id", unique=True,
              postgresql_where=text("source_event_id IS NOT NULL")),
    )

class ObservationResolution(Base):
    """
    Append-only guard confirmation for an observation: either the guard confirms
    which registered vehicle it is, or records that none of the candidates match.
    The referenced observation row is never modified. UPDATE/DELETE are rejected
    here and by a database trigger.
    """
    __tablename__ = "observation_resolutions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id = Column(UUID(as_uuid=True), ForeignKey("observation_events.id"), nullable=False, index=True)
    outcome = Column(SQLEnum(ResolutionOutcome, name="resolution_outcome_enum"), nullable=False)
    chosen_vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    observation = relationship("ObservationEvent")
    chosen_vehicle = relationship("Vehicle")
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        CheckConstraint(
            "(outcome = 'VEHICLE_CONFIRMED') = (chosen_vehicle_id IS NOT NULL)",
            name="ck_observation_resolutions_outcome_vehicle",
        ),
    )

@event.listens_for(ObservationResolution, "before_update")
def _reject_resolution_update(mapper, connection, target):
    raise ValueError("observation_resolutions is append-only; record a new resolution instead.")

@event.listens_for(ObservationResolution, "before_delete")
def _reject_resolution_delete(mapper, connection, target):
    raise ValueError("observation_resolutions is append-only; rows cannot be deleted.")

class ObservationFeedEvent(Base):
    """
    Change log behind the live feed. Each row says "this observation's resolved
    view may have changed"; the monotonic id is the cursor for GET /feed?since_id=
    and the SSE stream.
    """
    __tablename__ = "observation_feed_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    observation_id = Column(UUID(as_uuid=True), ForeignKey("observation_events.id"), nullable=False, index=True)
    kind = Column(SQLEnum(FeedEventKind, name="feed_event_kind_enum"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
