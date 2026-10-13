from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID
from pydantic import BaseModel, Field

from backend.app.models.enums import (
    ObservationSource,
    ObservationDirection,
    ObservedVehicleType,
    ResolutionOutcome,
    LinkStatus,
    LinkBasis,
    DirectionMethod,
)
from backend.app.schemas.observation import GateSummary, PlateObservation, VehicleTypeObservation
from backend.app.schemas.vehicle import OwnerContextResponse

class UserSummary(BaseModel):
    id: UUID
    username: str
    full_name: str
    role: str

class FeedObservation(BaseModel):
    """Sensor facts of an observation as shown on the feed (raw Frigate payload omitted)."""
    id: UUID
    gate: GateSummary
    camera_id: Optional[str] = None
    observed_at: datetime
    updated_at: datetime
    source: ObservationSource
    source_event_id: Optional[str] = None
    plate: PlateObservation
    vehicle_observation: VehicleTypeObservation
    direction: ObservationDirection
    note: Optional[str] = None
    created_by: Optional[UserSummary] = None
    update_count: int = 0
    has_snapshot: bool = False

class LinkedVehicle(BaseModel):
    id: UUID
    plate: str
    raw_plate: str
    category: str
    registry_status: str = Field(..., description="Vehicle.status exactly as recorded in the registry")
    is_active: bool
    make_model: Optional[str] = None
    color: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

class ResidenceInfo(BaseModel):
    person_type: Optional[str] = None
    residence_type: Optional[str] = None
    residence: Optional[str] = None
    department: Optional[str] = None

class RegistrySuggestion(BaseModel):
    """A registry candidate for a low-confidence read. Never applied automatically."""
    vehicle_id: UUID
    plate: str
    raw_plate: str
    similarity: float
    category: str
    registry_status: str
    owner_name: Optional[str] = None

class ResolutionSummary(BaseModel):
    id: UUID
    outcome: ResolutionOutcome
    chosen_vehicle_id: Optional[UUID] = None
    note: Optional[str] = None
    created_by: UserSummary
    created_at: datetime

class DirectionInfo(BaseModel):
    """Derived direction (Phase 6). The observation's own `direction` stays as the sensor reported it."""
    direction: ObservationDirection
    method: DirectionMethod
    confidence: Optional[float] = None
    evidence: Dict[str, Any] = {}

class MovementSummary(BaseModel):
    """Effective movement-log entry for an observation (latest correction applied)."""
    id: UUID
    direction: str = Field(..., description="ENTRY or EXIT")
    method: DirectionMethod
    timestamp: datetime
    normalized_plate: Optional[str] = None
    corrected: bool = False
    created_by: Optional[UserSummary] = None
    note: Optional[str] = None

class ResolvedObservation(BaseModel):
    observation: FeedObservation
    link_status: LinkStatus
    link_basis: Optional[LinkBasis] = None
    vehicle: Optional[LinkedVehicle] = None
    owner: Optional[OwnerContextResponse] = None
    residence: Optional[ResidenceInfo] = None
    suggestions: List[RegistrySuggestion] = []
    resolution: Optional[ResolutionSummary] = None
    flags: List[str] = []
    direction: Optional[DirectionInfo] = None
    movement: Optional[MovementSummary] = None
    movement_status: Optional[str] = Field(None, description="LOGGED, REPEAT_NOT_LOGGED or DIRECTION_UNKNOWN")

class FeedEntry(BaseModel):
    kind: str = Field(..., description="SNAPSHOT or a FeedEventKind value")
    cursor: int
    item: ResolvedObservation

class FeedPage(BaseModel):
    cursor: int = Field(..., description="Pass as since_id to receive later changes")
    has_more: bool = False
    entries: List[FeedEntry]

class ManualObservationCreate(BaseModel):
    gate_id: str = Field(..., max_length=30)
    plate: str = Field(..., min_length=1, max_length=30, description="Plate as read by the guard")
    direction: ObservationDirection = Field(..., description="Direction as chosen by the guard (UNKNOWN allowed)")
    vehicle_type: ObservedVehicleType = ObservedVehicleType.UNKNOWN
    note: Optional[str] = Field(None, max_length=1000)

class ResolutionCreate(BaseModel):
    observation_id: UUID
    chosen_vehicle_id: Union[UUID, Literal["none"]] = Field(..., description="Registered vehicle id, or \"none\"")
    note: Optional[str] = Field(None, max_length=1000)

class ResolutionCreated(BaseModel):
    resolution: ResolutionSummary
    item: ResolvedObservation
