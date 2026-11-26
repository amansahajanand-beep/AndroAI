"""DEV-ONLY live app preview: build the project's debug APK, run it on an Android emulator (or an
already-connected device) and let the browser look at the screen and tap on it.

Everything here runs on THIS machine with the Android SDK found on it, and it executes the
project's own Gradle build. Gradle scripts are arbitrary code, so this is only for projects you
trust, on a development machine. The production design runs the build and the emulator in
isolated, network-restricted workers (see docs/INFRASTRUCTURE.md); this module is the local
stand-in behind the same contract (``preview.start`` / ``EmulatorStreamSession``).

The screen is streamed as PNG frames (``adb exec-out screencap``) a few times a second and input
goes back through ``adb shell input``. That needs nothing beyond the SDK that is already installed.

External commands are run through an injectable ``Runner`` so the whole flow is unit tested
without an SDK.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

SESSION_SECONDS = 30 * 60
BUILD_TIMEOUT = 25 * 60
BOOT_TIMEOUT = 300
FRAME_CACHE_SECONDS = 0.08

# Folders of the work copy that are build output or caches, never project content.
_KEEP_DIRS = frozenset({"build", ".gradle", ".idea"})
_KEEP_FILES = frozenset({"local.properties"})
KEYS = {"back": 4, "home": 3, "recents": 187, "enter": 66, "delete": 67, "menu": 82}
_TEXT_ALLOWED = re.compile(r"[^A-Za-z0-9 ._@,:/+-]")


class PreviewError(Exception):
    """A preview step failed. ``code`` is one of the frontend's PreviewErrorCode values."""

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------------------------------------------------------------------------- processes


@dataclass
class Result:
    code: int
    out: bytes = b""


Runner = Callable[..., Result]  # (args, *, timeout, cwd=None, env=None, on_line=None) -> Result


def run_process(
    args: list[str],
    *,
    timeout: float = 60,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> Result:
    """Run a command. With ``on_line`` its output is passed on line by line while it runs."""
    try:
        if on_line is None:
            done = subprocess.run(
                args, capture_output=True, timeout=timeout, cwd=cwd, env=env, check=False
            )
            return Result(done.returncode, done.stdout)
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env
        )
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                on_line(raw.decode("utf-8", errors="replace").rstrip())
            proc.wait()
        finally:
            timer.cancel()
        return Result(proc.returncode)
    except subprocess.TimeoutExpired:
        return Result(124, b"timed out")
    except OSError as exc:
        return Result(127, str(exc).encode())


# ---------------------------------------------------------------------------- toolchain


@dataclass
class Toolchain:
    sdk: Path
    adb: Path
    emulator: Path | None
    aapt2: Path | None

    @classmethod
    def find(cls, env: dict[str, str] | None = None) -> Toolchain | None:
        env = dict(os.environ) if env is None else env
        exe = ".exe" if os.name == "nt" else ""
        candidates = [env.get("ANDROID_HOME"), env.get("ANDROID_SDK_ROOT")]
        if env.get("LOCALAPPDATA"):
            candidates.append(str(Path(env["LOCALAPPDATA"]) / "Android" / "Sdk"))
        candidates.append(str(Path.home() / "Android" / "Sdk"))
        candidates.append(str(Path.home() / "Library" / "Android" / "sdk"))
        for raw in candidates:
            if not raw:
                continue
            sdk = Path(raw)
            adb = sdk / "platform-tools" / f"adb{exe}"
            if not adb.is_file():
                continue
            emulator = sdk / "emulator" / f"emulator{exe}"
            tools = sorted((sdk / "build-tools").glob(f"*/aapt2{exe}"))
            return cls(sdk, adb, emulator if emulator.is_file() else None, tools[-1] if tools else None)
        return None


