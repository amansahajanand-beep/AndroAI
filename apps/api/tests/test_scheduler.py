import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from androai_api.config import get_settings
from androai_api.models import (BuildJob, BuildUsage, TestJob, WorkerRegistry)
from androai_api.services import dispatch

from .conftest import register_and_login
from .test_projects import _make_admin, make_zip, new_project, upload

W = "/api/v1/worker"
ANDROID = {
    "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip",
    "settings.gradle.kts": 'rootProject.name = "x"',
    "build.gradle.kts": 'plugins { id("com.android.application") version "8.5.0" apply false }',
    "app/build.gradle.kts": "android { compileSdk = 34\n defaultConfig { minSdk = 24 } }",
    "gradlew": "#!/bin/sh",
}
TOOLCHAIN = {"jdks": [17], "platforms": [34]}


@pytest.fixture()
def admin(client, db_factory):
    tokens, _ = register_and_login(client, "root@example.com")
    _make_admin(db_factory, "root@example.com")
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
    return {"Authorization": f"Bearer {r['access_token']}"}


def make_worker(client, admin, name="build-1", kind="build", capacity=1, toolchain=TOOLCHAIN, capabilities=None):
    r = client.post("/api/v1/admin/workers", headers=admin, json={"name": name, "kind": kind, "capacity": capacity})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post(f"{W}/register", headers=h, json={"toolchain": toolchain, "capabilities": capabilities or {}}).status_code == 200
    return r.json()["id"], h


def android_project(client, h, name="App", files=None):
    pid = new_project(client, h, name)
    assert upload(client, h, pid, make_zip(files or ANDROID)).status_code == 201
    return pid


def submit(client, h, pid, **kw):
    return client.post("/api/v1/builds", headers=h, json={"project_id": pid, **kw})


def claim(client, wh):
    return client.post(f"{W}/claim", headers=wh).json()["job"]


def test_full_build_lifecycle(client, alice, admin, notifier, db_factory, storage):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    r = submit(client, h, pid)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["state"] == "queued" and job["gradle_tasks"] == ["assembleDebug"]
    assert job["toolchain"]["required"]["jdk"] == 17 and job["toolchain"]["detected"]["agp"] == "8.5.0"

    c = claim(client, wh)
    assert c["id"] == job["id"] and c["jdk"] == 17 and c["kind"] == "build" and c["attempt"] == 1
    assert claim(client, wh) is None  # capacity 1
    src = client.get(f"{W}/jobs/build/{c['id']}/source", headers=wh)
    assert src.status_code == 200 and "gradle/wrapper/gradle-wrapper.properties" in zipfile.ZipFile(io.BytesIO(src.content)).namelist()

    assert client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh).json()["state"] == "running"
    for line in ("> Task :app:compileDebugKotlin\n", "BUILD SUCCESSFUL\n"):
        assert client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": line}).json() == {"cancel": False}
    logs = client.get(f"/api/v1/builds/{job['id']}/logs", headers=h).json()
    assert [x["seq"] for x in logs] == [0, 1]
    assert client.get(f"/api/v1/builds/{job['id']}/logs", headers=h, params={"after_seq": 0}).json()[0]["content"] == "BUILD SUCCESSFUL\n"

    # completing without uploading the artifact is refused
    assert client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh, json={"outcome": "completed"}).status_code == 422
    apk = b"PK-apk-bytes"
    up = client.post(f"{W}/jobs/build/{c['id']}/files", headers=wh, data={"role": "artifact", "name": "app-debug.apk"},
                     files={"file": ("app-debug.apk", apk)})
    assert up.status_code == 201, up.text
    done = client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh, json={"outcome": "completed", "artifact_id": up.json()["id"]})
    assert done.json() == {"state": "completed"}

    res = client.get(f"/api/v1/builds/{job['id']}/result", headers=h).json()
    assert res["state"] == "completed" and res["artifact_id"] == up.json()["id"]
    dl = client.post(f"/api/v1/artifacts/{res['artifact_id']}/download-url", headers=h).json()
    assert client.get(dl["url"]).content == apk
    n = notifier.builds[-1]
    assert n.build_job_id == job["id"] and n.state.value == "succeeded" and n.artifact_key and n.log_key
    assert storage.get_bytes(n.log_key).decode().endswith("BUILD SUCCESSFUL\n")
    with db_factory() as db:
        u = db.scalars(select(BuildUsage)).one()
        assert u.job_kind == "build" and u.attempt == 1 and u.runtime_seconds >= 0
    assert client.get(f"/api/v1/builds/{job['id']}", headers=h).json()["state"] == "completed"
    # worker is free again
    assert client.post(f"{W}/heartbeat", headers=wh, json={}).json()["active_jobs"] == 0


