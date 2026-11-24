"""The relationship graph and the tags that make it queryable.

Edges added here (the extractors add their own, such as ``renders`` or ``injects``):

``module contains file``       a file belongs to a module (by directory)
``file declares type``         a declaration is in a file
``type extends/implements``    a supertype that resolves to a project type
``file references type``       a project type is used by name in a file
``type hosts_fragment``        derived: an Activity whose layout holds a fragment (inferred)
``layout uses_nav_graph``      a layout's ``app:navGraph``

Tags are derived last, from facts and edges that already exist: ``role:*`` (what a type is),
``layer:*`` (ui, presentation, data, network, di, app, android_component) and ``entry-point``.
Layers are assigned from roles read from the code, never from a class or package name.
"""

from __future__ import annotations

import re

from .context import Run, module_label
from .store import make_id

MAX_REFERENCES_PER_FILE = 200
_NAV_GRAPH = re.compile(r"@navigation/(\w+)")
_LAYER_BY_KIND = {
    "activity": "ui",
    "activity_alias": "ui",
    "fragment": "ui",
    "composable": "ui",
    "compose_screen": "ui",
    "layout": "ui",
    "binding": "ui",
    "adapter": "ui",
    "custom_view": "ui",
    "viewmodel": "presentation",
    "hilt_viewmodel": "presentation",
    "room_database": "data",
    "room_entity": "data",
    "room_dao": "data",
    "shared_preferences": "data",
    "datastore": "data",
    "sqlite_helper": "data",
    "file_storage": "data",
    "retrofit_service": "network",
    "http_endpoint": "network",
    "http_interceptor": "network",
    "base_url": "network",
    "di_module": "di",
    "di_injectable": "di",
    "koin_module": "di",
    "dagger_component": "di",
    "hilt_application": "app",
    "application": "app",
    "service": "android_component",
    "receiver": "android_component",
    "provider": "android_component",
    "worker": "android_component",
}
_ENTRY_KINDS = ("hilt_application", "application", "hilt_android_entry")


def build_graph(run: Run) -> None:
    _file_edges(run)
    _extends(run)
    _references(run)
    _layout_derived(run)
    _tags(run)


def _file_edges(run: Run) -> None:
    store = run.store
    for path in sorted(run.infos):
        info = run.infos[path]
        file_id = make_id("file", path)
        module = run.a.module_of(path)
        if module is not None:
            module_id = make_id("module", module_label(module))
            if store.has(module_id):
                store.relate(
                    module_id,
                    "contains",
                    file_id,
                    basis="gradle",
                    evidence=[run.path_evidence(path)],
                )
        for decl in info.types:
            store.relate(
                file_id,
                "declares",
                make_id("type", decl.fqn),
                basis="source",
                evidence=[info.view.evidence(decl.offset)],
            )


def _extends(run: Run) -> None:
    store = run.store
    for fqn in sorted(run.types):
        decl = run.types[fqn]
        info = run.infos.get(decl.path)
        if info is None:
            continue
        for sup in decl.supertypes:
            resolved = run.resolver.resolve(info.source, sup.written, decl.owner)
            target = run.types.get(resolved.fqn or "")
            if target is None or target.fqn == decl.fqn or resolved.how == "unresolved":
                continue
            kind = "implements" if target.kind == "interface" else "extends"
            store.relate(
                make_id("type", decl.fqn),
                kind,
                make_id("type", target.fqn),
                basis="source",
                status="confirmed" if resolved.exact else "inferred",
                evidence=[info.view.evidence(decl.offset)],
                note=None if resolved.exact else "the supertype is matched by name only",
            )


def _references(run: Run) -> None:
    store = run.store
    for path in sorted(run.infos):
        if run.expired():
            return
        if run.is_build_logic(path):
            continue
        info = run.infos[path]
        own = {d.fqn for d in info.types}
        file_id = make_id("file", path)
        count = 0
        for name, offset in sorted(info.source.used_names.items()):
            if count >= MAX_REFERENCES_PER_FILE:
                break
            resolved = run.resolver.resolve(info.source, name)
            if not resolved.fqn or resolved.fqn in own or resolved.fqn not in run.types:
                continue
            store.relate(
                file_id,
                "references",
                make_id("type", resolved.fqn),
                basis="source",
                status="confirmed" if resolved.exact else "inferred",
                evidence=[info.view.evidence(offset)],
                note=None
                if resolved.exact
                else "the name matches one project type; no import shows it",
            )
            count += 1


