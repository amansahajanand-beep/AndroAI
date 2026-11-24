"""Gradle build facts: modules, plugins, SDK levels, build features, dependencies, libraries.

Build scripts are **read, never run**. A value is reported when it is written as a literal, or
when it is exactly a version-catalog entry or a ``buildSrc`` constant (both are plain text in the
project). Anything computed (``rootProject.ext``, arithmetic, a convention plugin that sets it) is
an ``unknown`` fact with a reason, and the module's dependency list is marked unreadable when the
build applies plugins this package cannot see into.
"""

from __future__ import annotations

import re

from androai_codegen.review.gradle import GradleScript

from .catalog import COORDINATE_TECH, PLUGIN_TECH, is_test_config, longest_prefix
from .context import Run, module_label
from .text import clip

_PLUGIN_ID = re.compile(r"(?<![\w.])id[ \t]*\(?[ \t]*")
_APPLY_PLUGIN = re.compile(r"\bapply[ \t]+plugin[ \t]*:[ \t]*")
_KOTLIN_PLUGIN = re.compile(r"(?<![\w.])kotlin[ \t]*\([ \t]*")
# ``ksp { arg(...) }`` and ``kapt { ... }`` configure a processor; review's dependency scan
# counts them as dependency calls it could not read, which they are not.
_CONFIG_BLOCK = re.compile(r"(?<![\w.])(?:ksp|kapt)[ \t]*\{")
_APPLY_FROM = re.compile(r"(?<![\w.])apply[ \t]*(?:\([ \t]*)?from[ \t]*[:=]")
_FEATURE_ON = re.compile(
    r"\b(viewBinding|dataBinding|buildConfig|aidl|renderScript|shaders)\b[ \t]*(?:=[ \t]*)?true\b"
)
_FEATURE_BLOCK = re.compile(
    r"\b(viewBinding|dataBinding)\b[ \t]*\{[ \t\n]*enabled?[ \t]*=?[ \t]*true\b"
)
_SDK_WORDS = {
    "minSdk": re.compile(r"\bminSdk(?:Version)?\b"),
    "targetSdk": re.compile(r"\btargetSdk(?:Version)?\b"),
    "compileSdk": re.compile(r"\bcompileSdk(?:Version)?\b"),
}
_MODULE_TYPES = {
    "com.android.application": "android_application",
    "com.android.library": "android_library",
    "com.android.dynamic-feature": "android_dynamic_feature",
    "com.android.test": "android_test",
    "com.android.kotlin.multiplatform.library": "kotlin_multiplatform",
    "org.jetbrains.kotlin.multiplatform": "kotlin_multiplatform",
    "org.jetbrains.kotlin.jvm": "jvm_library",
    "java-library": "jvm_library",
    "java": "jvm_library",
}
_MODULE_TYPE_ORDER = tuple(_MODULE_TYPES)


def _string_after(script: GradleScript, offset: int) -> str | None:
    masked = script.masked
    while offset < len(masked) and masked[offset] in " \t":
        offset += 1
    literal = script.lexed.string_starting_at(offset)
    return script.lexed.string_value(literal) if literal and literal.terminated else None


def plugin_occurrences(script: GradleScript, run: Run) -> list[tuple[str, int]]:
    """``(plugin id, line)`` for every plugin the script applies by id, alias or ``kotlin(...)``."""
    found: list[tuple[str, int]] = []
    for pattern, prefix in (
        (_PLUGIN_ID, ""),
        (_APPLY_PLUGIN, ""),
        (_KOTLIN_PLUGIN, "org.jetbrains.kotlin."),
    ):
        for match in pattern.finditer(script.masked):
            value = _string_after(script, match.end())
            if value:
                line = script.line(match.start())
                tail = script.masked[match.end() : match.end() + 200].split("\n", 1)[0]
                if "apply false" in tail:
                    continue  # declared for sub-modules, not applied here
                found.append((prefix + value, line))
    catalog = run.a.catalog
    if catalog:
        for alias, line in script.plugin_aliases:
            plugin_id = catalog.plugins.get(alias)
            tail = script.masked.split("\n")[line - 1] if line else ""
            if plugin_id and "apply false" not in tail:
                found.append((plugin_id, line))
    return sorted(set(found), key=lambda item: (item[1], item[0]))


def unparsed_calls(script: GradleScript) -> int:
    """Dependency calls of ``script`` that could not be read (processor config blocks excluded)."""
    return max(0, script.unparsed_dependency_calls - len(_CONFIG_BLOCK.findall(script.masked)))


