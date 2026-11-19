"""Navigation rules: destinations that do not exist, start destinations, duplicates, XML graphs.

Documented behaviour these rest on (developer.android.com): ``NavController.navigate(route)`` throws
``IllegalArgumentException`` for an invalid route, and a graph "is not valid until you add
destinations and set a start destination". ``popBackStack`` is *not* documented to throw, so it is
not checked. Navigation 3 and anything computed are not analysed: the rules stay silent there.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..models import Finding, Severity, finding
from ..navigation import NavigationFacts, Use, id_name

_CATEGORY = "navigation"


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    facts = a.navigation
    yield from _compose(a, facts)
    yield from _xml(a, facts)


# -- Compose -------------------------------------------------------------------------------------


def _segments(route: str) -> list[str]:
    base = route.split("?", 1)[0].strip("/")
    return base.split("/") if base else [""]


def _hole(segment: str) -> bool:
    return (segment.startswith("{") and segment.endswith("}")) or "$" in segment


def route_matches(pattern: str, route: str) -> bool:
    """``detail/{id}`` matches ``detail/42`` and ``detail/$id``; the query string is ignored."""
    mine, theirs = _segments(pattern), _segments(route)
    return len(mine) == len(theirs) and all(
        _hole(x) or _hole(y) or x == y for x, y in zip(mine, theirs, strict=True)
    )


def _is_serializable_route(a: ProjectAnalysis, name: str) -> bool:
    """The name is a project class annotated ``@Serializable``: what a type-safe route must be."""
    for source in a.sources.values():
        for decl in source.types:
            if decl.name == name and "@Serializable" in _annotations(source.masked, decl.offset):
                return True
    return False


def _annotations(masked: str, offset: int) -> str:
    """The annotations attached to the declaration at ``offset``: those earlier on its own line and
    the contiguous lines of annotations directly above it (a blank line or code ends them)."""
    line_start = masked.rfind("\n", 0, offset) + 1
    found = [masked[line_start:offset]]
    end = line_start - 1
    while end > 0:
        start = masked.rfind("\n", 0, end) + 1
        line = masked[start:end]
        if not line.strip().startswith("@"):
            break
        found.append(line)
        end = start - 1
    return " ".join(found)


def _compose(a: ProjectAnalysis, facts: NavigationFacts) -> Iterator[Finding]:
    nav = facts.compose
    if nav.unsupported or nav.dynamic:
        return  # Navigation 3 or a computed graph: the absence of a destination proves nothing
    patterns = [r.pattern for r in nav.declared]
    yield from _duplicate_routes(nav)
    for use in nav.navigates:
        yield from _missing(a, nav, use, patterns, start=False)
    for use in nav.starts:
        yield from _missing(a, nav, use, patterns, start=True)


def _missing(
    a: ProjectAnalysis, nav, use: Use, patterns: list[str], *, start: bool
) -> Iterator[Finding]:
    if use.route is not None:
        if not nav.declared or any(route_matches(p, use.route) for p in patterns):
            return
        shown = use.route
        key = use.route
        close = difflib.get_close_matches(use.route.split("?")[0], patterns, n=3, cutoff=0.6)
        hint = f"Did you mean {', '.join(close)}? " if close else ""
    elif use.type_name is not None:
        if (
            not nav.typed
            or use.type_name in nav.typed
            or not _is_serializable_route(a, use.type_name)
        ):
            return
        shown = use.type_name
        key = use.type_name
        hint = ""
    else:
        return
    if start:
        yield finding(
            Severity.ERROR,
            "navigation.start_destination_missing",
            _CATEGORY,
            use.path,
            f"The start destination '{shown}' is not declared by any destination in the project, "
            "so the graph is not valid and the NavHost fails when it is first shown.",
            line=use.line,
            column=use.column,
            fix=hint + "Declare that destination or start at one that exists.",
            key=key,
        )
    else:
        yield finding(
            Severity.ERROR,
            "navigation.destination_missing",
            _CATEGORY,
            use.path,
            f"navigate({shown!r}) has no matching destination: nothing in the project declares "
            "that route, and NavController.navigate throws IllegalArgumentException for an "
            "invalid route.",
            line=use.line,
            column=use.column,
            fix=hint
            + "Declare the destination (composable, dialog or navigation) or fix the route.",
            key=key,
        )


def _duplicate_routes(nav) -> Iterator[Finding]:
    seen: dict[tuple[str, str, str], int] = defaultdict(int)
    for route in nav.declared:
        ident = (route.path, route.scope, route.pattern)
        seen[ident] += 1
        if seen[ident] == 2:
            yield finding(
                Severity.WARNING,
                "navigation.duplicate_destination",
                _CATEGORY,
                route.path,
                f"The route '{route.pattern}' is declared more than once in this graph "
                "builder. A graph identifies a destination by its route, so the second "
                "declaration is ambiguous with "
                "the first.",
                line=route.line,
                fix="Give each destination its own route, or delete the duplicate.",
                key=route.pattern,
            )


# -- XML graphs ----------------------------------------------------------------------------------


def _xml(a: ProjectAnalysis, facts: NavigationFacts) -> Iterator[Finding]:
    if not facts.graphs:
        return
    all_ids = facts.xml_dest_ids
    for graph in facts.graphs:
        direct = {d.id for d in graph.dests if d.id}
        unresolved_include = False
        for name in graph.includes:
            if name in facts.root_ids:
                direct.add(facts.root_ids[name])
            else:
                unresolved_include = True
        yield from _start(graph, direct, unresolved_include)
        yield from _duplicate_ids(graph)
        if a.sources:
            yield from _classes(a, graph)
    for action in facts.actions:
        if action.destination not in all_ids:
            close = difflib.get_close_matches(action.destination, sorted(all_ids), n=3, cutoff=0.6)
            yield finding(
                Severity.ERROR,
                "navigation.action_target_missing",
                _CATEGORY,
                action.path,
                f"The action points to @id/{action.destination}, but no navigation graph "
                "declares a "
                "destination with that id.",
                line=action.line,
                fix=(f"Did you mean {', '.join(close)}? " if close else "")
                + "Declare the destination or correct the id.",
                key=action.destination,
            )


def _start(graph, direct: set[str], unresolved_include: bool) -> Iterator[Finding]:
    node = graph.node
    if not (graph.dests or graph.includes):
        return
    if graph.start_raw is None:
        if not graph.includes:
            yield finding(
                Severity.ERROR,
                "navigation.start_destination_missing",
                _CATEGORY,
                graph.path,
                "This navigation graph has destinations but no app:startDestination, so it is not "
                "valid: Navigation cannot tell which destination to show first.",
                line=node.line,
                fix='Add app:startDestination="@id/<destination>" to the <navigation> element.',
                key=id_name(node.attrs.get("android:id")) or "<root>",
            )
        return
    if graph.start is None or graph.start in direct or unresolved_include:
        return
    yield finding(
        Severity.ERROR,
        "navigation.start_destination_missing",
        _CATEGORY,
        graph.path,
        f"app:startDestination points to @id/{graph.start}, which is not a destination of "
        "this graph.",
        line=node.line,
        fix="Point it at one of this graph's own destinations.",
        key=graph.start,
    )


def _duplicate_ids(graph) -> Iterator[Finding]:
    seen: set[str] = set()
    for dest in graph.dests:
        if dest.id is None:
            continue
        if dest.id in seen:
            yield finding(
                Severity.WARNING,
                "navigation.duplicate_destination",
                _CATEGORY,
                graph.path,
                f"The id @id/{dest.id} is used by more than one destination in this graph.",
                line=dest.line,
                fix="Give each destination a unique android:id.",
                key=dest.id,
            )
        seen.add(dest.id)


def _classes(a: ProjectAnalysis, graph) -> Iterator[Finding]:
    """A fully qualified class in the app's own packages that does not exist."""
    packages = tuple(a.all_namespaces)
    for dest in graph.dests:
        name = dest.name
        if (
            dest.tag == "navigation"
            or not name
            or not any(name.startswith(p + ".") for p in packages)
        ):
            continue
        if a.symbols.has_type(name.replace("$", ".")):
            continue
        yield finding(
            Severity.ERROR,
            "navigation.destination_class_missing",
            _CATEGORY,
            graph.path,
            f"The <{dest.tag}> destination names {name}, but the project has no such class.",
            line=dest.line,
            fix=f"Create {name.rsplit('.', 1)[-1]} or correct the android:name.",
            key=name,
        )
