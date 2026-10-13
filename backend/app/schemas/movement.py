from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

from backend.app.models.enums import (
    DirectionMethod,
    LaneRole,
    LinkMethod,
    LogPlateSource,
    PersonType,
    PresenceStatus,
    ResidenceType,
    VehicleCategory,
)
from backend.app.schemas.feed import LinkedVehicle, ResidenceInfo, ResolvedObservation, UserSummary
from backend.app.schemas.observation import GateSummary
from backend.app.schemas.vehicle import OwnerContextResponse, VehicleDetailResponse

# ---- Lane configuration ----

class LaneUpsert(BaseModel):
    gate_id: str = Field(..., max_length=30)
    lane_role: LaneRole
    outside_zone: Optional[str] = Field(None, max_length=64, description="BIDIRECTIONAL only: Frigate zone on the public side")
    inside_zone: Optional[str] = Field(None, max_length=64, description="BIDIRECTIONAL only: Frigate zone on the campus side")
    is_active: bool = True
    notes: Optional[str] = Field(None, max_length=1000)

class LaneResponse(BaseModel):
    camera_id: str
    gate_id: str
    lane_role: LaneRole
    outside_zone: Optional[str] = None
    inside_zone: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None
    updated_at: datetime

# ---- Movement log ----

class MovementConfirm(BaseModel):
    observation_id: UUID
    direction: Literal["ENTRY", "EXIT"]
    note: Optional[str] = Field(None, max_length=1000)

class MovementCorrection(BaseModel):
    direction: Optional[Literal["ENTRY", "EXIT"]] = None
    plate: Optional[str] = Field(None, min_length=1, max_length=30, description="Guard-supplied plate")
    note: str = Field(..., min_length=3, max_length=1000, description="Why the record is being corrected")

    @model_validator(mode="after")
    def _something_to_correct(self) -> "MovementCorrection":
        if self.direction is None and self.plate is None:
            raise ValueError("Provide a corrected direction and/or plate.")
        return self

class MovementLogRow(BaseModel):
    """One stored row of a movement (root or correction), exactly as recorded."""
    id: UUID
    correction_of_id: Optional[UUID] = None
    direction: str
    direction_method: DirectionMethod
    direction_confidence: Optional[float] = None
    direction_evidence: Dict[str, Any] = {}
    plate: Optional[str] = None
    normalized_plate: Optional[str] = None
    plate_source: Optional[LogPlateSource] = None
    plate_confidence: Optional[float] = None
    recorded_vehicle_id: Optional[UUID] = Field(None, description="Registry attribution at the time the row was written")
    created_by: Optional[UserSummary] = None
    created_at: datetime
    note: Optional[str] = None

class MovementEntry(BaseModel):
    """Effective view of a movement: latest correction applied, owner resolved on read."""
    id: UUID
    observation_id: Optional[UUID] = None
    gate: GateSummary
    timestamp: datetime
    direction: str
    direction_method: DirectionMethod
    direction_confidence: Optional[float] = None
    plate: Optional[str] = None
    normalized_plate: Optional[str] = None
    plate_source: Optional[LogPlateSource] = None
    linked: bool = False
    link_basis: Optional[str] = None
    vehicle: Optional[LinkedVehicle] = None
    owner: Optional[OwnerContextResponse] = None
    residence: Optional[ResidenceInfo] = None
    flags: List[str] = []
    corrected: bool = False
    correction_count: int = 0
    recorded_by: Optional[UserSummary] = None
    last_corrected_by: Optional[UserSummary] = None
    note: Optional[str] = None

class MovementPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[MovementEntry]

class MovementDetail(BaseModel):
    movement: MovementEntry
    rows: List[MovementLogRow]

# ---- Presence ----

class PresenceEntry(BaseModel):
    subject: str = Field(..., description="vehicle:<id> or plate:<normalized plate>")
    status: PresenceStatus
    normalized_plate: Optional[str] = None
    linked: bool = False
    vehicle: Optional[LinkedVehicle] = None
    owner: Optional[OwnerContextResponse] = None
    residence: Optional[ResidenceInfo] = None
    last_movement: Optional[MovementEntry] = None
    inside_since: Optional[datetime] = None
    flags: List[str] = []

class PresencePage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[PresenceEntry]

class InsideResponse(BaseModel):
    total: int
    items: List[PresenceEntry]
    unattributed_entries: List[MovementEntry] = Field(
        default_factory=list, description="Recent ENTRY movements without a plate (cannot be paired with an exit)"
    )

# ---- Vehicle history ----

class TimelineItem(BaseModel):
    type: Literal["MOVEMENT", "SIGHTING"]
    time: datetime
    gate: GateSummary
    movement: Optional[MovementEntry] = None
    sighting: Optional[ResolvedObservation] = None

class LinkEventResponse(BaseModel):
    id: UUID
    vehicle_id: UUID
    owner_id: UUID
    method: LinkMethod
    evidence_note: str
    linked_by: UserSummary
    linked_at: datetime
    expires_at: Optional[datetime] = None

class VehicleHistory(BaseModel):
    plate: str
    normalized_plate: str
    registered: bool
    vehicle: Optional[LinkedVehicle] = None
    owner: Optional[OwnerContextResponse] = None
    residence: Optional[ResidenceInfo] = None
    presence: PresenceEntry
    timeline: List[TimelineItem]
    link_events: List[LinkEventResponse] = []

# ---- Linking an unknown vehicle to an owner ----

class NewOwnerForLink(BaseModel):
    """Minimum PII: identifier, name, person type and residence. No ID document images."""
    person_type: PersonType
    identifier: str = Field(..., min_length=1, max_length=50, description="SID, employee ID or other institutional ID")
    full_name: str = Field(..., min_length=1, max_length=100)
    residence_type: ResidenceType = ResidenceType.UNKNOWN
    residence: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)

class VehicleLinkRequest(BaseModel):
    owner_id: Optional[str] = Field(None, description="Existing owner UUID or institutional identifier")
    new_owner: Optional[NewOwnerForLink] = None
    vehicle_category: VehicleCategory
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = Field(None, description="Required for GUARD/SUPERVISOR (visitor/delivery links)")
    evidence_note: str = Field(..., min_length=3, max_length=1000, description="What was checked, e.g. 'Student ID card shown'")
    make_model: Optional[str] = Field(None, max_length=100)
    color: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def _exactly_one_owner(self) -> "VehicleLinkRequest":
        if (self.owner_id is None) == (self.new_owner is None):
            raise ValueError("Provide exactly one of owner_id or new_owner.")
        return self

class RetroactiveCounts(BaseModel):
    movements: int
    sightings: int

class VehicleLinkResponse(BaseModel):
    vehicle: VehicleDetailResponse
    link_event: LinkEventResponse
    retroactive: RetroactiveCounts = Field(..., description="Past records of this plate that now resolve to the owner (no rows rewritten)")