def extract_build(run: Run) -> None:
    a, store = run.a, run.store
    _version_catalog(run)
    _build_sources(run)
    for path in sorted(a.gradle_scripts):
        script = a.gradle_scripts[path]
        if path.endswith(".gradle"):
            store.limit(
                "groovy_dsl_partial",
                path,
                "Groovy build script read with patterns; dynamic Groovy code is not evaluated",
                affects_completeness=False,
            )
        if _APPLY_FROM.search(script.masked):
            store.limit(
                "applied_script_not_followed",
                path,
                "the script applies another script file, which is not followed",
            )
    for module in sorted(a.modules):
        if run.expired():
            return
        _module(run, module)
    _project_dependencies(run)
    _import_technologies(run)


def _version_catalog(run: Run) -> None:
    a = run.a
    path = a.catalog_path
    if path is None or a.catalog is None:
        return
    catalog = a.catalog
    if catalog.error:
        run.fact(
            "version_catalog",
            path,
            basis="gradle",
            status="unknown",
            reason="the version catalog is not valid TOML, so its aliases cannot be resolved",
            evidence=[run.path_evidence(path)],
        )
        run.store.limit(
            "malformed_build_file", path, "libs.versions.toml does not parse; aliases unresolved"
        )
        return
    run.fact(
        "version_catalog",
        path,
        basis="gradle",
        evidence=[run.path_evidence(path)],
        attrs={
            "libraries": len(catalog.libraries),
            "plugins": len(catalog.plugins),
            "versions": len(catalog.versions),
            "bundles": len(catalog.bundles),
        },
    )


def _build_sources(run: Run) -> None:
    seen: set[str] = set()
    for path in sorted(run.files.paths):
        match = re.match(r"((?:.*/)?(?:buildSrc|build-logic))/", path)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            run.fact(
                "build_source",
                match.group(1),
                basis="gradle",
                evidence=[run.path_evidence(path)],
                attrs={"directory": match.group(1)},
            )


def _module(run: Run, module: str) -> None:
    a, store = run.a, run.store
    label = module_label(module)
    scripts = a.module_scripts(module)
    tag = f"module:{label}"
    if not scripts:
        run.fact(
            "module",
            label,
            basis="gradle",
            evidence=[run.path_evidence(a._root_settings.path)] if a._root_settings else [],
            status="confirmed" if a._root_settings else "unknown",
            reason=None if a._root_settings else "no build script",
            attrs={"directory": label, "build_scripts": ()},
            tags=(tag,),
        )
        run.fact(
            "dependencies",
            label,
            basis="gradle",
            status="unknown",
            reason="the module has no build script, so its dependencies are not declared here",
            tags=(tag,),
        )
        return
    plugins: dict[str, tuple[int, GradleScript]] = {}
    for script in scripts:
        for plugin_id, line in plugin_occurrences(script, run):
            plugins.setdefault(plugin_id, (line, script))
    module_type = next((_MODULE_TYPES[p] for p in _MODULE_TYPE_ORDER if p in plugins), None)
    opaque = any(a.opaque_plugins(script) for script in scripts)
    namespace = next((s.namespace[0] for s in scripts if s.namespace), None)
    application_id = next((s.application_id[0] for s in scripts if s.application_id), None)
    attrs: dict = {
        "directory": label,
        "build_scripts": tuple(s.path for s in scripts),
    }
    if module_type:
        attrs["type"] = module_type
    if namespace:
        attrs["namespace"] = namespace
    if application_id:
        attrs["application_id"] = application_id
    attrs["dependencies_readable"] = not (
        opaque or a.shared_dependency_scope or any(unparsed_calls(s) for s in scripts)
    )
    run.fact(
        "module",
        label,
        basis="gradle",
        evidence=[run.path_evidence(s.path) for s in scripts],
        attrs=attrs,
        tags=(tag,),
    )
    if module_type is None:
        run.fact(
            "module_type",
            label,
            basis="gradle",
            status="unknown",
            reason="no recognised Android or JVM plugin: it may come from a convention plugin",
            tags=(tag,),
        )
    if module_type == "kotlin_multiplatform":
        store.limit(
            "kotlin_multiplatform_not_analysed",
            label,
            "Kotlin Multiplatform source sets (commonMain, iosMain...) are not modelled",
        )
    for plugin_id, (line, script) in sorted(plugins.items()):
        version = script.plugin_versions.get(plugin_id)
        plugin_attrs: dict = {"id": plugin_id, "module": label}
        if version:
            plugin_attrs["version"] = version
        run.fact(
            "gradle_plugin",
            f"{label}|{plugin_id}",
            basis="gradle",
            evidence=[run.gradle_evidence(script, line)],
            attrs=plugin_attrs,
            tags=(tag,),
        )
        mapped = PLUGIN_TECH.get(plugin_id)
        if mapped:
            run.fact(
                "technology",
                mapped[0],
                basis="gradle",
                evidence=[run.gradle_evidence(script, line)],
                attrs={"category": mapped[1]},
                tags=(tag,),
            )
    _sdk_levels(run, module, label, scripts, opaque)
    _features(run, label, scripts, plugins)
    _dependencies(run, module, label, scripts, opaque)


