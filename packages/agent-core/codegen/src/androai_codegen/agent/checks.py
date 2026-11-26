"""Fast, build-free checks of an edited Android project.

These catch the mistakes a rename or an edit most often leaves behind, before the user opens the
project in Android Studio: a Firebase config that does not know the new application id, source files
that disagree with their package, imports of ``R`` from a package that no longer exists, manifest
entries pointing at classes that are gone, and files that are no longer valid XML or JSON.

``check_project`` is a pure function over a ``ProjectView``; it never touches the disk.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Protocol
from xml.etree import ElementTree

MAX_PROBLEMS = 12
_MAX_TEXT = 400_000


class ProjectView(Protocol):
    def paths(self) -> list[str]: ...

    def text(self, path: str) -> str | None: ...

    def changed(self) -> set[str]: ...


_APP_ID = re.compile(r"""applicationId\s*(?:=\s*)?["']([^"']+)["']""")
_SUFFIX = re.compile(r"applicationIdSuffix")
_NAMESPACE = re.compile(r"""\bnamespace\s*(?:=\s*)?["']([^"']+)["']""")
_GMS = re.compile(r"google[-.]services|com\.google\.gms")
_PACKAGE_DECL = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
_IMPORT_GENERATED = re.compile(r"^\s*import\s+([\w.]+)\.(R|BuildConfig)\b", re.MULTILINE)
_MANIFEST_PACKAGE = re.compile(r"""<manifest[^>]*\spackage\s*=\s*["']([^"']+)["']""", re.S)
_COMPONENT = re.compile(
    r"""<(?:activity|activity-alias|service|receiver|provider)\b[^>]*?\sandroid:name\s*=\s*["']([^"']+)["']""",
    re.S,
)
_CLASS_DECL = re.compile(r"^\s*(?:[\w ]+\s)?(?:class|object|interface)\s+(\w+)", re.MULTILINE)
_SOURCE = (".kt", ".java")


class _Memo:
    """Reads each file and the change list once; the checks ask for them many times."""

    def __init__(self, view: ProjectView) -> None:
        self._view = view
        self._text: dict[str, str | None] = {}
        self._changed: set[str] | None = None

    def paths(self) -> list[str]:
        return self._view.paths()

    def text(self, path: str) -> str | None:
        if path not in self._text:
            self._text[path] = self._view.text(path)
        return self._text[path]

    def changed(self) -> set[str]:
        if self._changed is None:
            self._changed = self._view.changed()
        return self._changed


def check_project(view: ProjectView) -> list[str]:
    """Problems that would stop the project building or running. Empty when it looks fine."""
    view = _Memo(view)
    paths = view.paths()
    problems: list[str] = []
    problems += _firebase(view, paths)
    declared = _declared_packages(view, paths)
    problems += _java_folders(view, paths)
    problems += _generated_imports(view, paths, declared)
    problems += _manifest_classes(view, paths, declared)
    problems += _well_formed(view)
    return problems[:MAX_PROBLEMS]


# -- Firebase --------------------------------------------------------------------------------


def _firebase(view: ProjectView, paths: list[str]) -> list[str]:
    out: list[str] = []
    for gradle in paths:
        if gradle.rsplit("/", 1)[-1] not in ("build.gradle", "build.gradle.kts"):
            continue
        text = view.text(gradle)
        if not text or not _GMS.search(text):
            continue
        ids = _APP_ID.findall(text)
        if not ids or _SUFFIX.search(text):
            continue  # suffixes make the real ids hard to know without running Gradle
        folder = gradle.rsplit("/", 1)[0] if "/" in gradle else ""
        config = f"{folder}/google-services.json" if folder else "google-services.json"
        if config not in paths:
            continue  # a flavor or CI step may supply it; the build will say
        known = _firebase_packages(view.text(config) or "")
        if known is None:
            continue
        for app_id in dict.fromkeys(ids):
            if app_id not in known:
                out.append(
                    f"{config}: has no client for the application id '{app_id}' set in {gradle} "
                    f"(it lists: {', '.join(sorted(known)) or 'nothing'}). The Google Services "
                    "plugin will refuse to build. Add a client entry for it (copy the existing one "
                    "and change package_name) or use rename_package/set_application_id, which do."
                )
    return out


def _firebase_packages(text: str) -> set[str] | None:
    try:
        clients = json.loads(text)["client"]
        return {c["client_info"]["android_client_info"]["package_name"] for c in clients}
    except (ValueError, KeyError, TypeError):
        return None


# -- packages and generated classes ---------------------------------------------------------


def _declared_packages(view: ProjectView, paths: Iterable[str]) -> set[str]:
    """Every package the project defines: source declarations, namespaces, application ids."""
    found: set[str] = set()
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if path.endswith(_SOURCE):
            match = _PACKAGE_DECL.search(view.text(path) or "")
            if match:
                found.add(match.group(1))
        elif name in ("build.gradle", "build.gradle.kts"):
            text = view.text(path) or ""
            found.update(_NAMESPACE.findall(text))
            found.update(_APP_ID.findall(text))
        elif name == "AndroidManifest.xml":
            found.update(_MANIFEST_PACKAGE.findall(view.text(path) or ""))
    return found


def _java_folders(view: ProjectView, paths: Iterable[str]) -> list[str]:
    """Java needs the folder to match the package; a half-finished move breaks the build."""
    out = []
    for path in paths:
        if not path.endswith(".java") or path not in view.changed():
            continue
        match = _PACKAGE_DECL.search(view.text(path) or "")
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        if match and not folder.endswith(match.group(1).replace(".", "/")):
            out.append(
                f"{path}: declares package {match.group(1)} but is not in a matching folder"
            )
    return out


def _generated_imports(view: ProjectView, paths: Iterable[str], declared: set[str]) -> list[str]:
    """``import <pkg>.R`` where <pkg> looks like this project's package but is not defined."""
    roots = {".".join(p.split(".")[:2]) for p in declared if p.count(".") >= 1}
    out = []
    for path in paths:
        if not path.endswith(_SOURCE) or path not in view.changed():
            continue
        for pkg, cls in _IMPORT_GENERATED.findall(view.text(path) or ""):
            near = ".".join(pkg.split(".")[:2]) in roots
            if near and pkg not in declared:
                out.append(
                    f"{path}: imports {pkg}.{cls}, but no module in this project has the package "
                    f"or namespace '{pkg}' (the generated {cls} class will not be found)"
                )
    return out


