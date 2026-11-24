"""XML layouts and the code that uses them: ``R.layout`` references, View/Data Binding classes.

A layout is one fact per module and resource name; its configuration variants (``layout-land``,
``layout-sw600dp``) are folded into it. A binding class is tied to a layout only when the layout
exists in the project and the generated class name matches (``activity_main`` ->
``ActivityMainBinding``), so a project class that merely ends in ``Binding`` is not mistaken for
one. Data-binding expressions (``@{...}``) are not analysed; a layout that has any is marked.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .context import Run, module_label
from .members import FileInfo
from .model import Evidence
from .store import make_id
from .text import safe

_LAYOUT_PATH = re.compile(r"(?:^|/)res/(layout(?:-[^/]+)?)/([^/]+)\.xml$")
_LAYOUT_REF = re.compile(r"(?<!\w)R\.layout\.([A-Za-z_]\w*)")
_SYNTHETIC = re.compile(r"^kotlinx\.android\.synthetic\.[\w.]*?main\.(\w+)(?:\.|$)")
_INCLUDE_REF = re.compile(r"^@layout/(\w+)$")
_BINDING_NAME = re.compile(r"^[A-Z]\w*Binding$")
_FRAGMENT_TAGS = (
    "fragment",
    "androidx.fragment.app.FragmentContainerView",
    "FragmentContainerView",
)
_EXPRESSION = re.compile(r"@\{")
_WIDGET_PACKAGES = ("android.", "androidx.", "com.google.android.", "kotlin.", "java.")


def binding_class_name(layout_name: str) -> str:
    """The name AGP generates for a layout's binding class:
    ``item_user_row`` -> ``ItemUserRowBinding``."""
    parts = [p for p in layout_name.split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) + "Binding"


class LayoutIndex:
    """Layout facts by resource name, for resolving ``R.layout.x`` to the right module."""

    def __init__(self) -> None:
        self.by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)  # name -> (module, id)
        self.kind: dict[str, str] = {}  # fact id -> view_binding | data_binding | plain

    def add(self, name: str, module: str, fact_id: str) -> None:
        if (module, fact_id) not in self.by_name[name]:
            self.by_name[name].append((module, fact_id))

    def pick(self, name: str, module: str) -> list[tuple[str, str]]:
        """``[(fact id, status)]`` for the layout ``name`` seen from a file of ``module``."""
        options = self.by_name.get(name, [])
        same = [o for o in options if o[0] == module_label(module)]
        if same:
            return [(same[0][1], "confirmed")]
        if len(options) == 1:
            return [(options[0][1], "confirmed")]
        return [(o[1], "inferred") for o in options[:3]]


def extract_layouts(run: Run) -> None:
    index = LayoutIndex()
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in sorted(run.a.xml_docs):
        match = _LAYOUT_PATH.search(path)
        if match:
            groups[(run.module_of(path), match.group(2))].append(path)
    for (module, name), paths in sorted(groups.items()):
        _layout(run, index, module, name, paths)
    for (module, name), paths in sorted(groups.items()):
        _layout_edges(run, index, module, name, paths)
    _layout_usage(run, index)


def _layout(run: Run, index: LayoutIndex, module: str, name: str, paths: list[str]) -> None:
    label = module_label(module)
    fact_id = make_id("layout", f"{label}|{name}")
    docs = [(p, run.a.xml_docs[p]) for p in paths]
    parsed = [(p, d) for p, d in docs if d.root is not None]
    index.add(name, module, fact_id)
    if not parsed:
        run.fact(
            "layout",
            f"{label}|{name}",
            basis="layout",
            status="unknown",
            reason="the layout XML could not be parsed",
            evidence=[run.path_evidence(paths[0])],
            tags=(f"module:{label}",),
        )
        return
    ids: set[str] = set()
    custom: set[str] = set()
    includes: set[str] = set()
    fragments: set[str] = set()
    variables: set[str] = set()
    evidence: list[Evidence] = []
    data_binding = compose_view = expressions = False
    root_tags: set[str] = set()
    context = ""
    for path, doc in parsed:
        root = doc.root
        assert root is not None
        evidence.append(run.xml_evidence(path, root.line))
        root_tags.add(root.tag)
        if root.tag == "layout":
            data_binding = True
        context = context or root.attrs.get("tools:context", "")
        for node in root.iter():
            for value in node.attrs.values():
                if _EXPRESSION.search(value):
                    expressions = True
            ident = node.attrs.get("android:id", "")
            if ident.startswith(("@+id/", "@id/")):
                ids.add(ident.split("/", 1)[1])
            if "." in node.tag and not node.tag.startswith(_WIDGET_PACKAGES):
                custom.add(node.tag)
            if node.tag == "view" and node.attrs.get("class"):
                custom.add(node.attrs["class"])
            if node.tag in _FRAGMENT_TAGS and node.attrs.get("android:name"):
                fragments.add(node.attrs["android:name"])
            if node.tag == "ComposeView" or node.tag.endswith(".ComposeView"):
                compose_view = True
            if node.tag == "include":
                found = _INCLUDE_REF.match(node.attrs.get("layout", ""))
                if found:
                    includes.add(found.group(1))
            if node.tag == "variable" and node.attrs.get("name"):
                variables.add(f"{node.attrs['name']}: {node.attrs.get('type', '?')}")
    kind = "data_binding" if data_binding else "view_binding"
    index.kind[fact_id] = kind
    attrs: dict = {
        "name": name,
        "module": label,
        "root": sorted(root_tags)[0] if len(root_tags) == 1 else ",".join(sorted(root_tags)),
        "variants": tuple(sorted(p.rsplit("/", 2)[-2] for p in paths)),
        "view_ids": tuple(sorted(ids))[:200],
        "data_binding": data_binding,
        "compose_view": compose_view,
        "binding_class": binding_class_name(name),
    }
    if custom:
        attrs["custom_views"] = tuple(sorted(custom))
    if includes:
        attrs["includes"] = tuple(sorted(includes))
    if fragments:
        attrs["fragments"] = tuple(sorted(fragments))
    if variables:
        attrs["binding_variables"] = tuple(sorted(variables))
    if context:
        attrs["tools_context"] = safe(context, 100)
    if expressions:
        attrs["has_binding_expressions"] = True
        run.store.limit(
            "data_binding_expressions_not_analysed",
            paths[0],
            "data-binding expressions (@{...}) are not analysed",
            affects_completeness=False,
        )
    run.fact(
        "layout",
        f"{label}|{name}",
        basis="layout",
        evidence=evidence,
        attrs=attrs,
        tags=(f"module:{label}", "ui:xml"),
    )


def _layout_edges(run: Run, index: LayoutIndex, module: str, name: str, paths: list[str]) -> None:
    label = module_label(module)
    source_id = make_id("layout", f"{label}|{name}")
    store = run.store
    package = run.a.namespace_for(paths[0]) or ""
    for path in paths:
        doc = run.a.xml_docs[path]
        if doc.root is None:
            continue
        for node in doc.root.iter():
            ev = [run.xml_evidence(path, node.line)]
            if node.tag == "include":
                found = _INCLUDE_REF.match(node.attrs.get("layout", ""))
                if found:
                    for target, status in index.pick(found.group(1), module):
                        if target != source_id:
                            store.relate(
                                source_id,
                                "includes",
                                target,
                                basis="layout",
                                status=status,
                                evidence=ev,
                                note=None
                                if status == "confirmed"
                                else "the layout name exists in several modules",
                            )
            fragment = node.attrs.get("android:name") if node.tag in _FRAGMENT_TAGS else None
            if fragment:
                _link_class(run, source_id, "hosts_fragment", fragment, package, ev)
            custom = node.attrs.get("class") if node.tag == "view" else node.tag
            if custom and "." in custom and not custom.startswith(_WIDGET_PACKAGES):
                _link_class(run, source_id, "uses_view", custom, package, ev)
        context = doc.root.attrs.get("tools:context")
        if context:
            _link_class(
                run,
                source_id,
                "designed_for",
                context,
                package,
                [run.xml_evidence(path, doc.root.line)],
                inferred="tools:context is a design-time hint",
            )


def _link_class(
    run: Run,
    source_id: str,
    kind: str,
    class_name: str,
    package: str,
    evidence: list[Evidence],
    inferred: str | None = None,
) -> None:
    from .components import resolve_class_name

    fqn = resolve_class_name(class_name, package)
    for candidate in ("fragment", "activity", "type"):
        target = make_id(candidate, fqn)
        if run.store.has(target):
            run.store.relate(
                source_id,
                kind,
                target,
                basis="layout",
                status="inferred" if inferred else "confirmed",
                evidence=evidence,
                note=inferred,
            )
            return


def _containing(run: Run, info: FileInfo, offset: int) -> str:
    holder = info.type_at(offset)
    if holder is not None and run.store.has(make_id("type", holder.fqn)):
        return make_id("type", holder.fqn)
    return make_id("file", info.path)


def _layout_usage(run: Run, index: LayoutIndex) -> None:
    store = run.store
    binding_map: dict[str, list[tuple[str, str]]] = defaultdict(
        list
    )  # class -> (module, layout id)
    for name, entries in index.by_name.items():
        for module, fact_id in entries:
            binding_map[binding_class_name(name)].append((module, fact_id))
    for info in run.app_sources():
        if run.expired():
            return
        module = run.module_of(info.path)
        namespace = run.a.namespace_for(info.path) or ""
        masked = info.view.masked
        for match in _LAYOUT_REF.finditer(masked):
            for target, status in index.pick(match.group(1), module):
                source_id = _containing(run, info, match.start())
                store.relate(
                    source_id,
                    "uses_layout",
                    target,
                    basis="source",
                    status=status,
                    evidence=[info.view.evidence(match.start())],
                    note=None
                    if status == "confirmed"
                    else "the layout name exists in several modules",
                )
                holder = source_id if source_id.startswith("type:") else None
                if holder:
                    _mark_ui(run, holder, "xml")
        for imp in info.source.imports:
            found = _SYNTHETIC.match(imp.fqn)
            if found:
                offset = info.view.lines.line_start(imp.line) or 0
                for target, status in index.pick(found.group(1), module):
                    store.relate(
                        make_id("file", info.path),
                        "uses_layout",
                        target,
                        basis="source",
                        status=status,
                        evidence=[info.view.evidence(offset)],
                        note=None
                        if status == "confirmed"
                        else "the layout name exists in several modules",
                    )
        _binding_usage(run, info, index, binding_map, namespace)


def _mark_ui(run: Run, type_fact: str, toolkit: str) -> None:
    fqn = type_fact.split(":", 1)[1]
    for role in ("activity", "fragment"):
        run.store.annotate(make_id(role, fqn), attrs={"ui": toolkit}, tags=(f"ui:{toolkit}",))


def _binding_usage(
    run: Run,
    info: FileInfo,
    index: LayoutIndex,
    binding_map: dict[str, list[tuple[str, str]]],
    namespace: str,
) -> None:
    store = run.store
    explicit = {
        imp.simple_name: imp
        for imp in info.source.imports
        if not imp.wildcard and not imp.static and imp.simple_name
    }
    wildcard_pkgs = {imp.fqn for imp in info.source.imports if imp.wildcard and not imp.static}
    databinding_wildcard = any(pkg.endswith(".databinding") for pkg in wildcard_pkgs)
    for name, offset in sorted(info.source.used_names.items()):
        if not _BINDING_NAME.match(name) or name not in binding_map:
            continue
        imp = explicit.get(name)
        generated = f"{namespace}.databinding.{name}" if namespace else None
        if imp is not None and ".databinding." in f".{imp.fqn}":
            status, note = "confirmed", None
            if generated and imp.fqn != generated:
                status, note = "inferred", "the import is a databinding class of another package"
        elif databinding_wildcard:
            status, note = "confirmed", None
        else:
            status = "inferred"
            note = "the name matches the binding class generated for a layout; no import shows it"
        module = run.module_of(info.path)
        options = [o for o in binding_map[name] if o[0] == module_label(module)] or binding_map[
            name
        ]
        for _, layout_id in options[:3]:
            layout_name = layout_id.split("|", 1)[1]
            kind = index.kind.get(layout_id, "view_binding")
            binding_id = run.fact(
                "binding",
                f"{module_label(module)}|{name}",
                basis="source",
                status=status,
                note=note,
                evidence=[info.view.evidence(offset)],
                attrs={"layout": layout_name, "binding_kind": kind, "class": name},
                tags=("ui:xml", f"module:{module_label(module)}"),
            )
            holder = info.type_at(offset)
            source_id = (
                make_id("type", holder.fqn)
                if holder is not None and store.has(make_id("type", holder.fqn))
                else make_id("file", info.path)
            )
            evidence = [info.view.evidence(offset)]
            store.relate(
                binding_id,
                "generated_from",
                layout_id,
                basis="layout",
                status=status,
                evidence=evidence,
                note=note,
            )
            store.relate(
                source_id,
                "uses_binding",
                binding_id,
                basis="source",
                status=status,
                evidence=evidence,
                note=note,
            )
            store.relate(
                source_id,
                "uses_layout",
                layout_id,
                basis="source",
                status=status,
                evidence=evidence,
                note=note,
            )
            if source_id.startswith("type:"):
                _mark_ui(run, source_id, "xml")
