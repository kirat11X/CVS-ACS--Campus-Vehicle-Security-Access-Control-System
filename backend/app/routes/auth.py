from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_current_user, get_db
from backend.app.services.auth_service import authenticate, create_access_token
from backend.app.schemas.feed import UserSummary

router = APIRouter(prefix="/auth", tags=["Auth"])

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=256)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserSummary

@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Exchanges a username and password for a bearer token."""
    user = authenticate(db, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_at = create_access_token(user)
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserSummary(id=user.id, username=user.username, full_name=user.full_name, role=user.role),
    )

@router.get("/me", response_model=UserSummary)
def me(user: CurrentUser = Depends(get_current_user)):
    return UserSummary(id=user.id, username=user.username, full_name=user.full_name, role=user.role.value)
