"""Manifest rules: components that do not exist or are not declared, ``exported``, permissions.

Every rule here is silent when it cannot be sure: a class outside the app's own packages, a
placeholder name, a component marked ``tools:node="remove"``, a build whose dependencies cannot
be read. A manifest finding that is wrong would block a correct patch, so none is guessed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

from ..analysis import _BUILD_SOURCE, COMPONENT_TAGS, ManifestInfo, ProjectAnalysis, _resolve_class
from ..catalog import INTERNET_PROVIDING_GROUPS, PERMISSION_USES, PermissionUse
from ..models import Finding, Severity, finding
from ..source import SourceFile
from ..xmlparse import XmlNode

_INTENT_CALL_TAIL = re.compile(r"\bIntent\s*\([^;{}]*$")
_EXPORT_REQUIRED = ("activity", "activity-alias", "service", "receiver")


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    if not a.manifests:
        return
    yield from _declared_classes(a)
    yield from _undeclared_components(a)
    yield from _exported(a)
    yield from _duplicates(a)
    yield from _permissions(a)
    yield from _launcher(a)


# -- helpers -----------------------------------------------------------------------------------


def _fqn(a: ProjectAnalysis, info: ManifestInfo, name: str | None) -> str | None:
    """The class a manifest name refers to, or ``None`` if it cannot be known statically."""
    if not name or "${" in name:
        return None
    package = a.manifest_package(info)
    if ("." not in name or name.startswith(".")) and not package:
        return None
    return _resolve_class(name, package).replace("$", ".")


def _owned(a: ProjectAnalysis, info: ManifestInfo, name: str, fqn: str) -> bool:
    """The name is in the app's own code (relative, or under one of its packages), so the class
    must be in the project. A fully qualified library class is not ours to check."""
    if name.startswith(".") or "." not in name:
        return True
    packages = {*a.all_namespaces, *(p for p in (info.package,) if p)}
    return any(fqn == p or fqn.startswith(p + ".") for p in packages)


def _nodes(info: ManifestInfo) -> dict[tuple[int, str], XmlNode]:
    found: dict[tuple[int, str], XmlNode] = {}
    if info.application is not None:
        found[(info.application.line, "application")] = info.application
        for node in info.application.children:
            if node.tag in COMPONENT_TAGS:
                found[(node.line, node.tag)] = node
    return found


def _removed(node: XmlNode | None) -> bool:
    """``tools:node="remove|removeAll|replace"``: the element is edited out or replaced at merge
    time, so what it says is not what the app gets."""
    return node is not None and node.attrs.get("tools:node", "") in (
        "remove",
        "removeAll",
        "replace",
    )


def _declared_fqns(a: ProjectAnalysis) -> set[str]:
    return {
        fqn
        for info in a.manifests.values()
        for c in info.components
        if c.kind != "activity-alias" and (fqn := _fqn(a, info, c.name))
    }


def _has_prefix(fqn: str, prefix: str) -> bool:
    return fqn == prefix or fqn.startswith(prefix + ".")


# -- declared classes that do not exist --------------------------------------------------------


def _declared_classes(a: ProjectAnalysis) -> Iterator[Finding]:
    """``<activity android:name=".Gone">`` where no class ``Gone`` exists in the project."""
    if not a.sources:
        return  # nothing to compare against
    declared = _declared_fqns(a)
    for path, info in a.manifests.items():
        nodes = _nodes(info)
        for c in info.components:
            if _removed(nodes.get((c.line, c.kind))):
                continue
            if c.kind == "activity-alias":
                name, role = c.target_activity, "targets"
            else:
                name, role = c.name, "declares"
            fqn = _fqn(a, info, name)
            if not fqn or not _owned(a, info, name or "", fqn):
                continue
            if a.symbols.has_type(fqn) or (c.kind == "activity-alias" and fqn in declared):
                continue
            yield finding(
                Severity.ERROR,
                "manifest.class_missing",
                "manifest",
                path,
                f"<{c.kind}> {role} {name}, but the project has no class {fqn}.",
                line=c.line,
                fix=f"Create {fqn.rsplit('.', 1)[-1]}, or correct or remove the manifest entry.",
                key=fqn,
            )


# -- classes started through an Intent but never declared --------------------------------------


def _resolve_component(a: ProjectAnalysis, source: SourceFile, name: str) -> str | None:
    components = a.component_classes
    for imp in source.imports:
        if (
            not imp.static
            and not imp.wildcard
            and imp.simple_name == name
            and imp.fqn in components
        ):
            return imp.fqn
    local = f"{source.package}.{name}" if source.package else name
    if local in components:
        return local
    for imp in source.imports:
        if imp.wildcard and f"{imp.fqn}.{name}" in components:
            return f"{imp.fqn}.{name}"
    matches = [fqn for fqn in components if fqn.rsplit(".", 1)[-1] == name]
    return matches[0] if len(matches) == 1 else None


def _undeclared_components(a: ProjectAnalysis) -> Iterator[Finding]:
    """``Intent(this, Foo::class.java)`` where ``Foo`` is an Activity/Service/Receiver that no
    manifest declares: the call fails at run time (``ActivityNotFoundException``)."""
    if any("${" in c.name for info in a.manifests.values() for c in info.components):
        return  # placeholder names: we cannot tell which classes they stand for
    declared = _declared_fqns(a)
    reported: set[tuple[str, str]] = set()
    for path, source in a.sources.items():
        if _BUILD_SOURCE.search(path) or a.is_test_source(path):
            continue
        for name, offset in source.class_literals:
            fqn = _resolve_component(a, source, name)
            if fqn is None or fqn in declared or (path, fqn) in reported:
                continue
            if not _INTENT_CALL_TAIL.search(source.masked[max(0, offset - 200) : offset]):
                continue
            reported.add((path, fqn))
            kind = a.component_classes[fqn][0]
            yield finding(
                Severity.ERROR,
                "manifest.component_undeclared",
                "manifest",
                path,
                f"{name} is {'an' if kind[0] in 'aeiou' else 'a'} {kind} started through an "
                "Intent, but no AndroidManifest.xml declares it, so the call fails at run time.",
                line=source.line(offset),
                column=source.column(offset),
                fix=f'Add <{kind} android:name="{fqn}" android:exported="false" /> inside '
                "<application> in the manifest.",
                key=fqn,
            )


# -- android:exported ---------------------------------------------------------------------------


def _target_sdk(a: ProjectAnalysis, manifest_path: str) -> int | None:
    module = a.module_of(manifest_path)
    if module is not None:
        for script in a.module_scripts(module):
            declared = a.target_sdk_of(script)
            if declared:
                return declared[0]
    return a.target.target_sdk


def _exported(a: ProjectAnalysis) -> Iterator[Finding]:
    """Android 12 (API 31): a component with an intent filter must say whether it is exported,
    otherwise the manifest merger fails the build."""
    for path, info in a.manifests.items():
        target = _target_sdk(a, path)
        if target is None or target < 31:
            continue
        nodes = _nodes(info)
        for c in info.components:
            if (
                c.kind in _EXPORT_REQUIRED
                and c.has_intent_filter
                and c.exported is None
                and not _removed(nodes.get((c.line, c.kind)))
            ):
                yield finding(
                    Severity.ERROR,
                    "manifest.exported_missing",
                    "manifest",
                    path,
                    f"<{c.kind}> {c.name} has an <intent-filter> but no android:exported, which "
                    f"is required when targeting Android 12 or later (targetSdk {target}); the "
                    "build fails in the manifest merger.",
                    line=c.line,
                    fix='Add android:exported="true" (launcher, deep links) or "false" (internal).',
                    key=f"{c.kind}:{c.name}",
                )


# -- the same component twice -------------------------------------------------------------------


def _duplicates(a: ProjectAnalysis) -> Iterator[Finding]:
    for path, info in a.manifests.items():
        seen: Counter[tuple[str, str]] = Counter()
        for c in info.components:
            if c.kind == "application":
                continue
            ident = (c.kind, _fqn(a, info, c.name) or c.name)
            seen[ident] += 1
            if seen[ident] == 2:
                yield finding(
                    Severity.ERROR,
                    "manifest.duplicate_component",
                    "manifest",
                    path,
                    f"<{c.kind}> {c.name} is declared more than once in this manifest; "
                    "the manifest merger rejects duplicates.",
                    line=c.line,
                    fix="Delete the duplicate element.",
                    key=f"{c.kind}:{ident[1]}",
                )


# -- permissions --------------------------------------------------------------------------------


def _declared_permissions(a: ProjectAnalysis) -> set[str]:
    found: set[str] = set()
    for info in a.manifests.values():
        for node in info.root.iter():
            if node.tag in ("uses-permission", "uses-permission-sdk-23") and not _removed(node):
                found.add(node.attrs.get("android:name", ""))
    return found


def _project_groups(a: ProjectAnalysis) -> frozenset[str] | None:
    """Every Maven group any module can see, or ``None`` if some module is not readable."""
    groups: set[str] = set()
    for module in a.modules:
        module_groups = a.dependency_groups_for(module)
        if module_groups is None:
            return None
        groups |= module_groups
    return frozenset(groups)


def _first_use(a: ProjectAnalysis, use: PermissionUse) -> tuple[str, int] | None:
    for path, source in a.sources.items():
        if _BUILD_SOURCE.search(path) or a.is_test_source(path):
            continue
        imported = [i.fqn for i in source.imports if not i.static]
        for imp in imported:
            if any(_has_prefix(imp, prefix) for prefix in use.imports):
                return path, next(i.line for i in source.imports if i.fqn == imp)
        for imp_name, call in use.import_and_call:
            if any(
                _has_prefix(imp, imp_name) or imp == imp_name.rsplit(".", 1)[0] for imp in imported
            ):
                found = re.search(call, source.masked)
                if found:
                    return path, source.line(found.start())
    return None


def _permissions(a: ProjectAnalysis) -> Iterator[Finding]:
    """Code that needs a permission the app never declares (``SecurityException`` at run time).

    Only when every dependency can be read: a library's own manifest may declare the permission
    on the app's behalf, and we cannot see that for an unreadable build.
    """
    groups = _project_groups(a)
    if groups is None:
        return
    declared = _declared_permissions(a)
    for use in PERMISSION_USES:
        if declared.intersection(use.needs_any_of):
            continue
        if use.needs_any_of[0].endswith("INTERNET") and any(
            g.startswith(INTERNET_PROVIDING_GROUPS) for g in groups
        ):
            continue
        spot = _first_use(a, use)
        if spot is None:
            continue
        permission = use.needs_any_of[0]
        yield finding(
            Severity.ERROR,
            "manifest.permission_missing",
            "manifest",
            spot[0],
            f"The code uses {use.label} but no manifest declares {permission.rsplit('.', 1)[-1]}"
            f"{' (or a location alternative)' if len(use.needs_any_of) > 1 else ''}; "
            "it fails with a SecurityException at run time.",
            line=spot[1],
            fix=f'Add <uses-permission android:name="{permission}" /> to AndroidManifest.xml'
            + (" and request it at run time." if "INTERNET" not in permission else "."),
            key=permission,
        )


# -- launcher -----------------------------------------------------------------------------------


def _launcher(a: ProjectAnalysis) -> Iterator[Finding]:
    """An app module whose activities include no entry point (no ``action.MAIN`` at all)."""
    for module in sorted(a.modules):
        if not a.is_application(module):
            continue
        manifests = [info for p, info in a.manifests.items() if a.module_of(p) == module]
        activities = [c for info in manifests for c in info.components if c.kind == "activity"]
        if not activities:
            continue
        has_main = any(
            action.attrs.get("android:name") == "android.intent.action.MAIN"
            for info in manifests
            for action in info.root.find_all("action")
        )
        if has_main:
            continue
        main = next((i for i in manifests if i.path.endswith("src/main/AndroidManifest.xml")), None)
        target = main or manifests[0]
        yield finding(
            Severity.WARNING,
            "manifest.no_launcher",
            "manifest",
            target.path,
            "No activity in this app module declares the MAIN action, so the app has no entry "
            "point and cannot be started from the launcher.",
            line=target.application.line if target.application is not None else 1,
            fix="Give one activity <intent-filter> with action MAIN and category LAUNCHER (and "
            'android:exported="true").',
            key=module or ".",
        )
