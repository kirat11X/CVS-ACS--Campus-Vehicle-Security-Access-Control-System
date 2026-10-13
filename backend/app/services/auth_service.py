import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from backend.app.config import AUTH_SECRET_KEY, AUTH_TOKEN_TTL_MINUTES
from backend.app.models.identity import User

# scrypt parameters (~16 MiB per hash)
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def hash_password(password: str) -> str:
    """Returns 'scrypt$n$r$p$salt$hash' for storage in User.hashed_password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"

def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        expected = _b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)

def _sign(payload_b64: str) -> str:
    return _b64encode(hmac.new(AUTH_SECRET_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest())

def create_access_token(user: User) -> Tuple[str, datetime]:
    """Issues an HMAC-SHA256 signed bearer token: base64url(claims).base64url(signature)."""
    now = int(time.time())
    exp = now + AUTH_TOKEN_TTL_MINUTES * 60
    claims = {"sub": str(user.id), "role": user.role, "iat": now, "exp": exp}
    payload_b64 = _b64encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}", datetime.fromtimestamp(exp, tz=timezone.utc)

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Returns the token claims, or None if the token is malformed, forged or expired."""
    try:
        payload_b64, signature = token.split(".")
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(signature, _sign(payload_b64)):
        return None
    try:
        claims = json.loads(_b64decode(payload_b64))
    except ValueError:
        return None
    if not isinstance(claims, dict) or not isinstance(claims.get("exp"), int) or claims["exp"] < time.time():
        return None
    return claims

def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return None
    return user
