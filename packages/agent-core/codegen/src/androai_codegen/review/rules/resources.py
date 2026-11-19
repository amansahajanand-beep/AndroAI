"""Resource references (``R.x.y``, ``@x/y``), duplicates and invalid names."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..catalog import LIBRARY_RESOURCE_NAMES
from ..models import Finding, Severity, finding
from ..resources import CODE_REF, KNOWN_TYPES, STRICT_TYPES, VALUE_TAGS

_VALUES_DIR = re.compile(r"/res/values[^/]*/")
_FILE_NAME = re.compile(r"^[a-z0-9_.]+$")
_VALUE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_SKIPPED_TYPES = frozenset({"styleable", "attr"})


def _similar(a: ProjectAnalysis, kind: str, name: str) -> str:
    names = [n for (k, n) in a.resources.defs if k == kind]
    close = difflib.get_close_matches(name.replace(".", "_"), names, n=3, cutoff=0.6)
    return f" Did you mean: {', '.join(close)}?" if close else ""


def _is_resource_project(a: ProjectAnalysis) -> bool:
    """False for a partial snapshot with no resources at all (nothing to check against)."""
    return (
        bool(a.resources.defs)
        or any("/res/" in f"/{p}" for p in a.files.paths)
        or bool(a.manifests)
    )


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    yield from _duplicates(a)
    yield from _names(a)
    if not _is_resource_project(a):
        return
    unreliable = _unreliable_types(a)
    yield from _code_references(a, unreliable)
    yield from _xml_references(a, unreliable)


def _unreliable_types(a: ProjectAnalysis) -> frozenset[str]:
    """Resource types whose definitions may hide in a resource file that failed to parse.

    Reporting "unresolved" for those would blame every reference for what is really one
    malformed file (already reported as ``xml.malformed``).
    """
    types: set[str] = set()
    for path, doc in a.xml_docs.items():
        if not doc.error or "/res/" not in f"/{path}":
            continue
        types.add("id")
        if _VALUES_DIR.search(f"/{path}"):
            types.update(VALUE_TAGS.values())
    return frozenset(types)


def _provided_by_dependency(a: ProjectAnalysis, kind: str, name: str) -> bool:
    groups = LIBRARY_RESOURCE_NAMES.get((kind, name.replace(".", "_")), ())
    return any(
        declared == group or declared.startswith(group + ".")
        for declared in a.dependency_groups
        for group in groups
    )


def _unresolved(a: ProjectAnalysis, kind: str, name: str, unreliable: frozenset[str]) -> bool:
    if kind in _SKIPPED_TYPES or kind not in KNOWN_TYPES or kind in unreliable:
        return False
    if a.resources.has(kind, name) or a.resources.is_library_resource(kind, name):
        return False
    if _provided_by_dependency(a, kind, name):
        return False
    return kind in STRICT_TYPES or kind == "style"


def _code_references(a: ProjectAnalysis, unreliable: frozenset[str]) -> Iterator[Finding]:
    for path, source in a.sources.items():
        if any(imp.fqn == "android.R" and not imp.wildcard for imp in source.imports):
            continue  # R here is the framework's, not the app's
        seen: set[tuple[str, str]] = set()
        for match in CODE_REF.finditer(source.code):
            kind, name = match.groups()
            if (kind, name) in seen or not _unresolved(a, kind, name, unreliable):
                continue
            seen.add((kind, name))
            yield finding(
                Severity.ERROR,
                "resource.unresolved",
                "resources",
                path,
                f"R.{kind}.{name} does not exist: no '{kind}' resource named '{name}' is defined.",
                line=source.line(match.start()),
                column=source.column(match.start()),
                fix=f"Define the '{kind}' resource '{name}' or correct the name."
                + _similar(a, kind, name),
                key=f"{kind}/{name}",
            )


def _xml_references(a: ProjectAnalysis, unreliable: frozenset[str]) -> Iterator[Finding]:
    for path in a.xml_docs:
        if "/res/" not in f"/{path}" and not path.endswith("AndroidManifest.xml"):
            continue
        seen: set[tuple[str, str]] = set()
        for ref in a.resources.xml_refs(path):
            if (ref.type, ref.name) in seen or not _unresolved(a, ref.type, ref.name, unreliable):
                continue
            seen.add((ref.type, ref.name))
            yield finding(
                Severity.ERROR,
                "resource.unresolved",
                "resources",
                path,
                f"@{ref.type}/{ref.name} does not exist: no '{ref.type}' resource named "
                f"'{ref.name}' is defined.",
                line=ref.line,
                fix=f"Define the '{ref.type}' resource '{ref.name}' or correct the name."
                + _similar(a, ref.type, ref.name),
                key=f"{ref.type}/{ref.name}",
            )


def _duplicates(a: ProjectAnalysis) -> Iterator[Finding]:
    for kind, name, defs in a.resources.duplicates():
        ordered = sorted(defs, key=lambda d: (d.path, d.line))
        for definition in ordered:  # every involved file: the new one may sort first
            others = ", ".join(f"{d.path}:{d.line}" for d in ordered if d is not definition)
            yield finding(
                Severity.ERROR,
                "resource.duplicate",
                "resources",
                definition.path,
                f"Duplicate '{kind}' resource '{name}': also defined in {others}.",
                line=definition.line,
                fix="Remove one definition or rename it.",
                key=f"{kind}/{name}",
            )


def _names(a: ProjectAnalysis) -> Iterator[Finding]:
    for (kind, name), defs in a.resources.defs.items():
        for definition in defs:
            if definition.file_based:
                filename = definition.path.rsplit("/", 1)[-1]
                if not _FILE_NAME.match(filename):
                    yield finding(
                        Severity.ERROR,
                        "resource.invalid_name",
                        "resources",
                        definition.path,
                        f"Resource file name '{filename}' may only contain lowercase letters, "
                        "digits, '_' and '.'.",
                        line=1,
                        fix="Rename the file (for example to snake_case).",
                        key=f"{kind}/{filename}",
                    )
            elif kind != "id" and not _VALUE_NAME.match(name):
                yield finding(
                    Severity.ERROR,
                    "resource.invalid_name",
                    "resources",
                    definition.path,
                    f"'{name}' is not a valid resource name (letters, digits, '_' or '.', "
                    "not starting with a digit).",
                    line=definition.line,
                    fix="Rename the resource.",
                    key=f"{kind}/{name}",
                )
