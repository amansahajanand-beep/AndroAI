"""Behaviour the web app depends on: cookie sessions + CSRF, project metadata/enrichment, build
numbering and views, search/analysis, preferences, SSE logs, admin overview."""

import json

import pytest
from sqlalchemy import select

from androai_api.api.v1.builds import log_events
from androai_api.config import get_settings
from androai_api.models import BuildLog

from .conftest import PASSWORD
from .test_projects import make_zip, new_project, upload
from .test_scheduler import (ANDROID, W, admin, android_project, claim, make_worker, submit, submit_test)  # noqa: F401

A = "/api/v1/auth"
ORIGIN = {"Origin": "http://localhost:3000"}


def cookie_login(client, email="web@example.com"):
    client.post(f"{A}/register", json={"email": email, "password": PASSWORD})
    r = client.post(f"{A}/login", json={"email": email, "password": PASSWORD}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r


def test_login_sets_httponly_cookies_and_session_works_without_bearer(client):
    r = cookie_login(client)
    set_cookie = r.headers.get_list("set-cookie")
    access = next(c for c in set_cookie if c.startswith("ap_access="))
    refresh = next(c for c in set_cookie if c.startswith("ap_refresh="))
    for c in (access, refresh):
        assert "HttpOnly" in c and "SameSite=lax" in c
    assert "Path=/api/v1/auth" in refresh and "Path=/;" in access + ";"
    s = client.get(f"{A}/session")
    assert s.status_code == 200 and s.json()["user"]["email"] == "web@example.com" and s.json()["expires_at"]
    assert client.get("/api/v1/users/me").status_code == 200


def test_cookie_requests_need_a_trusted_origin(client):
    cookie_login(client)
    body = {"name": "Cookie Project"}
    assert client.post("/api/v1/projects", json=body).status_code == 403  # no Origin
    r = client.post("/api/v1/projects", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    assert client.post("/api/v1/projects", json=body, headers=ORIGIN).status_code == 201
    # reads are safe methods and need no Origin
    assert client.get("/api/v1/projects").status_code == 200
    # a foreign Origin cannot log in either
    assert client.post(f"{A}/login", json={"email": "web@example.com", "password": PASSWORD},
                       headers={"Origin": "https://evil.example"}).status_code == 403


def test_bearer_clients_are_not_subject_to_origin_checks(client, alice):
    _, h = alice
    client.cookies.clear()
    assert client.post("/api/v1/projects", json={"name": "api client"}, headers=h).status_code == 201


def test_refresh_and_logout_via_cookies(client):
    cookie_login(client)
    assert client.post(f"{A}/refresh").status_code == 403  # CSRF: needs Origin
    r = client.post(f"{A}/refresh", headers=ORIGIN)
    assert r.status_code == 200 and any(c.startswith("ap_access=") for c in r.headers.get_list("set-cookie"))
    assert client.get(f"{A}/session").status_code == 200
    out = client.post(f"{A}/logout", headers=ORIGIN)
    assert out.status_code == 204
    assert 'ap_access=""' in " ".join(out.headers.get_list("set-cookie")) or "Max-Age=0" in " ".join(out.headers.get_list("set-cookie"))
    client.cookies.clear()
    assert client.get(f"{A}/session").status_code == 401


def test_stolen_access_cookie_dies_on_logout(client):
    cookie_login(client)
    stolen = client.cookies.get("ap_access")
    client.post(f"{A}/logout", headers=ORIGIN)
    client.cookies.clear()
    client.cookies.set("ap_access", stolen)
    assert client.get(f"{A}/session").status_code == 401


def test_untrusted_origin_list_is_configurable(client, monkeypatch):
    cookie_login(client)
    monkeypatch.setattr(get_settings(), "allowed_origins", "https://app.example.com")
    assert client.post("/api/v1/projects", json={"name": "x"}, headers={"Origin": "https://app.example.com"}).status_code == 201


# ---------------------------------------------------------------- projects
def test_project_metadata_and_enrichment(client, alice, admin):
    _, h = alice
    meta = {"language": "kotlin", "ui_toolkit": "compose", "package_name": "com.example.app", "min_sdk": 26,
            "target_sdk": 35, "requirements": ["offline"], "config": {"MAPS": "x"}}
    r = client.post("/api/v1/projects", headers=h, json={"name": "Meta", "metadata": meta})
    assert r.status_code == 201 and r.json()["metadata"] == meta
    pid = r.json()["id"]
    assert r.json()["storage_bytes"] == 0 and r.json()["last_build"] is None
    bad = client.post("/api/v1/projects", headers=h, json={"name": "x", "metadata": {"package_name": "not a package"}})
    assert bad.status_code == 422
    assert client.post("/api/v1/projects", headers=h, json={"name": "x", "metadata": {"evil": 1}}).status_code == 422
    r = client.patch(f"/api/v1/projects/{pid}", headers=h, json={"metadata": {"min_sdk": 28}})
    assert r.json()["metadata"]["min_sdk"] == 28 and r.json()["metadata"]["language"] == "kotlin"

    make_worker(client, admin)
    pid2 = android_project(client, h, "Built")
    p = client.get(f"/api/v1/projects/{pid2}", headers=h).json()
    assert p["storage_bytes"] > 0 and p["active_jobs"] == 0
    submit(client, h, pid2)
    p = client.get(f"/api/v1/projects/{pid2}", headers=h).json()
    assert p["active_jobs"] == 1 and p["last_build"]["number"] == 1 and p["last_build"]["state"] == "queued"
    listed = {x["id"]: x for x in client.get("/api/v1/projects", headers=h).json()["items"]}
    assert listed[pid2]["last_build"]["number"] == 1 and listed[pid]["last_build"] is None


def test_search_and_analysis(client, alice):
    _, h = alice
    pid = android_project(client, h)
    hits = client.get(f"/api/v1/projects/{pid}/files/search", headers=h, params={"q": "COMPILESDK"}).json()
    assert hits and hits[0]["path"] == "app/build.gradle.kts" and hits[0]["line"] >= 1 and hits[0]["column"] >= 1
    assert client.get(f"/api/v1/projects/{pid}/files/search", headers=h, params={"q": "zzz-none"}).json() == []
    a = client.get(f"/api/v1/projects/{pid}/analysis", headers=h).json()
    assert a["detected"]["agp"] == "8.5.0" and a["required"]["problems"] == [] and a["build_system"] == "gradle-kts"
    assert a["file_count"] == 5
    empty = new_project(client, h, "empty")
    assert client.get(f"/api/v1/projects/{empty}/analysis", headers=h).status_code == 409


def test_search_and_analysis_are_tenant_scoped(client, alice, bob):
    _, ha = alice
    _, hb = bob
    pid = android_project(client, ha)
    assert client.get(f"/api/v1/projects/{pid}/files/search", headers=hb, params={"q": "a"}).status_code == 404
    assert client.get(f"/api/v1/projects/{pid}/analysis", headers=hb).status_code == 404
    assert client.get("/api/v1/projects/activity/recent", headers=hb).json() == []


# ---------------------------------------------------------------- builds
def _finish_build(client, wh, ok=True, errors=None):
    c = claim(client, wh)
    client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh)
    client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": "line one\nline two\n"})
    if ok:
        art = client.post(f"{W}/jobs/build/{c['id']}/files", headers=wh, data={"role": "artifact"},
                          files={"file": ("a.apk", b"apk")}).json()
        client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh, json={"outcome": "completed", "artifact_id": art["id"]})
        return c["id"], art["id"]
    client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh,
                json={"outcome": "failed", "error_code": "compile_error", "error_message": "boom", "errors": errors or []})
    return c["id"], None


