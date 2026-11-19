"""Navigation facts: Compose routes (string and type-safe) and XML navigation graphs.

Only what can be read with confidence is recorded. A route that is computed, a destination whose
type is not a plain name, a graph built by a function we cannot see: each sets a flag, and the rules
that depend on completeness then stay silent. Navigation 3 (``NavDisplay`` / ``NavKey``) is a
different library and is deliberately not analysed: its presence silences the Compose rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .source import SourceFile, matching_close
from .xmlparse import XmlNode

if TYPE_CHECKING:
    from .analysis import ProjectAnalysis

_NAV_FILE = re.compile(r"NavGraphBuilder|NavHost|NavController|navDeepLink|androidx\.navigation")
_CONTROLLER_FILE = re.compile(r"NavController|NavHostController|rememberNavController")
_DEST_STRING = re.compile(r"(?<![\w.])(composable|dialog|navigation)\s*\(")
_DEST_TYPED = re.compile(r"(?<![\w.])(composable|dialog|navigation)\s*<\s*([\w.]+)\s*>\s*[({]")
_NAVHOST = re.compile(r"(?<![\w.])NavHost\s*\(")
_NAVIGATE = re.compile(r"\.\s*navigate\s*\(")
_DEEPLINK_URI = re.compile(r"(?<![\w.])uriPattern\s*=\s*")
_DEEPLINK_BASE = re.compile(r"(?<![\w.])navDeepLink\s*<[^>]*>\s*\(")
_CONST = re.compile(
    r'\bconst[ \t]+val[ \t]+([A-Za-z_]\w*)[ \t]*(?::[ \t]*String[ \t]*)?=[ \t]*"([^"\n$]*)"'
)
_OBJECT = re.compile(r"\bobject[ \t]+([A-Za-z_]\w*)[ \t]*\{")
_NAMED = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)\s*")
_CHAIN = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*(?:\(|::|,|$)")
_NAV3 = re.compile(r"^import\s+androidx\.navigation3\.", re.MULTILINE)


@dataclass(frozen=True)
class Route:
    pattern: str
    path: str
    line: int
    column: int = 1
    scope: str = ""  # enclosing function, so duplicates are judged within one builder


@dataclass(frozen=True)
class Use:
    """A reference to a destination: a literal route or a route type, never both."""

    route: str | None
    type_name: str | None
    path: str
    line: int
    column: int


@dataclass
class ComposeNav:
    declared: list[Route] = field(
        default_factory=list
    )  # literal routes of composable/dialog/navigation
    typed: set[str] = field(default_factory=set)  # simple names of composable<T> route types
    dynamic: bool = False  # some destination or start is computed: absence proves nothing
    starts: list[Use] = field(default_factory=list)  # NavHost / navigation start destinations
    navigates: list[Use] = field(default_factory=list)
    deeplinks: list[Route] = field(default_factory=list)  # literal navDeepLink URIs
    unsupported: bool = False  # Navigation 3 is in use


@dataclass(frozen=True)
class XmlDest:
    tag: str
    id: str | None
    name: str | None
    line: int


@dataclass
class XmlGraph:
    path: str
    node: XmlNode
    dests: list[XmlDest] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)  # @navigation/<name> of <include> children
    start: str | None = None  # id name from app:startDestination="@id/x"
    start_raw: str | None = None


@dataclass(frozen=True)
class XmlAction:
    path: str
    line: int
    destination: str  # id name


@dataclass(frozen=True)
class XmlDeepLink:
    path: str
    line: int
    uri: str


def id_name(value: str | None) -> str | None:
    """``@+id/home`` or ``@id/home`` -> ``home``."""
    if value and (match := re.fullmatch(r"@\+?id/([A-Za-z_]\w*)", value.strip())):
        return match.group(1)
    return None


def nav_resource_name(path: str) -> str | None:
    """``app/src/main/res/navigation/main_nav.xml`` -> ``main_nav``."""
    parts = path.split("/")
    if len(parts) >= 3 and parts[-2].startswith("navigation") and parts[-3] == "res":
        return parts[-1].removesuffix(".xml")
    return None


def split_args(masked: str, open_index: int) -> list[tuple[int, int]]:
    """Offsets of the top-level, comma-separated arguments of the call opened at ``open_index``."""
    close = matching_close(masked, open_index, "(", ")")
    if close is None:
        return []
    spans: list[tuple[int, int]] = []
    depth, start = 0, open_index + 1
    for i in range(open_index + 1, close):
        char = masked[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            spans.append((start, i))
            start = i + 1
    if masked[start:close].strip():
        spans.append((start, close))
    return spans


class _FileScan:
    """Reads one Kotlin file's navigation calls."""

    def __init__(self, source: SourceFile, constants: dict[str, str]) -> None:
        self.source = source
        self.constants = constants
        self.masked = source.masked

    def literal(self, offset: int) -> str | None:
        n = len(self.masked)
        while offset < n and self.masked[offset] in " \t\r\n":
            offset += 1
        literal = self.source.lexed.string_starting_at(offset)
        if literal is not None and literal.terminated:
            return self.source.lexed.string_value(literal)
        return None

    def argument(
        self, spans: list[tuple[int, int]], name: str, position: int | None
    ) -> tuple[int, int] | None:
        """The span of the argument called ``name`` (named) or at ``position`` (positional)."""
        for index, (start, end) in enumerate(spans):
            named = _NAMED.match(self.masked[start:end])
            if named and named.group(1) == name:
                return start + named.end(), end
            if not named and position is not None and index == position:
                return start, end
        return None

    def value(self, span: tuple[int, int] | None) -> tuple[str | None, str | None]:
        """(literal route, route type name) of an argument expression; ``(None, None)`` if it is
        computed. A literal may still contain ``$`` (a string template): callers decide."""
        if span is None:
            return None, None
        start, end = span
        text = self.masked[start:end].strip()
        if text.startswith('"'):
            return self.literal(start), None
        chain = _CHAIN.match(self.masked[start:end])
        if not chain:
            return None, None
        dotted = re.sub(r"\s+", "", chain.group(1))
        last = dotted.rsplit(".", 1)[-1]
        if dotted in self.constants:
            return self.constants[dotted], None
        if dotted.startswith("R."):
            return None, None  # a resource id: the XML-graph overload
        is_type = last[:1].isupper() and not last.isupper()
        if is_type and ("(" in text or "::" in text or text == dotted):
            return None, last
        return None, None

    def scope_at(self, offset: int) -> str:
        best = ""
        best_size = None
        for function in self.source.functions:
            if function.body and function.body[0] <= offset <= function.body[1]:
                size = function.body[1] - function.body[0]
                if best_size is None or size < best_size:
                    best, best_size = function.name, size
        return best


