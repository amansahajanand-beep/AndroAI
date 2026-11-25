"""DEV ONLY: run the API on SQLite + local-disk storage so the web app can be developed and
integration-tested without PostgreSQL/Redis/S3. Never use this for anything but local work.

    python scripts/dev/run_api_sqlite.py            # http://localhost:8000, data in .data/dev/

Seeds an admin account on first run and prints its generated password once. Rate limiting uses
the in-process fallback (no Redis). Email links are logged to the console.
"""

from __future__ import annotations

import os
import secrets
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".data" / "dev"
DATA.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://dev:dev@localhost:5432/dev")  # satisfies validation; never connected
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")  # never connected (rate limiter falls back)
os.environ.setdefault("JWT_SECRET", "dev-only-" + "x" * 40)
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_LOCAL_PATH", str(DATA / "storage"))
os.environ.setdefault("APP_URL", "http://localhost:3000")

# AI assistant bridge: run the code-modification job inside this process (dev only). It needs the
# codegen library and the ai-agent job module importable, and the NVIDIA_* settings from .env.
os.environ.setdefault("AGENT_DEV_BRIDGE", "1")
for _src in (ROOT / "packages/agent-core/codegen/src", ROOT / "workers/ai-agent/src"):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
_dotenv = ROOT / ".env"
if _dotenv.is_file():
    for _line in _dotenv.read_text(encoding="utf-8").splitlines():
        _name, _sep, _value = _line.partition("=")
        if _sep and _name.strip() in ("NVIDIA_API_KEY", "NVIDIA_MODEL", "NVIDIA_BASE_URL"):
            os.environ.setdefault(_name.strip(), _value.split(" #", 1)[0].strip().strip("\"'"))

import uvicorn  # noqa: E402
from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from androai_api import rate_limit, security  # noqa: E402
from androai_api.db import get_db, get_session_factory, models  # noqa: E402,F401
from androai_api.db.base import Base  # noqa: E402
from androai_api.main import app  # noqa: E402
from androai_api.models import User, UserRole  # noqa: E402
from androai_api.services import rbac  # noqa: E402

engine = create_engine(f"sqlite:///{DATA / 'dev.db'}", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(engine, "connect")
def _fk(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")


Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)


def _db():
    with factory() as s:
        yield s


def _no_redis():
    raise ConnectionError("dev server runs without Redis")


rate_limit.get_redis = _no_redis  # type: ignore[assignment]
app.dependency_overrides[get_db] = _db
app.dependency_overrides[get_session_factory] = lambda: factory

with factory() as db:
    rbac.ensure_seeded(db)
    if db.scalars(select(User).where(User.email == "admin@example.com")).first() is None:
        pw = os.environ.get("DEV_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        uid = str(uuid.uuid4())
        db.add(User(id=uid, tenant_id=uid, email="admin@example.com", password_hash=security.hash_password(pw),
                    display_name="Dev Admin"))
        db.flush()
        for role in ("user", "admin"):
            db.add(UserRole(user_id=uid, role_id=rbac.get_role(db, role).id))
        db.commit()
        print(f"[dev] seeded admin@example.com  password: {pw}", flush=True)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning")
    sys.exit(0)