def test_build_numbers_views_artifacts_and_activity(client, alice, admin):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    b1 = submit(client, h, pid).json()
    assert b1["number"] == 1 and len(b1["commit_sha"]) == 7 and b1["artifact_ids"] == []
    jid, art = _finish_build(client, wh)
    done = client.get(f"/api/v1/builds/{b1['id']}", headers=h).json()
    assert done["state"] == "completed" and done["artifact_ids"] == [art] and done["duration_seconds"] is not None
    b2 = submit(client, h, pid).json()
    assert b2["number"] == 2
    other = android_project(client, h, "Other")
    assert submit(client, h, other).json()["number"] == 1  # numbering is per project
    _finish_build(client, wh, ok=False, errors=[{"file": "A.kt", "line": 3, "message": "bad"}])
    failed = client.get(f"/api/v1/builds/{b2['id']}", headers=h).json()
    assert failed["state"] == "failed" and failed["errors"] == [{"file": "A.kt", "line": 3, "message": "bad"}]
    arts = client.get("/api/v1/artifacts", headers=h, params={"build_id": b1["id"]}).json()
    assert [a["id"] for a in arts] == [art] and arts[0]["kind"] == "apk"
    assert client.get("/api/v1/artifacts", headers=h, params={"build_id": b2["id"]}).json() == []
    acts = client.get("/api/v1/projects/activity/recent", headers=h).json()
    actions = [a["action"] for a in acts]
    assert "build.completed" in actions and "build.failed" in actions and "project.create" in actions
    assert next(a for a in acts if a["action"] == "build.failed")["detail"]["number"] == 2
    assert all(a["project_name"] for a in acts)