class Adb:
    def __init__(self, tools: Toolchain, run: Runner) -> None:
        self._tools, self._run = tools, run

    def _a(self, *args: str, serial: str | None = None, timeout: float = 30) -> Result:
        prefix = ["-s", serial] if serial else []
        return self._run([str(self._tools.adb), *prefix, *args], timeout=timeout)

    def devices(self) -> list[str]:
        out = self._a("devices").out.decode("utf-8", errors="replace")
        return [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("device")]

    def booted(self, serial: str) -> bool:
        return self._a("shell", "getprop", "sys.boot_completed", serial=serial).out.strip() == b"1"

    def prop(self, serial: str, name: str) -> str:
        return self._a("shell", "getprop", name, serial=serial).out.decode("utf-8", "replace").strip()

    def size(self, serial: str) -> tuple[int, int]:
        out = self._a("shell", "wm", "size", serial=serial).out.decode("utf-8", "replace")
        found = re.findall(r"(\d{3,5})x(\d{3,5})", out)
        if not found:
            return 1080, 2400
        width, height = found[-1]  # an "Override size" line, when there is one, comes last
        return int(width), int(height)

    def screencap(self, serial: str) -> bytes:
        return self._a("exec-out", "screencap", "-p", serial=serial, timeout=10).out

    def install(self, serial: str, apk: Path) -> Result:
        return self._a("install", "-r", "-t", str(apk), serial=serial, timeout=180)

    def launch(self, serial: str, package: str) -> Result:
        return self._a(
            "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1",
            serial=serial,
        )

    def tap(self, serial: str, x: int, y: int) -> None:
        self._a("shell", "input", "tap", str(x), str(y), serial=serial, timeout=10)

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
        self._a(
            "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms),
            serial=serial, timeout=10,
        )

    def key(self, serial: str, code: int) -> None:
        self._a("shell", "input", "keyevent", str(code), serial=serial, timeout=10)

    def text(self, serial: str, text: str) -> None:
        self._a("shell", "input", "text", text, serial=serial, timeout=10)

    def kill_emulator(self, serial: str) -> None:
        self._a("emu", "kill", serial=serial, timeout=15)


def safe_text(text: str) -> str:
    """Text for ``adb shell input text``. The device shell would run anything else in it, so only a
    small safe alphabet is kept; a space is written ``%s``."""
    return _TEXT_ALLOWED.sub("", text)[:200].replace(" ", "%s")


# ---------------------------------------------------------------------------- the project build


