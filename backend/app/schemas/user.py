from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import UserRole

class UserAccount(BaseModel):
    """A console account as shown to administrators. The password hash is never returned."""
    id: UUID
    username: str
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=120)
    role: UserRole
    password: str = Field(..., min_length=8, max_length=256)

class UserUpdate(BaseModel):
    """Username is immutable (it is the sign-in name recorded on audit rows)."""
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = Field(None, min_length=3, max_length=120)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = Field(None, description="false disables sign-in; accounts are never deleted")
    password: Optional[str] = Field(None, min_length=8, max_length=256, description="Sets a new password (administrator reset)")

class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)
