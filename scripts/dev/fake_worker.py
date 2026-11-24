"""DEV ONLY - FAKE build worker. It speaks the real worker protocol (docs/API.md) so the
scheduler, API and web UI can be exercised end to end, but it NEVER RUNS GRADLE and the
"artifact" it uploads is a placeholder, not an app. Do not run it anywhere users could mistake
its output for a real build.

    WORKER_TOKEN=wk_... python scripts/dev/fake_worker.py [--api http://localhost:8000] [--once]

Create the worker + token first (admin): POST /api/v1/admin/workers {"name":"fake-1","kind":"build"}.
"""

from __future__ import annotations

import argparse
import io
import os
import time
import zipfile

import httpx

FAKE_ARTIFACT = b"FAKE-DEV-ARTIFACT: produced by scripts/dev/fake_worker.py. No Gradle build was run.\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--once", action="store_true", help="exit after one job (or one empty poll)")
    ap.add_argument("--fail", action="store_true", help="report a compile failure instead of success")
    args = ap.parse_args()
    token = os.environ.get("WORKER_TOKEN")
    if not token:
        raise SystemExit("WORKER_TOKEN is required")
    c = httpx.Client(base_url=args.api + "/api/v1/worker", headers={"Authorization": f"Bearer {token}"}, timeout=30)

    c.post("/register", json={"toolchain": {"jdks": [17], "platforms": [34, 35]}, "capabilities": {"fake": True},
                              "version": "fake-dev"}).raise_for_status()
    print("[fake-worker] registered", flush=True)
    while True:
        c.post("/heartbeat", json={}).raise_for_status()
        job = c.post("/claim").raise_for_status().json()["job"]
        if not job:
            if args.once:
                return
            time.sleep(2)
            continue
        jid, kind = job["id"], job["kind"]
        print(f"[fake-worker] claimed {kind} {jid} (requires JDK {job.get('jdk')})", flush=True)
        src = c.get(f"/jobs/{kind}/{jid}/source").raise_for_status().content
        names = zipfile.ZipFile(io.BytesIO(src)).namelist()
        c.post(f"/jobs/{kind}/{jid}/start").raise_for_status()
        for line in (f"[fake worker] source snapshot has {len(names)} files; NO GRADLE IS RUN",
                     f"> Task :app:{job.get('gradle_tasks', ['assembleDebug'])[0]} (simulated)"):
            c.post(f"/jobs/{kind}/{jid}/logs", json={"content": line + "\n"}).raise_for_status()
            time.sleep(1)
        if args.fail:
            c.post(f"/jobs/{kind}/{jid}/complete", json={
                "outcome": "failed", "error_code": "compile_error", "error_message": "simulated compile failure",
                "errors": [{"file": "app/src/main/Main.kt", "line": 12, "column": 5, "message": "Unresolved reference: simulated"}]}).raise_for_status()
        elif kind == "build":
            art = c.post(f"/jobs/{kind}/{jid}/files", data={"role": "artifact", "name": "app-debug-FAKE.apk"},
                         files={"file": ("app-debug-FAKE.apk", FAKE_ARTIFACT)}).raise_for_status().json()
            c.post(f"/jobs/{kind}/{jid}/complete", json={"outcome": "completed", "artifact_id": art["id"]}).raise_for_status()
        else:
            c.post(f"/jobs/{kind}/{jid}/complete", json={"outcome": "failed", "test_outcome": "not_run",
                                                         "not_run_reason": "fake dev worker cannot run tests"}).raise_for_status()
        print(f"[fake-worker] finished {jid}", flush=True)
        if args.once:
            return


if __name__ == "__main__":
    main()
