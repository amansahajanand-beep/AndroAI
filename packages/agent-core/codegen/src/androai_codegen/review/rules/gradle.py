"""Gradle build rules: project and catalog references, missing dependencies, Compose setup.

As with the manifest rules, a claim of the form "X is not declared" is only made when the build
is readable enough that X would have been seen (``ProjectAnalysis.dependency_groups_for``).
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Iterator

from ..analysis import _BUILD_SOURCE, ProjectAnalysis
from ..catalog import LIB_DEPENDENCIES
from ..gradle import sdk_label
from ..models import Finding, Severity, finding

_CATALOG_METHODS = frozenset(
    "get asProvider findLibrary findPlugin findVersion findBundle getLibraries".split()
)
COMPOSE_PLUGIN = "org.jetbrains.kotlin.plugin.compose"


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    yield from _unknown_projects(a)
    yield from _catalog_aliases(a)
    yield from _missing_dependencies(a)
    yield from _compose_plugin(a)
    yield from _sdk_order(a)
    yield from _duplicate_dependencies(a)
    yield from _unplanned_dependencies(a)


def _has_prefix(fqn: str, prefix: str) -> bool:
    return fqn == prefix or fqn.startswith(prefix + ".")


def _unknown_projects(a: ProjectAnalysis) -> Iterator[Finding]:
    """``project(":x")`` / ``projects.x`` naming a project that ``settings`` does not include.

    Only when the build's project list is readable (see ``ProjectAnalysis.projects_known``).
    """
    if not a.projects_known:
        return
    by_style = {
        True: [k for k in a.project_dirs if k.startswith("projects.")],
        False: [k for k in a.project_dirs if k.startswith(":") and k != ":"],
    }
    for dep in a.project_dependencies:
        if dep.target is not None:
            continue
        close = difflib.get_close_matches(
            dep.reference, by_style[dep.reference.startswith("projects.")], n=3, cutoff=0.6
        )
        hint = f"Did you mean {', '.join(close)}? " if close else ""
        yield finding(
            Severity.ERROR,
            "gradle.unknown_project",
            "dependencies",
            dep.path,
            f"{dep.config} depends on {dep.reference}, but settings does not include that project.",
            line=dep.line,
            fix=hint + "Otherwise add the project to settings (include(...)).",
            key=dep.reference,
        )


# -- version catalog references -----------------------------------------------------------------


def _catalog_aliases(a: ProjectAnalysis) -> Iterator[Finding]:
    """``libs.some.alias`` in a build script that ``libs.versions.toml`` does not define."""
    catalog = a.catalog
    if catalog is None or catalog.error or a.custom_catalogs:
        return
    if sum(1 for p in a.files.texts if p.endswith("libs.versions.toml")) > 1:
        return  # several catalogs (separate builds): which one a script means is not knowable
    tables = {
        "versions": set(catalog.versions),
        "plugins": set(catalog.plugins),
        "bundles": set(catalog.bundles),
    }
    libraries = set(catalog.libraries)
    for path, script in a.gradle_scripts.items():
        for accessor, line in script.catalog_refs:
            parts = accessor.split(".")
            if parts[0] in _CATALOG_METHODS:
                continue
            head = parts[0] if parts[0] in tables else None
            names = tables[head] if head else libraries
            candidate = ".".join(parts[1:] if head else parts)
            if not candidate or any(
                k == candidate or k.startswith(candidate + ".") or candidate.startswith(k + ".")
                for k in names
            ):
                continue
            close = difflib.get_close_matches(candidate, sorted(names), n=3, cutoff=0.6)
            hint = f"Did you mean libs.{head + '.' if head else ''}{close[0]}? " if close else ""
            yield finding(
                Severity.ERROR,
                "gradle.unknown_catalog_alias",
                "dependencies",
                path,
                f"libs.{accessor} is not defined in the version catalog ({a.catalog_path}).",
                line=line,
                fix=hint + "Otherwise add the entry to libs.versions.toml.",
                key=f"libs.{accessor}",
            )


# -- dependencies used but not declared ---------------------------------------------------------


def _missing_dependencies(a: ProjectAnalysis) -> Iterator[Finding]:
    """An import from a library whose Maven group no dependency of the module provides.

    Only well-known libraries that do not arrive transitively (see ``LIB_DEPENDENCIES``), and only
    when the module's whole dependency list is readable.
    """
    reported: set[tuple[str | None, str]] = set()
    for path, source in a.sources.items():
        if _BUILD_SOURCE.search(path):
            continue
        module = a.module_of(path)
        groups = a.dependency_groups_for(module)
        if groups is None:
            continue
        for imp in source.imports:
            if imp.static:
                continue
            for prefix, accepted, label in LIB_DEPENDENCIES:
                if not _has_prefix(imp.fqn, prefix) or (module, label) in reported:
                    continue
                if any(g == acc or g.startswith(acc + ".") for g in groups for acc in accepted):
                    continue
                reported.add((module, label))
                yield finding(
                    Severity.ERROR,
                    "gradle.dependency_missing",
                    "dependencies",
                    path,
                    f"{label} is imported ({imp.fqn}) but no dependency of this module provides "
                    f"{' or '.join(accepted)}; the build fails with an unresolved reference.",
                    line=imp.line,
                    fix=f"Add a {label} dependency to the module's build script.",
                    key=label,
                )


# -- Compose ------------------------------------------------------------------------------------


def _compose_plugin(a: ProjectAnalysis) -> Iterator[Finding]:
    """Kotlin 2.0+ with ``buildFeatures.compose`` but without the Compose compiler plugin."""
    version = a.kotlin_version
    if version is None or version < (2, 0, 0):
        return
    if any(
        "allprojects" in s.masked or "subprojects" in s.masked for s in a.gradle_scripts.values()
    ):
        return  # a shared block may apply the plugin
    for module in sorted(a.modules):
        for script in a.module_scripts(module):
            if script.compose_enabled is None or a.opaque_plugins(script):
                continue
            if COMPOSE_PLUGIN in script.plugin_ids(a.catalog):
                continue
            yield finding(
                Severity.ERROR,
                "gradle.compose_plugin_missing",
                "dependencies",
                script.path,
                "Compose is enabled (buildFeatures { compose = true }) and the project uses "
                f"Kotlin {'.'.join(map(str, version))}, which needs the Compose compiler Gradle "
                f"plugin ({COMPOSE_PLUGIN}); without it the build fails.",
                line=script.compose_enabled,
                fix=f'Apply the plugin in this module: id("{COMPOSE_PLUGIN}") '
                "(same version as Kotlin).",
                key=module or ".",
            )


# -- SDK levels ---------------------------------------------------------------------------------


def _sdk_order(a: ProjectAnalysis) -> Iterator[Finding]:
    for path, script in a.gradle_scripts.items():
        compile_sdk, min_sdk, target_sdk = script.compile_sdk, script.min_sdk, script.target_sdk
        if min_sdk and target_sdk and min_sdk[0] > target_sdk[0]:
            yield finding(
                Severity.WARNING,
                "gradle.sdk_order",
                "dependencies",
                path,
                f"minSdk ({min_sdk[0]}) is higher than targetSdk ({target_sdk[0]}).",
                line=min_sdk[1],
                fix="Lower minSdk or raise targetSdk so that minSdk <= targetSdk.",
                key="min>target",
            )
        if compile_sdk and target_sdk and target_sdk[0] > compile_sdk[0]:
            compile_label = sdk_label(compile_sdk[0], script.compile_sdk_minor)
            yield finding(
                Severity.WARNING,
                "gradle.sdk_order",
                "dependencies",
                path,
                f"targetSdk ({target_sdk[0]}) is higher than compileSdk ({compile_label}).",
                line=target_sdk[1],
                fix="Raise compileSdk to at least targetSdk.",
                key="target>compile",
            )


# -- duplicate and conflicting declarations -----------------------------------------------------


def _duplicate_dependencies(a: ProjectAnalysis) -> Iterator[Finding]:
    by_script: dict[str, list] = defaultdict(list)
    for resolved in a.dependencies:
        if resolved.coordinate and not resolved.dep.project:
            by_script[resolved.dep.path].append(resolved)
    for path, items in by_script.items():
        seen: dict[tuple[str, str], list] = defaultdict(list)
        for resolved in items:
            seen[(resolved.dep.config, resolved.coordinate or "")].append(resolved)
        for (config, coordinate), same in seen.items():
            if len(same) < 2:
                continue
            versions = {r.version for r in same if r.version}
            if len(versions) > 1:
                yield finding(
                    Severity.WARNING,
                    "gradle.conflicting_versions",
                    "dependencies",
                    path,
                    f"{coordinate} is declared in {config} with different versions "
                    f"({', '.join(sorted(versions))}).",
                    line=same[1].dep.line,
                    fix="Keep a single declaration with one version.",
                    key=coordinate,
                )
            else:
                yield finding(
                    Severity.WARNING,
                    "gradle.duplicate_dependency",
                    "dependencies",
                    path,
                    f"{coordinate} is declared more than once in {config}.",
                    line=same[1].dep.line,
                    fix="Delete the duplicate declaration.",
                    key=f"{config}:{coordinate}",
                )


# -- the plan -----------------------------------------------------------------------------------


def _allowed(plan: tuple[str, ...], group: str, coordinate: str) -> bool:
    return any(
        entry in (coordinate, group) or (entry.endswith(":*") and entry[:-2] == group)
        for entry in plan
    )


def _unplanned_dependencies(a: ProjectAnalysis) -> Iterator[Finding]:
    """With ``ReviewConfig.permitted_dependencies`` set, any other library is a deviation from
    the approved plan and needs approval."""
    plan = a.config.permitted_dependencies
    if plan is None:
        return
    for resolved in a.dependencies:
        if not resolved.group or not resolved.coordinate or _BUILD_SOURCE.search(resolved.dep.path):
            continue
        if _allowed(plan, resolved.group, resolved.coordinate):
            continue
        yield finding(
            Severity.ERROR,
            "gradle.unplanned_dependency",
            "dependencies",
            resolved.dep.path,
            f"{resolved.coordinate} is not in the list of dependencies this task may use.",
            line=resolved.dep.line,
            fix="Use a permitted library, or ask for approval to add this one.",
            key=resolved.coordinate,
            approval="other_high_impact",
        )
