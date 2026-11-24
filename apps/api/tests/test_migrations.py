"""The Alembic revision must (a) run up and down and (b) match the models exactly, so a
model change without a migration fails CI. Runs on SQLite; PostgreSQL DDL is checked
separately by `alembic upgrade head --sql` in CI."""

import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from androai_api.db import models as _models  # noqa: F401
from androai_api.db.base import Base

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(name: str):
    path = next(VERSIONS.glob(f"*_{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_single_linear_history():
    revs = {}
    for p in VERSIONS.glob("*.py"):
        spec = importlib.util.spec_from_file_location(p.stem, p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        revs[m.revision] = m.down_revision
    heads = set(revs) - {d for d in revs.values() if d}
    assert len(heads) == 1, f"multiple alembic heads: {heads}"


def test_migrations_match_models_and_downgrade():
    eng = create_engine("sqlite://")
    mods = [_load("0002"), _load("0003")]
    with eng.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            for m in mods:
                m.upgrade()
        assert len(inspect(conn).get_table_names()) == len(Base.metadata.tables)
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == [], f"models and migrations differ: {diff}"
        with Operations.context(ctx):
            for m in reversed(mods):
                m.downgrade()
        assert inspect(conn).get_table_names() == []


def test_0003_backfills_existing_build_rows():
    """Upgrading a database that already has build jobs numbers them per project in creation order."""
    import sqlalchemy as sa

    eng = create_engine("sqlite://")
    m2, m3 = _load("0002"), _load("0003")
    with eng.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            m2.upgrade()
        conn.execute(sa.text("INSERT INTO users (id, tenant_id, email, password_hash, is_active, created_at, updated_at) "
                             "VALUES ('u1','u1','a@b.c','x',1,'2026-01-01','2026-01-01')"))
        for pid in ("p1", "p2"):
            conn.execute(sa.text("INSERT INTO projects (id, tenant_id, owner_id, name, source_type, status, metadata, created_at, updated_at) "
                                 f"VALUES ('{pid}','u1','u1','{pid}','empty','active','{{}}','2026-01-01','2026-01-01')"))
            conn.execute(sa.text("INSERT INTO project_file_snapshots (id, tenant_id, project_id, version, storage_key, size, sha256, file_count, created_at) "
                                 f"VALUES ('s{pid}','u1','{pid}',1,'k',1,'h',1,'2026-01-01')"))
        for i, (job, pid) in enumerate([("j1", "p1"), ("j2", "p1"), ("j3", "p2")]):
            conn.execute(sa.text("INSERT INTO build_jobs (id, tenant_id, user_id, state, priority, attempts, max_attempts, timeout_seconds, "
                                 "cancel_requested, toolchain, project_id, snapshot_id, variant, output_type, gradle_tasks, created_at, updated_at) "
                                 f"VALUES ('{job}','u1','u1','queued',100,0,2,900,0,'{{}}','{pid}','s{pid}','debug','apk','[]','2026-01-0{i + 1}','2026-01-01')"))
        with Operations.context(ctx):
            m3.upgrade()
        got = dict(conn.execute(sa.text("SELECT id, number FROM build_jobs")).fetchall())
        assert got == {"j1": 1, "j2": 2, "j3": 1}