_WHOLE_VALUE_TAIL = re.compile(r"[ \t]*(?:;|\}|$)")


def _is_whole_literal(script: GradleScript, name: str, value: int, line: int) -> bool:
    """Is ``value`` the entire assigned expression, not just the start of one?

    Review's SDK readers take the first number after ``minSdk``, so ``minSdk = 21 + 3`` reads as
    21. Nothing is evaluated here, so such a line is *not* a literal and must not be confirmed.
    A different written form (``compileSdk { version = release(37) }``) is left as read.
    """
    lines = script.masked.split("\n")
    if not 1 <= line <= len(lines):
        return True
    text = lines[line - 1]
    match = re.search(rf"\b{name}(?:Version)?\b[ \t]*=?[ \t]*{value}\b", text)
    return match is None or bool(_WHOLE_VALUE_TAIL.match(text, match.end()))


def _sdk_levels(
    run: Run, module: str, label: str, scripts: list[GradleScript], opaque: bool
) -> None:
    a = run.a
    tag = f"module:{label}"
    for name in ("minSdk", "targetSdk", "compileSdk"):
        subject = f"{label}|{name}"
        done = False
        for script in scripts:
            direct: tuple[int, int] | None
            if name == "minSdk":
                direct = script.min_sdk
            elif name == "compileSdk":
                direct = script.compile_sdk
            else:
                direct = script.target_sdk
            value: tuple[int, int] | None
            if direct is not None:
                if not _is_whole_literal(script, name, direct[0], direct[1]):
                    continue  # ``minSdk = 21 + 3``: the number is only the start of an expression
                value, via = direct, "literal"
            elif name == "targetSdk":
                value, via = a.target_sdk_of(script), "catalog_or_constant"
            else:
                continue
            if value is None:
                continue
            attrs: dict = {"value": value[0], "module": label, "resolved_via": via}
            if name == "compileSdk" and script.compile_sdk_minor:
                attrs["minor"] = script.compile_sdk_minor
            evidence = [run.gradle_evidence(script, value[1])]
            if via != "literal" and a.catalog_path:
                evidence.append(run.path_evidence(a.catalog_path))
            run.fact(
                "sdk_level",
                subject,
                basis="gradle",
                evidence=evidence,
                attrs=attrs,
                tags=(tag,),
            )
            done = True
            break
        if done:
            continue
        written = any(_SDK_WORDS[name].search(s.masked) for s in scripts)
        if written or opaque:
            reason = (
                f"{name} is written as an expression that is not evaluated (scripts are never run)"
                if written
                else f"{name} may be set by a convention plugin that this analysis cannot read"
            )
            run.fact(
                "sdk_level", subject, basis="gradle", status="unknown", reason=reason, tags=(tag,)
            )


def _features(
    run: Run, label: str, scripts: list[GradleScript], plugins: dict[str, tuple[int, GradleScript]]
) -> None:
    tag = f"module:{label}"
    for script in scripts:
        names: dict[str, int] = {}
        for match in _FEATURE_ON.finditer(script.masked):
            names.setdefault(match.group(1), script.line(match.start()))
        for match in _FEATURE_BLOCK.finditer(script.masked):
            names.setdefault(match.group(1), script.line(match.start()))
        if script.compose_enabled:
            names.setdefault("compose", script.compose_enabled)
        for name, line in sorted(names.items()):
            run.fact(
                "build_feature",
                f"{label}|{name}",
                basis="gradle",
                evidence=[run.gradle_evidence(script, line)],
                attrs={"feature": name, "module": label},
                tags=(tag,),
            )
            if name in ("compose", "viewBinding", "dataBinding"):
                run.fact(
                    "technology",
                    {
                        "compose": "compose",
                        "viewBinding": "view_binding",
                        "dataBinding": "data_binding",
                    }[name],
                    basis="gradle",
                    evidence=[run.gradle_evidence(script, line)],
                    attrs={"category": "ui"},
                    tags=(tag,),
                )
    if "org.jetbrains.kotlin.plugin.compose" in plugins:
        line, script = plugins["org.jetbrains.kotlin.plugin.compose"]
        run.fact(
            "build_feature",
            f"{label}|compose",
            basis="gradle",
            evidence=[run.gradle_evidence(script, line)],
            attrs={"feature": "compose", "module": label},
            tags=(tag,),
        )