def materialize(files: Iterable[tuple[str, bytes]], target: Path) -> None:
    """Make ``target`` hold exactly these files, touching only what changed (so Gradle can reuse
    its previous work) and removing files the project no longer has (e.g. after a package rename)."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    wanted: set[Path] = set()
    for path, data in files:
        destination = (target / path).resolve()
        if root not in destination.parents:
            continue  # never write outside the work folder
        wanted.add(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != data:
            destination.write_bytes(data)
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _KEEP_DIRS]
        for name in names:
            candidate = Path(current) / name
            if candidate not in wanted and name not in _KEEP_FILES:
                candidate.unlink(missing_ok=True)


_NO_CLIENT = re.compile(r"No matching client found for package name '([^']+)' in (.+?google-services\.json)")


def _patch_google_services(project: Path, output: str) -> str | None:
    """A renamed app no longer matches its Firebase config and the Google Services plugin refuses to
    build. Give the preview's work copy a client entry for the new package (a copy of the first
    one). Only the work folder is touched. Returns the package, or None when this is not the problem."""
    import copy
    import json

    found = _NO_CLIENT.search(output)
    if not found:
        return None
    package, path = found.group(1), Path(found.group(2).strip())
    try:
        resolved = path.resolve()
        if project.resolve() not in resolved.parents or not resolved.is_file():
            return None
        data = json.loads(resolved.read_text(encoding="utf-8"))
        clients = data.get("client")
        if not isinstance(clients, list) or not clients:
            return None
        clone = copy.deepcopy(clients[0])
        clone["client_info"]["android_client_info"]["package_name"] = package
        clients.append(clone)
        resolved.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return package


def build_debug_apk(
    project: Path,
    tools: Toolchain,
    run: Runner,
    log: Callable[[str], None],
    *,
    patch_firebase: bool = True,
) -> Path:
    if not any((project / n).is_file() for n in ("settings.gradle", "settings.gradle.kts")):
        raise PreviewError("unsupported_project", "This is not a Gradle Android project.", 422)
    wrapper = project / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not wrapper.is_file():
        raise PreviewError(
            "unsupported_project",
            "The project has no Gradle wrapper (gradlew), so it can't be built here.",
            422,
        )
    if os.name != "nt":
        wrapper.chmod(wrapper.stat().st_mode | 0o111)
    (project / "local.properties").write_text(f"sdk.dir={tools.sdk.as_posix()}\n", encoding="utf-8")
    env = {**os.environ, "ANDROID_HOME": str(tools.sdk), "ANDROID_SDK_ROOT": str(tools.sdk)}
    tail: deque[str] = deque(maxlen=80)

    def line(text: str) -> None:
        if text.strip():
            tail.append(text[:300])
            log(text[:300])

    def attempt() -> Result:
        tail.clear()
        return run(
            [str(wrapper), "assembleDebug", "--console=plain", "-Dorg.gradle.daemon=false"],
            timeout=BUILD_TIMEOUT, cwd=project, env=env, on_line=line,
        )

    done = attempt()
    if done.code != 0 and patch_firebase:
        patched = _patch_google_services(project, "\n".join(tail))
        if patched:
            log(
                f"google-services.json has no client for {patched}; using a patched COPY for this "
                "preview only (your project is unchanged: register the new package in Firebase)."
            )
            done = attempt()
    if done.code != 0:
        shown = list(tail)[-25:]
        raise PreviewError("build_failed", "The Gradle build failed:\n" + "\n".join(shown), 422)
    apks = [
        p for p in project.glob("**/build/outputs/apk/**/*.apk")
        if "debug" in p.as_posix().lower() and "androidtest" not in p.as_posix().lower()
    ]
    if not apks:
        raise PreviewError("build_failed", "The build finished but produced no debug APK.", 422)
    return max(apks, key=lambda p: p.stat().st_mtime)


_ERROR_LINE = re.compile(
    r"(^e: )|(\berror:)|(\bERROR\b)|(AAPT)|(Unresolved reference)|(^> (?!Task ))", re.IGNORECASE
)


def build_problems(lines: Iterable[str], roots: Iterable[Path] = ()) -> list[str]:
    """What went wrong in a Gradle log, as a few short lines a model can act on: compiler and
    resource errors and Gradle's own "What went wrong" explanation. Work-folder paths are made
    relative so the model sees the same paths it edits."""
    prefixes: list[str] = []
    for root in roots:
        for form in (root.as_posix(), str(root)):
            prefixes += [f"file:///{form}/", f"{form}/", f"{form}\\"]
    cleaned: list[str] = []
    for raw in lines:
        text = raw.strip()
        for prefix in prefixes:
            text = text.replace(prefix, "")
        cleaned.append(text)
    found: list[str] = []
    for index, text in enumerate(cleaned):
        if text.startswith("* What went wrong"):
            found += [t for t in cleaned[index + 1 : index + 4] if t]
        elif _ERROR_LINE.search(text) and not text.startswith("Execution failed"):
            found.append(text)
    unique = list(dict.fromkeys(t[:300] for t in found if t))
    return unique[:12] or ["The Gradle build failed (no details were reported)."]


class BuildChecker:
    """Builds the agent's edited project so mistakes are found before the user sees the result.

    The edited files are written over a copy of the project in a work folder that is reused
    between rounds (so Gradle only redoes what changed). Like the preview, this runs the
    project's own Gradle build: dev machines and trusted projects only."""

    def __init__(
        self,
        data_dir: Path | None = None,
        run: Runner = run_process,
        tools: Toolchain | None = None,
    ) -> None:
        self.data_dir = data_dir or Path(os.environ.get("TEMP", "/tmp")) / "androai-verify"
        self.run = run
        self._tools = tools

    def tools(self) -> Toolchain | None:
        return self._tools or Toolchain.find()

    def available(self) -> bool:
        return self.tools() is not None

    def check(
        self,
        project_id: str,
        workspace: Path,
        staged: object,
        log: Callable[[str], None] = lambda _t: None,
    ) -> list[str]:
        """Problems the real build reports; empty when it builds or cannot be built here."""
        tools = self.tools()
        if tools is None:
            log("Skipping the build check: no Android SDK was found on this machine.")
            return []
        changed = staged.changed()  # type: ignore[attr-defined]

        def files() -> Iterable[tuple[str, bytes]]:
            for path in staged.paths():  # type: ignore[attr-defined]
                if path in changed:
                    text = staged.text(path)  # type: ignore[attr-defined]
                    if text is not None:
                        yield path, text.encode("utf-8")
                else:
                    try:
                        yield path, (workspace / path).read_bytes()
                    except OSError:
                        continue

        target = self.data_dir / f"v-{project_id[:8]}"
        lines: deque[str] = deque(maxlen=400)

        def note(text: str) -> None:
            lines.append(text)
            log(text)

        try:
            materialize(files(), target)
            build_debug_apk(target, tools, self.run, note, patch_firebase=False)
        except PreviewError as exc:
            if exc.code == "unsupported_project":
                log(f"Skipping the build check: {exc.message}")
                return []
            return build_problems(lines, [target])
        except OSError as exc:
            log(f"Skipping the build check: {type(exc).__name__}")
            return []
        return []


