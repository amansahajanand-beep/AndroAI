"""DEV: end-to-end smoke test of the web -> Next.js proxy -> API path with a browser-like cookie jar.

Prereqs: scripts/dev/run_api_sqlite.py (API) and `npm run dev` in apps/web with BACKEND_URL set,
and the dev admin password in DEV_ADMIN_PASSWORD. Uses the fake worker only if --with-worker.

    python scripts/dev/smoke_web_api.py [--base http://localhost:3000] [--big-upload-mb 15]
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
import uuid
import zipfile

import httpx

ANDROID = {
    "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip",
    "settings.gradle.kts": 'rootProject.name = "x"\ninclude(":app")',
    "build.gradle.kts": 'plugins { id("com.android.application") version "8.5.0" apply false }',
    "app/build.gradle.kts": "android { compileSdk = 34\n defaultConfig { minSdk = 24 } }",
    "gradlew": "#!/bin/sh",
}
OK, BAD = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
failures: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {OK if cond else BAD}  {name}" + ("" if cond else f"   -> {detail}"))
    if not cond:
        failures.append(name)


def zip_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--big-upload-mb", type=int, default=15)
    a = ap.parse_args()
    origin = {"Origin": "http://localhost:3000"}
    email, pw = f"smoke-{uuid.uuid4().hex[:8]}@example.com", "correct-horse-battery"
    admin_pw = os.environ.get("DEV_ADMIN_PASSWORD", "")

    user = httpx.Client(base_url=a.base, timeout=60)  # cookie jar = a browser tab
    print("== auth (cookies through the Next proxy)")
    r = user.post("/api/v1/auth/register", json={"email": email, "password": pw, "display_name": "Smoke"}, headers=origin)
    check("register", r.status_code == 201, r.text)
    r = user.post("/api/v1/auth/login", json={"email": email, "password": pw, "remember": True}, headers=origin)
    check("login", r.status_code == 200, r.text)
    jar = {c.name: c for c in user.cookies.jar}
    check("httpOnly session cookies set", "ap_access" in jar and "ap_refresh" in jar, list(jar))
    check("cookie flags", all(c.has_nonstandard_attr("HttpOnly") for c in jar.values()), "HttpOnly missing")
    r = user.get("/api/v1/auth/session")
    check("session via cookie", r.status_code == 200 and r.json()["user"]["email"] == email, r.text)
    r = user.post("/api/v1/projects", json={"name": "csrf"})
    check("cookie POST without Origin is refused (CSRF)", r.status_code == 403, r.status_code)
    r = user.post("/api/v1/projects", json={"name": "csrf"}, headers={"Origin": "https://evil.example"})
    check("cookie POST from a foreign Origin is refused", r.status_code == 403, r.status_code)

    print("== projects + upload")
    r = user.post("/api/v1/projects", json={"name": "Smoke app", "metadata": {"language": "kotlin", "min_sdk": 26}}, headers=origin)
    check("create project", r.status_code == 201 and r.json()["metadata"]["min_sdk"] == 26, r.text)
    pid = r.json()["id"]
    r = user.post(f"/api/v1/projects/{pid}/uploads", files={"file": ("app.zip", zip_bytes(ANDROID), "application/zip")}, headers=origin)
    check("zip upload through the proxy", r.status_code == 201 and r.json()["file_count"] == 5, r.text)
    r = user.get(f"/api/v1/projects/{pid}/analysis")
    check("analysis detects AGP/modules", r.status_code == 200 and r.json()["detected"]["agp"] == "8.5.0" and r.json()["modules"] == [":app"], r.text)
    r = user.get(f"/api/v1/projects/{pid}/files/search", params={"q": "compilesdk"})
    check("search", r.status_code == 200 and len(r.json()) == 1, r.text)
    r = user.post(f"/api/v1/projects/{pid}/files/move", json={"from": "app", "to": "mobile"}, headers=origin)
    check("move directory", r.status_code == 204, r.text)
    r = user.post(f"/api/v1/projects/{pid}/files/move", json={"from": "mobile", "to": "app"}, headers=origin)
    check("move back", r.status_code == 204, r.text)

    mb = a.big_upload_mb
    big = zip_bytes({"settings.gradle": "x", "big.bin": os.urandom(mb * 1024 * 1024)})
    p2 = user.post("/api/v1/projects", json={"name": "Big upload"}, headers=origin).json()["id"]
    r = user.post(f"/api/v1/projects/{p2}/uploads", files={"file": ("big.zip", big, "application/zip")}, headers=origin)
    check(f"{mb} MB upload survives the proxy (no silent truncation)", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    r = user.post(f"/api/v1/projects/{p2}/uploads", files={"file": ("evil.zip", zip_bytes({"../../evil.txt": "x"}), "application/zip")}, headers=origin)
    check("path traversal archive rejected", r.status_code == 422 and r.json()["error"]["code"] == "invalid_archive", r.text)

    print("== builds (needs a worker)")
    r = user.post("/api/v1/builds", json={"project_id": pid, "variant": "debug", "output_type": "apk"}, headers=origin)
    check("build is queued/blocked with a reason when no worker exists", r.status_code == 201 and r.json()["state"] in ("blocked", "queued"), r.text)
    b1 = r.json()
    check("build has number + commit", b1["number"] == 1 and len(b1["commit_sha"]) == 7, b1)

    if admin_pw:
        adm = httpx.Client(base_url=a.base, timeout=60)
        r = adm.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": admin_pw}, headers=origin)
        check("admin login", r.status_code == 200, r.text)
        r = adm.post("/api/v1/admin/workers", json={"name": f"fake-{uuid.uuid4().hex[:6]}", "kind": "build"}, headers=origin)
        token = r.json()["token"]
        check("admin creates worker (token shown once)", r.status_code == 201 and token.startswith("wk_"))
        here = os.path.dirname(os.path.abspath(__file__))
        api_base = os.environ.get("API_URL", "http://localhost:8000")
        proc = subprocess.run([sys.executable, os.path.join(here, "fake_worker.py"), "--api", api_base, "--once"],
                              env={**os.environ, "WORKER_TOKEN": token}, capture_output=True, text=True, timeout=120)
        check("fake worker registered", "registered" in proc.stdout, proc.stdout + proc.stderr)
        # reaper unblocks the blocked build; trigger it via the CLI-equivalent endpoint-free path: poll state
        for _ in range(10):
            s = user.get(f"/api/v1/builds/{b1['id']}").json()["state"]
            if s != "blocked":
                break
            time.sleep(1)
        print(f"  (build state after worker registration: {s}; the reaper normally unblocks it within ~15s)")

    print("== logout")
    r = user.post("/api/v1/auth/logout", headers=origin)
    check("logout clears the session", r.status_code == 204)
    user.cookies.clear()
    check("session gone", user.get("/api/v1/auth/session").status_code == 401)

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
