"""Which kind of project is this? A cheap, read-only classification of an uploaded project.

It runs on a ZIP (without extracting it) or a directory, before import. It reads only the file
list and a few small marker files (``pubspec.yaml``, ``package.json``, Gradle and version-catalog
files), never executes anything, and never raises for hostile input: a damaged archive or an
unreadable file just gives less evidence.

Only ``native_android`` is supported by the import and analysis stages today. Everything else is
classified so the caller can say "detected Flutter, not supported yet" instead of a generic refusal.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

MAX_MARKER_BYTES = 64 * 1024
MAX_GRADLE_FILES_READ = 40
_MAX_MARKER_DEPTH = 2

Reader = Callable[[str], str | None]


class ProjectKind(StrEnum):
    NATIVE_ANDROID = "native_android"
    FLUTTER = "flutter"
    REACT_NATIVE = "react_native"
    KOTLIN_MULTIPLATFORM = "kotlin_multiplatform"
    CAPACITOR_CORDOVA = "capacitor_cordova"
    UNKNOWN = "unknown"


class Detection(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ProjectKind
    supported: bool
    """True when the import and analysis stages can handle it (native Android only, today)."""
    project_root: str
    """Folder, relative to the archive or directory, that holds the project ("" for the top)."""
    android_root: str | None
    """Folder of the Android Gradle project, relative to the same base; None if there is none."""
    languages: list[str]
    ui_toolkits: list[str]
    evidence: list[str]
    reason: str


def detect_from_files(paths: Iterable[str], read: Reader | None = None) -> Detection:
    """Classify a project from its relative file paths and an optional reader for marker files."""
    files = sorted({p for p in (_clean(p) for p in paths) if p})
    prefix = _wrapper(files)
    if prefix:
        files = [f[len(prefix) :] for f in files]
    base = prefix.rstrip("/")

    def read_marker(rel: str) -> str | None:
        if read is None:
            return None
        try:
            text = read(prefix + rel)
        except Exception:  # a reader that fails only means less evidence
            return None
        return text[:MAX_MARKER_BYTES] if text is not None else None

    names = set(files)
    evidence: list[str] = []
    gradle = _gradle_files(files)
    gradle_text = _read_gradle(gradle, read_marker)

    def finish(kind: ProjectKind, root: str, reason: str, *, native: bool = False) -> Detection:
        android = _android_root(files, names)
        languages, toolkits = (
            _languages_and_ui(files, android, gradle_text) if android is not None else ([], [])
        )
        return Detection(
            kind=kind,
            supported=native,
            project_root=_join(base, root),
            android_root=None if android is None else _join(base, android),
            languages=languages,
            ui_toolkits=toolkits,
            evidence=evidence,
            reason=reason,
        )

    for root in _marker_roots(files):
        pubspec = _marker(names, root, "pubspec.yaml")
        if pubspec and _mentions(read_marker(pubspec), "flutter"):
            evidence.append(f"{pubspec} declares Flutter")
            return finish(
                ProjectKind.FLUTTER, root, "a Flutter project (pubspec.yaml with flutter)"
            )
        package = _marker(names, root, "package.json")
        if package and _mentions(read_marker(package), '"react-native"'):
            evidence.append(f'{package} depends on "react-native"')
            return finish(ProjectKind.REACT_NATIVE, root, "a React Native project (package.json)")
        for config in ("capacitor.config.ts", "capacitor.config.json", "capacitor.config.js"):
            marker = _marker(names, root, config)
            if marker:
                evidence.append(f"{marker} found")
                return finish(ProjectKind.CAPACITOR_CORDOVA, root, "a Capacitor project")
        cordova = _marker(names, root, "config.xml")
        if cordova and _mentions(read_marker(cordova), "cordova"):
            evidence.append(f"{cordova} is a Cordova config")
            return finish(ProjectKind.CAPACITOR_CORDOVA, root, "a Cordova project")

    if _is_multiplatform(files, gradle_text):
        evidence.append("Gradle build applies the Kotlin multiplatform plugin or has commonMain")
        return finish(ProjectKind.KOTLIN_MULTIPLATFORM, "", "a Kotlin Multiplatform project")

    android = _android_root(files, names)
    if android is not None:
        evidence.append(f"Gradle settings and AndroidManifest.xml found under '{android or '.'}'")
        reason = (
            "a native Android project"
            if not android
            else f"a native Android project in the '{android}' subfolder"
        )
        return finish(ProjectKind.NATIVE_ANDROID, android, reason, native=True)

    return finish(
        ProjectKind.UNKNOWN,
        "",
        "no Android Gradle project, Flutter, React Native or Kotlin Multiplatform markers found",
    )


def detect_zip(path: str | PurePosixPath | object) -> Detection:
    """Classify a ZIP archive without extracting it. A damaged archive gives ``unknown``."""
    try:
        with zipfile.ZipFile(path) as archive:  # type: ignore[arg-type]
            infos = {i.filename: i for i in archive.infolist() if not i.is_dir()}

            def read(rel: str) -> str | None:
                info = infos.get(rel)
                if info is None or info.file_size > MAX_MARKER_BYTES * 4:
                    return None
                try:
                    with archive.open(info) as handle:
                        return handle.read(MAX_MARKER_BYTES).decode("utf-8", errors="replace")
                except (RuntimeError, zipfile.BadZipFile, OSError, NotImplementedError):
                    return None

            return detect_from_files(infos, read)
    except (zipfile.BadZipFile, OSError):
        return detect_from_files([])


def detect_directory(root: str | object) -> Detection:
    """Classify a directory on disk (links are not followed)."""
    from pathlib import Path

    base = Path(root)  # type: ignore[arg-type]
    paths: list[str] = []
    try:
        for item in base.rglob("*"):
            if item.is_symlink() or not item.is_file():
                continue
            rel = item.relative_to(base).as_posix()
            if any(part in _SKIP_DIRS for part in rel.split("/")[:-1]):
                continue
            paths.append(rel)
    except OSError:
        pass

    def read(rel: str) -> str | None:
        try:
            with open(base / rel, "rb") as handle:
                return handle.read(MAX_MARKER_BYTES).decode("utf-8", errors="replace")
        except OSError:
            return None

    return detect_from_files(paths, read)


# ---------------------------------------------------------------------------------------------

_SKIP_DIRS = {"node_modules", ".git", "build", ".gradle", ".dart_tool", "Pods", "__MACOSX"}
_GRADLE_NAMES = {
    "settings.gradle",
    "settings.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
    "libs.versions.toml",
}


def _clean(path: str) -> str:
    p = path.replace("\\", "/").lstrip("/")
    if not p or p.endswith("/") or ".." in p.split("/"):
        return ""
    parts = p.split("/")
    if parts[0] == "__MACOSX" or any(part in _SKIP_DIRS - {"build"} for part in parts[:-1]):
        return ""
    return p


def _wrapper(files: list[str]) -> str:
    """The single top-level folder that wraps every file ('app-main/'), or ''."""
    tops = {f.split("/", 1)[0] for f in files if "/" in f}
    if len(tops) == 1 and all("/" in f for f in files) and files:
        return next(iter(tops)) + "/"
    return ""


def _join(base: str, rel: str) -> str:
    return "/".join(p for p in (base, rel) if p)


def _marker_roots(files: list[str]) -> list[str]:
    roots = {""}
    for f in files:
        parts = f.split("/")[:-1]
        for depth in range(1, min(len(parts), _MAX_MARKER_DEPTH) + 1):
            roots.add("/".join(parts[:depth]))
    return sorted(roots, key=lambda r: (r.count("/") if r else -1, r))


def _marker(names: set[str], root: str, name: str) -> str | None:
    candidate = f"{root}/{name}" if root else name
    return candidate if candidate in names else None


def _mentions(text: str | None, needle: str) -> bool:
    return text is not None and needle in text


def _gradle_files(files: list[str]) -> list[str]:
    found = [f for f in files if f.rsplit("/", 1)[-1] in _GRADLE_NAMES]
    return sorted(found, key=lambda f: (f.count("/"), f))[:MAX_GRADLE_FILES_READ]


def _read_gradle(paths: list[str], read: Callable[[str], str | None]) -> dict[str, str]:
    return {p: t for p in paths if (t := read(p)) is not None}


def _is_multiplatform(files: list[str], gradle_text: dict[str, str]) -> bool:
    for text in gradle_text.values():
        if (
            'kotlin("multiplatform")' in text
            or "org.jetbrains.kotlin.multiplatform" in text
            or "kotlin-multiplatform" in text
            or "kotlinMultiplatform" in text
        ):
            return True
    return any("/commonMain/" in f or f.startswith("commonMain/") for f in files)


def _android_root(files: list[str], names: set[str]) -> str | None:
    """The shallowest folder with Gradle settings (or a build file) and a manifest beneath it."""
    manifests = [
        f for f in files if f.endswith("/AndroidManifest.xml") or f == "AndroidManifest.xml"
    ]
    if not manifests:
        return None
    candidates: set[str] = set()
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name in ("settings.gradle", "settings.gradle.kts"):
            candidates.add(f.rsplit("/", 1)[0] if "/" in f else "")
    if not candidates:
        for f in files:
            if f.rsplit("/", 1)[-1] in ("build.gradle", "build.gradle.kts"):
                candidates.add(f.rsplit("/", 1)[0] if "/" in f else "")
    for root in sorted(candidates, key=lambda r: (r.count("/") if r else -1, r)):
        prefix = f"{root}/" if root else ""
        if any(m.startswith(prefix) for m in manifests):
            return root
    return None


def _languages_and_ui(
    files: list[str], android: str, gradle_text: dict[str, str]
) -> tuple[list[str], list[str]]:
    prefix = f"{android}/" if android else ""
    scoped = [f for f in files if f.startswith(prefix)]
    languages = []
    if any(f.endswith(".kt") for f in scoped):
        languages.append("kotlin")
    if any(f.endswith(".java") for f in scoped):
        languages.append("java")
    toolkits = []
    compose = any(
        "compose" in text.lower() for path, text in gradle_text.items() if path.startswith(prefix)
    )
    if compose:
        toolkits.append("compose")
    if any("/res/layout" in f and f.endswith(".xml") for f in scoped):
        toolkits.append("views")
    return languages, toolkits