BUILD_CHECKER = BuildChecker()


def package_of(tools: Toolchain, run: Runner, apk: Path) -> str:
    if tools.aapt2 is None:
        raise PreviewError("emulator_unavailable", "aapt2 (Android build-tools) was not found.")
    out = run([str(tools.aapt2), "dump", "badging", str(apk)], timeout=60).out.decode("utf-8", "replace")
    found = re.search(r"package: name='([^']+)'", out)
    if not found:
        raise PreviewError("build_failed", "Could not read the package name from the built APK.", 422)
    return found.group(1)


# ---------------------------------------------------------------------------- sessions


@dataclass
class Session:
    project_id: str
    tenant_id: str
    id: str = field(default_factory=lambda: secrets.token_hex(8))
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    phase: str = "building"  # building | booting | installing | ready | failed | stopped
    message: str = "Starting…"
    error_code: str | None = None
    serial: str | None = None
    own_emulator: bool = False
    process: object | None = None
    thread: threading.Thread | None = None
    width: int = 1080
    height: int = 2400
    device_name: str = "Android emulator"
    api_level: int = 0
    log: deque = field(default_factory=lambda: deque(maxlen=14))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS)
    )
    lock: threading.RLock = field(default_factory=threading.RLock)
    _frame: bytes = b""
    _frame_at: float = 0.0

    @property
    def active(self) -> bool:
        return self.phase not in ("failed", "stopped")

    def public(self) -> dict:
        return {
            "state": "ready" if self.phase == "ready" else "starting",
            "device": {
                "name": self.device_name, "apiLevel": self.api_level,
                "width": self.width, "height": self.height,
            },
            "expiresAt": self.expires_at.isoformat(),
        }

    def status(self) -> dict:
        return {
            "phase": self.phase, "message": self.message, "errorCode": self.error_code,
            "log": list(self.log), "width": self.width, "height": self.height,
            "expiresAt": self.expires_at.isoformat(),
        }

    def set(self, phase: str, message: str) -> None:
        with self.lock:
            self.phase, self.message = phase, message


