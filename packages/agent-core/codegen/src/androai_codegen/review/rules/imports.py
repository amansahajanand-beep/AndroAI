"""Missing and unresolved imports, duplicate classes, unresolved class literals."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..catalog import (
    CALL_IMPORTS,
    JAVA_LANG_NAMES,
    KOTLIN_DEFAULT_NAMES,
    MODIFIER_EXTENSIONS,
    TYPE_IMPORTS,
    ImportPattern,
    type_candidates,
)
from ..models import Finding, Severity, finding
from ..resources import CODE_REF
from ..source import SourceFile

_DELEGATE = re.compile(
    r"\b(val|var)[ \t]+\w+(?:[ \t]*:[^=\n]+?)?[ \t]+by[ \t]+"
    r"(?:remember|rememberSaveable|mutableStateOf|derivedStateOf"
    r"|[\w.]+\.collectAsState(?:WithLifecycle)?|[\w.]+\.observeAsState)\b"
)
_UNIT = re.compile(r"(?<=[\w)])\.(dp|sp)\b(?!\s*\()")
_ICON = re.compile(
    r"\bIcons\.(AutoMirrored\.)?(Default|Filled|Outlined|Rounded|Sharp|TwoTone)\.([A-Za-z_]\w*)"
)
_ICON_STYLE = {
    "Default": "filled",
    "Filled": "filled",
    "Outlined": "outlined",
    "Rounded": "rounded",
    "Sharp": "sharp",
    "TwoTone": "twotone",
}
_GENERATED_NAMES = {"R", "BuildConfig", "BR", "DataBindingComponent"}
_GENERATED_SUFFIXES = ("Binding", "Directions", "Args", "_Impl", "_Factory", "_MembersInjector")
_GENERATED_PREFIXES = ("Dagger", "Hilt_")


class _Imports:
    """What a file imports, with the lookups the rules need."""

    def __init__(self, source: SourceFile) -> None:
        self.explicit: dict[str, str] = {}  # simple (or alias) name -> fqn
        self.wildcards: set[str] = set()
        for imp in source.imports:
            if imp.static:
                continue
            if imp.wildcard:
                self.wildcards.add(imp.fqn)
            elif imp.simple_name:
                self.explicit[imp.simple_name] = imp.fqn

    def provides(self, candidates: tuple[str, ...]) -> bool:
        """True if an explicit import names one of the candidates or a wildcard covers it."""
        for candidate in candidates:
            if candidate in self.explicit.values():
                return True
            if candidate.rsplit(".", 1)[0] in self.wildcards:
                return True
        return False


def _is_compose(source: SourceFile) -> bool:
    return "androidx.compose" in source.masked or "@Composable" in source.code


def _suggest(candidates: tuple[str, ...]) -> str:
    first = f"Add `import {candidates[0]}`."
    if len(candidates) > 1:
        return first + " Other possibilities: " + ", ".join(candidates[1:]) + "."
    return first


def _declared_names(source: SourceFile) -> set[str]:
    names = {t.name for t in source.types}
    names.update(f.name for f in source.functions)
    names.update(source.top_level_values)
    return names


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    yield from _duplicate_classes(a)
    for path, source in a.sources.items():
        imports = _Imports(source)
        yield from _import_hygiene(a, path, source)
        yield from _missing_types(a, path, source, imports)
        yield from _unresolved_class_literals(a, path, source, imports)
        yield from _missing_r(a, path, source, imports)
        if source.language == "kotlin":
            yield from _missing_calls(a, path, source, imports)
            yield from _missing_delegates(path, source, imports)
            yield from _missing_units(path, source, imports)
            yield from _missing_icons(path, source, imports)


# --- types ----------------------------------------------------------------------------------


def _missing_types(
    a: ProjectAnalysis, path: str, source: SourceFile, imports: _Imports
) -> Iterator[Finding]:
    declared = _declared_names(source)
    same_package = a.symbols.top_names.get(source.package, set())
    defaults = KOTLIN_DEFAULT_NAMES if source.language == "kotlin" else JAVA_LANG_NAMES
    for name, offset in source.used_names.items():
        if name in declared or name in imports.explicit or name in same_package or name in defaults:
            continue
        project = tuple(
            f for f in a.symbols.cap_names.get(name, ()) if f.rsplit(".", 1)[0] != source.package
        )
        library = type_candidates(name, source.language)
        candidates = tuple(dict.fromkeys((*project, *library)))
        if not candidates or imports.provides(candidates):
            continue
        yield finding(
            Severity.ERROR,
            "import.missing",
            "imports",
            path,
            f"'{name}' is used but not imported or declared in this package.",
            line=source.line(offset),
            column=source.column(offset),
            fix=_suggest(candidates),
            key=name,
        )


def _unresolved_class_literals(
    a: ProjectAnalysis, path: str, source: SourceFile, imports: _Imports
) -> Iterator[Finding]:
    """``Foo::class`` where Foo is declared nowhere, imported nowhere and not a known library."""
    known_packages = a.symbols.packages
    unknown_wildcard = any(
        w not in known_packages and w not in _library_packages() for w in imports.wildcards
    )
    if unknown_wildcard:
        return  # a wildcard import of something we cannot see might provide it
    declared = _declared_names(source)
    same_package = a.symbols.top_names.get(source.package, set())
    defaults = KOTLIN_DEFAULT_NAMES if source.language == "kotlin" else JAVA_LANG_NAMES
    seen: set[str] = set()
    for name, offset in source.class_literals:
        if len(name) <= 2 or name.isupper() or name in seen:
            continue
        seen.add(name)
        if name in declared or name in imports.explicit or name in same_package or name in defaults:
            continue
        if a.symbols.cap_names.get(name) or name in TYPE_IMPORTS:
            continue  # reported by import.missing
        yield finding(
            Severity.ERROR,
            "reference.unresolved_class",
            "imports",
            path,
            f"Unresolved reference '{name}': it is not declared in this project and not imported.",
            line=source.line(offset),
            column=source.column(offset),
            fix=f"Create '{name}', or import it from the library that provides it.",
            key=name,
        )


_LIB_PACKAGES: frozenset[str] | None = None


def _library_packages() -> frozenset[str]:
    global _LIB_PACKAGES
    if _LIB_PACKAGES is None:
        _LIB_PACKAGES = frozenset(c.rsplit(".", 1)[0] for fq in TYPE_IMPORTS.values() for c in fq)
    return _LIB_PACKAGES


def _missing_r(
    a: ProjectAnalysis, path: str, source: SourceFile, imports: _Imports
) -> Iterator[Finding]:
    if "R" in imports.explicit or not CODE_REF.search(source.code):
        return
    namespace = a.namespace_for(path)
    if not namespace or source.package == namespace or namespace in imports.wildcards:
        return
    offset = CODE_REF.search(source.code).start()  # type: ignore[union-attr]
    yield finding(
        Severity.ERROR,
        "import.missing_r",
        "imports",
        path,
        f"'R' is used but this file's package '{source.package or '(default)'}' is not the app "
        f"namespace '{namespace}', so it must be imported.",
        line=source.line(offset),
        fix=f"Add `import {namespace}.R`.",
        key="R",
    )


# --- calls and extension members -------------------------------------------------------------


def _missing_calls(
    a: ProjectAnalysis, path: str, source: SourceFile, imports: _Imports
) -> Iterator[Finding]:
    compose = _is_compose(source)
    declared_functions = {f.name for f in source.functions}
    for pattern in (*CALL_IMPORTS, *MODIFIER_EXTENSIONS):
        yield from _one_pattern(a, path, source, imports, pattern, compose, declared_functions)


def _one_pattern(
    a: ProjectAnalysis,
    path: str,
    source: SourceFile,
    imports: _Imports,
    pattern: ImportPattern,
    compose: bool,
    declared_functions: set[str],
) -> Iterator[Finding]:
    if pattern.compose_only and not compose:
        return
    if pattern.requires and not pattern.requires.search(source.code):
        return
    match = pattern.regex.search(source.code)
    if not match:
        return
    if pattern.label in declared_functions or pattern.label in a.symbols.fun_names:
        return  # the project defines its own function with this name
    if imports.provides(pattern.candidates):
        return
    yield finding(
        Severity.ERROR,
        "import.missing",
        "imports",
        path,
        f"'{pattern.label}' is used but its import is missing.",
        line=source.line(match.start()),
        column=source.column(match.start()),
        fix=_suggest(pattern.candidates),
        key=pattern.label,
    )


def _missing_delegates(path: str, source: SourceFile, imports: _Imports) -> Iterator[Finding]:
    if not _is_compose(source):
        return
    wanted: dict[str, int] = {}
    for match in _DELEGATE.finditer(source.code):
        wanted.setdefault("getValue", match.start())
        if match.group(1) == "var":
            wanted.setdefault("setValue", match.start())
    for name, offset in wanted.items():
        fqn = f"androidx.compose.runtime.{name}"
        if imports.provides((fqn,)):
            continue
        yield finding(
            Severity.ERROR,
            "import.missing",
            "imports",
            path,
            f"A 'by' delegate on Compose state needs the '{name}' operator import.",
            line=source.line(offset),
            fix=f"Add `import {fqn}`.",
            key=name,
        )


def _missing_units(path: str, source: SourceFile, imports: _Imports) -> Iterator[Finding]:
    if not _is_compose(source):
        return
    seen: set[str] = set()
    for match in _UNIT.finditer(source.code):
        unit = match.group(1)
        if unit in seen:
            continue
        seen.add(unit)
        fqn = f"androidx.compose.ui.unit.{unit}"
        if imports.provides((fqn,)):
            continue
        yield finding(
            Severity.ERROR,
            "import.missing",
            "imports",
            path,
            f"'.{unit}' is used but its extension is not imported.",
            line=source.line(match.start()),
            fix=f"Add `import {fqn}`.",
            key=unit,
        )


def _missing_icons(path: str, source: SourceFile, imports: _Imports) -> Iterator[Finding]:
    if not _is_compose(source):
        return
    seen: set[str] = set()
    for match in _ICON.finditer(source.code):
        mirrored, style, name = match.groups()
        base = "androidx.compose.material.icons." + ("automirrored." if mirrored else "")
        fqn = f"{base}{_ICON_STYLE[style]}.{name}"
        if fqn in seen:
            continue
        seen.add(fqn)
        if imports.provides((fqn,)):
            continue
        yield finding(
            Severity.ERROR,
            "import.missing",
            "imports",
            path,
            f"Icon '{name}' is used but not imported.",
            line=source.line(match.start()),
            fix=f"Add `import {fqn}`.",
            key=fqn,
        )


# --- hygiene --------------------------------------------------------------------------------


def _import_hygiene(a: ProjectAnalysis, path: str, source: SourceFile) -> Iterator[Finding]:
    seen: dict[str, str] = {}
    for imp in source.imports:
        if imp.static or imp.wildcard:
            continue
        name = imp.simple_name or ""
        if name in seen and seen[name] == imp.fqn:
            yield finding(
                Severity.WARNING,
                "import.duplicate",
                "imports",
                path,
                f"'{imp.fqn}' is imported more than once.",
                line=imp.line,
                fix="Remove the duplicate import.",
                key=imp.fqn,
            )
        elif name in seen:
            yield finding(
                Severity.ERROR,
                "import.conflicting",
                "imports",
                path,
                f"Two imports provide the simple name '{name}': {seen[name]} and {imp.fqn}.",
                line=imp.line,
                fix="Remove one, or give one an alias with 'as'.",
                key=name,
            )
        seen.setdefault(name, imp.fqn)
        yield from _unresolved_project_import(a, path, imp)


def _is_generated(fqn: str) -> bool:
    package, _, last = fqn.rpartition(".")
    return (
        last in _GENERATED_NAMES
        or last.endswith(_GENERATED_SUFFIXES)
        or last.startswith(_GENERATED_PREFIXES)
        or package.endswith(".databinding")
    )


def _unresolved_project_import(a: ProjectAnalysis, path: str, imp) -> Iterator[Finding]:
    if imp.static or imp.wildcard or _is_generated(imp.fqn):
        return
    symbols = a.symbols
    segments = imp.fqn.split(".")
    for end in range(len(segments) - 1, 0, -1):
        if symbols.has_type(".".join(segments[:end])):
            return  # a member of a project type (object constant, enum entry, ...)
    package = ".".join(segments[:-1])
    in_project_namespace = any(
        package == ns or package.startswith(ns + ".") for ns in a.all_namespaces
    )
    if package in symbols.packages:
        if segments[-1] in symbols.top_names.get(package, set()):
            return
    elif not in_project_namespace:
        return  # a library, or a package we know nothing about
    yield finding(
        Severity.ERROR,
        "import.unresolved_project",
        "imports",
        path,
        f"Import '{imp.fqn}' does not match any declaration in this project.",
        line=imp.line,
        fix="Create the missing class, fix the package or name, or remove the import.",
        key=imp.fqn,
    )


# --- duplicate classes ----------------------------------------------------------------------


def _duplicate_classes(a: ProjectAnalysis) -> Iterator[Finding]:
    groups: dict[tuple[str | None, str, str], list[tuple[str, int]]] = defaultdict(list)
    for path, source in a.sources.items():
        for decl in source.types:
            if decl.top_level and not decl.private:
                key = (a.module_of(path), a.source_set(path), decl.fqn)
                groups[key].append((path, decl.line))
    for (_module, _source_set, fqn), where in groups.items():
        if len(where) < 2:
            continue
        files = sorted(where)
        for path, line in files:  # every involved file: the new one may sort first
            others = ", ".join(p for p, _ in files if p != path)
            yield finding(
                Severity.ERROR,
                "class.duplicate",
                "imports",
                path,
                f"'{fqn}' is declared more than once (redeclaration); also in {others}.",
                line=line,
                fix="Rename or remove one of the declarations.",
                key=fqn,
            )