def _layout_derived(run: Run) -> None:
    store = run.store
    graphs = {store.attribute(i, "resource"): i for i in store.ids_of_kind("nav_graph")}
    for layout_id in store.ids_of_kind("layout"):
        names = {
            m.group(1)
            for path in _layout_paths(run, layout_id)
            for m in _NAV_GRAPH.finditer(_nav_attr_text(run, path))
        }
        for name in sorted(names):
            if name in graphs:
                store.relate(
                    layout_id,
                    "uses_nav_graph",
                    graphs[name],
                    basis="layout",
                    evidence=[run.path_evidence(_layout_paths(run, layout_id)[0])],
                )
    uses = store.relation_pairs("uses_layout")
    hosts = {}
    for source, target in store.relation_pairs("hosts_fragment"):
        if source.startswith("layout:"):
            hosts.setdefault(source, []).append(target)
    graph_uses: dict[str, list[str]] = {}
    for source, target in store.relation_pairs("uses_nav_graph"):
        graph_uses.setdefault(source, []).append(target)
    for holder, layout_id in uses:
        if not holder.startswith("type:"):
            continue
        for fragment in hosts.get(layout_id, []):
            store.relate(
                holder,
                "hosts_fragment",
                fragment,
                basis="layout",
                status="inferred",
                evidence=[run.path_evidence(_layout_paths(run, layout_id)[0])],
                note=f"the layout {layout_id.split(':', 1)[1]} holds this fragment",
            )
        for graph in graph_uses.get(layout_id, []):
            store.relate(
                holder,
                "uses_nav_graph",
                graph,
                basis="layout",
                status="inferred",
                evidence=[run.path_evidence(_layout_paths(run, layout_id)[0])],
                note=f"the layout {layout_id.split(':', 1)[1]} points at this navigation graph",
            )


def _layout_paths(run: Run, layout_id: str) -> list[str]:
    subject = layout_id.split(":", 1)[1]
    module, _, name = subject.partition("|")
    paths = [
        p
        for p in sorted(run.a.xml_docs)
        if re.search(rf"(?:^|/)res/layout(?:-[^/]+)?/{re.escape(name)}\.xml$", p)
        and module_label(run.module_of(p)) == module
    ]
    return paths or [""]


def _nav_attr_text(run: Run, path: str) -> str:
    doc = run.a.xml_docs.get(path)
    if doc is None or doc.root is None:
        return ""
    return " ".join(
        node.attrs["app:navGraph"] for node in doc.root.iter() if "app:navGraph" in node.attrs
    )


def _tags(run: Run) -> None:
    store = run.store
    for kind, layer in _LAYER_BY_KIND.items():
        for fact_id in store.ids_of_kind(kind):
            store.tag(fact_id, f"layer:{layer}", f"role:{kind}")
    for source, target in store.relation_pairs("role_of"):
        kind = source.split(":", 1)[0]
        tags = [f"role:{kind}"]
        layer = _LAYER_BY_KIND.get(kind)
        if layer:
            tags.append(f"layer:{layer}")
        store.tag(target, *tags)
    for kind in _ENTRY_KINDS:
        for fact_id in store.ids_of_kind(kind):
            store.tag(fact_id, "entry-point")
            store.tag(make_id("type", fact_id.split(":", 1)[1]), "entry-point")
    for kind in ("activity", "activity_alias"):
        for fact_id in store.ids_of_kind(kind):
            if store.attribute(fact_id, "launcher") is True:
                store.tag(fact_id, "entry-point", "launcher")
                store.tag(make_id("type", fact_id.split(":", 1)[1]), "entry-point", "launcher")
