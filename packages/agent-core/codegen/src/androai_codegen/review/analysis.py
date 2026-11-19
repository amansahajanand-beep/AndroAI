"""Project-wide facts, computed lazily and shared by every rule."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property

from .gradle import Dependency, GradleScript, VersionCatalog, parse_catalog
from .models import ReviewConfig, ReviewTarget
from .project import ProjectFiles
from .proto import generated_classes
from .resources import ResourceIndex
from .source import SourceFile, TypeDecl, matching_close
from .xmlparse import DOCTYPE_REFUSED, XmlDoc, XmlNode, parse_xml

COMPONENT_TAGS = ("activity", "activity-alias", "service", "receiver", "provider")
_XML_PROLOG_AND_COMMENTS = re.compile(r"<\?.*?\?>|<!--.*?-->", re.DOTALL)
_BUILD_SOURCE = re.compile(r"(?:^|/)(?:buildSrc|build-logic)/")
_OBJECT = re.compile(r"\bobject[ \t]+([A-Za-z_]\w*)[ \t]*\{")
_CONST = re.compile(
    r'\bconst[ \t]+val[ \t]+([A-Za-z_]\w*)[ \t]*(?::[ \t]*String[ \t]*)?=[ \t]*"([^"\n]*)"'
)


class SymbolIndex:
    """Declarations across all Kotlin/Java sources."""

    def __init__(self, sources: dict[str, SourceFile]) -> None:
        self.by_fqn: dict[str, list[tuple[str, TypeDecl]]] = defaultdict(list)
        self.packages: set[str] = set()
        self.top_names: dict[str, set[str]] = defaultdict(set)
        self.cap_names: dict[str, list[str]] = defaultdict(list)
        self.fun_names: set[str] = set()
        for path, source in sources.items():
            package = source.package
            self.packages.add(package)
            for decl in source.types:
                self.by_fqn[decl.fqn].append((path, decl))
                if decl.top_level and not decl.private:
                    self.top_names[package].add(decl.name)
                    self._add_cap(decl.name, decl.fqn)
            for function in source.functions:
                self.fun_names.add(function.name)
                if function.top_level and not function.private:
                    self.top_names[package].add(function.name)
                    if function.name[:1].isupper():
                        self._add_cap(
                            function.name,
                            f"{package}.{function.name}" if package else function.name,
                        )
            self.top_names[package].update(source.top_level_values)

    def _add_cap(self, name: str, fqn: str) -> None:
        if fqn not in self.cap_names[name]:
            self.cap_names[name].append(fqn)

    def has_type(self, fqn: str) -> bool:
        return fqn in self.by_fqn


@dataclass(frozen=True)
class Component:
    kind: str  # application | activity | activity-alias | service | receiver | provider
    name: str  # as written
    fqn: str  # resolved against the package
    line: int
    exported: str | None
    has_intent_filter: bool
    is_launcher: bool
    target_activity: str | None = None  # for activity-alias


@dataclass
class ManifestInfo:
    path: str
    package: str | None
    root: XmlNode
    permissions: list[tuple[str, int]]
    components: list[Component]
    application: XmlNode | None


@dataclass(frozen=True)
class ResolvedDependency:
    dep: Dependency
    group: str | None
    artifact: str | None
    version: str | None
    unresolved_alias: bool = False

    @property
    def coordinate(self) -> str | None:
        return f"{self.group}:{self.artifact}" if self.group and self.artifact else None


@dataclass(frozen=True)
class ProjectDependency:
    """A dependency of one module on another module of the same build."""

    source: str  # directory of the module whose script declares it
    target: str | None  # directory of the module it points at; None if it is not included
    reference: str  # as written: ":core:data" or "projects.core.dataTest"
    config: str
    path: str  # the build script
    line: int


def _camel(segment: str) -> str:
    """Gradle's typesafe accessor name of a project path segment: ``data-test`` -> ``dataTest``."""
    return re.sub(r"[-_]+([A-Za-z0-9])", lambda m: m.group(1).upper(), segment)


def _resolve_class(name: str, package: str | None) -> str:
    if name.startswith("."):
        return f"{package}{name}" if package else name[1:]
    if "." not in name:
        return f"{package}.{name}" if package else name
    return name


