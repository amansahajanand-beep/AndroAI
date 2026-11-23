"""Registration, login, refresh-token rotation, email verification, password reset."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import security
from ..config import get_settings
from ..errors import AppError
from ..mail import Mail, Mailer
from ..models import User, UserRole, UserSession, UserToken
from . import rbac
from .audit import audit

VERIFY, RESET = "verify_email", "reset_password"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def _issue_session(
    db: Session, user: User, *, family_id: str | None, user_agent: str | None, ip: str | None
) -> TokenPair:
    s = get_settings()
    refresh = security.new_opaque_token()
    exp = _now() + timedelta(days=s.refresh_ttl_days)
    sess = UserSession(
        id=str(uuid.uuid4()), user_id=user.id, family_id=family_id or str(uuid.uuid4()),
        refresh_token_hash=security.hash_token(refresh), expires_at=exp,
        user_agent=(user_agent or "")[:300] or None, ip_address=ip, last_used_at=_now(),
    )
    db.add(sess)
    db.flush()
    access, access_exp = security.create_access_token(user.id, sess.id)
    return TokenPair(access, access_exp, refresh, exp)


def _create_email_token(db: Session, user: User, purpose: str, ttl: timedelta) -> str:
    token = security.new_opaque_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=security.hash_token(token),
                     expires_at=_now() + ttl))
    return token


def _consume_token(db: Session, token: str, purpose: str) -> User:
    h = security.hash_token(token)
    row = db.scalars(select(UserToken).where(UserToken.token_hash == h, UserToken.purpose == purpose)).first()
    if not row or row.used_at or row.expires_at < _now():
        raise AppError(400, "invalid_token", "This link is invalid or has expired")
    claimed = db.execute(
        update(UserToken).where(UserToken.id == row.id, UserToken.used_at.is_(None)).values(used_at=_now())
    ).rowcount
    if claimed != 1:
        raise AppError(400, "invalid_token", "This link is invalid or has expired")
    user = db.get(User, row.user_id)
    if not user:
        raise AppError(400, "invalid_token", "This link is invalid or has expired")
    return user


def register(db: Session, mailer: Mailer, *, email: str, password: str, display_name: str | None,
             ip: str | None) -> User:
    s = get_settings()
    if not s.allow_registration:
        raise AppError(403, "registration_disabled", "Registration is currently closed")
    problem = security.validate_password_strength(password)
    if problem:
        raise AppError(422, "weak_password", problem)
    email = normalize_email(email)
    rbac.ensure_seeded(db)
    uid = str(uuid.uuid4())
    user = User(id=uid, tenant_id=uid, email=email, password_hash=security.hash_password(password),
                display_name=display_name)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Generic message would hide the duplicate from enumeration but harms UX; we accept
        # the standard trade-off: registration reveals existence, login/reset do not.
        raise AppError(409, "email_taken", "An account with this email already exists") from None
    db.add(UserRole(user_id=user.id, role_id=rbac.get_role(db, "user").id))
    token = _create_email_token(db, user, VERIFY, timedelta(hours=s.email_token_ttl_hours))
    audit(db, "auth.register", actor_id=user.id, tenant_id=user.tenant_id, resource_type="user",
          resource_id=user.id, ip=ip)
    db.commit()
    mailer.send(Mail(email, "Verify your AndroAI email",
                     f"Verify your email: {s.app_url}/verify-email?token={token}\n\nExpires in {s.email_token_ttl_hours}h."))
    db.refresh(user)
    return user


def login(db: Session, *, email: str, password: str, user_agent: str | None, ip: str | None) -> tuple[User, TokenPair]:
    s = get_settings()
    user = db.scalars(select(User).where(User.email == normalize_email(email))).first()
    ok = security.verify_password(password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        audit(db, "auth.login_failed", actor_id=user.id if user else None, ip=ip,
              detail={"reason": "bad_credentials" if not ok else "inactive"})
        db.commit()
        raise AppError(401, "invalid_credentials", "Invalid email or password")
    if s.require_email_verification and not user.email_verified_at:
        raise AppError(403, "email_not_verified", "Verify your email before signing in")
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    user.last_login_at = _now()
    pair = _issue_session(db, user, family_id=None, user_agent=user_agent, ip=ip)
    audit(db, "auth.login", actor_id=user.id, tenant_id=user.tenant_id, ip=ip)
    db.commit()
    return user, pair


def refresh(db: Session, *, refresh_token: str, user_agent: str | None, ip: str | None) -> TokenPair:
    sess = db.scalars(
        select(UserSession).where(UserSession.refresh_token_hash == security.hash_token(refresh_token))
    ).first()
    if not sess or sess.revoked_at or sess.expires_at < _now():
        raise AppError(401, "invalid_refresh_token", "Session expired, please sign in again")
    # Atomic claim: only one concurrent request may rotate this token.
    claimed = db.execute(
        update(UserSession)
        .where(UserSession.id == sess.id, UserSession.rotated_at.is_(None), UserSession.revoked_at.is_(None))
        .values(rotated_at=_now())
    ).rowcount
    if claimed != 1:
        # Token reuse => likely theft. Kill the whole family.
        db.execute(update(UserSession).where(UserSession.family_id == sess.family_id,
                                             UserSession.revoked_at.is_(None)).values(revoked_at=_now()))
        audit(db, "auth.refresh_reuse_detected", actor_id=sess.user_id, ip=ip,
              detail={"family_id": sess.family_id})
        db.commit()
        raise AppError(401, "invalid_refresh_token", "Session expired, please sign in again")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        db.commit()
        raise AppError(401, "invalid_refresh_token", "Session expired, please sign in again")
    pair = _issue_session(db, user, family_id=sess.family_id, user_agent=user_agent, ip=ip)
    db.commit()
    return pair


def revoke_family(db: Session, session_id: str) -> None:
    sess = db.get(UserSession, session_id)
    if sess:
        db.execute(update(UserSession).where(UserSession.family_id == sess.family_id,
                                             UserSession.revoked_at.is_(None)).values(revoked_at=_now()))


def logout_by_refresh_token(db: Session, refresh_token: str) -> None:
    sess = db.scalars(
        select(UserSession).where(UserSession.refresh_token_hash == security.hash_token(refresh_token))
    ).first()
    if sess:
        revoke_family(db, sess.id)
        audit(db, "auth.logout", actor_id=sess.user_id)
        db.commit()


def revoke_all_sessions(db: Session, user_id: str) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id,
                                         UserSession.revoked_at.is_(None)).values(revoked_at=_now()))


def verify_email(db: Session, token: str) -> None:
    user = _consume_token(db, token, VERIFY)
    user.email_verified_at = user.email_verified_at or _now()
    audit(db, "auth.email_verified", actor_id=user.id, tenant_id=user.tenant_id)
    db.commit()


def resend_verification(db: Session, mailer: Mailer, user: User) -> None:
    if user.email_verified_at:
        return
    s = get_settings()
    token = _create_email_token(db, user, VERIFY, timedelta(hours=s.email_token_ttl_hours))
    db.commit()
    mailer.send(Mail(user.email, "Verify your AndroAI email", f"{s.app_url}/verify-email?token={token}"))


def request_password_reset(db: Session, mailer: Mailer, *, email: str, ip: str | None) -> None:
    """Always succeeds from the caller's perspective (no account enumeration)."""
    s = get_settings()
    user = db.scalars(select(User).where(User.email == normalize_email(email))).first()
    if user and user.is_active:
        token = _create_email_token(db, user, RESET, timedelta(minutes=s.reset_token_ttl_minutes))
        audit(db, "auth.password_reset_requested", actor_id=user.id, ip=ip)
        db.commit()
        mailer.send(Mail(user.email, "Reset your AndroAI password",
                         f"Reset your password: {s.app_url}/reset-password?token={token}\n\n"
                         f"Expires in {s.reset_token_ttl_minutes} minutes. Ignore this email if you did not ask."))


def reset_password(db: Session, *, token: str, new_password: str, ip: str | None) -> None:
    problem = security.validate_password_strength(new_password)
    if problem:
        raise AppError(422, "weak_password", problem)
    user = _consume_token(db, token, RESET)
    user.password_hash = security.hash_password(new_password)
    user.email_verified_at = user.email_verified_at or _now()  # proved mailbox control
    revoke_all_sessions(db, user.id)
    audit(db, "auth.password_reset", actor_id=user.id, tenant_id=user.tenant_id, ip=ip)
    db.commit()


def change_password(db: Session, user: User, *, current: str, new: str) -> None:
    if not security.verify_password(current, user.password_hash):
        raise AppError(403, "invalid_credentials", "Current password is incorrect")
    problem = security.validate_password_strength(new)
    if problem:
        raise AppError(422, "weak_password", problem)
    user.password_hash = security.hash_password(new)
    revoke_all_sessions(db, user.id)
    audit(db, "auth.password_changed", actor_id=user.id, tenant_id=user.tenant_id)
    db.commit()
