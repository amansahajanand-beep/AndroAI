"""Operational CLI:
  python -m androai_api.cli create-admin <email>
  python -m androai_api.cli sweep [--loop SECONDS]   # scheduler maintenance (reap lost/timed-out jobs)

The password is read from the ADMIN_PASSWORD environment variable or an interactive
prompt, never from argv (which is visible in process listings).
"""

from __future__ import annotations

import getpass
import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from . import security
from .db.session import _session_factory
from .models import User, UserRole
from .services import rbac
from .services.audit import audit


def create_admin(email: str, password: str) -> str:
    problem = security.validate_password_strength(password)
    if problem:
        raise SystemExit(problem)
    with _session_factory()() as db:
        rbac.ensure_seeded(db)
        email = email.strip().lower()
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            uid = str(uuid.uuid4())
            user = User(id=uid, tenant_id=uid, email=email, password_hash=security.hash_password(password),
                        email_verified_at=datetime.now(timezone.utc))
            db.add(user)
            db.flush()
            db.add(UserRole(user_id=user.id, role_id=rbac.get_role(db, "user").id))
        if "admin" not in {r.name for r in user.roles}:
            db.add(UserRole(user_id=user.id, role_id=rbac.get_role(db, "admin").id))
        audit(db, "admin.cli_create_admin", actor_id=user.id, tenant_id=user.tenant_id)
        db.commit()
        return user.id


def sweep(loop_seconds: float | None = None) -> None:
    import time

    from .deps import get_storage
    from .services import dispatch
    from .services.notify import get_notifier

    while True:
        with _session_factory()() as db:
            stats = dispatch.reap(db, get_storage(), get_notifier())
        if any(stats.values()):
            print(stats, flush=True)
        if loop_seconds is None:
            return
        time.sleep(loop_seconds)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "sweep":
        sweep(float(argv[2]) if len(argv) == 3 and argv[1] == "--loop" else None)
        return
    if len(argv) != 2 or argv[0] != "create-admin":
        sys.exit("usage: python -m androai_api.cli create-admin <email> | sweep [--loop SECONDS]")
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    print(f"admin ready: {create_admin(argv[1], pw)}")


if __name__ == "__main__":
    main()
