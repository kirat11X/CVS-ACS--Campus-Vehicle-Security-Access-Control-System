from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.models.enums import PersonType, ResidenceType
from backend.app.schemas.vehicle import OwnerContextResponse, VehicleDetailResponse
from backend.app.services.identifier_validator import validate_and_normalize_identifier

class OwnerCreate(BaseModel):
    identifier: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Institutional ID: Student (8 digits, e.g. 24103042), Faculty (F + 7 digits, e.g. F1234567), Resident (R + 4-digit house no, e.g. R1042)",
    )
    full_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=20)
    person_type: PersonType
    residence_type: ResidenceType = Field(default=ResidenceType.UNKNOWN, description="Residence belongs to the person")
    residence: Optional[str] = Field(None, max_length=100, description="e.g. BH-4, Room 312 or House 1042")
    department: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_identifier_format(self) -> "OwnerCreate":
        self.identifier = validate_and_normalize_identifier(self.identifier, self.person_type)
        if self.person_type == PersonType.RESIDENT and not self.residence:
            self.residence = f"House {self.identifier[1:]}"
        return self

class OwnerUpdate(BaseModel):
    """The institutional identifier is immutable, like a plate; everything else is editable by ADMIN."""
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=20)
    person_type: Optional[PersonType] = None
    residence_type: Optional[ResidenceType] = None
    residence: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)

class OwnerDetailResponse(BaseModel):
    owner: OwnerContextResponse
    vehicles: List[VehicleDetailResponse]