def _constants(sources: dict[str, SourceFile]) -> dict[str, str]:
    """``const val ROUTE = "home"`` -> {"ROUTE": "home", "Routes.ROUTE": "home"}. A name defined
    with
    two different values is dropped: it cannot be resolved without knowing which one is meant."""
    found: dict[str, str] = {}
    clashing: set[str] = set()

    def add(key: str, value: str) -> None:
        if found.setdefault(key, value) != value:
            clashing.add(key)

    for source in sources.values():
        masked, raw = source.masked, source.lexed.source
        objects = [
            (m.start(), matching_close(masked, m.end() - 1), m.group(1))
            for m in _OBJECT.finditer(masked)
        ]
        for match in _CONST.finditer(raw):
            if not masked.startswith("const", match.start()):
                continue
            name, value = match.group(1), match.group(2)
            add(name, value)
            chain = [
                n for start, end, n in objects if end is not None and start < match.start() < end
            ]
            if chain:
                add(".".join([*chain, name]), value)
    return {k: v for k, v in found.items() if k not in clashing}


def scan_compose(sources: dict[str, SourceFile], constants: dict[str, str]) -> ComposeNav:
    result = ComposeNav()
    for path, source in sorted(sources.items()):
        if not path.endswith(".kt"):
            continue
        if _NAV3.search(source.text):
            result.unsupported = True
        if not _NAV_FILE.search(source.masked) and "androidx.navigation" not in source.text:
            continue
        scan = _FileScan(source, constants)
        _scan_destinations(scan, path, result)
        _scan_hosts(scan, path, result)
        if _CONTROLLER_FILE.search(source.masked):
            _scan_navigates(scan, path, result)
        _scan_deeplinks(scan, path, result)
    return result


def _scan_destinations(scan: _FileScan, path: str, result: ComposeNav) -> None:
    masked = scan.masked
    for match in _DEST_TYPED.finditer(masked):
        name = match.group(2).rsplit(".", 1)[-1]
        if len(name) == 1 and name.isupper():
            result.dynamic = True  # composable<T>: the type is a parameter
        else:
            result.typed.add(name)
        if match.group(1) == "navigation" and masked[match.end() - 1] == "(":
            _record_start(scan, path, result, match.end() - 1)
    for match in _DEST_STRING.finditer(masked):
        kind = match.group(1)
        open_index = match.end() - 1
        spans = split_args(masked, open_index)
        if kind == "navigation":
            _record_start(scan, path, result, open_index)
            route_span = scan.argument(spans, "route", 1)
            if route_span is None:
                continue  # an unnamed graph: nothing to navigate to by name
        else:
            route_span = scan.argument(spans, "route", 0)
            if route_span is None:
                result.dynamic = True  # e.g. composable(id = ...) or a lambda-only call
                continue
        literal, type_name = scan.value(route_span)
        if literal is not None and "$" not in literal:
            result.declared.append(
                Route(
                    literal,
                    path,
                    scan.source.line(match.start()),
                    scope=scan.scope_at(match.start()),
                )
            )
        elif type_name is not None:
            result.typed.add(type_name)
        else:
            result.dynamic = True  # computed, or a template: we cannot list this destination


