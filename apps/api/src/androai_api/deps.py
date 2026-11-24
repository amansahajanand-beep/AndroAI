"""FastAPI dependencies: authentication, authorisation, tenant-scoped lookups, storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from androai_storage import LocalStorage, ObjectStorage, S3Storage

from .config import get_settings
from .db import get_db
from .errors import AppError
from .models import Project, User, UserSession
from .rate_limit import client_ip
from .security import decode_access_token
from .services import rbac

_bearer = HTTPBearer(auto_error=False, description="Access token from /api/v1/auth/login")


@dataclass
class AuthContext:
    user: User
    session_id: str
    permissions: set[str]
    ip: str | None
    expires_at: datetime | None = None
    via_cookie: bool = False

    @property
    def tenant_id(self) -> str:
        return self.user.tenant_id

    @property
    def user_id(self) -> str:
        return self.user.id


ACCESS_COOKIE = "ap_access"
REFRESH_COOKIE = "ap_refresh"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def check_origin(request: Request, *, require: bool) -> None:
    """CSRF defence for cookie sessions: browsers always send Origin on cross-site and on
    same-site unsafe requests, so a state-changing request whose Origin is missing/foreign is
    refused. (SameSite=Lax on the cookies is the second layer.) Bearer-token clients are exempt."""
    origin = request.headers.get("origin")
    if origin is None:
        ref = request.headers.get("referer")
        if ref:
            from urllib.parse import urlsplit

            p = urlsplit(ref)
            origin = f"{p.scheme}://{p.netloc}"
    if origin is None:
        if require:
            raise AppError(403, "csrf", "Missing Origin header")
        return
    if origin.rstrip("/") not in get_settings().trusted_origins:
        raise AppError(403, "csrf", "Cross-origin request refused")


def current_auth(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    via_cookie = False
    token = creds.credentials if creds is not None else None
    if token is None:
        token = request.cookies.get(ACCESS_COOKIE)
        via_cookie = token is not None
    if token is None:
        raise AppError(401, "not_authenticated", "Authentication required")
    if via_cookie and request.method not in _SAFE_METHODS:
        check_origin(request, require=True)
    claims = decode_access_token(token)
    if claims is None:
        raise AppError(401, "invalid_token", "Invalid or expired access token")
    sess = db.get(UserSession, claims.session_id)
    # Revocation check: logout / password change / refresh-reuse kill access tokens immediately.
    if sess is None or sess.revoked_at is not None or sess.user_id != claims.user_id:
        raise AppError(401, "invalid_token", "Invalid or expired access token")
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "invalid_token", "Invalid or expired access token")
    return AuthContext(user, sess.id, rbac.permissions_of(user.roles), client_ip(request),
                       expires_at=claims.expires_at, via_cookie=via_cookie)


def require_permission(name: str):
    def dep(ctx: AuthContext = Depends(current_auth)) -> AuthContext:
        if name not in ctx.permissions:
            raise AppError(403, "forbidden", "You do not have permission to perform this action")
        return ctx

    return dep


def get_owned_project(db: Session, ctx: AuthContext, project_id: str) -> Project:
    """The only way routes load a project: scoped to the caller's tenant. A project in
    another tenant is indistinguishable from a missing one (404)."""
    try:
        project = db.scalars(
            select(Project).where(
                Project.id == project_id, Project.tenant_id == ctx.tenant_id, Project.status != "deleted"
            )
        ).first()
    except Exception:  # malformed id on strict-UUID backends
        project = None
    if project is None:
        raise AppError(404, "project_not_found", "Project not found")
    return project


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return S3Storage(
            s.s3_bucket, endpoint_url=s.s3_endpoint_url, access_key_id=s.s3_access_key_id,
            secret_access_key=s.s3_secret_access_key, region=s.s3_region,
        )
    return LocalStorage(s.storage_local_path)
