"""Project-wide facts, computed lazily and shared by every rule."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property

from .gradle import Dependency, GradleScript, VersionCatalog, parse_catalog
from .models import ReviewConfig, ReviewTarget
from .project import ProjectFiles
from .resources import ResourceIndex
from .source import SourceFile, TypeDecl
from .xmlparse import XmlDoc, XmlNode, parse_xml

COMPONENT_TAGS = ("activity", "activity-alias", "service", "receiver", "provider")


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
    def catalog_path(self) -> str | None:
        found = [p for p in self.files.texts if p.endswith("libs.versions.toml")]
        return sorted(found)[0] if found else None

    @cached_property
    def catalog(self) -> VersionCatalog | None:
        return parse_catalog(self.files.texts[self.catalog_path]) if self.catalog_path else None

    @cached_property
    def custom_catalogs(self) -> bool:
        """The build defines version catalogs other than the default ``libs`` one."""
        return any("versionCatalogs" in s.masked for s in self.gradle_scripts.values())

    # -- indexes ------------------------------------------------------------------------

    @cached_property
    def symbols(self) -> SymbolIndex:
        return SymbolIndex(self.sources)

    @cached_property
    def resources(self) -> ResourceIndex:
        return ResourceIndex(self.files.paths, self.xml_docs)

    # -- modules ------------------------------------------------------------------------

    @cached_property
    def modules(self) -> frozenset[str]:
        found = set()
        for path in self.gradle_scripts:
            name = path.rsplit("/", 1)[-1]
            if name in ("build.gradle", "build.gradle.kts"):
                found.add(path.rsplit("/", 1)[0] if "/" in path else "")
        return frozenset(found)

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
    def dependencies(self) -> list[ResolvedDependency]:
        resolved: list[ResolvedDependency] = []
        for script in self.gradle_scripts.values():
            for dep in script.dependencies:
                if dep.alias is None:
                    resolved.append(ResolvedDependency(dep, dep.group, dep.artifact, dep.version))
                    continue
                accessor = dep.alias.removeprefix("libs.")
                for suffix in (".get", ".asProvider"):
                    accessor = accessor.removesuffix(suffix)
                entry = self.catalog.libraries.get(accessor) if self.catalog else None
                if entry:
                    resolved.append(ResolvedDependency(dep, entry[0], entry[1], entry[2]))
                else:
                    resolved.append(
                        ResolvedDependency(dep, None, None, None, unresolved_alias=True)
                    )
        return resolved

    @cached_property
    def has_build_scripts(self) -> bool:
        return bool(self.gradle_scripts)