class PreviewManager:
    """One preview at a time (one emulator). Sessions end after ``SESSION_SECONDS`` or on stop."""

    def __init__(
        self,
        *,
        find_tools: Callable[[], Toolchain | None] = Toolchain.find,
        run: Runner = run_process,
        spawn: Callable[..., object] = subprocess.Popen,
        data_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        env: dict[str, str] | None = None,
    ) -> None:
        self._find_tools, self._run, self._spawn, self._sleep = find_tools, run, spawn, sleep
        self._data = data_dir or Path(os.environ.get("DEV_DATA_DIR") or ".data/dev") / "preview"
        self._env = env if env is not None else dict(os.environ)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    # -- lookup -------------------------------------------------------------------------

    def by_token(self, token: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(token)
        if session is not None and session.active and datetime.now(UTC) > session.expires_at:
            self.stop(session)
        return session

    def by_id(self, project_id: str, session_id: str) -> Session | None:
        with self._lock:
            return next(
                (s for s in self._sessions.values() if s.id == session_id and s.project_id == project_id),
                None,
            )

    # -- start / stop -------------------------------------------------------------------

    def start(
        self, *, project_id: str, tenant_id: str, files: Callable[[], Iterable[tuple[str, bytes]]]
    ) -> Session:
        tools = self._find_tools()
        if tools is None:
            raise PreviewError(
                "emulator_unavailable",
                "The Android SDK was not found on this machine (set ANDROID_HOME).",
            )
        with self._lock:
            for s in list(self._sessions.values()):
                if s.active and datetime.now(UTC) > s.expires_at:
                    self.stop(s)
            for s in self._sessions.values():
                if s.active:
                    if s.project_id == project_id and s.tenant_id == tenant_id:
                        return s
                    raise PreviewError(
                        "emulator_unavailable", "Another preview is already running; stop it first.", 409
                    )
            session = Session(project_id=project_id, tenant_id=tenant_id)
            self._sessions[session.token] = session
        session.thread = threading.Thread(
            target=self._run_session, args=(session, tools, files), daemon=True,
            name=f"preview-{session.id}",
        )
        session.thread.start()
        return session

    def stop(self, session: Session) -> None:
        with session.lock:
            if session.phase == "stopped":
                return
            was_ready_serial, own, proc = session.serial, session.own_emulator, session.process
            session.phase, session.message = "stopped", "The preview was stopped."
        tools = self._find_tools()
        if own and was_ready_serial and tools is not None:
            Adb(tools, self._run).kill_emulator(was_ready_serial)
        if own and proc is not None:
            try:
                proc.terminate()  # type: ignore[attr-defined]
            except OSError:
                pass

    # -- the background job -------------------------------------------------------------

    def _run_session(
        self, session: Session, tools: Toolchain, files: Callable[[], Iterable[tuple[str, bytes]]]
    ) -> None:
        adb = Adb(tools, self._run)
        try:
            session.set("building", "Preparing your project…")
            work = self._data / session.project_id
            materialize(files(), work)
            if not session.active:
                return
            session.set("building", "Building your app with Gradle (the first build takes a few minutes)…")
            apk = build_debug_apk(work, tools, self._run, lambda text: session.log.append(text))
            package = package_of(tools, self._run, apk)
            if not session.active:
                return
            session.set("booting", "Starting the emulator…")
            serial = self._ensure_device(session, tools, adb)
            session.set("installing", "Installing and launching your app…")
            installed = adb.install(serial, apk)
            if installed.code != 0 or b"Success" not in installed.out:
                detail = installed.out.decode("utf-8", "replace").strip()[-300:]
                raise PreviewError("emulator_unavailable", f"Installing the app failed: {detail}")
            adb.launch(serial, package)
            with session.lock:
                session.width, session.height = adb.size(serial)
                session.device_name = adb.prop(serial, "ro.product.model") or "Android emulator"
                level = adb.prop(serial, "ro.build.version.sdk")
                session.api_level = int(level) if level.isdigit() else 0
            if session.active:
                session.set("ready", "Live")
        except PreviewError as exc:
            with session.lock:
                session.phase, session.message, session.error_code = "failed", exc.message, exc.code
        except Exception as exc:  # noqa: BLE001  (a preview problem must never take the API down)
            with session.lock:
                session.phase, session.error_code = "failed", "emulator_unavailable"
                session.message = f"The preview failed unexpectedly ({type(exc).__name__})."

    def _ensure_device(self, session: Session, tools: Toolchain, adb: Adb) -> str:
        existing = adb.devices()
        if existing:  # an emulator or phone is already connected: use it, never kill it
            session.serial = existing[0]
            return existing[0]
        if tools.emulator is None:
            raise PreviewError(
                "emulator_unavailable", "No device is connected and the Android emulator isn't installed."
            )
        avd = self._env.get("PREVIEW_AVD") or self._first_avd(tools)
        if not avd:
            raise PreviewError(
                "emulator_unavailable",
                "No Android virtual device exists. Create one in Android Studio (Device Manager).",
            )
        args = [str(tools.emulator), "-avd", avd, "-no-audio", "-no-snapshot-save", "-no-boot-anim",
                "-gpu", "swiftshader_indirect"]
        if self._env.get("PREVIEW_EMULATOR_WINDOW") != "1":
            args.append("-no-window")
        try:
            session.process = self._spawn(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise PreviewError("emulator_unavailable", f"Could not start the emulator: {exc}") from exc
        session.own_emulator = True
        deadline = time.monotonic() + BOOT_TIMEOUT
        while time.monotonic() < deadline and session.active:
            exited = getattr(session.process, "poll", lambda: None)()
            if exited is not None:
                raise PreviewError(
                    "emulator_unavailable",
                    f"The emulator '{avd}' stopped right after starting (exit code {exited}). Check "
                    "that its system image is installed and hardware acceleration is on.",
                )
            for serial in adb.devices():
                if serial.startswith("emulator-") and adb.booted(serial):
                    session.serial = serial
                    return serial
            self._sleep(2)
        raise PreviewError("emulator_unavailable", f"The emulator '{avd}' did not finish starting in time.")

    def _first_avd(self, tools: Toolchain) -> str | None:
        out = self._run([str(tools.emulator), "-list-avds"], timeout=30).out.decode("utf-8", "replace")
        names = [line.strip() for line in out.splitlines() if re.fullmatch(r"[A-Za-z0-9._-]+", line.strip())]
        return names[0] if names else None

    # -- the screen and input -----------------------------------------------------------

    def _adb_for(self, session: Session) -> tuple[Adb, str]:
        tools = self._find_tools()
        if session.phase != "ready" or session.serial is None or tools is None:
            raise PreviewError("emulator_unavailable", "The preview is not ready.", 409)
        return Adb(tools, self._run), session.serial

    def frame(self, session: Session) -> bytes:
        adb, serial = self._adb_for(session)
        with session.lock:
            if time.monotonic() - session._frame_at < FRAME_CACHE_SECONDS and session._frame:
                return session._frame
            data = adb.screencap(serial)
            if not data.startswith(b"\x89PNG"):
                raise PreviewError("emulator_unavailable", "The device did not return a screen image.", 502)
            session._frame, session._frame_at = data, time.monotonic()
            return data

    def tap(self, session: Session, x: float, y: float) -> None:
        adb, serial = self._adb_for(session)
        adb.tap(serial, *self._clamp(session, x, y))

    def swipe(self, session: Session, x1: float, y1: float, x2: float, y2: float, ms: int) -> None:
        adb, serial = self._adb_for(session)
        a, b = self._clamp(session, x1, y1), self._clamp(session, x2, y2)
        adb.swipe(serial, *a, *b, max(50, min(ms, 3000)))

    def key(self, session: Session, name: str) -> None:
        adb, serial = self._adb_for(session)
        if name not in KEYS:
            raise PreviewError("unsupported_project", "Unknown key.", 422)
        adb.key(serial, KEYS[name])

    def text(self, session: Session, text: str) -> None:
        adb, serial = self._adb_for(session)
        cleaned = safe_text(text)
        if cleaned:
            adb.text(serial, cleaned)

    @staticmethod
    def _clamp(session: Session, x: float, y: float) -> tuple[int, int]:
        return (
            int(max(0, min(x, session.width - 1))),
            int(max(0, min(y, session.height - 1))),
        )

    def wait_idle(self, timeout: float = 15) -> None:
        """Block until every session's background job has finished (used by tests)."""
        with self._lock:
            threads = [s.thread for s in self._sessions.values() if s.thread is not None]
        for thread in threads:
            thread.join(timeout)

    def cleanup_files(self, project_id: str) -> None:  # pragma: no cover - manual housekeeping
        shutil.rmtree(self._data / project_id, ignore_errors=True)


MANAGER = PreviewManager()
