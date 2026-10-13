import uuid
from dataclasses import dataclass
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.app.db import SessionLocal
from backend.app.models.identity import User
from backend.app.models.enums import UserRole
from backend.app.services.auth_service import decode_access_token

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    username: str
    full_name: str
    role: UserRole

bearer_scheme = HTTPBearer(auto_error=False)

def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> CurrentUser:
    """
    Resolves the bearer token to an active user. Uses its own short-lived session
    (not get_db) so long-lived responses such as the SSE stream hold no connection.
    The role is read from the database, never trusted from the token.
    """
    if credentials is None:
        raise _unauthorized("Authentication required.")
    claims = decode_access_token(credentials.credentials)
    if not claims:
        raise _unauthorized("Invalid or expired token.")
    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError:
        raise _unauthorized("Invalid or expired token.")

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            raise _unauthorized("User account is not active.")
        try:
            role = UserRole(user.role)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Unrecognised role '{user.role}'.")
        return CurrentUser(id=user.id, username=user.username, full_name=user.full_name, role=role)

def require_roles(*roles: UserRole):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.role.value} is not permitted for this action.",
            )
        return user
    return dependency

require_staff = require_roles(UserRole.GUARD, UserRole.SUPERVISOR, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)