def test_compile_failure_is_final_with_extracted_errors(client, alice, admin, notifier):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    j = submit(client, h, pid).json()
    c = claim(client, wh)
    client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh)
    errs = [{"file": "app/src/Main.kt", "line": 3, "message": "Unresolved reference: foo"}]
    r = client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh,
                    json={"outcome": "failed", "error_code": "compile_error", "error_message": "compile failed", "errors": errs})
    assert r.json() == {"state": "failed"}
    assert client.get(f"/api/v1/builds/{j['id']}/result", headers=h).json()["errors"] == errs
    assert notifier.builds[-1].state.value == "failed" and notifier.builds[-1].error.code == "compile_error"
    assert notifier.builds[-1].error.retryable is False


def test_infrastructure_failure_is_retried_then_final(client, alice, admin, monkeypatch, db_factory):
    monkeypatch.setattr(get_settings(), "retry_backoff_seconds", 0)
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    j = submit(client, h, pid).json()
    for attempt in (1, 2):
        c = claim(client, wh)
        assert c["id"] == j["id"] and c["attempt"] == attempt
        client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh)
        r = client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh,
                        json={"outcome": "failed", "error_code": "infrastructure", "error_message": "disk full", "retryable": True})
        assert r.json()["state"] == ("queued" if attempt == 1 else "failed")
    with db_factory() as db:
        usage = db.scalars(select(BuildUsage).order_by(BuildUsage.attempt)).all()
        assert [u.attempt for u in usage] == [1, 2]  # retry cost recorded


def test_blocked_until_a_capable_worker_exists(client, alice, admin, monkeypatch, db_factory):
    _, h = alice
    pid = android_project(client, h)
    j = submit(client, h, pid).json()
    assert j["state"] == "blocked" and "no live build worker" in j["blocked_reason"]
    make_worker(client, admin, "old", toolchain={"jdks": [11], "platforms": [34]})
    with db_factory() as db:
        dispatch.reap(db)
    j = client.get(f"/api/v1/builds/{j['id']}", headers=h).json()
    assert j["state"] == "blocked" and "toolchain" in j["blocked_reason"]
    _, wh = make_worker(client, admin, "good")
    with db_factory() as db:
        assert dispatch.reap(db)["unblocked"] == 1
    assert client.get(f"/api/v1/builds/{j['id']}", headers=h).json()["state"] == "queued"
    assert claim(client, wh)["id"] == j["id"]


def test_worker_with_wrong_toolchain_never_gets_the_job(client, alice, admin):
    _, h = alice
    _, w11 = make_worker(client, admin, "w-jdk11", toolchain={"jdks": [11], "platforms": [34]})
    _, w17 = make_worker(client, admin, "w-jdk17")
    pid = android_project(client, h)
    j = submit(client, h, pid).json()
    assert claim(client, w11) is None
    assert claim(client, w17)["id"] == j["id"]