def _record_start(scan: _FileScan, path: str, result: ComposeNav, open_index: int) -> None:
    spans = split_args(scan.masked, open_index)
    span = scan.argument(
        spans,
        "startDestination",
        0 if scan.masked[:open_index].rstrip().endswith("navigation") else None,
    )
    if span is None:
        return
    literal, type_name = scan.value(span)
    offset = span[0]
    if literal is not None and "$" not in literal:
        result.starts.append(
            Use(literal, None, path, scan.source.line(offset), scan.source.column(offset))
        )
    elif type_name is not None:
        result.starts.append(
            Use(None, type_name, path, scan.source.line(offset), scan.source.column(offset))
        )
    else:
        result.dynamic = True


def _scan_hosts(scan: _FileScan, path: str, result: ComposeNav) -> None:
    for match in _NAVHOST.finditer(scan.masked):
        open_index = match.end() - 1
        spans = split_args(scan.masked, open_index)
        span = scan.argument(spans, "startDestination", 1)
        if span is None:
            result.dynamic = True  # NavHost(navController, graph): the graph is built elsewhere
            continue
        literal, type_name = scan.value(span)
        line, column = scan.source.line(span[0]), scan.source.column(span[0])
        if literal is not None and "$" not in literal:
            result.starts.append(Use(literal, None, path, line, column))
        elif type_name is not None:
            result.starts.append(Use(None, type_name, path, line, column))
        else:
            result.dynamic = True


def _scan_navigates(scan: _FileScan, path: str, result: ComposeNav) -> None:
    for match in _NAVIGATE.finditer(scan.masked):
        spans = split_args(scan.masked, match.end() - 1)
        span = scan.argument(spans, "route", 0)
        if span is None:
            continue
        literal, type_name = scan.value(span)
        if literal is None and type_name is None:
            continue
        offset = span[0]
        result.navigates.append(
            Use(literal, type_name, path, scan.source.line(offset), scan.source.column(offset))
        )


def _scan_deeplinks(scan: _FileScan, path: str, result: ComposeNav) -> None:
    for match in _DEEPLINK_URI.finditer(scan.masked):
        literal = scan.literal(match.end())
        if literal:
            result.deeplinks.append(Route(literal, path, scan.source.line(match.start())))
    for match in _DEEPLINK_BASE.finditer(scan.masked):
        spans = split_args(scan.masked, match.end() - 1)
        span = scan.argument(spans, "basePath", 0)
        literal = scan.literal(span[0]) if span else None
        if literal:
            result.deeplinks.append(Route(literal, path, scan.source.line(match.start())))


# -- XML graphs ----------------------------------------------------------------------------------

_DEST_TAGS = ("fragment", "activity", "dialog", "navigation", "include")


def scan_xml(
    a: ProjectAnalysis,
) -> tuple[list[XmlGraph], list[XmlAction], list[XmlDeepLink], dict[str, str]]:
    graphs: list[XmlGraph] = []
    actions: list[XmlAction] = []
    deeplinks: list[XmlDeepLink] = []
    root_ids: dict[str, str] = {}  # nav resource name -> the graph's own android:id
    for path, doc in sorted(a.xml_docs.items()):
        name = nav_resource_name(path)
        if name is None or doc.root is None or doc.root.tag != "navigation":
            continue
        if (own := id_name(doc.root.attrs.get("android:id"))) is not None:
            root_ids[name] = own
        stack = [doc.root]
        while stack:
            node = stack.pop()
            graph = XmlGraph(path, node)
            start = node.attrs.get("app:startDestination")
            graph.start_raw = start
            graph.start = id_name(start)
            for child in node.children:
                if child.tag in _DEST_TAGS:
                    if child.tag == "include":
                        ref = child.attrs.get("app:graph", "")
                        graph.includes.append(ref.removeprefix("@navigation/"))
                    else:
                        graph.dests.append(
                            XmlDest(
                                child.tag,
                                id_name(child.attrs.get("android:id")),
                                child.attrs.get("android:name"),
                                child.line,
                            )
                        )
                    if child.tag == "navigation":
                        stack.append(child)
            graphs.append(graph)
        for node in doc.root.iter():
            if node.tag == "action" and (dest := id_name(node.attrs.get("app:destination"))):
                actions.append(XmlAction(path, node.line, dest))
            elif node.tag == "deepLink" and node.attrs.get("app:uri"):
                deeplinks.append(XmlDeepLink(path, node.line, node.attrs["app:uri"]))
    return graphs, actions, deeplinks, root_ids


@dataclass
class NavigationFacts:
    compose: ComposeNav
    graphs: list[XmlGraph]
    actions: list[XmlAction]
    xml_deeplinks: list[XmlDeepLink]
    root_ids: dict[str, str]

    @classmethod
    def build(cls, a: ProjectAnalysis) -> NavigationFacts:
        sources = {p: s for p, s in a.sources.items() if not a.is_test_source(p)}
        compose = scan_compose(sources, _constants(a.sources))
        graphs, actions, deeplinks, root_ids = scan_xml(a)
        return cls(compose, graphs, actions, deeplinks, root_ids)

    @property
    def xml_dest_ids(self) -> set[str]:
        """Every destination id declared in any navigation graph (and each graph's own id)."""
        ids = {d.id for g in self.graphs for d in g.dests if d.id}
        ids.update(self.root_ids.values())
        return ids
