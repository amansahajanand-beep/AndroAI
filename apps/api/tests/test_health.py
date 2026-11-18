import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from androai_api.config import Settings
from androai_api.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["service"] == "androai-api"


def test_error_envelope():
    with TestClient(app) as client:
        r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "http_404"


def test_missing_required_config_fails(monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_placeholder_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "change-me-change-me-change-me-change-me")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
