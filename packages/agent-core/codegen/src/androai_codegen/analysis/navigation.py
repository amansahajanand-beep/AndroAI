"""Navigation facts: Compose routes, XML navigation graphs, actions, deep links, and their users.

Compose routes and ``NavHost`` start destinations are taken from the review engine's navigation scan
(``ProjectAnalysis.navigation``), which already resolves ``const val`` route names. This module
adds what that scan does not keep: which composable each destination shows, which route a
``navigate`` call is made from, and the XML graph structure (destinations, actions, arguments).

A route that is computed, a graph built by a function that is not read, and Navigation 3 are
reported as ``unknown`` facts with a limitation: they are never silently treated as "no navigation".
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from androai_codegen.review.navigation import id_name, nav_resource_name
from androai_codegen.review.xmlparse import XmlNode

from .components import resolve_class_name
from .context import Run, module_label
from .members import FileInfo
from .model import Evidence
from .screens import ComposeIndex, mark_screen, project_calls
from .store import make_id
from .text import redact_url, safe, split_spans

_DEST_CALL_ANY = re.compile(r"(?<![\w])(composable|dialog)\s*(?:<\s*([\w.]+)\s*>)?\s*[({]")
_TYPED_ANY = re.compile(r"(?<![\w.])(?:composable|dialog|navigation)\s*<\s*([\w.]+)\s*>\s*[({]")
_CONTENT_ARG = re.compile(r"(?<![\w.])content\s*=\s*\{")
_ARGUMENT = re.compile(r"\{(\w+)\}")
_XML_NAVIGATE = re.compile(r"\.\s*navigate\s*\(\s*R\.id\.(\w+)")
_DIRECTIONS = re.compile(r"(?<![\w.])(\w+)Directions\s*\.\s*(action\w+)\s*\(")
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")
_DEST_TAGS = ("fragment", "activity", "dialog", "navigation", "include")


@dataclass
class _Span:
    path: str
    start: int
    end: int
    route_id: str


def extract_navigation(run: Run, compose: ComposeIndex) -> None:
    facts = run.a.navigation
    store = run.store
    if facts.compose.unsupported:
        run.fact(
            "navigation",
            "navigation3",
            basis="navigation",
            status="unknown",
            reason="Navigation 3 (NavDisplay / NavKey) is used; its back stack is not analysed",
        )
        store.limit(
            "navigation3_unsupported", "project", "Navigation 3 is in use and is not analysed"
        )
    if facts.compose.dynamic:
        run.fact(
            "navigation",
            "compose",
            basis="navigation",
            status="unknown",
            reason="some Compose routes or start destinations are computed, so the list of "
            "destinations may be incomplete",
        )
        store.limit(
            "dynamic_navigation",
            "project",
            "some Compose destinations or start routes are computed and cannot be listed",
        )
    spans = _compose_routes(run, compose)
    _compose_navigates(run, spans, compose)
    _xml_navigation(run)


# -- Compose -------------------------------------------------------------------------------------


def _route_id(subject: str) -> str:
    return make_id("compose_route", subject)


def _line_evidence(run: Run, path: str, line: int) -> list[Evidence]:
    info = run.infos.get(path)
    if info is None:
        return [Evidence(path=path, line=line)]
    return [Evidence(path=path, line=line, excerpt=info.view.lines.excerpt_at_line(line))]


def _compose_routes(run: Run, compose: ComposeIndex) -> list[_Span]:
    compose_nav = run.a.navigation.compose
    store = run.store
    declared: dict[tuple[str, int], str] = {}
    for route in compose_nav.declared:
        declared[(route.path, route.line)] = route.pattern
        arguments = tuple(sorted(set(_ARGUMENT.findall(route.pattern))))
        attrs: dict = {"route": safe(route.pattern, 200), "typed": False}
        if route.scope:
            attrs["scope"] = route.scope
        if arguments:
            attrs["arguments"] = arguments
        run.fact(
            "compose_route",
            safe(route.pattern, 200),
            basis="navigation",
            evidence=_line_evidence(run, route.path, route.line),
            attrs=attrs,
            tags=(*run.path_tags(route.path), "ui:compose"),
        )
    for start in compose_nav.starts:
        subject = safe(start.route, 200) if start.route is not None else f"typed:{start.type_name}"
        run.fact(
            "compose_route",
            subject,
            basis="navigation",
            evidence=_line_evidence(run, start.path, start.line),
            attrs={"start_destination": True},
            tags=(*run.path_tags(start.path), "ui:compose"),
        )
    for link in compose_nav.deeplinks:
        run.fact(
            "deep_link",
            redact_url(link.pattern, 200),
            basis="navigation",
            evidence=_line_evidence(run, link.path, link.line),
            attrs={"source": "compose"},
            tags=(*run.path_tags(link.path), "ui:compose"),
        )
    spans: list[_Span] = []
    for info in run.app_sources():
        masked = info.view.masked
        if not info.path.endswith(".kt") or ("composable" not in masked and "dialog" not in masked):
            continue
        for match in _TYPED_ANY.finditer(info.view.masked):
            simple = match.group(1).rsplit(".", 1)[-1]
            if len(simple) == 1 and simple.isupper():
                continue
            resolved = run.resolver.resolve(info.source, match.group(1))
            run.fact(
                "compose_route",
                f"typed:{simple}",
                basis="navigation",
                evidence=[info.view.evidence(match.start())],
                attrs={"typed": True, "route_type": resolved.fqn or simple},
                tags=(*run.path_tags(info.path), "ui:compose"),
            )
            if resolved.fqn and store.has(make_id("type", resolved.fqn)):
                store.relate(
                    _route_id(f"typed:{simple}"),
                    "route_type",
                    make_id("type", resolved.fqn),
                    basis="navigation",
                    status="confirmed" if resolved.exact else "inferred",
                    evidence=[info.view.evidence(match.start())],
                    note=None if resolved.exact else "the route type is matched by name only",
                )
        for match in _DEST_CALL_ANY.finditer(info.view.masked):
            line = info.view.line(match.start())
            subject = declared.get((info.path, line))
            if match.group(2):
                subject = f"typed:{match.group(2).rsplit('.', 1)[-1]}"
            elif subject is None and _has_receiver(info, match):
                # ``builder.composable("a") { }``: the review scan only sees bare calls
                subject = _receiver_route(run, info, match)
            span = _destination_span(info, match)
            if span is None or subject is None:
                continue
            route_id = _route_id(
                safe(subject, 200) if not subject.startswith("typed:") else subject
            )
            if not store.has(route_id):
                continue
            spans.append(_Span(info.path, span[0], span[1], route_id))
            _renders(run, compose, info, span, route_id)
    return spans


def _has_receiver(info: FileInfo, match: re.Match[str]) -> bool:
    """A destination call written ``something.composable(...)`` in a file that uses navigation."""
    before = info.view.masked[: match.start()].rstrip()
    return before.endswith(".") and "androidx.navigation" in info.view.text


def _receiver_route(run: Run, info: FileInfo, match: re.Match[str]) -> str | None:
    """The literal route of an explicit-receiver destination call, recorded as a route fact.

    A route that is not a plain string (a variable, a template) cannot be listed: that is an
    ``unknown`` fact and a limitation, never silence.
    """
    view = info.view
    open_index = match.end() - 1
    literal: str | None = None
    if view.masked[open_index] == "(":
        close = view.close.get(open_index)
        spans = split_spans(view.masked, open_index + 1, close) if close is not None else []
        if spans:
            start = view.skip_space(spans[0][0], spans[0][1])
            named = re.match(r"route\s*=\s*", view.masked[start : spans[0][1]])
            if named:
                start += named.end()
            string = info.source.lexed.string_starting_at(start)
            if string is not None and string.terminated:
                value = info.source.lexed.string_value(string)
                literal = value if "$" not in value else None
    if literal is None:
        run.fact(
            "navigation",
            "compose",
            basis="navigation",
            status="unknown",
            reason="some Compose routes or start destinations are computed, so the list of "
            "destinations may be incomplete",
        )
        run.store.limit(
            "dynamic_navigation",
            "project",
            "some Compose destinations or start routes are computed and cannot be listed",
        )
        return None
    arguments = tuple(sorted(set(_ARGUMENT.findall(literal))))
    attrs: dict = {"route": safe(literal, 200), "typed": False}
    if arguments:
        attrs["arguments"] = arguments
    run.fact(
        "compose_route",
        safe(literal, 200),
        basis="navigation",
        evidence=[view.evidence(match.start())],
        attrs=attrs,
        tags=(*run.path_tags(info.path), "ui:compose"),
    )
    return literal


def _destination_span(info: FileInfo, match: re.Match[str]) -> tuple[int, int] | None:
    view = info.view
    m = view.masked
    open_index = match.end() - 1
    if m[open_index] == "{":
        close = view.close.get(open_index)
        return (open_index, close) if close is not None else None
    close_paren = view.close.get(open_index)
    if close_paren is None:
        return None
    after = view.skip_space(close_paren + 1, len(m))
    if m[after : after + 1] == "{":
        close = view.close.get(after)
        return (after, close) if close is not None else None
    inside = _CONTENT_ARG.search(m, open_index, close_paren)
    if inside:
        brace = inside.end() - 1
        close = view.close.get(brace)
        return (brace, close) if close is not None else None
    return None


def _renders(
    run: Run, compose: ComposeIndex, info: FileInfo, span: tuple[int, int], route_id: str
) -> None:
    taken = 0
    seen: set[str] = set()
    for name, offset in project_calls(info, span):
        for entry, certain in compose.resolve(info, name):
            if entry.preview or entry.wrapper or entry.fact_id in seen:
                continue
            seen.add(entry.fact_id)
            status = "confirmed" if certain else "inferred"
            note = None if certain else "the call matches one composable by name only"
            evidence = [info.view.evidence(offset)]
            run.store.relate(
                route_id,
                "renders",
                entry.fact_id,
                basis="navigation",
                status=status,
                evidence=evidence,
                note=note,
            )
            if not entry.nav_host:
                mark_screen(
                    run,
                    entry,
                    status=status,
                    basis="navigation",
                    note=note or None,
                    evidence=evidence,
                )
            taken += 1
            if taken >= 3:
                return


def _compose_navigates(run: Run, spans: list[_Span], compose: ComposeIndex) -> None:
    store = run.store
    rendered_by: dict[str, list[str]] = defaultdict(list)
    for source_id, target_id in store.relation_pairs("renders"):
        rendered_by[target_id].append(source_id)
    for use in run.a.navigation.compose.navigates:
        info = run.infos.get(use.path)
        if info is None:
            continue
        start = info.view.lines.line_start(use.line)
        if start is None:
            continue
        offset = start + use.column - 1
        target = (
            _route_id(safe(use.route, 200))
            if use.route is not None
            else _route_id(f"typed:{use.type_name}")
        )
        if not store.has(target):
            continue
        evidence = [info.view.evidence(offset)]
        inside = [s for s in spans if s.path == use.path and s.start < offset < s.end]
        if inside:
            source = min(inside, key=lambda s: s.end - s.start)
            store.relate(
                source.route_id, "navigates_to", target, basis="navigation", evidence=evidence
            )
            continue
        function = info.function_at(offset)
        if function is None:
            continue
        composable_id = make_id("composable", f"{function.owner}#{function.signature}")
        if composable_id in rendered_by:
            for route in sorted(set(rendered_by[composable_id])):
                store.relate(
                    route,
                    "navigates_to",
                    target,
                    basis="navigation",
                    status="inferred",
                    evidence=evidence,
                    note=f"the navigate call is in {function.name}, which this route shows",
                )
        source_id = (
            composable_id
            if store.has(composable_id)
            else make_id("member", f"{function.owner}#{function.signature}")
        )
        if store.has(source_id):
            store.relate(source_id, "navigates_to", target, basis="navigation", evidence=evidence)


# -- XML navigation graphs -----------------------------------------------------------------------


@dataclass
class _Pending:
    source: str
    target_name: str
    graph_key: str
    evidence: list[Evidence]


def _xml_navigation(run: Run) -> None:
    store = run.store
    dest_by_id: dict[str, list[tuple[str, str]]] = defaultdict(list)  # id -> (graph key, fact id)
    local_ids: dict[str, dict[str, str]] = defaultdict(dict)
    actions: list[_Pending] = []
    starts: list[tuple[str, str, str, list[Evidence]]] = []  # graph fact, key, id, evidence
    includes: list[tuple[str, str, list[Evidence]]] = []
    action_targets: dict[str, list[str]] = defaultdict(list)  # action id -> target dest ids
    for path in sorted(run.a.xml_docs):
        resname = nav_resource_name(path)
        doc = run.a.xml_docs[path]
        if resname is None or doc.root is None or doc.root.tag != "navigation":
            continue
        label = module_label(run.module_of(path))
        namespace = run.a.namespace_for(path) or ""
        key = f"{label}|{resname}"
        root_id = run.fact(
            "nav_graph",
            key,
            basis="navigation",
            evidence=[run.xml_evidence(path, doc.root.line)],
            attrs={"resource": resname, "path": path, "module": label},
            tags=(f"module:{label}", "ui:xml"),
        )
        own = id_name(doc.root.attrs.get("android:id"))
        if own:
            dest_by_id[own].append((key, root_id))
            local_ids[key][own] = root_id
        _walk(
            run,
            path,
            doc.root,
            root_id,
            key,
            label,
            namespace,
            dest_by_id,
            local_ids,
            actions,
            starts,
            includes,
            action_targets,
        )
    for graph_id, key, ident, evidence in starts:
        target = local_ids[key].get(ident)
        if target:
            store.relate(graph_id, "starts_at", target, basis="navigation", evidence=evidence)
    for graph_id, resource, evidence in includes:
        for other in store.ids_of_kind("nav_graph"):
            if other.split(":", 1)[1].endswith(f"|{resource}") and other != graph_id:
                store.relate(graph_id, "includes", other, basis="navigation", evidence=evidence)
    for pending in actions:
        for target in _lookup(pending.target_name, pending.graph_key, dest_by_id, local_ids):
            store.relate(
                pending.source,
                "navigates_to",
                target,
                basis="navigation",
                evidence=pending.evidence,
            )
    _code_navigation(run, dest_by_id, local_ids, action_targets)


def _lookup(
    name: str,
    graph_key: str,
    dest_by_id: dict[str, list[tuple[str, str]]],
    local_ids: dict[str, dict[str, str]],
) -> list[str]:
    if name in local_ids.get(graph_key, {}):
        return [local_ids[graph_key][name]]
    options = dest_by_id.get(name, [])
    return [options[0][1]] if len(options) == 1 else []


def _walk(
    run: Run,
    path: str,
    node: XmlNode,
    graph_id: str,
    key: str,
    label: str,
    namespace: str,
    dest_by_id: dict[str, list[tuple[str, str]]],
    local_ids: dict[str, dict[str, str]],
    actions: list[_Pending],
    starts: list[tuple[str, str, str, list[Evidence]]],
    includes: list[tuple[str, str, list[Evidence]]],
    action_targets: dict[str, list[str]],
) -> None:
    store = run.store
    start = id_name(node.attrs.get("app:startDestination"))
    if start:
        starts.append((graph_id, key, start, [run.xml_evidence(path, node.line)]))
    for action in node.child_nodes("action"):
        _action(run, path, action, graph_id, key, actions, action_targets)
    for child in node.children:
        if child.tag not in _DEST_TAGS:
            continue
        evidence = [run.xml_evidence(path, child.line)]
        if child.tag == "include":
            ref = child.attrs.get("app:graph", "").removeprefix("@navigation/")
            if ref:
                includes.append((graph_id, ref, evidence))
            continue
        ident = id_name(child.attrs.get("android:id"))
        class_name = child.attrs.get("android:name")
        fqn = resolve_class_name(class_name, namespace) if class_name else None
        subject = f"{key}|{ident or fqn or f'{child.tag}@{child.line}'}"
        attrs: dict = {"tag": child.tag, "graph": key, "module": label}
        if ident:
            attrs["id"] = ident
        if fqn:
            attrs["class"] = fqn
        if child.attrs.get("android:label"):
            attrs["label"] = safe(child.attrs["android:label"], 100)
        arguments = tuple(
            sorted(
                a.attrs["android:name"]
                for a in child.child_nodes("argument")
                if a.attrs.get("android:name")
            )
        )
        if arguments:
            attrs["arguments"] = arguments
        dest_id = run.fact(
            "nav_nested_graph" if child.tag == "navigation" else "nav_destination",
            subject,
            basis="navigation",
            evidence=evidence,
            attrs=attrs,
            tags=(f"module:{label}", "ui:xml"),
        )
        store.relate(graph_id, "contains", dest_id, basis="navigation", evidence=evidence)
        if ident:
            dest_by_id[ident].append((key, dest_id))
            local_ids[key][ident] = dest_id
        if fqn:
            for candidate in ("fragment", "activity", "type"):
                target = make_id(candidate, fqn)
                if store.has(target):
                    store.relate(
                        dest_id, "implemented_by", target, basis="navigation", evidence=evidence
                    )
                    break
        for link in child.iter():
            if link.tag == "deepLink" and link.attrs.get("app:uri"):
                uri = redact_url(link.attrs["app:uri"], 200)
                link_id = run.fact(
                    "deep_link",
                    uri,
                    basis="navigation",
                    evidence=[run.xml_evidence(path, link.line)],
                    attrs={"source": "nav_xml"},
                    tags=(f"module:{label}", "ui:xml"),
                )
                store.relate(
                    dest_id,
                    "handles_deep_link",
                    link_id,
                    basis="navigation",
                    evidence=[run.xml_evidence(path, link.line)],
                )
        if child.tag == "navigation":
            _walk(
                run,
                path,
                child,
                dest_id,
                key,
                label,
                namespace,
                dest_by_id,
                local_ids,
                actions,
                starts,
                includes,
                action_targets,
            )
        else:
            for action in child.child_nodes("action"):
                _action(run, path, action, dest_id, key, actions, action_targets)


def _action(
    run: Run,
    path: str,
    action: XmlNode,
    source_id: str,
    key: str,
    actions: list[_Pending],
    action_targets: dict[str, list[str]],
) -> None:
    target = id_name(action.attrs.get("app:destination"))
    if not target:
        return
    actions.append(_Pending(source_id, target, key, [run.xml_evidence(path, action.line)]))
    ident = id_name(action.attrs.get("android:id"))
    if ident:
        action_targets[ident].append(f"{key}|{target}")


def _code_navigation(
    run: Run,
    dest_by_id: dict[str, list[tuple[str, str]]],
    local_ids: dict[str, dict[str, str]],
    action_targets: dict[str, list[str]],
) -> None:
    store = run.store
    for info in run.app_sources():
        masked = info.view.masked
        if "navigate" not in masked and "Directions" not in masked:
            continue
        for match in _XML_NAVIGATE.finditer(masked):
            name = match.group(1)
            holder = info.type_at(match.start())
            source = make_id("type", holder.fqn) if holder else make_id("file", info.path)
            evidence = [info.view.evidence(match.start())]
            options = dest_by_id.get(name, [])
            if len(options) == 1:
                store.relate(
                    source, "navigates_to", options[0][1], basis="source", evidence=evidence
                )
            for packed in action_targets.get(name, [])[:1]:
                graph_key, _, target = packed.rpartition("|")
                for dest in _lookup(target, graph_key, dest_by_id, local_ids):
                    store.relate(source, "navigates_to", dest, basis="source", evidence=evidence)
        for match in _DIRECTIONS.finditer(masked):
            snake = _CAMEL.sub("_", match.group(2)).lower()
            holder = info.type_at(match.start())
            source = make_id("type", holder.fqn) if holder else make_id("file", info.path)
            for packed in action_targets.get(snake, [])[:1]:
                graph_key, _, target = packed.rpartition("|")
                for dest in _lookup(target, graph_key, dest_by_id, local_ids):
                    store.relate(
                        source,
                        "navigates_to",
                        dest,
                        basis="source",
                        status="inferred",
                        evidence=[info.view.evidence(match.start())],
                        note="a Safe Args Directions method was mapped to the action id by name",
                    )
