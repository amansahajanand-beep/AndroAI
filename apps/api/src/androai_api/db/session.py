"""Database connection abstraction (sync SQLAlchemy 2.x + psycopg 3).

The engine is created lazily so importing this module never opens a connection.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    with _session_factory()() as session:
        yield session


def get_session_factory() -> sessionmaker[Session]:
    """Dependency for streaming endpoints that must open their own short-lived sessions."""
    return _session_factory()


def check_database() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
