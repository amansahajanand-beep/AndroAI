import time

import jwt
import pytest
from sqlalchemy import select

from androai_api import rate_limit
from androai_api.config import get_settings
from androai_api.models import AuditLog, User

from .conftest import PASSWORD, register_and_login

A = "/api/v1/auth"


def test_register_login_me(client, outbox):
    r = client.post(f"{A}/register", json={"email": "Alice@Example.com", "password": PASSWORD, "display_name": "Al"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com" and body["roles"] == ["user"]
    assert "password" not in str(body).lower().replace("password_", "")
    assert outbox.sent and "verify-email?token=" in outbox.sent[0].body
    tokens, h = register_and_login(client, "second@example.com")
    me = client.get("/api/v1/users/me", headers=h).json()
    assert me["email"] == "second@example.com" and "projects:manage" in me["permissions"]
    assert "admin:users" not in me["permissions"]


def test_duplicate_and_weak_password(client):
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    r = client.post(f"{A}/register", json={"email": "A@example.com", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = client.post(f"{A}/register", json={"email": "b@example.com", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"


def test_passwords_are_hashed_with_argon2(client, db_factory):
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    with db_factory() as db:
        u = db.scalars(select(User)).one()
        assert u.password_hash.startswith("$argon2id$") and PASSWORD not in u.password_hash


def test_login_failures_are_uniform_and_audited(client, db_factory):
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    bad_pw = client.post(f"{A}/login", json={"email": "a@example.com", "password": "wrong-password-1"})
    no_user = client.post(f"{A}/login", json={"email": "ghost@example.com", "password": "wrong-password-1"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()
    with db_factory() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")))) == 2


def test_protected_routes_require_valid_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/users/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    s = get_settings()
    forged = jwt.encode({"sub": "x", "sid": "y", "exp": time.time() + 99, "iat": time.time(), "typ": "access",
                         "iss": s.app_name}, "wrong-secret-wrong-secret-wrong-secret-1", algorithm="HS256")
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": "x", "sid": "y", "exp": time.time() + 99, "iat": time.time(), "typ": "access",
                           "iss": s.app_name}, None, algorithm="none")
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    tokens, h = register_and_login(client)
    r1 = client.post(f"{A}/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 200
    # old token reused => whole family revoked, including the freshly rotated one
    assert client.post(f"{A}/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post(f"{A}/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 401


def test_logout_revokes_access_immediately(client):
    tokens, h = register_and_login(client)
    assert client.post(f"{A}/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.get("/api/v1/users/me", headers=h).status_code == 401
    assert client.post(f"{A}/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    # idempotent
    assert client.post(f"{A}/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204


def test_email_verification_flow(client, outbox, db_factory):
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    token = outbox.last_token()
    assert client.post(f"{A}/verify-email", json={"token": token}).status_code == 200
    assert client.post(f"{A}/verify-email", json={"token": token}).status_code == 400  # single use
    with db_factory() as db:
        assert db.scalars(select(User)).one().email_verified_at is not None


def test_unverified_login_blocked_when_required(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    r = client.post(f"{A}/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"


def test_password_reset_flow(client, outbox):
    tokens, h = register_and_login(client)
    n = len(outbox.sent)
    r = client.post(f"{A}/forgot-password", json={"email": "alice@example.com"})
    assert r.status_code == 202 and len(outbox.sent) == n + 1
    # unknown email: same response, no mail
    r2 = client.post(f"{A}/forgot-password", json={"email": "nobody@example.com"})
    assert r2.status_code == 202 and r2.json() == r.json() and len(outbox.sent) == n + 1
    token = outbox.last_token()
    assert client.post(f"{A}/reset-password", json={"token": token, "new_password": "weak"}).status_code == 422
    # weak password attempt must not burn the token? it does not consume it before validation:
    assert client.post(f"{A}/reset-password", json={"token": token, "new_password": "brand-new-password!"}).status_code == 200
    assert client.post(f"{A}/reset-password", json={"token": token, "new_password": "another-password-1"}).status_code == 400
    assert client.get("/api/v1/users/me", headers=h).status_code == 401  # sessions revoked
    assert client.post(f"{A}/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 401
    assert client.post(f"{A}/login", json={"email": "alice@example.com", "password": "brand-new-password!"}).status_code == 200


def test_change_password_revokes_sessions(client):
    tokens, h = register_and_login(client)
    r = client.post(f"{A}/change-password", headers=h, json={"current_password": "nope-nope-nope", "new_password": "new-password-123"})
    assert r.status_code == 403
    r = client.post(f"{A}/change-password", headers=h, json={"current_password": PASSWORD, "new_password": "new-password-123"})
    assert r.status_code == 200
    assert client.get("/api/v1/users/me", headers=h).status_code == 401


def test_login_rate_limited_per_account(client):
    client.post(f"{A}/register", json={"email": "a@example.com", "password": PASSWORD})
    codes = [client.post(f"{A}/login", json={"email": "a@example.com", "password": "wrong-password-1"}).status_code
             for _ in range(8)]
    assert 429 in codes and codes[0] == 401


def test_deactivated_user_loses_access(client, db_factory):
    tokens, h = register_and_login(client)
    with db_factory() as db:
        u = db.scalars(select(User)).one()
        u.is_active = False
        db.commit()
    assert client.get("/api/v1/users/me", headers=h).status_code == 401
    assert client.post(f"{A}/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 401