def test_artifacts_listing_is_tenant_scoped(client, alice, bob, admin):
    _, ha = alice
    _, hb = bob
    _, wh = make_worker(client, admin)
    pid = android_project(client, ha)
    b = submit(client, ha, pid).json()
    _finish_build(client, wh)
    assert client.get("/api/v1/artifacts", headers=hb, params={"build_id": b["id"]}).json() == []


def test_test_job_embeds_result(client, alice, admin):
    _, h = alice
    _, wh = make_worker(client, admin, "test-1", kind="test")
    pid = android_project(client, h)
    t = submit_test(client, h, pid, kind="unit").json()
    assert t["result"] is None
    c = claim(client, wh)
    client.post(f"{W}/jobs/test/{c['id']}/start", headers=wh)
    client.post(f"{W}/jobs/test/{c['id']}/complete", headers=wh,
                json={"outcome": "completed", "test_outcome": "passed", "passed": 4})
    got = client.get(f"/api/v1/tests/{t['id']}", headers=h).json()
    assert got["result"]["outcome"] == "passed" and got["result"]["passed"] == 4
    assert client.get("/api/v1/tests", headers=h).json()["items"][0]["result"]["outcome"] == "passed"


# ---------------------------------------------------------------- SSE
def test_log_events_continue_history_numbering(db_factory, client, alice, admin):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    job = submit(client, h, pid).json()
    c = claim(client, wh)
    client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh)
    client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": "old 1\nold 2\n"})
    history = client.get(f"/api/v1/builds/{job['id']}/logs", headers=h).json()
    base_lines = "".join(x["content"] for x in history).rstrip("\n").split("\n")
    assert base_lines == ["old 1", "old 2"]

    from androai_api.models import BuildJob, User
    with db_factory() as s:
        tenant = s.scalars(select(User)).first().tenant_id
        tenant = s.get(BuildJob, job["id"]).tenant_id
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 1:  # between polls: the worker logs more, then the job ends
            client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": "new 3\nnew 4\n"})
        else:
            art = client.post(f"{W}/jobs/build/{c['id']}/files", headers=wh, data={"role": "artifact"},
                              files={"file": ("a.apk", b"x")}).json()
            client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh, json={"outcome": "completed", "artifact_id": art["id"]})

    frames = list(log_events(db_factory, tenant, job["id"], sleep=sleep))
    events = [(f.split("\n")[0], json.loads(f.split("\n")[1][6:])) for f in frames if f.startswith("event:")]
    assert events[0] == ("event: log", {"seq": 3, "line": "new 3"})
    assert events[1] == ("event: log", {"seq": 4, "line": "new 4"})
    assert events[-1] == ("event: end", {"status": "completed"})


def test_log_stream_endpoint_for_finished_build_ends_immediately(client, alice, admin):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    job = submit(client, h, pid).json()
    _finish_build(client, wh)
    with client.stream("GET", f"/api/v1/builds/{job['id']}/logs/stream", headers=h) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.startswith("event: end") and '"completed"' in body


def test_log_stream_is_tenant_scoped(client, alice, bob, admin):
    _, ha = alice
    _, hb = bob
    make_worker(client, admin)
    job = submit(client, ha, android_project(client, ha)).json()
    assert client.get(f"/api/v1/builds/{job['id']}/logs/stream", headers=hb).status_code == 404


