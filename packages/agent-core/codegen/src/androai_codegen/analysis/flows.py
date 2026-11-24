"""Entry points and application flows (M2B, task M2.9).

Three things are added here, none of them by running anything:

``entry_point``
    A manifest component that the system or another app can start: the launcher activity, the
    Application class, and every exported component (an intent filter makes a component exported
    when ``android:exported`` is absent). Always ``confirmed``, read from the manifest.

Intent targets (``launches_activity`` edges, ``intent_launch`` facts)
    An explicit Intent names its target with a class literal (``Intent(this, X::class.java)``,
    ``new Intent(ctx, X.class)``, ``setClass``, ``ComponentName``): the target is read, so the edge
    is ``confirmed`` when the Intent is passed straight to ``startActivity`` (or ``launch``), and
    ``inferred`` when this analysis cannot see it being started. An implicit Intent names an action
    (a string literal or an ``Intent.ACTION_*`` constant): it is matched to the manifest components
    whose intent filters declare that action. That is always ``inferred``: Android picks the target
    at run time, and another app may also match. Everything else is ``unknown`` with a reason, never
    an edge: a computed class or action, and an Intent that is built for a ``PendingIntent`` or a
    ``TaskStackBuilder`` (a launch that happens later is not modelled). ``ActivityResultContracts``,
    reflection and ``Class.forName`` are not modelled.

``app_flow``
    What can be reached from an entry point: a bounded breadth-first walk over the navigation edges
    that already exist (Compose routes, XML graphs, Fragment transactions, ``setContent``) and the
    Intent edges above. A flow lists screens, not paths, and says whether it reached its cap
    (``truncated``) or a place it cannot follow (``dynamic``); then an ``unknown`` ``flow_gap``
    fact says why. Composable calls are followed from a reached composable to find a ``NavHost``,
    and a ``NavHost`` is linked to the start route written inside the same composable: both are
    ``inferred``.

Presence only: a screen that is not in a flow was not reached by what this analysis can read, which
is not a claim that it cannot be reached.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass

from .context import Run
from .members import FileInfo
from .model import Evidence, FactStatus
from .screens import Composable, ComposeIndex, project_calls
from .store import make_id
from .text import split_spans

COMPONENT_KINDS = ("activity", "activity_alias", "service", "receiver", "provider")
SCREEN_KINDS = frozenset(
    {"activity", "activity_alias", "fragment", "composable", "compose_route", "nav_destination"}
)
# Edges a flow follows. ``renders``: a route shows a composable; ``starts_at``: a graph (or a
# NavHost, see ``_bridge_nav_host``) begins at a destination; ``implemented_by``: a destination is
# a Fragment or Activity class.
FLOW_EDGES = (
    "launches_activity",
    "navigates_to",
    "hosts_content",
    "hosts_fragment",
    "renders",
    "starts_at",
    "implemented_by",
    "uses_nav_graph",
    "calls_composable",
)
_ROLES = (
    "activity",
    "fragment",
    "activity_alias",
    "service",
    "receiver",
    "provider",
    "application",
)
MAX_CALLS_PER_COMPOSABLE = 40

_INTENT_CTOR = re.compile(r"(?<![\w.])(?:new\s+)?Intent\s*\(")
_COMPONENT_CTOR = re.compile(r"(?<![\w.])(?:new\s+)?ComponentName\s*\(")
_SET_CLASS = re.compile(r"\.\s*setClass\s*\(")
_SET_ACTION = re.compile(r"\.\s*setAction\s*\(")
_KT_CLASS = re.compile(r"\s*([A-Za-z_][\w.]*)\s*::\s*class\s*\.\s*java\s*")
_JAVA_CLASS = re.compile(r"\s*([A-Za-z_][\w.]*)\s*\.\s*class\s*")
_ACTION_CONST = re.compile(r"\s*(?:android\.content\.)?Intent\s*\.\s*(ACTION_[A-Z0-9_]+)\s*")
_ANY_ACTION_CONST = re.compile(r"\s*(?:[A-Za-z_][\w]*\s*\.\s*)*ACTION_[A-Z0-9_]+\s*")
_ASSIGNED = re.compile(
    r"(?:\bval|\bvar|\bIntent|\bfinal\s+Intent)\s+(\w+)\s*(?::\s*[\w.?<>]+\s*)?=\s*(?:new\s+)?$"
)
_CALLEE = re.compile(r"([\w.]+)\s*(?:<[^<>]*>)?\s*$")
_URI_PARSE = re.compile(r"Uri\s*\.\s*parse\s*\(")
_LAUNCH_CALLS = frozenset(
    {
        "startActivity",
        "startActivityForResult",
        "startActivities",
        "startActivityIfNeeded",
        "launch",
    }
)
_DEFER_CALLS = frozenset(
    {
        "getActivity",
        "getActivities",
        "getService",
        "getBroadcast",
        "getForegroundService",
        "addNextIntent",
        "addNextIntentWithParentStack",
    }
)
_LOOKBACK = 400
_UNKNOWN_ACTION = "the Intent action or class is computed, so its target cannot be listed"
_DEFERRED = (
    "the Intent is built for a PendingIntent or a TaskStackBuilder; a launch that happens later "
    "is not modelled"
)


def extract_flows(run: Run, compose: ComposeIndex) -> None:
    entries = _entry_points(run)
    for info in run.app_sources():
        if run.expired():
            return
        _intents(run, info)
    _flows(run, compose, entries)


# -- entry points --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    fact_id: str  # entry_point:<subject>
    component_id: str  # the manifest fact it describes
    subject: str
    kind: str
    evidence: tuple[Evidence, ...]


def exposure(attrs: dict) -> str:
    """``true`` / ``false`` as written, ``implicit`` when an intent filter makes a component
    reachable and ``android:exported`` is absent, otherwise ``unset``."""
    value = attrs.get("exported")
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower()
    return "implicit" if attrs.get("has_intent_filter") is True else "unset"


def _entry_points(run: Run) -> list[Entry]:
    store = run.store
    entries: list[Entry] = []
    for kind in COMPONENT_KINDS:
        for fact_id in store.ids_of_kind(kind):
            attrs = store.attributes_of(fact_id)
            if "manifest" not in attrs:  # a class that only looks like a component is not declared
                continue
            reachable = exposure(attrs)
            categories: list[str] = []
            if attrs.get("launcher") is True:
                categories.append("launcher")
            if reachable in ("true", "implicit"):
                categories.append("exported_component")
                links = attrs.get("deep_links")
                if isinstance(links, tuple) and links and kind in ("activity", "activity_alias"):
                    categories.append("deep_link")
                actions = attrs.get("actions")
                if isinstance(actions, tuple) and set(actions) - {"android.intent.action.MAIN"}:
                    categories.append("intent_action")
            if not categories:
                continue
            extra: dict = {}
            for key in ("actions", "deep_links", "launch_mode"):
                if key in attrs:
                    extra[key] = attrs[key]
            made = _entry(run, fact_id, kind, tuple(sorted(categories)), reachable, attrs, extra)
            if made is not None:
                entries.append(made)
    for fact_id in store.ids_of_kind("application"):
        attrs = store.attributes_of(fact_id)
        if "class" in attrs and "manifest" in attrs:
            made = _entry(run, fact_id, "application", ("application",), "n/a", attrs, {})
            if made is not None:
                entries.append(made)
    return entries


def _entry(
    run: Run,
    component_id: str,
    kind: str,
    categories: tuple[str, ...],
    reachable: str,
    attrs: dict,
    extra: dict,
) -> Entry | None:
    store = run.store
    subject = component_id.split(":", 1)[1]
    evidence = store.evidence_of(component_id)
    if not evidence:
        return None  # a confirmed fact needs a place it was read; a manifest fact always has one
    module = attrs.get("module")
    attributes: dict = {
        "categories": categories,
        "component_kind": kind,
        "exposure": reachable,
        **extra,
    }
    tags = ["entry-point"]
    if isinstance(module, str):
        attributes["module"] = module
        tags.append(f"module:{module}")
    fact_id = run.fact(
        "entry_point",
        subject,
        basis="manifest",
        evidence=list(evidence),
        attrs=attributes,
        tags=tuple(tags),
    )
    store.relate(
        fact_id,
        "entry_point_for",
        component_id,
        basis="manifest",
        evidence=list(evidence),
    )
    return Entry(fact_id, component_id, subject, kind, evidence)


# -- Intents -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Construct:
    kind: str  # explicit | action
    offset: int
    written: str | None = None  # the class named by a class literal
    action: str | None = None  # a literal action, ``Intent.ACTION_*`` already expanded
    computed: bool = False
    uri: str | None = None  # a literal URI passed with the action


def action_name(constant: str) -> str:
    """``ACTION_VIEW`` -> ``android.intent.action.VIEW``."""
    return "android.intent.action." + constant.removeprefix("ACTION_")


def _intents(run: Run, info: FileInfo) -> None:
    text = info.view.masked
    if "Intent" not in text and "ComponentName" not in text:
        return
    found: list[_Construct] = []
    for match in _INTENT_CTOR.finditer(text):
        found.extend(_from_ctor(info, match))
    for match in _COMPONENT_CTOR.finditer(text):
        found.extend(_from_class_args(info, match))
    for match in _SET_CLASS.finditer(text):
        found.extend(_from_class_args(info, match, needs_intent=True))
    for match in _SET_ACTION.finditer(text):
        found.extend(_from_set_action(info, match))
    found.sort(key=lambda c: c.offset)
    cap = run.config.max_intents_per_file
    if len(found) > cap:
        run.store.limit(
            "intent_cap_reached",
            info.path,
            f"{len(found) - cap} Intent constructions beyond the first {cap} were not examined",
            affects_completeness=False,
        )
        found = found[:cap]
    for construct in found:
        _record(run, info, construct)


def _args(info: FileInfo, open_index: int) -> list[tuple[int, int]] | None:
    close = info.view.close.get(open_index)
    if close is None:
        return None
    return split_spans(info.view.masked, open_index + 1, close)


def _arg_text(info: FileInfo, span: tuple[int, int]) -> str:
    return info.view.masked[span[0] : span[1]]


def _class_literal(text: str) -> str | None:
    for pattern in (_KT_CLASS, _JAVA_CLASS):
        match = pattern.fullmatch(text)
        if match:
            return match.group(1)
    return None


def _string_at(info: FileInfo, span: tuple[int, int]) -> str | None:
    start = info.view.skip_space(span[0], span[1])
    literal = info.source.lexed.string_starting_at(start)
    if literal is None or not literal.terminated:
        return None
    value = info.source.lexed.string_value(literal)
    return None if "$" in value else value


def _action_of(info: FileInfo, span: tuple[int, int]) -> str | None:
    """The action named by an argument: a string literal, or ``Intent.ACTION_*``."""
    literal = _string_at(info, span)
    if literal is not None:
        return literal
    match = _ACTION_CONST.fullmatch(_arg_text(info, span))
    return action_name(match.group(1)) if match else None


def _looks_like_action(info: FileInfo, span: tuple[int, int]) -> bool:
    start = info.view.skip_space(span[0], span[1])
    if info.source.lexed.string_starting_at(start) is not None:
        return True
    return _ANY_ACTION_CONST.fullmatch(_arg_text(info, span)) is not None


def _uri_literal(info: FileInfo, spans: list[tuple[int, int]]) -> str | None:
    for span in spans:
        match = _URI_PARSE.search(info.view.masked, span[0], span[1])
        if match:
            inner = info.view.skip_space(match.end(), span[1])
            literal = info.source.lexed.string_starting_at(inner)
            if literal is not None and literal.terminated:
                value = info.source.lexed.string_value(literal)
                return None if "$" in value else value
    return None


def _from_ctor(info: FileInfo, match: re.Match[str]) -> list[_Construct]:
    open_index = match.end() - 1
    spans = _args(info, open_index)
    if spans is None:
        return []
    offset = match.start()
    if not spans:
        return []  # ``Intent()``: what it targets is set by the calls chained to it
    first = spans[0]
    if _looks_like_action(info, first):
        action = _action_of(info, first)
        if action is None:
            return [_Construct("action", offset, computed=True)]
        return [_Construct("action", offset, action=action, uri=_uri_literal(info, spans[1:]))]
    if len(spans) == 1:
        # ``Intent(other)`` copies an Intent, ``Intent(action)`` names one by a variable
        return [_Construct("action", offset, computed=True)]
    literal = _class_literal(_arg_text(info, spans[1]))
    if literal is None:
        return [_Construct("explicit", offset, computed=True)]
    return [_Construct("explicit", offset, written=literal)]


def _from_class_args(
    info: FileInfo, match: re.Match[str], *, needs_intent: bool = False
) -> list[_Construct]:
    """``ComponentName(ctx, X::class.java)`` or ``.setClass(ctx, X::class.java)``: the class is
    the last argument. ``needs_intent``: a ``.setClass`` on something that is not an Intent is no
    claim."""
    spans = _args(info, match.end() - 1)
    if not spans or len(spans) < 2:
        return []
    if (
        needs_intent
        and "Intent" not in info.view.masked[max(0, match.start() - 200) : match.start()]
    ):
        return []
    literal = _class_literal(_arg_text(info, spans[-1]))
    if literal is None:
        if (
            needs_intent
            or "Intent" in info.view.masked[max(0, match.start() - 200) : match.start()]
        ):
            return [_Construct("explicit", match.start(), computed=True)]
        return []
    return [_Construct("explicit", match.start(), written=literal)]


def _from_set_action(info: FileInfo, match: re.Match[str]) -> list[_Construct]:
    before = info.view.masked[max(0, match.start() - 200) : match.start()]
    if "Intent" not in before:
        return []
    spans = _args(info, match.end() - 1)
    if not spans:
        return []
    action = _action_of(info, spans[0])
    if action is None:
        return [_Construct("action", match.start(), computed=True)]
    return [_Construct("action", match.start(), action=action)]


# How an Intent is used, as far as the text shows.
_LAUNCHED, _DEFERRED_USE, _UNCLEAR = "launched", "deferred", "unclear"


def _statement_start(text: str, offset: int) -> int:
    stop = max(0, offset - _LOOKBACK)
    depth = 0
    for i in range(offset - 1, stop - 1, -1):
        ch = text[i]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth == 0:
                if ch == "{":
                    return i + 1
            else:
                depth -= 1
        elif ch == ";" and depth == 0:
            return i + 1
    return stop


def _enclosing_callees(text: str, offset: int) -> list[str]:
    """Names of the calls whose argument list contains ``offset``, innermost first (at most 3)."""
    names: list[str] = []
    depth = 0
    stop = max(0, offset - _LOOKBACK)
    i = offset - 1
    while i >= stop and len(names) < 3:
        ch = text[i]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth == 0:
                if ch == "(":
                    callee = _CALLEE.search(text[max(0, i - 80) : i])
                    names.append(callee.group(1) if callee else "")
                elif ch == "{":
                    break  # a block: the enclosing statement started inside it
            else:
                depth -= 1
        elif ch == ";" and depth == 0:
            break
        i -= 1
    return names


def _usage(info: FileInfo, offset: int) -> str:
    text = info.view.masked
    verdicts: set[str] = set()
    for callee in _enclosing_callees(text, offset):
        last = callee.rsplit(".", 1)[-1]
        if last in _LAUNCH_CALLS:
            verdicts.add(_LAUNCHED)
        elif last in _DEFER_CALLS or "PendingIntent" in callee or "TaskStackBuilder" in callee:
            verdicts.add(_DEFERRED_USE)
    if not verdicts:
        start = _statement_start(text, offset)
        assigned = _ASSIGNED.search(text[start:offset])
        if assigned:
            name = re.escape(assigned.group(1))
            function = info.function_at(offset)
            holder = info.type_at(offset)
            span = (
                function.body
                if function is not None and function.body
                else holder.body
                if holder is not None and holder.body
                else (0, len(text))
            )
            scope = text[span[0] : span[1]]
            if re.search(rf"\b(?:{'|'.join(sorted(_LAUNCH_CALLS))})\s*\(\s*{name}\b", scope):
                verdicts.add(_LAUNCHED)
            if re.search(
                rf"(?:PendingIntent\s*\.\s*get\w+|addNextIntent\w*)\s*\([^;{{}}]{{0,200}}\b{name}\b",
                scope,
            ):
                verdicts.add(_DEFERRED_USE)
    if verdicts == {_LAUNCHED}:
        return _LAUNCHED
    if verdicts == {_DEFERRED_USE}:
        return _DEFERRED_USE
    return _UNCLEAR


def source_node(run: Run, info: FileInfo, offset: int) -> str:
    """The fact an Intent built at ``offset`` belongs to: a composable, a type, or the file."""
    store = run.store
    function = info.function_at(offset)
    if function is not None:
        composable = make_id("composable", f"{function.owner}#{function.signature}")
        if store.has(composable):
            return composable
    holder = info.type_at(offset)
    return make_id("type", holder.fqn) if holder else make_id("file", info.path)


def _activity_ids(run: Run) -> dict[str, str]:
    cache = run.__dict__.get("_activity_ids")
    if cache is None:
        cache = {
            fact_id.split(":", 1)[1]: fact_id
            for kind in ("activity", "activity_alias")
            for fact_id in run.store.ids_of_kind(kind)
        }
        run.__dict__["_activity_ids"] = cache
    return cache


def _action_index(run: Run) -> dict[str, list[str]]:
    cache = run.__dict__.get("_action_index")
    if cache is None:
        cache = defaultdict(list)
        for kind in ("activity", "activity_alias"):
            for fact_id in run.store.ids_of_kind(kind):
                attrs = run.store.attributes_of(fact_id)
                actions = attrs.get("actions")
                if "manifest" in attrs and isinstance(actions, tuple):
                    for action in actions:
                        cache[action].append(fact_id)
        run.__dict__["_action_index"] = cache
    return cache


def _uri_matches(links: object, literal: str) -> bool:
    if not isinstance(links, tuple):
        return False
    scheme, _, rest = literal.partition("://")
    host = rest.split("/", 1)[0].split("?", 1)[0]
    for link in links:
        link_scheme, _, link_rest = link.partition("://")
        link_host = link_rest.split("/", 1)[0]
        if link_scheme == scheme and (not link_host or link_host == host):
            return True
    return False


def _record(run: Run, info: FileInfo, construct: _Construct) -> None:
    store = run.store
    offset = construct.offset
    evidence = [info.view.evidence(offset)]
    source = source_node(run, info, offset)
    if construct.computed:
        _unknown_launch(run, info, source, offset, _UNKNOWN_ACTION)
        return
    usage = _usage(info, offset)
    if construct.kind == "explicit" and construct.written:
        holder = info.type_at(offset)
        resolved = run.resolver.resolve(
            info.source, construct.written, holder.fqn if holder else None
        )
        written = construct.written.rsplit(".", 1)[-1]
        if not written[:1].isupper() or (len(written) == 1 and written.isupper()):
            _unknown_launch(run, info, source, offset, _UNKNOWN_ACTION)
            return
        target = _activity_ids(run).get(resolved.fqn or "")
        if target is None:
            return  # a class outside the project, or not an Activity: no claim
        if usage == _DEFERRED_USE:
            _unknown_launch(run, info, source, offset, _DEFERRED)
            return
        if usage == _LAUNCHED and resolved.exact:
            store.relate(source, "launches_activity", target, basis="source", evidence=evidence)
            return
        why = (
            "the Intent is not seen being started here"
            if usage == _UNCLEAR
            else "the target class is matched by name only"
        )
        store.relate(
            source,
            "launches_activity",
            target,
            basis="source",
            status="inferred",
            evidence=evidence,
            note=f"an explicit Intent names this Activity; {why}",
        )
        return
    if construct.kind == "action" and construct.action:
        if usage == _DEFERRED_USE:
            if _action_index(run).get(construct.action):
                _unknown_launch(run, info, source, offset, _DEFERRED)
            return
        candidates = list(_action_index(run).get(construct.action, []))
        if construct.uri is not None:
            candidates = [
                c
                for c in candidates
                if _uri_matches(store.attributes_of(c).get("deep_links"), construct.uri)
            ]
        for target in sorted(candidates):
            store.relate(
                source,
                "launches_activity",
                target,
                basis="source",
                status="inferred",
                evidence=evidence,
                note=(
                    f"the action {construct.action.rsplit('.', 1)[-1]} matches an intent filter "
                    f"in the manifest ({len(candidates)} match); Android chooses the target at "
                    "run time and another app may match too"
                ),
            )


def _unknown_launch(run: Run, info: FileInfo, source: str, offset: int, reason: str) -> None:
    owner = source.split(":", 1)[1]
    line = info.view.line(offset)
    subject = f"{owner}@{info.path}:{line}"
    evidence = [info.view.evidence(offset)]
    fact_id = run.fact(
        "intent_launch",
        subject,
        basis="source",
        status="unknown",
        reason=reason,
        evidence=evidence,
        attrs={"owner": source, "path": info.path},
        tags=run.path_tags(info.path),
    )
    run.store.relate(
        source,
        "launches",
        fact_id,
        basis="source",
        status="unknown",
        reason=reason,
        evidence=evidence,
    )
    run.store.limit(
        "dynamic_navigation",
        info.path,
        "an Intent in this file has a target that cannot be listed",
        affects_completeness=False,
    )


# -- flows ---------------------------------------------------------------------------------------


@dataclass
class _Edge:
    target: str
    status: FactStatus
    evidence: tuple[Evidence, ...]


class _Graph:
    """The edges a flow follows, keyed by the canonical node of their source. Composable calls and
    NavHost links are added the first time a composable is reached."""

    def __init__(self, run: Run, compose: ComposeIndex) -> None:
        self.run = run
        self.store = run.store
        self.compose = {entry.fact_id: entry for entry in compose.entries}
        self.compose_index = compose
        self._canon: dict[str, str] = {}
        self._expanded: set[str] = set()
        self.edges: dict[str, list[_Edge]] = defaultdict(list)
        self.start_routes: dict[str, list[str]] = defaultdict(list)  # file path -> route ids
        for kind in FLOW_EDGES:
            for source, target, status, evidence in self.store.relation_items(kind):
                self._add(source, target, status, evidence)
        for route in self.store.ids_of_kind("compose_route"):
            if self.store.attributes_of(route).get("start_destination") is True:
                for ev in self.store.evidence_of(route):
                    self.start_routes[ev.path].append(route)

    def canon(self, node: str) -> str:
        found = self._canon.get(node)
        if found is None:
            found = node
            if node.startswith("type:"):
                fqn = node[5:]
                for role in _ROLES:
                    candidate = f"{role}:{fqn}"
                    if self.store.has(candidate):
                        found = candidate
                        break
            self._canon[node] = found
        return found

    def _add(
        self, source: str, target: str, status: FactStatus, evidence: tuple[Evidence, ...]
    ) -> None:
        origin, goal = self.canon(source), self.canon(target)
        if origin != goal:  # a role fact "implemented by" its own class is not a link to a screen
            self.edges[origin].append(_Edge(goal, status, evidence))

    def neighbours(self, node: str) -> list[_Edge]:
        if node.startswith("composable:") and node not in self._expanded:
            self._expanded.add(node)
            self._expand_composable(node)
        return sorted(self.edges.get(node, ()), key=lambda e: (e.target, e.status))

    def _expand_composable(self, node: str) -> None:
        entry: Composable | None = self.compose.get(node)
        if entry is None or entry.member.body is None:
            return
        store = self.store
        taken = 0
        seen: set[str] = set()
        for name, offset in project_calls(entry.info, entry.member.body):
            for target, certain in self.compose_index.resolve(entry.info, name):
                if target.preview or target.fact_id == node or target.fact_id in seen:
                    continue
                seen.add(target.fact_id)
                status: FactStatus = "confirmed" if certain else "inferred"
                evidence = (entry.info.view.evidence(offset),)
                store.relate(
                    node,
                    "calls_composable",
                    target.fact_id,
                    basis="source",
                    status=status,
                    evidence=list(evidence),
                    note=None if certain else "the call matches one composable by name only",
                )
                self._add(node, target.fact_id, status, evidence)
                taken += 1
                if taken >= MAX_CALLS_PER_COMPOSABLE:
                    return
        if store.attributes_of(node).get("nav_host") is True:
            self._bridge_nav_host(node, entry)

    def _bridge_nav_host(self, node: str, entry: Composable) -> None:
        """Link a composable that holds a ``NavHost`` to the start route written inside it."""
        body = entry.member.body
        if body is None:
            return
        view = entry.info.view
        first, last = view.line(body[0]), view.line(body[1])
        path = entry.info.path
        for route in sorted(self.start_routes.get(path, ())):
            evidence = tuple(
                ev
                for ev in self.store.evidence_of(route)
                if ev.path == path and ev.line is not None and first <= ev.line <= last
            )
            if not evidence:
                continue  # that start route belongs to another NavHost in the same file
            self.store.relate(
                node,
                "starts_at",
                route,
                basis="navigation",
                status="inferred",
                evidence=list(evidence),
                note="the NavHost and this start route are written in the same composable",
            )
            self._add(node, route, "inferred", evidence)


@dataclass
class _Reach:
    order: list[str]
    depth: dict[str, int]
    via: dict[str, _Edge]  # node -> the edge it was first reached by
    parent: dict[str, str]
    edge_count: int
    truncated: bool
    work: int


def _walk(
    graph: _Graph, root: str, *, confirmed_only: bool, max_depth: int, max_visited: int
) -> _Reach:
    order = [root]
    depth = {root: 0}
    via: dict[str, _Edge] = {}
    parent: dict[str, str] = {}
    queue: deque[str] = deque([root])
    edges = work = 0
    truncated = False
    while queue:
        node = queue.popleft()
        if depth[node] >= max_depth:
            if graph.neighbours(node):
                truncated = True
            continue
        for edge in graph.neighbours(node):
            if confirmed_only and edge.status != "confirmed":
                continue
            edges += 1
            work += 1
            if edge.target in depth:
                continue
            if len(depth) >= max_visited:
                truncated = True
                queue.clear()
                break
            depth[edge.target] = depth[node] + 1
            via[edge.target] = edge
            parent[edge.target] = node
            order.append(edge.target)
            queue.append(edge.target)
    return _Reach(order, depth, via, parent, edges, truncated, work + len(order))


def _kind(node: str) -> str:
    return node.split(":", 1)[0]


def _flows(run: Run, compose: ComposeIndex, entries: list[Entry]) -> None:
    store = run.store
    config = run.config
    graph = _Graph(run, compose)
    dynamic_owners = {
        graph.canon(str(store.attributes_of(fact_id).get("owner", "")))
        for fact_id in store.ids_of_kind("intent_launch")
    }
    compose_dynamic = store.has(make_id("navigation", "compose")) or store.has(
        make_id("navigation", "navigation3")
    )
    budget = config.max_flow_visited * 40
    spent = 0
    for entry in sorted(entries, key=lambda e: e.fact_id):
        if run.expired():
            return
        root = graph.canon(entry.component_id)
        if spent >= budget:
            store.limit(
                "flow_cap_reached",
                "project",
                "the work limit for flows was reached; later entry points have no flow",
                affects_completeness=False,
            )
            return
        reach = _walk(
            graph,
            root,
            confirmed_only=False,
            max_depth=config.max_flow_depth,
            max_visited=config.max_flow_visited,
        )
        spent += reach.work
        leads_to_screen = any(n != root and _kind(n) in SCREEN_KINDS for n in reach.order)
        if not leads_to_screen and entry.kind not in ("activity", "activity_alias"):
            continue  # a service, receiver or Application that reaches no screen has no flow
        sure = _walk(
            graph,
            root,
            confirmed_only=True,
            max_depth=config.max_flow_depth,
            max_visited=config.max_flow_visited,
        )
        spent += sure.work
        _flow_facts(run, entry, root, reach, sure, dynamic_owners, compose_dynamic)


def _flow_facts(
    run: Run,
    entry: Entry,
    root: str,
    reach: _Reach,
    sure: _Reach,
    dynamic_owners: set[str],
    compose_dynamic: bool,
) -> None:
    store = run.store
    config = run.config
    screens = [n for n in reach.order if _kind(n) in SCREEN_KINDS]
    shown = screens[: config.max_flow_screens]
    truncated = reach.truncated or len(screens) > len(shown)
    inferred = [n for n in shown if n not in sure.depth]
    uses_compose = any(_kind(n) in ("composable", "compose_route") for n in reach.order)
    dynamic = any(n in dynamic_owners for n in reach.order) or (compose_dynamic and uses_compose)
    attrs: dict = {
        "entry": entry.subject,
        "screens": tuple(shown),
        "screen_count": len(screens),
        "edge_count": reach.edge_count,
        "max_depth": max(reach.depth.values()),
        "truncated": truncated,
        "dynamic": dynamic,
        "inferred_screens": len(inferred),
    }
    status: FactStatus = "inferred" if inferred else "confirmed"
    flow_id = run.fact(
        "app_flow",
        entry.subject,
        basis="navigation",
        status=status,
        evidence=list(entry.evidence),
        note=(
            f"{len(inferred)} of {len(shown)} screens are reached through a link that is inferred"
            if inferred
            else None
        ),
        attrs=attrs,
        tags=tuple(sorted(t for t in store.tags_of(entry.fact_id) if t.startswith("module:"))),
    )
    store.relate(
        entry.fact_id, "starts_flow", flow_id, basis="navigation", evidence=list(entry.evidence)
    )
    for node in shown:
        if node == root:
            continue
        edge = reach.via[node]
        sure_path = node in sure.depth
        store.relate(
            flow_id,
            "reaches",
            node,
            basis="navigation",
            status="confirmed" if sure_path else "inferred",
            evidence=list(edge.evidence or entry.evidence),
            note=None if sure_path else "every path to it uses a link that is inferred",
        )
    reasons: list[str] = []
    if reach.truncated or len(screens) > len(shown):
        reasons.append(
            f"the walk stopped at its limit ({config.max_flow_screens} screens, "
            f"depth {config.max_flow_depth}); more screens may be reachable"
        )
        store.limit(
            "flow_cap_reached",
            entry.subject,
            "a flow reached its screen, depth or work limit",
            affects_completeness=False,
        )
    if dynamic:
        reasons.append(
            "part of the flow is computed (an Intent target, a Compose route or Navigation 3) and "
            "cannot be followed"
        )
    if reasons:
        gap = run.fact(
            "flow_gap",
            entry.subject,
            basis="navigation",
            status="unknown",
            reason="; ".join(reasons)[:290],
            attrs={"entry": entry.subject},
            tags=tuple(sorted(t for t in store.tags_of(entry.fact_id) if t.startswith("module:"))),
        )
        store.relate(
            flow_id,
            "has_gap",
            gap,
            basis="navigation",
            status="unknown",
            reason="; ".join(reasons)[:290],
        )
