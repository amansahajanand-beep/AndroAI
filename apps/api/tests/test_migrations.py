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


def test_migration_matches_models_and_downgrades():
    eng = create_engine("sqlite://")
    m2 = _load("0002")
    with eng.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            m2.upgrade()
        assert len(inspect(conn).get_table_names()) == len(Base.metadata.tables)
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == [], f"models and migration differ: {diff}"
        with Operations.context(ctx):
            m2.downgrade()
        assert inspect(conn).get_table_names() == []