# ---------------------------------------------------------------- preferences / admin
def test_preferences_roundtrip(client, alice):
    _, h = alice
    d = client.get("/api/v1/users/me/preferences", headers=h).json()
    assert d["theme"] == "system" and d["default_language"] == "kotlin" and d["email_build_failed"] is True
    new = {**d, "theme": "dark", "default_language": "java", "email_usage_threshold": True}
    assert client.put("/api/v1/users/me/preferences", headers=h, json=new).json() == new
    assert client.get("/api/v1/users/me/preferences", headers=h).json() == new
    assert client.put("/api/v1/users/me/preferences", headers=h, json={**new, "theme": "neon"}).status_code == 422
    assert client.put("/api/v1/users/me/preferences", headers=h, json={**new, "evil": 1}).status_code == 422


def test_admin_overview(client, alice, admin):
    _, h = alice
    assert client.get("/api/v1/admin/overview", headers=h).status_code == 403
    o = client.get("/api/v1/admin/overview", headers=admin).json()
    assert o["users"] == 2 and o["projects"] == 0 and o["build_failure_rate_24h"] == 0
    assert set(o["queue_depth"]) == {"builds", "tests"}


# ---------------------------------------------------------------- move / recursive delete
def test_move_and_recursive_delete(client, alice):
    _, h = alice
    pid = android_project(client, h)
    P = f"/api/v1/projects/{pid}"

    def paths():
        return sorted(f["path"] for f in client.get(f"{P}/files", headers=h).json())

    r = client.post(f"{P}/files/move", headers=h, json={"from": "app", "to": "mobile"})
    assert r.status_code == 204 and paths() == ["build.gradle.kts", "gradle/wrapper/gradle-wrapper.properties", "gradlew",
                                                "mobile/build.gradle.kts", "settings.gradle.kts"]
    # contents survive a move (nothing rewritten)
    assert "compileSdk" in client.get(f"{P}/files/content", headers=h, params={"path": "mobile/build.gradle.kts"}).json()["content"]
    # conflicts and nonsense are refused atomically
    assert client.post(f"{P}/files/move", headers=h, json={"from": "mobile/build.gradle.kts", "to": "build.gradle.kts"}).status_code == 409
    assert client.post(f"{P}/files/move", headers=h, json={"from": "mobile", "to": "mobile/inner"}).status_code == 422
    assert client.post(f"{P}/files/move", headers=h, json={"from": "nope", "to": "x"}).status_code == 404
    assert client.post(f"{P}/files/move", headers=h, json={"from": "gradlew", "to": "../evil"}).status_code == 422
    assert "mobile/build.gradle.kts" in paths()
    # recursive delete of a directory
    assert client.delete(f"{P}/files", headers=h, params={"path": "gradle", "recursive": "true"}).status_code == 204
    assert not any(p.startswith("gradle/") for p in paths())
    assert client.delete(f"{P}/files", headers=h, params={"path": "gradle", "recursive": "true"}).status_code == 404
    hist = client.get(f"{P}/files/history", headers=h, params={"limit": 50}).json()
    assert {"delete", "create"} <= {c["change_type"] for c in hist}


def test_move_is_tenant_scoped(client, alice, bob):
    _, ha = alice
    _, hb = bob
    pid = android_project(client, ha)
    assert client.post(f"/api/v1/projects/{pid}/files/move", headers=hb, json={"from": "app", "to": "x"}).status_code == 404
    assert client.delete(f"/api/v1/projects/{pid}/files", headers=hb, params={"path": "app", "recursive": "true"}).status_code == 404


def test_admin_lists_include_emails_and_project_counts(client, alice, admin):
    _, h = alice
    android_project(client, h)
    users = client.get("/api/v1/admin/users", headers=admin).json()["items"]
    counts = {u["email"]: u["project_count"] for u in users}
    assert counts["alice@example.com"] == 1 and counts["root@example.com"] == 0
    logs = client.get("/api/v1/admin/audit-logs", headers=admin).json()["items"]
    assert any(item["actor_email"] == "alice@example.com" for item in logs)
