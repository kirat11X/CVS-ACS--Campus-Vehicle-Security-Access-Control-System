from typing import Optional
from pydantic import BaseModel, Field
from backend.app.models.enums import PersonType, ResidenceType

class OwnerCreate(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=50, description="Institutional ID, e.g. STUDENT-2026-123")
    full_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=20)
    person_type: PersonType
    residence_type: ResidenceType = Field(default=ResidenceType.UNKNOWN, description="Residence belongs to the person")
    residence: Optional[str] = Field(None, max_length=100, description="e.g. BH-4, Room 312")
    department: Optional[str] = Field(None, max_length=100)
