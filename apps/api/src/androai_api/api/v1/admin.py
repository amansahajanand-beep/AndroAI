from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import AuthContext, require_permission
from ...errors import AppError
from ...models import AuditLog, Role, User, UserRole
from ...schemas import AdminUserOut, AdminUserPatchIn, AuditLogOut, OverviewOut, Page
from ...services import auth as auth_svc
from ...services import rbac
from ...services.audit import audit
from .users import user_out

router = APIRouter(tags=["admin"])
users_perm = require_permission("admin:users")
audit_perm = require_permission("admin:audit")


def _admin_out(u: User) -> AdminUserOut:
    return AdminUserOut(**user_out(u).model_dump(), last_login_at=u.last_login_at)


@router.get("/users", response_model=Page[AdminUserOut])
def list_users(q: str | None = Query(default=None, max_length=100), limit: int = Query(50, ge=1, le=200),
               offset: int = Query(0, ge=0), ctx: AuthContext = Depends(users_perm), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.contains(q.strip().lower(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)))
    from ...models import Project

    counts = dict(db.execute(select(Project.tenant_id, func.count()).where(
        Project.tenant_id.in_([u.tenant_id for u in rows]), Project.status != "deleted").group_by(Project.tenant_id)).all()) if rows else {}
    items = []
    for u in rows:
        out = _admin_out(u)
        out.project_count = counts.get(u.tenant_id, 0)
        items.append(out)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=AdminUserOut)
def get_user(user_id: str, ctx: AuthContext = Depends(users_perm), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise AppError(404, "user_not_found", "User not found")
    return _admin_out(u)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(user_id: str, body: AdminUserPatchIn, ctx: AuthContext = Depends(users_perm),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise AppError(404, "user_not_found", "User not found")
    changes: dict = {}
    if body.is_active is not None and body.is_active != u.is_active:
        if u.id == ctx.user_id:
            raise AppError(409, "self_lockout", "You cannot deactivate your own account")
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            auth_svc.revoke_all_sessions(db, u.id)
    if body.roles is not None:
        rbac.ensure_seeded(db)
        wanted = set(body.roles)
        roles = {r.name: r for r in db.scalars(select(Role))}
        unknown = wanted - set(roles)
        if unknown:
            raise AppError(422, "unknown_role", f"Unknown role(s): {', '.join(sorted(unknown))}")
        if u.id == ctx.user_id and "admin" not in wanted:
            raise AppError(409, "self_lockout", "You cannot remove your own admin role")
        db.query(UserRole).filter(UserRole.user_id == u.id).delete()
        for name in wanted:
            db.add(UserRole(user_id=u.id, role_id=roles[name].id))
        changes["roles"] = sorted(wanted)
    audit(db, "admin.user_update", actor_id=ctx.user_id, tenant_id=u.tenant_id, resource_type="user",
          resource_id=u.id, ip=ctx.ip, detail=changes)
    db.commit()
    db.refresh(u)
    return _admin_out(u)


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(action: str | None = Query(default=None, max_length=64), actor_id: str | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               ctx: AuthContext = Depends(audit_perm), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit).offset(offset)))
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_({r.actor_id for r in rows if r.actor_id}))).all()) if rows else {}
    items = []
    for r in rows:
        out = AuditLogOut.model_validate(r)
        out.actor_email = emails.get(r.actor_id) if r.actor_id else None
        items.append(out)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/overview", response_model=OverviewOut)
def overview(ctx: AuthContext = Depends(require_permission("admin:system")), db: Session = Depends(get_db)):
    from datetime import datetime, timedelta, timezone

    from ...models import AiUsage, BuildJob, Project, TestJob

    now = datetime.now(timezone.utc)
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    finished_24h = count(select(func.count()).select_from(BuildJob).where(BuildJob.finished_at >= day))
    failed_24h = count(select(func.count()).select_from(BuildJob).where(BuildJob.finished_at >= day, BuildJob.state == "failed"))
    cost = count(select(func.coalesce(func.sum(AiUsage.cost_micros), 0)).where(AiUsage.created_at >= day))
    return OverviewOut(
        users=count(select(func.count()).select_from(User)),
        active_users_7d=count(select(func.count()).select_from(User).where(User.last_login_at >= week)),
        projects=count(select(func.count()).select_from(Project).where(Project.status != "deleted")),
        builds_today=count(select(func.count()).select_from(BuildJob).where(BuildJob.created_at >= day)),
        build_failure_rate_24h=(failed_24h / finished_24h) if finished_24h else 0.0,
        queue_depth={
            "builds": count(select(func.count()).select_from(BuildJob).where(BuildJob.state.in_(("queued", "blocked")))),
            "tests": count(select(func.count()).select_from(TestJob).where(TestJob.state.in_(("queued", "blocked")))),
        },
        ai_cost_today_usd=round(cost / 1_000_000, 4),
    )
