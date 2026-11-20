"""Gradle build scripts (Groovy and Kotlin DSL) and version catalogs, read statically.

Nothing is executed: scripts are lexed (comments and strings handled) and mined with regexes for
the few things review needs: dependencies, plugins, SDK levels, namespace and application id.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import cached_property

from .lexer import Lexed, check_brackets, lex, normalize_newlines

_CONFIGS = (
    "implementation|api|compileOnly|runtimeOnly|testImplementation|androidTestImplementation"
    "|debugImplementation|releaseImplementation|testRuntimeOnly|testCompileOnly|ksp|kapt"
    "|annotationProcessor|kaptTest|kaptAndroidTest|kspTest|kspAndroidTest|coreLibraryDesugaring"
    "|lintChecks|classpath|androidTestUtil|debugApi|compile|testCompile|androidTestCompileOnly"
)
_DEPENDENCY = re.compile(
    rf"(?<![\w.])({_CONFIGS})\b[ \t]*\(?[ \t]*(?:(?:platform|enforcedPlatform)[ \t]*\([ \t]*)?"
)
_CATALOG_REF = re.compile(r"(?<![\w.])libs((?:\.[A-Za-z_]\w*)+)")
_NUMBER = r"[ \t]*=?[ \t]*(\d+)"
_COMPILE_SDK = re.compile(rf"\bcompileSdk(?:Version)?\b{_NUMBER}")
_MIN_SDK = re.compile(rf"\bminSdk(?:Version)?\b{_NUMBER}")
_TARGET_SDK = re.compile(rf"\btargetSdk(?:Version)?\b{_NUMBER}")
_RELEASE_SDK = re.compile(r"\bcompileSdk\b[^\n]*?\brelease\((\d+)\s*\)")
# AGP 9: ``compileSdk { version = release(37) { minorApiLevel = 1 } }``, usually over several lines.
_COMPILE_SDK_BLOCK = re.compile(r"\bcompileSdk\b[ \t]*\{")
_RELEASE_CALL = re.compile(r"\brelease\s*\(\s*(\d+)\s*\)")  # a literal: not ``release(36 + 1)``
_MINOR_API_LEVEL = re.compile(r"\bminorApiLevel\b[ \t]*=?[ \t]*(\d+)")
_NAMESPACE = re.compile(r"\bnamespace\b[ \t]*=?[ \t]*")
_APPLICATION_ID = re.compile(r"\bapplicationId\b[ \t]*=?[ \t]*")
_PLUGIN_ID = re.compile(r"(?<![\w.])id[ \t]*\(?[ \t]*")
_APPLY_PLUGIN = re.compile(r"\bapply[ \t]+plugin[ \t]*:[ \t]*")
_KOTLIN_PLUGIN = re.compile(r"(?<![\w.])kotlin[ \t]*\([ \t]*")
_PLUGIN_ALIAS = re.compile(r"(?<![\w.])alias[ \t]*\([ \t]*libs\.plugins((?:\.[A-Za-z_]\w*)+)")
_ARTIFACT_MAP = re.compile(r"\bgroup[ \t]*[:=]")
_PROJECT_CALL = re.compile(
    r"(?:testFixtures[ \t]*\([ \t]*)?project[ \t]*\([ \t]*(?:path[ \t]*[:=][ \t]*)?"
)
_PROJECT_ACCESSOR = re.compile(
    r"(?:testFixtures[ \t]*\([ \t]*)?projects((?:\.[A-Za-z_]\w*)+)(?![\w(])"
)
_CONSTANT_REF = re.compile(r"([A-Z]\w*(?:\.[A-Za-z_]\w*)+)(?![\w(])")
_RES_VALUE = re.compile(r"(?<![\w.])resValue\b[ \t]*\(?[ \t]*")
_INCLUDE = re.compile(r"(?<![\w.])include\b[ \t]*\(?")
_INCLUDE_BUILD = re.compile(r"(?<![\w.])includeBuild\b[ \t]*\(")
_CATALOG_CREATE = re.compile(r"(?<![\w.])create[ \t]*\([ \t]*")
_FROM_FILES = re.compile(r"(?<![\w.])from[ \t]*\([ \t]*files[ \t]*\(")
_KOTLIN_DEP = re.compile(r"(?<![\w.])kotlin[ \t]*\([ \t]*")
_IGNORED_DEP = re.compile(r"(?:gradleApi|localGroovy|gradleKotlinDsl)[ \t]*\(")
_COMPOSE_ON = re.compile(r"(?<![\w.])compose[ \t]*(?:=[ \t]*)?true\b")
_VERSION_AFTER = re.compile(r"[ \t]*\)?[ \t]*version[ \t]*\(?[ \t]*")


def sdk_label(api: int, minor: int | None) -> str:
    """``37`` for API 37, ``37.1`` for API 37 minor level 1."""
    return f"{api}.{minor}" if minor else str(api)


@dataclass(frozen=True)
class Dependency:
    config: str
    group: str | None
    artifact: str | None
    version: str | None
    alias: str | None  # catalog accessor, e.g. "libs.androidx.core.ktx"
    path: str
    line: int
    is_platform: bool = False
    project: str | None = None  # ``project(":core:data")``: the project path as written
    project_accessor: str | None = None  # ``projects.core.dataTest``: the part after ``projects.``
    constant: str | None = None  # ``Libs.MATERIAL``: a constant from buildSrc, resolved by analysis

    @property
    def coordinate(self) -> str | None:
        return f"{self.group}:{self.artifact}" if self.group and self.artifact else None


@dataclass
class VersionCatalog:
    libraries: dict[str, tuple[str | None, str | None, str | None]] = field(default_factory=dict)
    plugins: dict[str, str | None] = field(default_factory=dict)
    plugin_versions: dict[str, str | None] = field(default_factory=dict)  # alias -> version
    version_values: dict[str, str] = field(default_factory=dict)  # [versions] name -> literal
    versions: set[str] = field(default_factory=set)
    bundles: set[str] = field(default_factory=set)
    bundle_members: dict[str, tuple[str, ...]] = field(default_factory=dict)  # bundle -> libraries
    error: str | None = None
    error_line: int | None = None


def _accessor(key: str) -> str:
    return re.sub(r"[-_.]", ".", key)


def parse_catalog(text: str) -> VersionCatalog:
    catalog = VersionCatalog()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        catalog.error = str(exc)
        found = re.search(r"line (\d+)", str(exc))
        catalog.error_line = int(found.group(1)) if found else None
        return catalog
    for key, value in (data.get("libraries") or {}).items():
        group = name = version = None
        if isinstance(value, str):
            parts = value.split(":")
            group, name = parts[0], parts[1] if len(parts) > 1 else None
            version = parts[2] if len(parts) > 2 else None
        elif isinstance(value, dict):
            if "module" in value and isinstance(value["module"], str):
                group, _, name = value["module"].partition(":")
            else:
                group, name = value.get("group"), value.get("name")
            raw = value.get("version")
            version = raw if isinstance(raw, str) else (raw or {}).get("ref") if raw else None
        catalog.libraries[_accessor(key)] = (group, name or None, version)
    for key, value in (data.get("versions") or {}).items():
        if isinstance(value, str):
            catalog.version_values[key] = value
    for key, value in (data.get("plugins") or {}).items():
        plugin_id = value if isinstance(value, str) else (value or {}).get("id")
        catalog.plugins[_accessor(key)] = plugin_id.split(":")[0] if plugin_id else None
        if isinstance(value, str):
            catalog.plugin_versions[_accessor(key)] = (
                value.split(":")[1] if value.count(":") else None
            )
        elif isinstance(value, dict):
            raw = value.get("version")
            ref = raw.get("ref") if isinstance(raw, dict) else None
            catalog.plugin_versions[_accessor(key)] = (
                catalog.version_values.get(ref) if ref else raw if isinstance(raw, str) else None
            )
    catalog.versions = {_accessor(k) for k in (data.get("versions") or {})}
    for key, members in (data.get("bundles") or {}).items():
        names = tuple(_accessor(m) for m in members if isinstance(m, str)) if members else ()
        catalog.bundle_members[_accessor(key)] = names
    catalog.bundles = set(catalog.bundle_members)
    return catalog


class GradleScript:
    def __init__(self, path: str, text: str) -> None:
        self.path = path
        self.text = normalize_newlines(text)
        self.language = "kotlin" if path.endswith(".kts") else "groovy"
        self.lexed: Lexed = lex(self.text, self.language)  # type: ignore[arg-type]
        self.masked = self.lexed.masked

    def line(self, offset: int) -> int:
        return self.lexed.line(offset)

    @cached_property
    def bracket_errors(self):
        return check_brackets(self.lexed)

    def _string_after(self, offset: int) -> str | None:
        """Value of the string literal starting at (or after spaces from) ``offset``."""
        n = len(self.masked)
        while offset < n and self.masked[offset] in " \t":
            offset += 1
        literal = self.lexed.string_starting_at(offset)
        return self.lexed.string_value(literal) if literal and literal.terminated else None

    @cached_property
    def dependencies(self) -> list[Dependency]:
        found: list[Dependency] = []
        for match in _DEPENDENCY.finditer(self.masked):
            config = match.group(1)
            offset = match.end()
            is_platform = "platform" in match.group(0)
            line = self.line(match.start())
            value = self._string_after(offset)
            if value is not None:
                parts = value.split(":")
                found.append(
                    Dependency(
                        config=config,
                        group=parts[0] or None,
                        artifact=parts[1] if len(parts) > 1 and parts[1] else None,
                        version=parts[2] if len(parts) > 2 and parts[2] else None,
                        alias=None,
                        path=self.path,
                        line=line,
                        is_platform=is_platform,
                    )
                )
                continue
            call = _PROJECT_CALL.match(self.masked, offset)
            if call:
                arguments = self._string_arguments(call.end())
                if arguments:
                    found.append(
                        Dependency(
                            config,
                            None,
                            None,
                            None,
                            None,
                            self.path,
                            line,
                            is_platform,
                            project=arguments[0],
                        )
                    )
                continue
            accessor = _PROJECT_ACCESSOR.match(self.masked, offset)
            if accessor:
                found.append(
                    Dependency(
                        config,
                        None,
                        None,
                        None,
                        None,
                        self.path,
                        line,
                        is_platform,
                        project_accessor=accessor.group(1).lstrip("."),
                    )
                )
                continue
            constant = _CONSTANT_REF.match(self.masked, offset)
            if constant:
                found.append(
                    Dependency(
                        config,
                        None,
                        None,
                        None,
                        None,
                        self.path,
                        line,
                        is_platform,
                        constant=constant.group(1),
                    )
                )
                continue
            kotlin = _KOTLIN_DEP.match(self.masked, offset)
            if kotlin:
                module = self._string_after(kotlin.end())
                if module:
                    found.append(
                        Dependency(
                            config,
                            "org.jetbrains.kotlin",
                            f"kotlin-{module.split(':')[0]}",
                            None,
                            None,
                            self.path,
                            line,
                            is_platform,
                        )
                    )
                continue
            ref = re.compile(r"libs((?:\.[A-Za-z_]\w*)+)").match(self.masked, offset)
            if ref:
                found.append(
                    Dependency(
                        config,
                        None,
                        None,
                        None,
                        "libs" + ref.group(1),
                        self.path,
                        line,
                        is_platform,
                    )
                )
        return found

    @cached_property
    def unparsed_dependency_calls(self) -> int:
        """Dependency-configuration calls we could not read (a loop variable, ``files(...)``, a
        computed string...). Where this is non-zero the dependency list is incomplete, so a rule
        must not conclude that something is *not* declared."""
        total = 0
        for match in _DEPENDENCY.finditer(self.masked):
            if not _IGNORED_DEP.match(self.masked, match.end()):
                total += 1
        return max(0, total - len(self.dependencies))

    @cached_property
    def compose_enabled(self) -> int | None:
        """Line of ``buildFeatures { compose = true }``, if present."""
        match = _COMPOSE_ON.search(self.masked)
        return self.line(match.start()) if match else None

    @cached_property
    def plugin_versions(self) -> dict[str, str]:
        """Plugin id -> literal version (``id("x") version "1"``, ``kotlin("jvm") version "1"`` or
        a ``classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.22")`` dependency)."""
        found: dict[str, str] = {}
        for pattern, prefix in ((_PLUGIN_ID, ""), (_KOTLIN_PLUGIN, "org.jetbrains.kotlin.")):
            for match in pattern.finditer(self.masked):
                literal = self.lexed.string_starting_at(match.end())
                if literal is None or not literal.terminated:
                    continue
                tail = _VERSION_AFTER.match(self.masked, literal.end)
                version = self._string_after(tail.end()) if tail else None
                if version:
                    found[prefix + self.lexed.string_value(literal)] = version
        for dep in self.dependencies:
            if dep.artifact == "kotlin-gradle-plugin" and dep.version:
                found.setdefault("org.jetbrains.kotlin.android", dep.version)
        return found

    def _string_arguments(self, offset: int) -> list[str]:
        """The string literals of a call's comma-separated arguments, starting at ``offset``."""
        values: list[str] = []
        n = len(self.masked)
        while offset < n:
            while offset < n and self.masked[offset] in " \t\r\n,":
                offset += 1
            literal = self.lexed.string_starting_at(offset)
            if literal is None or not literal.terminated:
                break
            values.append(self.lexed.string_value(literal))
            offset = literal.end
        return values

    @cached_property
    def res_values(self) -> list[tuple[str, str]]:
        """``(type, name)`` of resources generated by ``resValue "string", "app_name", "..."``."""
        found: list[tuple[str, str]] = []
        for match in _RES_VALUE.finditer(self.masked):
            arguments = self._string_arguments(match.end())
            if len(arguments) >= 2:
                found.append((arguments[0], arguments[1]))
        return found

    @cached_property
    def includes(self) -> list[str]:
        """Directories of the projects a settings script includes (``":a:b"`` -> ``a/b``)."""
        found: list[str] = []
        for match in _INCLUDE.finditer(self.masked):
            for value in self._string_arguments(match.end()):
                directory = value.strip(":").replace(":", "/")
                if directory:
                    found.append(directory)
        return found

    @cached_property
    def includes_are_dynamic(self) -> bool:
        """The set of included projects cannot be read from literals: ``include(it)`` in a loop,
        or a ``projectDir`` remap. Then a project that is "not included" may still exist."""
        if "projectDir" in self.masked:
            return True
        return any(not self._string_arguments(m.end()) for m in _INCLUDE.finditer(self.masked))

    @cached_property
    def included_builds(self) -> list[str]:
        """Directories (relative to this script) of ``includeBuild("...")`` builds."""
        return [
            value.strip("/")
            for match in _INCLUDE_BUILD.finditer(self.masked)
            for value in self._string_arguments(match.end())[:1]
            if value.strip("/")
        ]

    @cached_property
    def catalog_declarations(self) -> list[tuple[str, bool]]:
        """``(name, from_local_file)`` for each ``versionCatalogs { create("name") { ... } }``."""
        matches = list(_CATALOG_CREATE.finditer(self.masked))
        found: list[tuple[str, bool]] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(self.masked)
            names = self._string_arguments(match.end())
            local = bool(_FROM_FILES.search(self.masked, match.end(), end))
            found.append((names[0] if names else "", local))
        return found

    @cached_property
    def catalog_refs(self) -> list[tuple[str, int]]:
        """``libs.x.y`` references as (accessor path without 'libs.', line)."""
        return [
            (match.group(1).lstrip("."), self.line(match.start()))
            for match in _CATALOG_REF.finditer(self.masked)
        ]

    @cached_property
    def plugin_aliases(self) -> list[tuple[str, int]]:
        return [
            (match.group(1).lstrip("."), self.line(match.start()))
            for match in _PLUGIN_ALIAS.finditer(self.masked)
        ]

    def plugin_ids(self, catalog: VersionCatalog | None) -> set[str]:
        ids: set[str] = set()
        for pattern in (_PLUGIN_ID, _APPLY_PLUGIN):
            for match in pattern.finditer(self.masked):
                value = self._string_after(match.end())
                if value:
                    ids.add(value)
        for match in _KOTLIN_PLUGIN.finditer(self.masked):
            value = self._string_after(match.end())
            if value:
                ids.add(f"org.jetbrains.kotlin.{value}")
        if catalog:
            for alias, _line in self.plugin_aliases:
                plugin_id = catalog.plugins.get(alias)
                if plugin_id:
                    ids.add(plugin_id)
        return ids

    def _number(self, pattern: re.Pattern[str]) -> tuple[int, int] | None:
        match = pattern.search(self.masked)
        return (int(match.group(1)), self.line(match.start())) if match else None

    def _block_end(self, brace: int) -> int | None:
        """Offset of the ``}`` closing the ``{`` at ``brace`` (strings and comments are masked)."""
        depth = 0
        for index in range(brace, len(self.masked)):
            char = self.masked[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    @cached_property
    def _compile_sdk_release(self) -> tuple[int, int, int] | None:
        """``(api level, minor level, line)`` of ``compileSdk { version = release(N) { ... } }``.

        The block may span several lines. ``minorApiLevel`` defaults to 0 when it is not written.
        ``preview(...)``, a property or any other expression is not read.
        """
        for block in _COMPILE_SDK_BLOCK.finditer(self.masked):
            end = self._block_end(block.end() - 1)
            if end is None:
                continue
            body = self.masked[block.end() : end]
            release = _RELEASE_CALL.search(body)
            if release:
                minor = _MINOR_API_LEVEL.search(body, release.end())
                return (
                    int(release.group(1)),
                    int(minor.group(1)) if minor else 0,
                    self.line(block.end() + release.start()),
                )
        return None

    @cached_property
    def compile_sdk(self) -> tuple[int, int] | None:
        """``(api level, line)``: a number written out, or ``release(N)`` in a ``compileSdk {}``."""
        plain = self._number(_COMPILE_SDK)
        if plain:
            return plain
        release = self._compile_sdk_release
        if release:
            return release[0], release[2]
        return self._number(_RELEASE_SDK)

    @cached_property
    def compile_sdk_minor(self) -> int | None:
        """Minor API level of ``compile_sdk`` (``release(37) { minorApiLevel = 1 }`` is 37.1).

        0 for a whole number, ``None`` when the compile SDK is not known.
        """
        if self._number(_COMPILE_SDK):
            return 0
        release = self._compile_sdk_release
        if release:
            return release[1]
        return 0 if self.compile_sdk else None

    @cached_property
    def min_sdk(self) -> tuple[int, int] | None:
        return self._number(_MIN_SDK)

    @cached_property
    def target_sdk(self) -> tuple[int, int] | None:
        return self._number(_TARGET_SDK)

    def _quoted(self, pattern: re.Pattern[str]) -> tuple[str, int] | None:
        match = pattern.search(self.masked)
        if not match:
            return None
        value = self._string_after(match.end())
        return (value, self.line(match.start())) if value else None

    @cached_property
    def namespace(self) -> tuple[str, int] | None:
        return self._quoted(_NAMESPACE)

    @cached_property
    def application_id(self) -> tuple[str, int] | None:
        return self._quoted(_APPLICATION_ID)