class ProjectAnalysis:
    def __init__(
        self, files: ProjectFiles, config: ReviewConfig, target: ReviewTarget | None = None
    ) -> None:
        self.files = files
        self.config = config
        self.target = target or ReviewTarget()

    # -- parsed files -------------------------------------------------------------------

    @cached_property
    def sources(self) -> dict[str, SourceFile]:
        return {
            path: SourceFile(path, text)
            for path, text in sorted(self.files.texts.items())
            if path.endswith((".kt", ".java"))
        }

    @cached_property
    def gradle_scripts(self) -> dict[str, GradleScript]:
        return {
            path: GradleScript(path, text)
            for path, text in sorted(self.files.texts.items())
            if path.endswith((".gradle", ".kts"))
        }

    @cached_property
    def xml_docs(self) -> dict[str, XmlDoc]:
        return {
            path: parse_xml(text)
            for path, text in sorted(self.files.texts.items())
            if path.endswith(".xml")
        }

    @cached_property
    def proto_types(self) -> frozenset[str]:
        """Classes generated from the project's ``.proto`` files (importable, not in sources)."""
        found: set[str] = set()
        for path, text in self.files.texts.items():
            if path.endswith(".proto"):
                found |= generated_classes(path, text)
        return frozenset(found)

    @cached_property
    def template_xml(self) -> frozenset[str]:
        """XML files holding only a prolog and comments (e.g. a license-header template).

        They have no root element on purpose and are not read by Android, so "no element found"
        is not an error for them. Resource files and manifests are excluded: a rootless file
        there does break the build.
        """
        found = set()
        for path, doc in self.xml_docs.items():
            if not doc.error or path.endswith("AndroidManifest.xml") or "/res/" in f"/{path}":
                continue
            if not _XML_PROLOG_AND_COMMENTS.sub("", self.files.texts[path]).strip():
                found.add(path)
        return frozenset(found)

    @cached_property
    def refused_xml(self) -> frozenset[str]:
        """Well-formed XML we refuse to parse because it has a DOCTYPE, outside ``res/`` and the
        manifest (tool configuration such as ``checkstyle.xml``). It is not Android input, so
        refusing it is not a project error; it stays listed as unparsed."""
        return frozenset(
            path
            for path, doc in self.xml_docs.items()
            if doc.error
            and doc.error.message == DOCTYPE_REFUSED
            and not path.endswith("AndroidManifest.xml")
            and "/res/" not in f"/{path}"
        )

    @cached_property
    def catalog_path(self) -> str | None:
        found = [p for p in self.files.texts if p.endswith("libs.versions.toml")]
        return sorted(found)[0] if found else None

    @cached_property
    def catalog(self) -> VersionCatalog | None:
        return parse_catalog(self.files.texts[self.catalog_path]) if self.catalog_path else None

    @cached_property
    def custom_catalogs(self) -> bool:
        """The build defines version catalogs other than the default ``libs`` one.

        ``create("libs") { from(files("../gradle/libs.versions.toml")) }`` (what an included build
        does to share the root catalog) is the default catalog, not a custom one. A second name,
        a remote ``from("group:artifact:version")`` or a block we cannot read counts as custom.
        """
        for script in self.gradle_scripts.values():
            if "versionCatalogs" not in script.masked:
                continue
            declared = script.catalog_declarations
            if not declared or any(name != "libs" or not local for name, local in declared):
                return True
        return False

    # -- indexes ------------------------------------------------------------------------

    @cached_property
    def symbols(self) -> SymbolIndex:
        return SymbolIndex(self.sources)

    @cached_property
    def resources(self) -> ResourceIndex:
        generated = [rv for script in self.gradle_scripts.values() for rv in script.res_values]
        return ResourceIndex(self.files.paths, self.xml_docs, generated)

    # -- modules ------------------------------------------------------------------------

    @cached_property
    def modules(self) -> frozenset[str]:
        """Module directories. A directory with a build script is a module, except that in a
        multi-module build (root ``settings`` with ``include``) the root itself is not one and
        neither is anything inside an ``includeBuild`` (e.g. ``build-logic``), which is a
        separate build. Included projects count even without a build script."""
        found = set()
        for path in self.gradle_scripts:
            name = path.rsplit("/", 1)[-1]
            if name in ("build.gradle", "build.gradle.kts"):
                found.add(path.rsplit("/", 1)[0] if "/" in path else "")
        settings = self.gradle_scripts.get("settings.gradle.kts") or self.gradle_scripts.get(
            "settings.gradle"
        )
        if settings is None or not settings.includes:
            return frozenset(found)
        separate = [*settings.included_builds, "buildSrc"]  # buildSrc is an implicit build
        found = {
            m for m in found if m and not any(m == b or m.startswith(b + "/") for b in separate)
        }
        return frozenset(found | set(settings.includes))

    def module_of(self, path: str) -> str | None:
        parts = path.split("/")[:-1]
        for end in range(len(parts), -1, -1):
            candidate = "/".join(parts[:end])
            if candidate in self.modules:
                return candidate
        return None

    def source_set(self, path: str) -> str:
        parts = path.split("/")
        if "src" in parts:
            index = parts.index("src")
            if index + 1 < len(parts) - 1:
                return parts[index + 1]
        return ""

    @cached_property
    def module_namespaces(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for module in self.modules:
            prefix = f"{module}/" if module else ""
            for name in ("build.gradle.kts", "build.gradle"):
                script = self.gradle_scripts.get(prefix + name)
                if script and script.namespace:
                    result[module] = script.namespace[0]
                    break
            else:
                info = self.manifests.get(f"{prefix}src/main/AndroidManifest.xml")
                if info and info.package:
                    result[module] = info.package
        return result

    def namespace_for(self, path: str) -> str | None:
        module = self.module_of(path)
        if module is not None and module in self.module_namespaces:
            return self.module_namespaces[module]
        return self.target.package_name

    @cached_property
    def all_namespaces(self) -> frozenset[str]:
        names = set(self.module_namespaces.values())
        if self.target.package_name:
            names.add(self.target.package_name)
        return frozenset(names)

    # -- manifests ----------------------------------------------------------------------

    @cached_property
    def manifests(self) -> dict[str, ManifestInfo]:
        found: dict[str, ManifestInfo] = {}
        for path, doc in self.xml_docs.items():
            if (
                not path.endswith("AndroidManifest.xml")
                or not doc.root
                or doc.root.tag != "manifest"
            ):
                continue
            root = doc.root
            package = root.attrs.get("package")
            application = next(iter(root.child_nodes("application")), None)
            permissions = [
                (node.attrs["android:name"], node.line)
                for node in root.iter()
                if node.tag in ("uses-permission", "uses-permission-sdk-23")
                and "android:name" in node.attrs
            ]
            components: list[Component] = []
            if application is not None:
                if application.attrs.get("android:name"):
                    components.append(self._component(application, "application", package))
                for node in application.children:
                    if node.tag in COMPONENT_TAGS and node.attrs.get("android:name", "x"):
                        components.append(self._component(node, node.tag, package))
            found[path] = ManifestInfo(path, package, root, permissions, components, application)
        return found

    def _component(self, node: XmlNode, kind: str, package: str | None) -> Component:
        name = node.attrs.get("android:name", node.attrs.get("android:targetActivity", ""))
        filters = node.child_nodes("intent-filter")
        launcher = False
        for intent_filter in filters:
            actions = {a.attrs.get("android:name") for a in intent_filter.child_nodes("action")}
            categories = {
                c.attrs.get("android:name") for c in intent_filter.child_nodes("category")
            }
            if (
                "android.intent.action.MAIN" in actions
                and "android.intent.category.LAUNCHER" in categories
            ):
                launcher = True
        return Component(
            kind=kind,
            name=name,
            fqn=_resolve_class(name, package) if name else "",
            line=node.line,
            exported=node.attrs.get("android:exported"),
            has_intent_filter=bool(filters),
            is_launcher=launcher,
            target_activity=node.attrs.get("android:targetActivity"),
        )

    def manifest_package(self, manifest: ManifestInfo) -> str | None:
        """The package components resolve against: Gradle namespace, else the manifest's."""
        return self.namespace_for(manifest.path) or manifest.package

    # -- dependencies -------------------------------------------------------------------

    @cached_property
    def build_constants(self) -> dict[str, tuple[str, str, str | None]]:
        """``Libs.MATERIAL`` -> (group, artifact, version) from ``const val`` declarations in
        ``buildSrc`` / ``build-logic`` Kotlin files, e.g.
        ``object Libs { const val MATERIAL = "com.google.android.material:material" }``.
        Nested objects give dotted names (``Libs.Fragment.TESTING``). Strings with a template
        (``"$group:artifact"``) or without a ``group:artifact`` shape are not coordinates."""
        found: dict[str, tuple[str, str, str | None]] = {}
        for path, source in self.sources.items():
            if not _BUILD_SOURCE.search(path) or not path.endswith(".kt"):
                continue
            masked, raw = source.masked, source.lexed.source
            objects = [
                (m.start(), matching_close(masked, m.end() - 1), m.group(1))
                for m in _OBJECT.finditer(masked)
            ]
            for match in _CONST.finditer(raw):
                if not masked.startswith("const", match.start()):
                    continue  # inside a comment
                parts = match.group(2).split(":")
                if len(parts) < 2 or not parts[0] or not parts[1] or "$" in parts[0] + parts[1]:
                    continue
                chain = [
                    name
                    for start, end, name in objects
                    if end is not None and start < match.start() < end
                ]
                version = parts[2] if len(parts) > 2 and parts[2] else None
                found[".".join([*chain, match.group(1)])] = (parts[0], parts[1], version)
        return found

    @cached_property
    def dependencies(self) -> list[ResolvedDependency]:
        resolved: list[ResolvedDependency] = []
        for script in self.gradle_scripts.values():
            for dep in script.dependencies:
                if dep.constant:
                    coordinate = self.build_constants.get(dep.constant)
                    resolved.append(
                        ResolvedDependency(dep, *coordinate)
                        if coordinate
                        else ResolvedDependency(dep, None, None, None)
                    )
                    continue
                if dep.alias is None:
                    resolved.append(ResolvedDependency(dep, dep.group, dep.artifact, dep.version))
                    continue
                accessor = dep.alias.removeprefix("libs.")
                for suffix in (".get", ".asProvider"):
                    accessor = accessor.removesuffix(suffix)
                members = (
                    self.catalog.bundle_members.get(accessor.removeprefix("bundles."))
                    if self.catalog and accessor.startswith("bundles.")
                    else None
                )
                if members is not None:  # a catalog bundle stands for all of its libraries
                    for member in members:
                        known = self.catalog.libraries.get(member) if self.catalog else None
                        resolved.append(
                            ResolvedDependency(dep, *known)
                            if known
                            else ResolvedDependency(dep, None, None, None, unresolved_alias=True)
                        )
                    continue
                entry = self.catalog.libraries.get(accessor) if self.catalog else None
                if entry:
                    resolved.append(ResolvedDependency(dep, entry[0], entry[1], entry[2]))
                else:
                    resolved.append(
                        ResolvedDependency(dep, None, None, None, unresolved_alias=True)
                    )
        return resolved

    # -- project dependencies -----------------------------------------------------------------

    @cached_property
    def _root_settings(self) -> GradleScript | None:
        return self.gradle_scripts.get("settings.gradle.kts") or self.gradle_scripts.get(
            "settings.gradle"
        )

    @cached_property
    def projects_known(self) -> bool:
        """The root ``settings`` lists its projects as literals, so a reference to a project that
        is not in the list is certainly wrong. Otherwise we cannot tell and never claim it."""
        settings = self._root_settings
        return bool(settings and settings.includes and not settings.includes_are_dynamic)

    @cached_property
    def project_dirs(self) -> dict[str, str]:
        """Every way of naming an included project -> its directory.

        ``":core:data-test"`` and the typesafe accessor ``"projects.core.dataTest"`` both map to
        ``"core/data-test"``; ``":"`` is the root project.
        """
        found = {":": ""}
        for directory in self._root_settings.includes if self._root_settings else ():
            found[":" + directory.replace("/", ":")] = directory
            accessor = ".".join(_camel(part) for part in directory.split("/"))
            found[f"projects.{accessor}"] = directory
        return found

    @cached_property
    def project_dependencies(self) -> list[ProjectDependency]:
        """``project(":x")`` and ``projects.x`` dependencies of the main build's modules."""
        separate = [
            *(self._root_settings.included_builds if self._root_settings else []),
            "buildSrc",
        ]
        found: list[ProjectDependency] = []
        for path, script in self.gradle_scripts.items():
            if any(path == b or path.startswith(b + "/") for b in separate):
                continue  # a separate build with its own settings
            source = path.rsplit("/", 1)[0] if "/" in path else ""
            for dep in script.dependencies:
                reference = dep.project or (
                    f"projects.{dep.project_accessor}" if dep.project_accessor else None
                )
                if reference is None:
                    continue
                target = self.project_dirs.get(reference) if self.projects_known else None
                found.append(
                    ProjectDependency(source, target, reference, dep.config, path, dep.line)
                )
        return found

    @cached_property
    def module_graph(self) -> dict[str, frozenset[str]]:
        """Module directory -> directories of the modules it depends on (resolved ones only)."""
        graph: dict[str, set[str]] = defaultdict(set)
        for dep in self.project_dependencies:
            if dep.target is not None:
                graph[dep.source].add(dep.target)
        return {source: frozenset(targets) for source, targets in sorted(graph.items())}

    @cached_property
    def dependency_groups(self) -> frozenset[str]:
        """Maven groups of the declared dependencies (e.g. ``androidx.test.uiautomator``)."""
        return frozenset(d.group for d in self.dependencies if d.group)

    @cached_property
    def has_build_scripts(self) -> bool:
        return bool(self.gradle_scripts)
