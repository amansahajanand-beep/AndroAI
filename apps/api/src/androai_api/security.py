"""Password hashing, access tokens, opaque tokens. No I/O."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import get_settings

_hasher = PasswordHasher()  # argon2id, library defaults (RFC 9106 low-memory profile)
# Verified against when the account does not exist, so response time doesn't reveal it.
_DUMMY_HASH = _hasher.hash("androai-dummy-password")

PASSWORD_MIN, PASSWORD_MAX = 10, 128


def validate_password_strength(password: str) -> str | None:
    """Return a user-facing problem description, or None if acceptable."""
    if len(password) < PASSWORD_MIN:
        return f"Password must be at least {PASSWORD_MIN} characters"
    if len(password) > PASSWORD_MAX:
        return f"Password must be at most {PASSWORD_MAX} characters"
    if password.lower() in {"password123", "1234567890", "qwertyuiop"} or len(set(password)) < 4:
        return "Password is too easy to guess"
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Same work whether or not the user exists (pass None for unknown users)."""
    try:
        ok = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 is appropriate for high-entropy random tokens (no salt/stretching needed)."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    expires_at: datetime


def create_access_token(user_id: str, session_id: str) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.jwt_access_ttl_minutes)
    token = jwt.encode(
        {"sub": user_id, "sid": session_id, "iat": now, "exp": exp, "jti": str(uuid.uuid4()),
         "typ": "access", "iss": s.app_name},
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )
    return token, exp


def decode_access_token(token: str) -> AccessClaims | None:
    s = get_settings()
    try:
        data = jwt.decode(
            token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer=s.app_name,
            options={"require": ["sub", "sid", "exp", "iat", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if data.get("typ") != "access":
        return None
    return AccessClaims(data["sub"], data["sid"], datetime.fromtimestamp(data["exp"], timezone.utc))