# -- manifest ---------------------------------------------------------------------------------


def _manifest_classes(view: ProjectView, paths: list[str], declared: set[str]) -> list[str]:
    classes = _class_names(view, paths)
    out = []
    for path in paths:
        if path.rsplit("/", 1)[-1] != "AndroidManifest.xml" or path not in view.changed():
            continue
        text = view.text(path) or ""
        base = (_MANIFEST_PACKAGE.search(text) or [None, ""])[1] or _module_namespace(
            view, path, paths
        )
        for name in _COMPONENT.findall(text):
            if "$" in name:
                continue
            if name.startswith("."):
                full = base + name if base else ""
            elif "." in name:
                full = name
            else:
                full = f"{base}.{name}" if base else ""
            # A name outside this project's packages is a library component; leave it alone.
            if full and _is_ours(full, declared) and full not in classes:
                out.append(f"{path}: declares {name} but no class {full} exists in the project")
    return out


def _module_namespace(view: ProjectView, manifest: str, paths: list[str]) -> str:
    module = manifest.split("/src/")[0] if "/src/" in manifest else ""
    for name in ("build.gradle.kts", "build.gradle"):
        gradle = f"{module}/{name}" if module else name
        if gradle in paths:
            found = _NAMESPACE.findall(view.text(gradle) or "")
            if found:
                return found[0]
    return ""


def _is_ours(full: str, declared: set[str]) -> bool:
    return any(full == p or full.startswith(p + ".") for p in declared)


def _class_names(view: ProjectView, paths: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        if path.endswith(_SOURCE):
            text = view.text(path) or ""
            match = _PACKAGE_DECL.search(text)
            if match:
                stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                names.add(f"{match.group(1)}.{stem}")
                names.update(f"{match.group(1)}.{n}" for n in _CLASS_DECL.findall(text))
    return names


# -- syntax ------------------------------------------------------------------------------------


def _well_formed(view: ProjectView) -> list[str]:
    out = []
    for path in sorted(view.changed()):
        text = view.text(path)
        if not text or len(text) > _MAX_TEXT:
            continue
        if path.endswith(".xml"):
            if "<!DOCTYPE" in text or "<!ENTITY" in text:
                continue  # not parsed: entity expansion is a denial-of-service risk
            try:
                ElementTree.fromstring(text)
            except ElementTree.ParseError as exc:
                out.append(f"{path}: is not valid XML ({exc})")
        elif path.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as exc:
                out.append(f"{path}: is not valid JSON ({str(exc)[:120]})")
    return out
