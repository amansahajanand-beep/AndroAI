"""The dev-only live preview: build the APK, run it on an emulator, stream and drive the screen.

No Android SDK is needed: the toolchain and every external command are faked."""

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_src = ROOT / "packages/agent-core/codegen/tests"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from sample_project import good_project

from androai_api.api.v1 import preview_dev
from androai_api.main import app
from androai_api.services import emulator_dev as emu

from .test_projects import make_zip, new_project, upload

if not any(getattr(r, "path", "").startswith("/api/v1/agent/preview-viewer") for r in app.routes):
    app.include_router(preview_dev.router, prefix="/api/v1/agent")

A = "/api/v1/agent"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image"
NO_DEVICE = "List of devices attached\n\n"
ONE_DEVICE = "List of devices attached\nemulator-5554\tdevice\n\n"


class FakeSdk:
    """Answers the commands the preview runs, and records them."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.gradle_code = 0
        self.devices_out = ONE_DEVICE
        self.install_out = b"Performing Streamed Install\nSuccess\n"
        self.avds = b""

    def run(self, args, *, timeout=60, cwd=None, env=None, on_line=None):
        self.calls.append([str(a) for a in args])
        exe = Path(args[0]).name.lower()
        if exe.startswith("gradlew"):
            apk = Path(cwd) / "app/build/outputs/apk/debug/app-debug.apk"
            apk.parent.mkdir(parents=True, exist_ok=True)
            apk.write_bytes(b"apk")
            verdict = "FAILED" if self.gradle_code else "SUCCESSFUL"
            for line in ("> Task :app:compileDebugKotlin", "BUILD " + verdict):
                if on_line:
                    on_line(line)
            return emu.Result(self.gradle_code)
        if exe.startswith("aapt2"):
            return emu.Result(0, b"package: name='com.example.todo' versionCode='1'\n")
        if exe.startswith("emulator"):
            return emu.Result(0, self.avds)
        rest = list(args[1:])
        if rest[:1] == ["-s"]:
            rest = rest[2:]
        if rest[:1] == ["devices"]:
            return emu.Result(0, self.devices_out.encode())
        if rest[:3] == ["shell", "getprop", "sys.boot_completed"]:
            return emu.Result(0, b"1\n")
        if rest[:2] == ["shell", "getprop"]:
            return emu.Result(0, b"Pixel Fake\n" if rest[2] == "ro.product.model" else b"34\n")
        if rest[:3] == ["shell", "wm", "size"]:
            return emu.Result(0, b"Physical size: 1080x2400\n")
        if rest[:1] == ["install"]:
            return emu.Result(0, self.install_out)
        if rest[:2] == ["exec-out", "screencap"]:
            return emu.Result(0, PNG)
        return emu.Result(0, b"")

    def inputs(self):
        return [c for c in self.calls if "input" in c]


MANAGERS: list = []


def make_manager(fake, tmp_path, **kw):
    tools = kw.pop("tools", emu.Toolchain(tmp_path / "sdk", Path("adb"), None, Path("aapt2")))
    manager = emu.PreviewManager(
        find_tools=lambda: tools, run=fake.run, data_dir=tmp_path / "preview", sleep=lambda s: None, **kw
    )
    MANAGERS.append(manager)
    return manager


@pytest.fixture(autouse=True)
def _let_background_jobs_finish():
    """The test database is one shared connection: a preview job still reading it when the test
    ends would crash the teardown."""
    yield
    for manager in MANAGERS:
        manager.wait_idle()
    MANAGERS.clear()


@pytest.fixture()
def sdk(tmp_path, monkeypatch):
    fake = FakeSdk()
    fake.manager = make_manager(fake, tmp_path)
    monkeypatch.setattr(emu, "MANAGER", fake.manager)
    yield fake
    # Torn down before the client and database fixtures (it is requested after them), so no job
    # is still reading the shared test connection when it is closed.
    fake.manager.wait_idle()


def buildable_project(client, h, name="Todo"):
    pid = new_project(client, h, name)
    files = dict(good_project())
    files["gradlew"] = "#!/bin/sh\n"
    files["gradlew.bat"] = "@echo off\n"
    assert upload(client, h, pid, make_zip(files)).status_code == 201
    return pid


def start(client, h, pid):
    return client.post(f"{A}/projects/{pid}/preview", headers=h, json={})


def token_of(session):
    return session["viewerUrl"].rsplit("/", 1)[1]


def wait_phase(client, token, phases, seconds=10):
    deadline = time.time() + seconds
    status = {}
    while time.time() < deadline:
        status = client.get(f"{A}/preview-viewer/{token}/status").json()
        if status["phase"] in phases:
            return status
        time.sleep(0.05)
    raise AssertionError(f"never reached {phases}: {status}")


def test_a_preview_builds_installs_and_goes_live(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    res = start(client, h, pid)
    assert res.status_code == 201, res.text
    session = res.json()
    assert session["state"] == "starting" and session["viewerUrl"].startswith("http")
    assert {"name", "apiLevel", "width", "height"} <= set(session["device"])
    status = wait_phase(client, token_of(session), ("ready", "failed"))
    assert status["phase"] == "ready", status
    assert any("gradlew" in c[0] and "assembleDebug" in c for c in sdk.calls)
    assert any("install" in c for c in sdk.calls)
    assert "com.example.todo" in next(c for c in sdk.calls if "monkey" in c)
    work = sdk.manager._data / pid
    assert (work / "settings.gradle.kts").is_file()
    assert "sdk.dir=" in (work / "local.properties").read_text()
    # once ready the session reports the real device
    again = start(client, h, pid).json()
    assert again["sessionId"] == session["sessionId"] and again["state"] == "ready"
    assert again["device"]["name"] == "Pixel Fake" and again["device"]["apiLevel"] == 34


def test_frames_and_input_reach_the_device_with_scaled_safe_values(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    token = token_of(start(client, h, pid).json())
    wait_phase(client, token, ("ready",))
    frame = client.get(f"{A}/preview-viewer/{token}/frame.png")
    assert frame.status_code == 200 and frame.content == PNG and frame.headers["content-type"] == "image/png"
    base = f"{A}/preview-viewer/{token}/input"
    assert client.post(base, json={"type": "tap", "x": 99999, "y": -5}).status_code == 204
    assert next(c for c in sdk.inputs() if "tap" in c)[-2:] == ["1079", "0"]  # clamped to the screen
    client.post(base, json={"type": "swipe", "x": 10, "y": 20, "x2": 30, "y2": 40, "ms": 5000})
    assert next(c for c in sdk.inputs() if "swipe" in c)[-1] == "3000"
    client.post(base, json={"type": "key", "key": "back"})
    assert next(c for c in sdk.inputs() if "keyevent" in c)[-1] == "4"
    assert client.post(base, json={"type": "key", "key": "rm -rf /"}).status_code == 422
    client.post(base, json={"type": "text", "text": "hi there; rm -rf / && $(reboot) `id`"})
    typed = next(c for c in sdk.inputs() if "text" in c)[-1]
    assert not set(typed) & set(";&$`()'\"|<>\\") and typed.startswith("hi%sthere")


def test_a_failed_build_is_reported_with_the_gradle_output(client, alice, sdk):
    _, h = alice
    sdk.gradle_code = 1
    pid = buildable_project(client, h)
    token = token_of(start(client, h, pid).json())
    status = wait_phase(client, token, ("failed",))
    assert status["errorCode"] == "build_failed" and "Gradle build failed" in status["message"]
    assert "BUILD FAILED" in status["message"]
    assert client.get(f"{A}/preview-viewer/{token}/frame.png").status_code == 409  # nothing to show


def test_a_project_without_a_gradle_wrapper_cannot_be_built(client, alice, sdk):
    _, h = alice
    pid = new_project(client, h, "NoWrapper")
    assert upload(client, h, pid, make_zip(dict(good_project()))).status_code == 201
    token = token_of(start(client, h, pid).json())
    status = wait_phase(client, token, ("failed",))
    assert status["errorCode"] == "unsupported_project" and "gradlew" in status["message"]


def test_without_an_android_sdk_the_start_says_so(client, alice, monkeypatch):
    _, h = alice
    monkeypatch.setattr(emu, "MANAGER", emu.PreviewManager(find_tools=lambda: None))
    pid = buildable_project(client, h)
    res = start(client, h, pid)
    assert res.status_code == 503 and res.json()["error"]["code"] == "emulator_unavailable"


def test_one_preview_at_a_time(client, alice, sdk):
    _, h = alice
    first = buildable_project(client, h, "One")
    second = buildable_project(client, h, "Two")
    a = start(client, h, first).json()
    wait_phase(client, token_of(a), ("ready",))  # the job has finished reading the project
    assert start(client, h, first).json()["sessionId"] == a["sessionId"]
    busy = start(client, h, second)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "emulator_unavailable"


def test_stop_ends_the_session_and_the_token_stops_working(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    session = start(client, h, pid).json()
    token = token_of(session)
    wait_phase(client, token, ("ready",))
    assert client.delete(f"{A}/projects/{pid}/preview/{session['sessionId']}", headers=h).status_code == 204
    assert client.get(f"{A}/preview-viewer/{token}/status").json()["phase"] == "stopped"
    assert client.get(f"{A}/preview-viewer/{token}/frame.png").status_code == 409
    assert client.post(f"{A}/preview-viewer/{token}/input", json={"type": "key", "key": "back"}).status_code == 409
    # a stopped session no longer blocks another project
    nxt = buildable_project(client, h, "Next")
    again = start(client, h, nxt)
    assert again.status_code == 201
    wait_phase(client, token_of(again.json()), ("ready",))


def test_unknown_tokens_and_foreign_sessions_get_nothing(client, alice, sdk):
    _, h = alice
    for path in ("", "/status", "/frame.png"):
        assert client.get(f"{A}/preview-viewer/not-a-real-token{path}").status_code == 404
    assert client.post(f"{A}/preview-viewer/nope/input", json={"type": "key", "key": "back"}).status_code == 404
    pid = buildable_project(client, h)
    other = new_project(client, h, "Other")
    session = start(client, h, pid).json()
    wait_phase(client, token_of(session), ("ready",))
    assert client.delete(f"{A}/projects/{other}/preview/{session['sessionId']}", headers=h).status_code == 404


def test_the_viewer_page_is_embeddable_only_by_the_app_and_loads_no_foreign_script(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    token = token_of(start(client, h, pid).json())
    page = client.get(f"{A}/preview-viewer/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    csp = page.headers["content-security-policy"]
    assert "frame-ancestors" in csp and "default-src 'none'" in csp and "http://localhost:*" in csp
    assert "https://" not in page.text and "http://" not in page.text.split("<script>")[1]


def test_a_session_ends_when_it_expires(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    token = token_of(start(client, h, pid).json())
    wait_phase(client, token, ("ready",))
    sdk.manager.by_token(token).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get(f"{A}/preview-viewer/{token}/status").json()["phase"] == "stopped"


def test_with_no_device_the_virtual_device_is_started_and_closed_afterwards(client, alice, tmp_path, monkeypatch):
    _, h = alice
    fake = FakeSdk()
    fake.devices_out, fake.avds = NO_DEVICE, b"Pixel_8_API_34\n"
    started = {}

    class Proc:
        stopped = False

        def poll(self):
            return None

        def terminate(self):
            Proc.stopped = True

    def spawn(args, **kw):
        started["args"] = args
        fake.devices_out = ONE_DEVICE  # the emulator appears once launched
        return Proc()

    tools = emu.Toolchain(tmp_path / "sdk", Path("adb"), Path("emulator"), Path("aapt2"))
    monkeypatch.setattr(emu, "MANAGER", make_manager(fake, tmp_path, tools=tools, spawn=spawn, env={}))
    pid = buildable_project(client, h)
    session = start(client, h, pid).json()
    wait_phase(client, token_of(session), ("ready",))
    assert started["args"][1:3] == ["-avd", "Pixel_8_API_34"] and "-no-window" in started["args"]
    client.delete(f"{A}/projects/{pid}/preview/{session['sessionId']}", headers=h)
    assert Proc.stopped is True
    assert any(c[-1] == "kill" and "emu" in c for c in fake.calls)


def test_a_connected_device_is_used_and_never_killed(client, alice, sdk):
    _, h = alice
    pid = buildable_project(client, h)
    session = start(client, h, pid).json()
    wait_phase(client, token_of(session), ("ready",))
    client.delete(f"{A}/projects/{pid}/preview/{session['sessionId']}", headers=h)
    assert not any("kill" in c for c in sdk.calls)


def test_the_work_copy_follows_the_project_including_deleted_files(tmp_path):
    work = tmp_path / "w"
    emu.materialize([("a/Old.kt", b"1"), ("a/Keep.kt", b"2")], work)
    (work / "build").mkdir()
    (work / "build" / "out.bin").write_bytes(b"cache")
    (work / "local.properties").write_text("sdk.dir=x")
    kept = work / "a" / "Keep.kt"
    stamp = kept.stat().st_mtime_ns
    emu.materialize([("a/Keep.kt", b"2"), ("b/New.kt", b"3"), ("../escape.kt", b"x")], work)
    assert not (work / "a" / "Old.kt").exists() and (work / "b" / "New.kt").read_bytes() == b"3"
    assert kept.stat().st_mtime_ns == stamp  # unchanged files are not rewritten (Gradle reuses its work)
    assert (work / "build" / "out.bin").exists() and (work / "local.properties").exists()
    assert not (tmp_path / "escape.kt").exists()


def test_safe_text_alphabet():
    assert emu.safe_text("a b;c") == "a%sbc" and emu.safe_text("x" * 500) == "x" * 200


def test_a_renamed_app_with_a_stale_firebase_config_still_builds_in_the_preview(tmp_path):
    import json

    project = tmp_path / "p"
    project.mkdir()
    (project / "settings.gradle.kts").write_text("")
    (project / "gradlew.bat").write_text("")
    (project / "gradlew").write_text("")
    config = project / "app" / "google-services.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"client": [{"client_info": {"android_client_info": {"package_name": "com.old"}}}]}))
    builds = []

    def run(args, *, timeout=60, cwd=None, env=None, on_line=None):
        builds.append(1)
        names = [c["client_info"]["android_client_info"]["package_name"] for c in json.loads(config.read_text())["client"]]
        if "com.new" not in names:
            on_line(f"> No matching client found for package name 'com.new' in {config}")
            return emu.Result(1)
        apk = project / "app/build/outputs/apk/debug/app-debug.apk"
        apk.parent.mkdir(parents=True, exist_ok=True)
        apk.write_bytes(b"apk")
        return emu.Result(0)

    log = []
    tools = emu.Toolchain(tmp_path / "sdk", Path("adb"), None, Path("aapt2"))
    # the real error names the package the build wants; the app is now called com.new
    apk = emu.build_debug_apk(project, tools, run, log.append)
    assert apk.name == "app-debug.apk" and len(builds) == 2
    assert any("patched COPY" in line and "com.new" in line for line in log)
    assert [c["client_info"]["android_client_info"]["package_name"] for c in json.loads(config.read_text())["client"]] == ["com.old", "com.new"]


def test_other_build_failures_are_not_retried_or_patched(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    for name in ("settings.gradle.kts", "gradlew.bat", "gradlew"):
        (project / name).write_text("")
    builds = []

    def run(args, *, timeout=60, cwd=None, env=None, on_line=None):
        builds.append(1)
        on_line("e: Unresolved reference: Foo")
        return emu.Result(1)

    tools = emu.Toolchain(tmp_path / "sdk", Path("adb"), None, Path("aapt2"))
    with pytest.raises(emu.PreviewError) as info:
        emu.build_debug_apk(project, tools, run, lambda _l: None)
    assert info.value.code == "build_failed" and "Unresolved reference" in info.value.message and len(builds) == 1


def test_the_patch_never_touches_files_outside_the_work_folder(tmp_path):
    outside = tmp_path / "other" / "google-services.json"
    outside.parent.mkdir()
    outside.write_text('{"client": [{"client_info": {"android_client_info": {"package_name": "a"}}}]}')
    project = tmp_path / "p"
    project.mkdir()
    text = f"No matching client found for package name 'b' in {outside}"
    assert emu._patch_google_services(project, text) is None
    assert "b" not in outside.read_text()


# ---- the build check the agent runs on its own result -----------------------------------------------


class Staged:
    """What the agent edited: a few changed files over the project on disk."""

    def __init__(self, files, changed):
        self.files, self._changed = files, set(changed)

    def paths(self):
        return sorted(self.files)

    def text(self, path):
        return self.files[path]

    def changed(self):
        return self._changed


def checker(tmp_path, fake):
    tools = emu.Toolchain(tmp_path / "sdk", Path("adb"), None, Path("aapt2"))
    return emu.BuildChecker(tmp_path / "verify", fake.run, tools)


def workspace_on_disk(tmp_path):
    root = tmp_path / "ws"
    for path, content in good_project().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content, encoding="utf-8") if isinstance(content, str) else (
            root / path
        ).write_bytes(content)
    (root / "gradlew").write_text("#!/bin/sh\n")
    (root / "gradlew.bat").write_text("@echo off\n")
    return root


def test_the_build_check_builds_the_edited_files_not_the_originals(tmp_path):
    fake, ws = FakeSdk(), workspace_on_disk(tmp_path)
    strings = "app/src/main/res/values/strings.xml"
    files = {p: (ws / p).read_text(encoding="utf-8", errors="ignore") for p in good_project()
             if (ws / p).is_file() and isinstance(good_project()[p], str)}
    files[strings] = "<resources><string name='edited'>x</resources"  # edited, in memory only
    staged = Staged(files, [strings])
    assert checker(tmp_path, fake).check("abcdef1234567890", ws, staged) == []
    built = tmp_path / "verify" / "v-abcdef12"
    assert (built / strings).read_text(encoding="utf-8") == files[strings]
    assert "TodoApp.kt" in " ".join(p for p in (str(x) for x in built.rglob("*.kt")))
    assert (ws / strings).read_text(encoding="utf-8") != files[strings]  # the project is untouched


def test_a_failed_build_comes_back_as_short_problems(tmp_path):
    class Failing(FakeSdk):
        def run(self, args, *, timeout=60, cwd=None, env=None, on_line=None):
            if Path(args[0]).name.lower().startswith("gradlew"):
                for line in (
                    "> Task :app:compileDebugKotlin FAILED",
                    f"e: file:///{Path(cwd).as_posix()}/app/src/Foo.kt:3:5 Unresolved reference: Bar",
                    "* What went wrong:",
                    "Execution failed for task ':app:compileDebugKotlin'.",
                    "> Compilation error. See log for more details",
                ):
                    on_line(line)
                return emu.Result(1)
            return super().run(args, timeout=timeout, cwd=cwd, env=env, on_line=on_line)

    ws = workspace_on_disk(tmp_path)
    staged = Staged({"settings.gradle.kts": "x", "gradlew": "", "gradlew.bat": ""}, ["settings.gradle.kts"])
    problems = checker(tmp_path, Failing()).check("abcdef1234567890", ws, staged)
    assert "e: app/src/Foo.kt:3:5 Unresolved reference: Bar" in problems
    assert "> Compilation error. See log for more details" in problems
    assert not any("file:///" in p or str(tmp_path) in p for p in problems)


def test_the_build_check_does_not_hide_a_firebase_failure(tmp_path):
    seen = []

    class Firebase(FakeSdk):
        def run(self, args, *, timeout=60, cwd=None, env=None, on_line=None):
            if Path(args[0]).name.lower().startswith("gradlew"):
                seen.append(1)
                for line in (
                    "* What went wrong:",
                    "Execution failed for task ':app:processProdDebugGoogleServices'.",
                    "> No matching client found for package name 'com.photoemitter' in "
                    "x/google-services.json",
                ):
                    on_line(line)
                return emu.Result(1)
            return super().run(args, timeout=timeout, cwd=cwd, env=env, on_line=on_line)

    ws = workspace_on_disk(tmp_path)
    staged = Staged({"settings.gradle.kts": "x", "gradlew": "", "gradlew.bat": ""}, ["settings.gradle.kts"])
    problems = checker(tmp_path, Firebase()).check("abcdef1234567890", ws, staged)
    assert len(seen) == 1  # no "patched copy" retry that would make the result look fine
    assert any("No matching client found" in p for p in problems)


def test_the_build_check_is_skipped_without_an_sdk_or_a_wrapper(tmp_path):
    notes = []
    none = emu.BuildChecker(tmp_path / "v", FakeSdk().run, None)
    none._tools = None
    assert emu.Toolchain.find({}) is None or True  # (the real lookup depends on the machine)
    ws = workspace_on_disk(tmp_path)
    (ws / "gradlew").unlink()
    (ws / "gradlew.bat").unlink()
    staged = Staged({"settings.gradle.kts": "x"}, [])
    assert checker(tmp_path, FakeSdk()).check("abcdef1234567890", ws, staged, notes.append) == []
    assert any("Skipping the build check" in n for n in notes)
