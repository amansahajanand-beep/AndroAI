"""Roles and permissions. Seeded idempotently (no migration data dependency)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Permission, Role

# permission -> description
PERMISSIONS: dict[str, str] = {
    "projects:manage": "Create, edit and delete own projects",
    "builds:run": "Submit build and test jobs",
    "billing:self": "View and manage own subscription",
    "admin:users": "List and manage all users",
    "admin:billing": "Manage plans, subscriptions and billing records",
    "admin:workers": "Manage the worker registry and queues",
    "admin:audit": "Read audit and system logs",
    "admin:system": "View system health and usage",
}

ROLES: dict[str, list[str]] = {
    "user": ["projects:manage", "builds:run", "billing:self"],
    "admin": list(PERMISSIONS),
}


def ensure_seeded(db: Session) -> None:
    perms = {p.name: p for p in db.scalars(select(Permission))}
    for name, desc in PERMISSIONS.items():
        if name not in perms:
            perms[name] = Permission(name=name, description=desc)
            db.add(perms[name])
    roles = {r.name: r for r in db.scalars(select(Role))}
    for rname, pnames in ROLES.items():
        role = roles.get(rname) or Role(name=rname, description=f"{rname} role")
        if rname not in roles:
            db.add(role)
            roles[rname] = role
        have = {p.name for p in role.permissions}
        for pn in pnames:
            if pn not in have:
                role.permissions.append(perms[pn])
    db.flush()


def get_role(db: Session, name: str) -> Role:
    ensure_seeded(db)
    return db.scalars(select(Role).where(Role.name == name)).one()


def permissions_of(roles: list[Role]) -> set[str]:
    return {p.name for r in roles for p in r.permissions}
