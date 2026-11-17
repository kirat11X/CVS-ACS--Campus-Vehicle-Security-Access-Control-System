from datetime import datetime
from typing import Dict, List
from pydantic import BaseModel, Field

class ActivityBucket(BaseModel):
    start: datetime
    observations: int = 0
    entries: int = 0
    exits: int = 0

class ObservationCounts(BaseModel):
    total: int
    camera: int
    manual: int
    without_plate: int
    low_confidence_unresolved: int = Field(..., description="Uncertain camera reads with no guard confirmation yet")

class MovementCounts(BaseModel):
    entries: int
    exits: int

class PresenceCounts(BaseModel):
    inside: int
    inside_linked: int
    inside_unlinked: int
    long_stay: int
    unattributed_entries: int = Field(..., description="Recent entries without a plate (cannot be paired with an exit)")

class RegistryCounts(BaseModel):
    vehicles: int
    vehicles_by_status: Dict[str, int]
    vehicles_by_category: Dict[str, int]
    temporary_active: int = Field(..., description="VISITOR / DELIVERY registrations active and inside their validity window")
    owners: int

class DashboardSummary(BaseModel):
    """Counts for the console overview. Context only: nothing here is an access decision."""
    since: datetime
    generated_at: datetime
    bucket_minutes: int
    observations: ObservationCounts
    movements: MovementCounts
    presence: PresenceCounts
    registry: RegistryCounts
    activity: List[ActivityBucket]
    delivery_flags: int = Field(0, description="Screened deliveries (latest invoice) with overall REVIEW/ALERT and no guard decision yet")
    unlinked_plates: int = Field(0, description="Plates read in the window with no registry plate within one edit (one per plate, unresolved)")
    plates_to_review: int = Field(0, description="Plates read in the window that need a guard: several close registry plates, low confidence")