def test_project_validation_and_task_injection(client, alice, admin):
    _, h = alice
    make_worker(client, admin)
    bad = android_project(client, h, "nowrapper", {"settings.gradle": "x", "build.gradle": "// nothing"})
    r = submit(client, h, bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_project"
    assert "wrapper" in r.json()["error"]["message"]
    pid = android_project(client, h)
    for tasks in (["--init-script=/etc/passwd"], ["assemble; rm -rf /"], ["a"] * 11, []):
        assert submit(client, h, pid, gradle_tasks=tasks).status_code == 422, tasks
    assert submit(client, h, pid, variant="release", output_type="aab").json()["gradle_tasks"] == ["bundleRelease"]


def test_priority_fifo_and_per_user_fairness(client, alice, bob, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_active_jobs_per_user", 1)
    _, ha = alice
    _, hb = bob
    _, wh = make_worker(client, admin, capacity=3)
    pa = android_project(client, ha, "A")
    pb = android_project(client, hb, "B")
    a_low = submit(client, ha, pa, priority=150).json()
    a_high = submit(client, ha, pa, priority=60).json()
    b1 = submit(client, hb, pb, priority=150).json()
    first = claim(client, wh)
    assert first["id"] == a_high["id"]  # lowest priority number first
    second = claim(client, wh)
    assert second["id"] == b1["id"]  # alice is at her limit, so bob (older than nothing else) is served
    assert claim(client, wh) is None  # a_low waits for alice's slot
    assert client.get(f"/api/v1/builds/{a_low['id']}", headers=ha).json()["state"] == "queued"


def test_cancel_queued_and_running(client, alice, admin, notifier):
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    q = submit(client, h, pid).json()
    assert client.post(f"/api/v1/builds/{q['id']}/cancel", headers=h).json()["state"] == "cancelled"
    assert notifier.builds[-1].state.value == "cancelled"
    assert client.post(f"/api/v1/builds/{q['id']}/cancel", headers=h).status_code == 409

    r = submit(client, h, pid).json()
    c = claim(client, wh)
    client.post(f"{W}/jobs/build/{c['id']}/start", headers=wh)
    assert client.post(f"/api/v1/builds/{r['id']}/cancel", headers=h).json()["cancel_requested"] is True
    assert client.post(f"{W}/heartbeat", headers=wh, json={}).json()["cancel"] == [r["id"]]
    assert client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": "x"}).json() == {"cancel": True}
    client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh, json={"outcome": "failed", "error_message": "aborted"})
    assert client.get(f"/api/v1/builds/{r['id']}", headers=h).json()["state"] == "cancelled"


def test_lease_expiry_retries_then_fails_and_timeout(client, alice, admin, notifier, db_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "retry_backoff_seconds", 0)
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    j = submit(client, h, pid).json()

    def expire_lease():
        with db_factory() as db:
            job = db.get(BuildJob, j["id"])
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

    claim(client, wh)
    expire_lease()
    with db_factory() as db:
        assert dispatch.reap(db, notifier=notifier)["requeued"] == 1
    assert client.get(f"/api/v1/builds/{j['id']}", headers=h).json()["state"] == "queued"
    claim(client, wh)
    expire_lease()
    with db_factory() as db:
        assert dispatch.reap(db, notifier=notifier)["lost"] == 1
    done = client.get(f"/api/v1/builds/{j['id']}", headers=h).json()
    assert done["state"] == "failed" and done["error_code"] == "worker_lost"
    assert notifier.builds[-1].error.retryable is True
    # the dead worker can no longer report on it
    assert client.post(f"{W}/jobs/build/{j['id']}/complete", headers=wh, json={"outcome": "completed"}).status_code == 409

    j2 = submit(client, h, pid, timeout_seconds=60).json()
    claim(client, wh)
    with db_factory() as db:
        job = db.get(BuildJob, j2["id"])
        job.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        db.commit()
        assert dispatch.reap(db, notifier=notifier)["timed_out"] == 1
    assert client.get(f"/api/v1/builds/{j2['id']}", headers=h).json()["error_code"] == "timeout"


def test_silent_worker_goes_offline(client, admin, db_factory):
    wid, wh = make_worker(client, admin)
    with db_factory() as db:
        w = db.get(WorkerRegistry, wid)
        w.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        db.commit()
        assert dispatch.reap(db)["workers_offline"] == 1
    ws = client.get("/api/v1/admin/workers", headers=admin).json()
    assert ws[0]["status"] == "offline" and ws[0]["live"] is False


def test_tenant_and_credential_isolation(client, alice, bob, admin):
    _, ha = alice
    _, hb = bob
    _, wh = make_worker(client, admin)
    _, wh2 = make_worker(client, admin, "build-2")
    pid = android_project(client, ha)
    j = submit(client, ha, pid).json()
    for url in (f"/api/v1/builds/{j['id']}", f"/api/v1/builds/{j['id']}/logs", f"/api/v1/builds/{j['id']}/result"):
        assert client.get(url, headers=hb).status_code == 404
    assert client.post(f"/api/v1/builds/{j['id']}/cancel", headers=hb).status_code == 404
    assert client.get("/api/v1/builds", headers=hb).json()["total"] == 0
    assert submit(client, hb, pid).status_code == 404  # cannot build someone else's project
    c = claim(client, wh)
    # a different worker cannot read or finish a job it does not hold
    assert client.get(f"{W}/jobs/build/{c['id']}/source", headers=wh2).status_code == 404
    assert client.post(f"{W}/jobs/build/{c['id']}/complete", headers=wh2, json={"outcome": "completed"}).status_code == 404
    # tokens are not interchangeable
    assert client.post(f"{W}/claim", headers=ha).status_code == 401
    assert client.get("/api/v1/builds", headers=wh).status_code == 401
    assert client.post(f"{W}/claim").status_code == 401
    assert client.post(f"{W}/claim", headers={"Authorization": "Bearer wk_nope"}).status_code == 401
    # a regular user is not an admin
    assert client.get("/api/v1/admin/workers", headers=ha).status_code == 403
    assert client.post("/api/v1/admin/workers", headers=ha, json={"name": "evil", "kind": "build"}).status_code == 403


def test_queue_limits_and_backpressure(client, alice, bob, admin, monkeypatch):
    _, ha = alice
    _, hb = bob
    make_worker(client, admin)  # live worker => submitted jobs are 'queued', not 'blocked'
    pa, pb = android_project(client, ha, "A"), android_project(client, hb, "B")
    monkeypatch.setattr(get_settings(), "max_pending_jobs_per_user", 2)
    assert submit(client, ha, pa).status_code == 201 and submit(client, ha, pa).status_code == 201
    r = submit(client, ha, pa)
    assert r.status_code == 429 and r.json()["error"]["code"] == "queue_limit"
    monkeypatch.setattr(get_settings(), "max_queue_depth", 2)  # two queued already
    r = submit(client, hb, pb)
    assert r.status_code == 503 and r.json()["error"]["code"] == "queue_full"
    assert client.get("/api/v1/builds", headers=hb).json()["total"] == 0


def test_log_size_is_bounded(client, alice, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_log_bytes_per_job", 100)
    _, h = alice
    _, wh = make_worker(client, admin)
    pid = android_project(client, h)
    j = submit(client, h, pid).json()
    c = claim(client, wh)
    for _ in range(5):
        client.post(f"{W}/jobs/build/{c['id']}/logs", headers=wh, json={"content": "x" * 60})
    logs = client.get(f"/api/v1/builds/{j['id']}/logs", headers=h).json()
    assert sum(len(x["content"]) for x in logs) < 250 and "truncated" in logs[-1]["content"]


# ---------------------------------------------------------------- tests / emulator
def submit_test(client, h, pid, **kw):
    return client.post("/api/v1/tests", headers=h, json={"project_id": pid, **kw})


def test_unit_test_job_and_validation_rules(client, alice, admin, notifier):
    _, h = alice
    _, wh = make_worker(client, admin, "test-1", kind="test")
    pid = android_project(client, h)
    t = submit_test(client, h, pid, kind="unit").json()
    assert t["state"] == "queued"
    c = claim(client, wh)
    assert c["kind"] == "test" and c["test_kind"] == "unit"
    client.post(f"{W}/jobs/test/{c['id']}/start", headers=wh)
    # claiming "passed" without running any test is refused
    bad = client.post(f"{W}/jobs/test/{c['id']}/complete", headers=wh,
                      json={"outcome": "completed", "test_outcome": "passed", "passed": 0})
    assert bad.status_code == 422
    bad = client.post(f"{W}/jobs/test/{c['id']}/complete", headers=wh,
                      json={"outcome": "completed", "test_outcome": "passed", "passed": 3, "failed": 1})
    assert bad.status_code == 422
    rep = client.post(f"{W}/jobs/test/{c['id']}/files", headers=wh, data={"role": "report", "format": "junit_xml"},
                      files={"file": ("report.xml", b"<testsuite/>")})
    assert rep.status_code == 201
    ok = client.post(f"{W}/jobs/test/{c['id']}/complete", headers=wh,
                     json={"outcome": "completed", "test_outcome": "passed", "passed": 12, "skipped": 1})
    assert ok.json() == {"state": "completed"}
    res = client.get(f"/api/v1/tests/{t['id']}/result", headers=h).json()
    assert res["outcome"] == "passed" and res["passed"] == 12
    assert client.get(f"/api/v1/tests/{t['id']}/reports", headers=h).json()[0]["format"] == "junit_xml"
    assert notifier.tests[-1].state.value == "succeeded" and notifier.tests[-1].passed == 12


def test_emulator_job_blocked_without_kvm_and_never_passes(client, alice, admin, notifier, db_factory):
    _, h = alice
    pid = android_project(client, h)
    # needs a finished build
    assert submit_test(client, h, pid, kind="emulator").status_code == 422
    _, bw = make_worker(client, admin)
    b = submit(client, h, pid).json()
    c = claim(client, bw)
    client.post(f"{W}/jobs/build/{c['id']}/start", headers=bw)
    art = client.post(f"{W}/jobs/build/{c['id']}/files", headers=bw, data={"role": "artifact"}, files={"file": ("a.apk", b"apk")}).json()
    client.post(f"{W}/jobs/build/{c['id']}/complete", headers=bw, json={"outcome": "completed", "artifact_id": art["id"]})

    t = submit_test(client, h, pid, kind="emulator", build_job_id=b["id"]).json()
    assert t["state"] == "blocked"
    # a worker without KVM does not unblock it, and the reason says why
    _, ew = make_worker(client, admin, "emu-0", kind="emulator", capabilities={"kvm": False, "emulator": True})
    with db_factory() as db:
        dispatch.reap(db)
    blocked = client.get(f"/api/v1/tests/{t['id']}", headers=h).json()
    assert blocked["state"] == "blocked" and "KVM" in blocked["blocked_reason"]
    assert claim(client, ew) is None
    # a KVM-capable worker does; if it then cannot run, the result is not_run, never passed
    _, kw = make_worker(client, admin, "emu-1", kind="emulator", capabilities={"kvm": True, "emulator": True})
    with db_factory() as db:
        assert dispatch.reap(db)["unblocked"] == 1
    c = claim(client, kw)
    assert client.get(f"{W}/jobs/test/{c['id']}/apk", headers=kw).content == b"apk"
    client.post(f"{W}/jobs/test/{c['id']}/start", headers=kw)
    assert client.post(f"{W}/jobs/test/{c['id']}/complete", headers=kw,
                       json={"outcome": "failed", "test_outcome": "not_run"}).status_code == 422  # reason required
    assert client.post(f"{W}/jobs/test/{c['id']}/complete", headers=kw,
                       json={"outcome": "completed", "test_outcome": "not_run", "not_run_reason": "x"}).status_code == 422
    r = client.post(f"{W}/jobs/test/{c['id']}/complete", headers=kw,
                    json={"outcome": "failed", "test_outcome": "not_run", "not_run_reason": "KVM device /dev/kvm missing"})
    assert r.json() == {"state": "failed"}
    res = client.get(f"/api/v1/tests/{t['id']}/result", headers=h).json()
    assert res["outcome"] == "not_run" and "KVM" in res["not_run_reason"]
    n = notifier.tests[-1]
    assert n.state.value == "failed" and n.error.code == "runtime_unavailable"


def test_admin_worker_management(client, admin, db_factory):
    from androai_api.models import WorkerRegistry
    r = client.post("/api/v1/admin/workers", headers=admin, json={"name": "w-1", "kind": "build"})
    token, wid = r.json()["token"], r.json()["id"]
    assert token.startswith("wk_")
    with db_factory() as db:
        w = db.get(WorkerRegistry, wid)
        assert token not in w.token_hash and len(w.token_hash) == 64  # only the hash is stored
    assert client.post("/api/v1/admin/workers", headers=admin, json={"name": "w-1", "kind": "build"}).status_code == 409
    assert "token" not in client.get("/api/v1/admin/workers", headers=admin).json()[0]
    new = client.post(f"/api/v1/admin/workers/{wid}/rotate-token", headers=admin).json()["token"]
    assert client.post(f"{W}/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={}).status_code == 401
    assert client.post(f"{W}/heartbeat", headers={"Authorization": f"Bearer {new}"}, json={}).status_code == 200
    assert client.patch(f"/api/v1/admin/workers/{wid}", headers=admin, json={"draining": True}).json()["draining"] is True
    stats = client.get("/api/v1/admin/queues", headers=admin).json()
    assert stats["workers"]["build"]["live"] == 1
    assert client.delete(f"/api/v1/admin/workers/{wid}", headers=admin).status_code == 204


def test_draining_worker_gets_no_new_jobs(client, alice, admin):
    _, h = alice
    wid, wh = make_worker(client, admin)
    pid = android_project(client, h)
    submit(client, h, pid)
    client.patch(f"/api/v1/admin/workers/{wid}", headers=admin, json={"draining": True})
    assert claim(client, wh) is None
