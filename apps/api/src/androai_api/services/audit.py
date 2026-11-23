"""Audit trail. Rows are added to the caller's transaction; never pass secrets in `detail`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog

_FORBIDDEN_KEYS = {"password", "token", "secret", "refresh_token", "access_token", "api_key"}


def audit(
    db: Session,
    action: str,
    *,
    actor_id: str | None = None,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    detail: dict | None = None,
) -> None:
    clean = {k: v for k, v in (detail or {}).items() if k.lower() not in _FORBIDDEN_KEYS}
    db.add(
        AuditLog(
            action=action, actor_id=actor_id, tenant_id=tenant_id, resource_type=resource_type,
            resource_id=resource_id, ip_address=ip, detail=clean,
        )
    )
