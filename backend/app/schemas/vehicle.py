from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from backend.app.models.enums import VehicleCategory, VehicleStatus

class VehicleCreate(BaseModel):
    plate: str = Field(..., description="License plate number (will be normalized)", example="PB65 AB 1234")
    vehicle_category: VehicleCategory = Field(default=VehicleCategory.STUDENT, description="Classification category")
    owner_id: Optional[str] = Field(None, description="UUID or Institutional Identifier (e.g. STUDENT-2026-123)")
    make_model: Optional[str] = Field(None, description="Vehicle make and model", example="Hyundai i20")
    color: Optional[str] = Field(None, description="Vehicle color", example="White")
    valid_from: Optional[datetime] = Field(None, description="Access validity start time (UTC)")
    valid_until: Optional[datetime] = Field(None, description="Access validity end time (UTC)")
    notes: Optional[str] = Field(None, description="Security / parking notes")

class VehicleUpdate(BaseModel):
    owner_id: Optional[str] = Field(None, description="Updated owner UUID or institutional identifier")
    vehicle_category: Optional[VehicleCategory] = None
    status: Optional[VehicleStatus] = None
    make_model: Optional[str] = None
    color: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None
    plate: Optional[str] = Field(None, description="Plate cannot be mutated; if provided, must match existing plate")

class VehicleSimpleResponse(BaseModel):
    id: str
    plate: str
    raw_plate: str
    category: str
    status: str
    is_active: bool
    make_model: Optional[str] = None
    color: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    notes: Optional[str] = None

class OwnerContextResponse(BaseModel):
    id: str
    institutional_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    person_type: Optional[str] = None
    residence_type: Optional[str] = None
    residence: Optional[str] = None
    department: Optional[str] = None
    status: str

class ResidenceContextResponse(BaseModel):
    person_type: Optional[str] = None
    residence_type: Optional[str] = None
    residence: Optional[str] = None
    department: Optional[str] = None
    is_active: bool
    vehicle_status: str

class VehicleDetailResponse(BaseModel):
    vehicle: VehicleSimpleResponse
    owner: Optional[OwnerContextResponse] = None
    context: ResidenceContextResponse
