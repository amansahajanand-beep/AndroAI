import os

# Must be set before androai_api is imported. No real services are contacted.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from androai_api import rate_limit  # noqa: E402
from androai_api.db import models as _models  # noqa: E402,F401
from androai_api.db.base import Base  # noqa: E402
from androai_api.db import get_db, get_session_factory  # noqa: E402
from androai_api.deps import get_storage  # noqa: E402
from androai_api.mail import Mail, get_mailer  # noqa: E402
from androai_api.main import app  # noqa: E402
from androai_api.services.notify import get_notifier  # noqa: E402
from androai_storage import LocalStorage  # noqa: E402

import tempfile  # noqa: E402


class Outbox:
    def __init__(self):
        self.sent: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.sent.append(mail)

    def last_token(self) -> str:
        return self.sent[-1].body.split("token=")[1].split()[0]


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def storage():
    return LocalStorage(tempfile.mkdtemp(prefix="st"))  # short path (Windows MAX_PATH)


class Notifier:
    def __init__(self):
        self.builds, self.tests = [], []

    def build_finished(self, r):
        self.builds.append(r)

    def test_finished(self, r):
        self.tests.append(r)


@pytest.fixture()
def notifier():
    return Notifier()


@pytest.fixture()
def outbox():
    return Outbox()


@pytest.fixture()
def client(db_factory, storage, outbox, notifier, monkeypatch):
    def _db():
        with db_factory() as s:
            yield s

    def _no_redis():
        raise ConnectionError("no redis in unit tests")

    monkeypatch.setattr(rate_limit, "get_redis", _no_redis)
    rate_limit.reset_local_state()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_session_factory] = lambda: db_factory
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_mailer] = lambda: outbox
    app.dependency_overrides[get_notifier] = lambda: notifier
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


PASSWORD = "correct-horse-battery"


def register_and_login(client, email="alice@example.com", password=PASSWORD):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["tokens"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


@pytest.fixture()
def alice(client):
    return register_and_login(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    return register_and_login(client, "bob@example.com")