def _dependencies(
    run: Run, module: str, label: str, scripts: list[GradleScript], opaque: bool
) -> None:
    a, store = run.a, run.store
    tag = f"module:{label}"
    paths = {s.path: s for s in scripts}
    for resolved in a.dependencies:
        dep = resolved.dep
        script = paths.get(dep.path)
        if script is None or dep.project or dep.project_accessor:
            continue
        evidence = [run.gradle_evidence(script, dep.line)]
        scope = "test" if is_test_config(dep.config) else "main"
        coordinate = resolved.coordinate
        if coordinate is None:
            origin = dep.alias or dep.constant or "?"
            run.fact(
                "dependency",
                f"{label}|{dep.config}|{origin}",
                basis="gradle",
                status="unknown",
                reason=(
                    "the catalog alias has no entry in libs.versions.toml (or there is no catalog)"
                    if dep.alias
                    else "the constant is not a readable group:artifact string"
                    if dep.constant
                    else "the dependency notation is not readable"
                ),
                evidence=evidence,
                attrs={"module": label, "config": dep.config, "scope": scope},
                tags=(tag,),
            )
            continue
        via = (
            "bundle"
            if dep.alias and ".bundles." in f".{dep.alias}"
            else ("catalog" if dep.alias else "build_constant" if dep.constant else "literal")
        )
        attrs: dict = {
            "module": label,
            "config": dep.config,
            "group": resolved.group or "",
            "artifact": resolved.artifact or "",
            "scope": scope,
            "via": via,
            "platform": dep.is_platform,
        }
        if resolved.version:
            attrs["version"] = clip(resolved.version, 60)
        if via != "literal" and a.catalog_path and dep.alias:
            evidence.append(run.path_evidence(a.catalog_path))
        run.fact(
            "dependency",
            f"{label}|{dep.config}|{coordinate}",
            basis="gradle",
            evidence=evidence,
            attrs=attrs,
            tags=(tag, f"scope:{scope}"),
        )
        tech = longest_prefix(COORDINATE_TECH, coordinate)
        if tech and (scope == "main" or tech[1] == "testing"):
            run.fact(
                "technology",
                tech[0],
                basis="gradle",
                evidence=evidence,
                attrs={"category": tech[1]},
                tags=(tag,),
            )
    # how far the dependency list can be trusted
    if opaque:
        store.limit(
            "convention_plugin_dependencies_unknown",
            label,
            "the module applies plugins this analysis cannot read (for example a convention "
            "plugin from build-logic); dependencies and settings they add are not visible",
        )
    if any(unparsed_calls(s) for s in scripts):
        store.limit(
            "unparsed_dependency_calls",
            label,
            "some dependency declarations are computed or written in a form that is not read",
        )
    if a.shared_dependency_scope:
        store.limit(
            "shared_dependency_scope",
            label,
            "allprojects/subprojects adds dependencies to modules from outside their own script",
        )
    if opaque or a.shared_dependency_scope or any(unparsed_calls(s) for s in scripts):
        run.fact(
            "dependencies",
            label,
            basis="gradle",
            status="unknown",
            reason="the dependency list is incomplete: some are added by code that is not read",
            tags=(tag,),
        )


def _project_dependencies(run: Run) -> None:
    a = run.a
    for dep in a.project_dependencies:
        source = module_label(dep.source)
        script = a.gradle_scripts.get(dep.path)
        evidence = (
            [run.gradle_evidence(script, dep.line)] if script else [run.path_evidence(dep.path)]
        )
        if dep.target is not None and run.store.has(f"module:{module_label(dep.target)}"):
            run.store.relate(
                f"module:{source}",
                "depends_on",
                f"module:{module_label(dep.target)}",
                basis="gradle",
                evidence=evidence,
            )
            continue
        run.fact(
            "module_dependency",
            f"{source}|{dep.reference}",
            basis="gradle",
            status="unknown",
            reason="the project path does not match an included module, or the includes "
            "are dynamic",
            evidence=evidence,
            attrs={"config": dep.config},
            tags=(f"module:{source}",),
        )


def _import_technologies(run: Run) -> None:
    """Libraries the sources import: evidence that holds even when the build is unreadable."""
    from .catalog import IMPORT_TECH  # local: avoids a long module-level import list

    for info in run.app_sources():
        if run.expired():
            return
        source = info.source
        for imp in source.imports:
            if imp.static:
                continue
            text = imp.fqn if not imp.wildcard else f"{imp.fqn}."
            tech = longest_prefix(IMPORT_TECH, text)
            if tech is None:
                continue
            offset = info.view.lines.line_start(imp.line)
            run.fact(
                "technology",
                tech[0],
                basis="source",
                evidence=[run.path_evidence(info.path)]
                if offset is None
                else [info.view.evidence(offset)],
                attrs={"category": tech[1]},
                tags=run.path_tags(info.path)[:1],
            )
