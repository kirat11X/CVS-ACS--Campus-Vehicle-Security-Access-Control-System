from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from backend.app.models.enums import GateStatus

class GateCreate(BaseModel):
    id: str = Field(..., max_length=30, description="Unique gate identifier, e.g. GATE_1")
    name: str = Field(..., max_length=100, description="Gate display name, e.g. Main North Gate")
    location: Optional[str] = Field(None, max_length=200, description="Physical location or description")
    status: GateStatus = Field(default=GateStatus.ACTIVE, description="Operational status of gate infrastructure")
    camera_id: Optional[str] = Field(None, max_length=50, description="Associated Frigate camera ID")
    direction_capability: str = Field(default="BIDIRECTIONAL", max_length=20)

class GateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    status: Optional[GateStatus] = None
    camera_id: Optional[str] = Field(None, max_length=50)
    direction_capability: Optional[str] = Field(None, max_length=20)

class GateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: Optional[str]
    status: GateStatus
    camera_id: Optional[str]
    direction_capability: str
    created_at: datetime
    updated_at: datetime
