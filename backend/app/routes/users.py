from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.dependencies import CurrentUser, get_db, require_admin
from backend.app.models.enums import UserRole
from backend.app.models.identity import User
from backend.app.schemas.user import UserAccount, UserCreate, UserUpdate
from backend.app.services.auth_service import hash_password

router = APIRouter(prefix="/users", tags=["Users"])

def _account(user: User) -> UserAccount:
    return UserAccount(
        id=user.id, username=user.username, full_name=user.full_name, email=user.email, role=user.role,
        is_active=user.is_active, created_at=user.created_at, updated_at=user.updated_at,
    )

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def _email_taken(db: Session, email: str, exclude_id: Optional[UUID] = None) -> bool:
    query = db.query(User.id).filter(func.lower(User.email) == email.lower())
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.first() is not None

@router.get("", response_model=List[UserAccount])
def list_users(
    q: Optional[str] = Query(None, min_length=1, max_length=100, description="Username, name or email fragment"),
    role: Optional[UserRole] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """Console accounts (ADMIN only). Password hashes are never returned."""
    query = db.query(User)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.filter(or_(
            User.username.ilike(pattern, escape="\\"),
            User.full_name.ilike(pattern, escape="\\"),
            User.email.ilike(pattern, escape="\\"),
        ))
    if role:
        query = query.filter(User.role == role.value)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    users = query.order_by(User.is_active.desc(), User.role.asc(), User.username.asc()).offset(skip).limit(limit).all()
    return [_account(u) for u in users]

@router.post("", response_model=UserAccount, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """Creates a GUARD, SUPERVISOR or ADMIN account (ADMIN only). 409 if the username or email is taken."""
    username = payload.username.strip()
    if db.query(User.id).filter(User.username == username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Username '{username}' is already taken.")
    email = payload.email.strip()
    if _email_taken(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account already uses this email.")
    account = User(
        username=username,
        full_name=payload.full_name.strip(),
        email=email,
        role=payload.role.value,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account(account)

@router.patch("/{user_id}", response_model=UserAccount)
def update_user(user_id: UUID, payload: UserUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """
    Updates an account (ADMIN only): name, email, role, active flag or a password reset.
    Accounts are never deleted (they are referenced by audit records); set is_active=false instead.
    An administrator cannot disable or demote their own account, so the console cannot be locked out.
    """
    account = db.get(User, user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.")
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(k, "") is None for k in ("full_name", "email", "role", "is_active", "password")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fields cannot be set to null.")

    if account.id == user.id:
        if changes.get("is_active") is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot disable your own account.")
        if "role" in changes and changes["role"] != UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own ADMIN role.")

    if "email" in changes:
        email = changes["email"].strip()
        if _email_taken(db, email, exclude_id=account.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another account already uses this email.")
        account.email = email
    if "full_name" in changes:
        account.full_name = changes["full_name"].strip()
    if "role" in changes:
        account.role = changes["role"].value
    if "is_active" in changes:
        account.is_active = changes["is_active"]
    if "password" in changes:
        account.hashed_password = hash_password(changes["password"])
    db.commit()
    db.refresh(account)
    return _account(account)
