"""Change-aware rules: what a patch removed or altered compared with the 'before' project.

These are about *unintended or high-impact* changes (a component, permission or dependency that
disappeared, a renamed application id, a converted language or UI toolkit, deleted tests). They
run only when a 'before' state exists, and only look at files that differ between the two states.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from ..analysis import ManifestInfo, ProjectAnalysis
from ..catalog import SENSITIVE_DEPENDENCY_GROUPS
from ..models import Finding, Severity, finding
from .manifest import _fqn, _nodes, _removed

_XML_UI = re.compile(r"\bR\.layout\.\w+|\b\w+Binding\.inflate\s*\(|\bDataBindingUtil\.")
_COMPOSE_UI = re.compile(r"\bsetContent\s*\{|@Composable\b")
_TEST_ANNOTATION = re.compile(r"@(?:Test|ParameterizedTest|RepeatedTest)\b")


def compare(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    yield from _components(before, after)
    yield from _permissions(before, after)
    yield from _dependencies(before, after)
    yield from _identity(before, after)
    yield from _language(before, after)
    yield from _toolkit(before, after)
    yield from _tests(before, after)
    yield from _sdk(before, after)
    yield from _exposure(before, after)


def _changed(
    before: ProjectAnalysis, after: ProjectAnalysis, suffixes: tuple[str, ...]
) -> list[str]:
    """Paths of reviewable files that differ between the two states (added, removed, edited)."""
    old, new = before.files.texts, after.files.texts
    return sorted(
        p for p in old.keys() | new.keys() if p.endswith(suffixes) and old.get(p) != new.get(p)
    )


# -- manifest: components and permissions -------------------------------------------------------


@dataclass(frozen=True)
class _Seen:
    kind: str
    name: str  # as written in the manifest
    keys: frozenset[str]  # every spelling of the same class: relative to the package, and full
    line: int
    launcher: bool
    exported: str | None
    has_filter: bool


def _components_of(a: ProjectAnalysis, info: ManifestInfo | None) -> list[_Seen]:
    """The manifest's components (merge-time edits skipped), each with all spellings of its class.

    Two components are the same if any spelling matches. That keeps both ways of renaming a
    package from looking like "everything was removed": relative names (``.Foo``) still match
    after the package changes, and fully qualified names still match when it does.
    """
    if info is None:
        return []
    nodes = _nodes(info)
    package = a.manifest_package(info)
    found = []
    for c in info.components:
        if c.kind == "application" or _removed(nodes.get((c.line, c.kind))):
            continue
        name = c.name
        if "." not in name:
            relative = "." + name
        elif name.startswith(".") or not (package and name.startswith(package + ".")):
            relative = name
        else:
            relative = name[len(package) :]
        keys = {relative}
        if fqn := _fqn(a, info, name):
            keys.add(fqn)
        found.append(
            _Seen(
                c.kind,
                name,
                frozenset(keys),
                c.line,
                c.is_launcher,
                c.exported,
                c.has_intent_filter,
            )
        )
    return found


def _match(items: list[_Seen], other: _Seen) -> _Seen | None:
    return next((s for s in items if s.kind == other.kind and s.keys & other.keys), None)


def _components(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    for path, old_info in before.manifests.items():
        old = _components_of(before, old_info)
        new = _components_of(after, after.manifests.get(path))
        for gone in old:
            if _match(new, gone) is not None:
                continue
            launcher = " It was the app's launcher." if gone.launcher else ""
            yield finding(
                Severity.WARNING,
                "change.component_removed",
                "changes",
                path,
                f"The change removes the <{gone.kind}> {gone.name} from the manifest.{launcher}",
                line=gone.line,
                fix="Make sure removing it is intended, and that nothing still starts it.",
                key=f"{gone.kind}:{min(gone.keys)}",
            )


def _permission_set(a: ProjectAnalysis, path: str) -> dict[str, int]:
    info = a.manifests.get(path)
    if info is None:
        return {}
    return {
        node.attrs.get("android:name", ""): node.line
        for node in info.root.iter()
        if node.tag in ("uses-permission", "uses-permission-sdk-23") and not _removed(node)
    }


def _permissions(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    for path in before.manifests:
        old, new = _permission_set(before, path), _permission_set(after, path)
        for permission, line in old.items():
            if permission not in new:
                yield finding(
                    Severity.WARNING,
                    "change.permission_removed",
                    "changes",
                    path,
                    f"The change removes the permission {permission.rsplit('.', 1)[-1]}.",
                    line=line,
                    fix="Make sure nothing in the app still needs it.",
                    key=permission,
                )


def _exposure(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    """A component without an intent filter that becomes exported is newly reachable."""
    for path, new_info in after.manifests.items():
        old = _components_of(before, before.manifests.get(path))
        for now in _components_of(after, new_info):
            was = _match(old, now)
            if was is None or now.has_filter or now.exported != "true" or was.exported == "true":
                continue
            yield finding(
                Severity.WARNING,
                "change.component_exported",
                "changes",
                path,
                f"The change makes the <{now.kind}> {now.name} exported, so other apps can "
                "start it.",
                line=now.line,
                fix='Keep android:exported="false" unless other apps must reach it.',
                key=f"{now.kind}:{min(now.keys)}",
            )


# -- build: dependencies, identity, SDK levels --------------------------------------------------


def _sensitive(coordinate: str) -> bool:
    group = coordinate.split(":")[0]
    return any(
        coordinate == entry
        or coordinate.startswith(entry + ":")
        or group == entry
        or group.startswith(entry + ".")
        for entry in SENSITIVE_DEPENDENCY_GROUPS
    )


def _dependencies(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    old = {r.coordinate: r for r in before.dependencies if r.coordinate and not r.dep.project}
    new = {r.coordinate for r in after.dependencies if r.coordinate}
    unresolved = {r.dep.alias for r in after.dependencies if r.unresolved_alias}
    for coordinate, resolved in sorted(old.items()):
        if coordinate in new or resolved.dep.alias in unresolved:
            continue  # still there, or only unresolvable now (reported as a catalog error)
        if _sensitive(coordinate):
            yield finding(
                Severity.ERROR,
                "change.integration_removed",
                "changes",
                resolved.dep.path,
                f"The change removes {coordinate}, a payment or authentication integration.",
                line=resolved.dep.line,
                fix="Removing it needs the user's approval.",
                key=coordinate,
                approval="remove_integration",
            )
        else:
            yield finding(
                Severity.WARNING,
                "change.dependency_removed",
                "changes",
                resolved.dep.path,
                f"The change removes the dependency {coordinate}.",
                line=resolved.dep.line,
                fix="Make sure no code still uses it.",
                key=coordinate,
            )


def _identity(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    """Renaming the application id, namespace or manifest package breaks installs and updates."""
    for path, old in before.gradle_scripts.items():
        new = after.gradle_scripts.get(path)
        if new is None:
            continue
        for label, was, now in (
            ("applicationId", old.application_id, new.application_id),
            ("namespace", old.namespace, new.namespace),
        ):
            if was and now and was[0] != now[0]:
                yield finding(
                    Severity.ERROR,
                    "change.package_renamed",
                    "changes",
                    path,
                    f"The change renames the {label} from {was[0]} to {now[0]}. An installed app "
                    "cannot be updated under a different application id.",
                    line=now[1],
                    fix="Keep the original value unless the user asked for a rename.",
                    key=f"{path}:{label}",
                    approval="rename_package",
                )
    for path, old_info in before.manifests.items():
        new_info = after.manifests.get(path)
        if (
            new_info
            and old_info.package
            and new_info.package
            and old_info.package != new_info.package
        ):
            yield finding(
                Severity.ERROR,
                "change.package_renamed",
                "changes",
                path,
                f"The change renames the manifest package from {old_info.package} "
                f"to {new_info.package}.",
                line=new_info.root.line,
                fix="Keep the original package unless the user asked for a rename.",
                key=f"{path}:package",
                approval="rename_package",
            )


def _sdk(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    for path, old in before.gradle_scripts.items():
        new = after.gradle_scripts.get(path)
        if new is None:
            continue
        if old.min_sdk and new.min_sdk and new.min_sdk[0] > old.min_sdk[0]:
            yield finding(
                Severity.WARNING,
                "change.sdk_changed",
                "changes",
                path,
                f"minSdk is raised from {old.min_sdk[0]} to {new.min_sdk[0]}: devices on older "
                "Android versions can no longer install the app.",
                line=new.min_sdk[1],
                key=f"{path}:minSdk",
            )
        for label, was, now in (
            ("targetSdk", old.target_sdk, new.target_sdk),
            ("compileSdk", old.compile_sdk, new.compile_sdk),
        ):
            if was and now and now[0] < was[0]:
                yield finding(
                    Severity.WARNING,
                    "change.sdk_changed",
                    "changes",
                    path,
                    f"{label} is lowered from {was[0]} to {now[0]}.",
                    line=now[1],
                    key=f"{path}:{label}",
                )


# -- source: language, UI toolkit, tests --------------------------------------------------------


def _language(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    """A source file replaced by one of the same name in the other language (Java <-> Kotlin)."""
    old, new = before.files.texts, after.files.texts
    moved: dict[str, list[str]] = {"java -> kotlin": [], "kotlin -> java": []}
    for path in _changed(before, after, (".java", ".kt")):
        stem, _, ext = path.rpartition(".")
        other = stem + (".kt" if ext == "java" else ".java")
        if path in old and path not in new and other in new and other not in old:
            moved["java -> kotlin" if ext == "java" else "kotlin -> java"].append(path)
    for direction, paths in moved.items():
        if paths:
            names = ", ".join(p.rsplit("/", 1)[-1] for p in paths[:5])
            yield finding(
                Severity.ERROR,
                "change.language_converted",
                "changes",
                paths[0],
                f"The change converts {len(paths)} file(s) from {direction}: {names}"
                f"{'...' if len(paths) > 5 else ''}.",
                fix="Converting a project's language needs the user's approval.",
                key=direction,
                approval="convert_language",
            )


def _toolkit(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    """A file that built its screen from an XML layout and now uses Compose, or the reverse."""
    old, new = before.sources, after.sources
    for path in _changed(before, after, (".kt", ".java")):
        if path not in old or path not in new:
            continue
        was_xml, was_compose = _ui(old[path].masked)
        now_xml, now_compose = _ui(new[path].masked)
        for direction, hit in (
            ("XML layouts -> Compose", was_xml and not was_compose and now_compose and not now_xml),
            ("Compose -> XML layouts", was_compose and not was_xml and now_xml and not now_compose),
        ):
            if hit:
                yield finding(
                    Severity.ERROR,
                    "change.ui_toolkit_converted",
                    "changes",
                    path,
                    f"The change converts this screen from {direction}.",
                    fix="Converting the UI toolkit needs the user's approval.",
                    key=f"{path}:{direction}",
                    approval="convert_ui_toolkit",
                )


def _ui(masked: str) -> tuple[bool, bool]:
    return bool(_XML_UI.search(masked)), bool(_COMPOSE_UI.search(masked))


def _test_count(a: ProjectAnalysis, path: str) -> int:
    source = a.sources.get(path)
    return len(_TEST_ANNOTATION.findall(source.masked)) if source else 0


def _tests(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    """Fewer tests than before (deleted files or removed test methods): often a way of making a
    build pass. Judged on the total, so moving a test between files is not reported."""
    paths = [
        p
        for p in _changed(before, after, (".kt", ".java"))
        if before.is_test_source(p) or after.is_test_source(p)
    ]
    drops = Counter()
    for path in paths:
        delta = _test_count(after, path) - _test_count(before, path)
        if delta:
            drops[path] = delta
    if sum(drops.values()) >= 0:
        return
    for path, delta in sorted(drops.items()):
        if delta < 0:
            yield finding(
                Severity.WARNING,
                "change.tests_removed",
                "changes",
                path,
                f"The change removes {-delta} test(s) from this file"
                f"{' (the file is deleted)' if path not in after.sources else ''}.",
                fix="Fix a failing test instead of deleting it, unless the user asked for this.",
                key=path,
            )
