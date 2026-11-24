"""Compose screens and how Activities and Fragments put content on screen.

* ``composable`` facts for every ``@Composable`` function of application code;
* ``compose_screen`` facts for the composables that are screens: confirmed when a navigation
  destination renders them (see ``navigation.py``), inferred when an Activity's ``setContent`` shows
  them or when the name or parameters say so (``HomeScreen``, a ``NavController`` parameter);
* ``hosts_content`` edges from an Activity or Fragment to the composables its ``setContent`` shows;
* ``hosts_fragment`` edges for fragments placed with ``FragmentTransaction.replace/add``.

A composable that takes a ``content: @Composable`` lambda is a wrapper (a theme, a scaffold), not a
screen. One that contains a ``NavHost`` is a navigation host, also not a screen.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .catalog import accepted
from .context import Run
from .members import FileInfo, Member
from .resolve import import_index
from .store import make_id

_SET_CONTENT = re.compile(r"(?<![\w.])setContent\s*[({]")
_UPPER_CALL = re.compile(r"(?<![\w.])([A-Z]\w*)\s*(?:<[^>\n]*>)?\s*[({]")
_NAV_HOST = re.compile(r"(?<![\w.])NavHost\s*[({]")
_TRANSACTION = re.compile(r"(?:\.\s*|(?<![\w.]))(?:replace|add|show)\s*\(")
_FRAGMENT_REF = re.compile(
    r"(?<![\w.])([A-Z]\w*)\s*(?:\(|::\s*class|\.\s*newInstance|\.\s*Companion)"
)
_SCREEN_NAME = re.compile(r"(?:Screen|Page|Route)$")
_NAV_PARAM = re.compile(r"\b(?:NavController|NavHostController)\b")


@dataclass(frozen=True)
class Composable:
    member: Member
    info: FileInfo
    fact_id: str
    preview: bool
    wrapper: bool
    nav_host: bool


class ComposeIndex:
    def __init__(self) -> None:
        self.entries: list[Composable] = []
        self.by_name: dict[str, list[Composable]] = defaultdict(list)

    def add(self, entry: Composable) -> None:
        self.entries.append(entry)
        self.by_name[entry.member.name].append(entry)

    def resolve(self, info: FileInfo, name: str) -> list[tuple[Composable, bool]]:
        """Composables a call to ``name`` in ``info`` can mean, with whether that is certain."""
        options = self.by_name.get(name, [])
        if not options:
            return []
        imports = import_index(info.source)
        imported = imports.explicit.get(name)
        if imported is not None:
            hits = [e for e in options if f"{e.member.owner}.{e.member.name}" == imported]
            if hits:
                return [(h, True) for h in hits]
        same = [e for e in options if e.member.owner == info.package]
        if same:
            return [(h, True) for h in same]
        hits = [e for e in options if e.member.owner in imports.wildcards]
        if hits:
            return [(h, len(hits) == 1) for h in hits]
        if len(options) == 1:
            return [(options[0], False)]
        return []


def extract_compose(run: Run) -> ComposeIndex:
    index = ComposeIndex()
    for info in run.app_sources():
        if run.expired():
            break
        members: list[Member] = [*info.top_level]
        for decl in info.types:
            members.extend(decl.members)
        for member in members:
            if member.kind != "function":
                continue
            annotation = next(
                (a for a in member.annotations if a.simple == "Composable" and a.use_site is None),
                None,
            )
            if annotation is None:
                continue
            level = annotation.level(accepted("Composable"))
            if level is None:
                continue
            preview = any(
                a.simple == "Preview" or a.simple.startswith("Preview") for a in member.annotations
            )
            wrapper = any("@Composable" in p.type_text for p in member.params)
            nav_host = bool(
                member.body and _NAV_HOST.search(info.view.masked, member.body[0], member.body[1])
            )
            attrs: dict = {
                "name": member.name,
                "owner": member.owner,
                "visibility": member.visibility,
                "preview": preview,
                "wrapper": wrapper,
                "nav_host": nav_host,
                "params": tuple(f"{p.name}: {p.type_text}" for p in member.params),
            }
            if member.type_text:
                attrs["returns"] = member.type_text
            fact_id = run.fact(
                "composable",
                f"{member.owner}#{member.signature}",
                basis="source",
                status=level,
                note=None
                if level == "confirmed"
                else "@Composable matches by name only; no import shows its package",
                evidence=[info.view.evidence(member.offset)],
                attrs=attrs,
                tags=(*run.path_tags(info.path), "ui:compose"),
            )
            index.add(Composable(member, info, fact_id, preview, wrapper, nav_host))
    _heuristic_screens(run, index)
    _content_hosts(run, index)
    _fragment_transactions(run)
    return index


def mark_screen(
    run: Run,
    entry: Composable,
    *,
    status: str,
    basis: str,
    note: str | None,
    evidence: list,
) -> str:
    screen_id = run.fact(
        "compose_screen",
        entry.fact_id.split(":", 1)[1],
        basis=basis,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        note=note,
        evidence=evidence,
        attrs={"name": entry.member.name, "owner": entry.member.owner},
        tags=(*run.path_tags(entry.info.path), "ui:compose"),
    )
    run.store.relate(
        screen_id,
        "role_of",
        entry.fact_id,
        basis="source",
        status="confirmed",
        evidence=[entry.info.view.evidence(entry.member.offset)],
    )
    return screen_id


def _heuristic_screens(run: Run, index: ComposeIndex) -> None:
    for entry in index.entries:
        member = entry.member
        if entry.preview or entry.wrapper or entry.nav_host or member.visibility == "private":
            continue
        evidence = [entry.info.view.evidence(member.offset)]
        if _SCREEN_NAME.search(member.name):
            mark_screen(
                run,
                entry,
                status="inferred",
                basis="heuristic",
                note=f"{member.name} is named like a screen",
                evidence=evidence,
            )
        elif any(_NAV_PARAM.search(p.type_text) for p in member.params):
            mark_screen(
                run,
                entry,
                status="inferred",
                basis="heuristic",
                note="it takes a NavController, as screens usually do",
                evidence=evidence,
            )


def lambda_span(info: FileInfo, start: int, end: int) -> tuple[int, int] | None:
    """Span of the lambda of a call whose name ends just before ``start`` (``{`` or ``(...) {``)."""
    view = info.view
    m = view.masked
    if start >= end:
        return None
    if m[start] == "{":
        close = view.close.get(start)
        return (start, close) if close is not None else None
    if m[start] == "(":
        after = view.group_end(start)
        if after is None:
            return None
        nxt = view.skip_space(after, end)
        if m[nxt : nxt + 1] == "{":
            close = view.close.get(nxt)
            return (nxt, close) if close is not None else None
    return None


def project_calls(info: FileInfo, span: tuple[int, int]) -> list[tuple[str, int]]:
    """Capitalised calls (``Name(...)`` or ``Name { }``) written inside a span, in order."""
    found: list[tuple[str, int]] = []
    for match in _UPPER_CALL.finditer(info.view.masked, span[0] + 1, span[1]):
        found.append((match.group(1), match.start(1)))
    return found


def _content_hosts(run: Run, index: ComposeIndex) -> None:
    store = run.store
    for info in run.app_sources():
        for decl in info.types:
            if decl.body is None or decl.kind != "class":
                continue
            for match in _SET_CONTENT.finditer(info.view.masked, decl.body[0], decl.body[1]):
                span = lambda_span(info, match.end() - 1, decl.body[1])
                if span is None:
                    continue
                source_id = make_id("type", decl.fqn)
                for role in ("activity", "fragment"):
                    store.annotate(
                        make_id(role, decl.fqn),
                        attrs={"ui": "compose"},
                        evidence=[info.view.evidence(match.start())],
                        tags=("ui:compose",),
                    )
                for name, offset in project_calls(info, span):
                    for entry, certain in index.resolve(info, name):
                        if entry.preview or entry.wrapper:
                            continue
                        status = "confirmed" if certain else "inferred"
                        note = (
                            None
                            if certain
                            else "the called name matches one composable by name only"
                        )
                        evidence = [info.view.evidence(offset)]
                        store.relate(
                            source_id,
                            "hosts_content",
                            entry.fact_id,
                            basis="source",
                            status=status,
                            evidence=evidence,
                            note=note,
                        )
                        if not entry.nav_host:
                            mark_screen(
                                run,
                                entry,
                                status="inferred",
                                basis="source",
                                note=f"shown by setContent in {decl.name}",
                                evidence=evidence,
                            )


def _fragment_transactions(run: Run) -> None:
    store = run.store
    for info in run.app_sources():
        for decl in info.types:
            if decl.body is None or decl.kind != "class":
                continue
            source_id = make_id("type", decl.fqn)
            for match in _TRANSACTION.finditer(info.view.masked, decl.body[0], decl.body[1]):
                end = info.view.group_end(match.end() - 1)
                if end is None:
                    continue
                for ref in _FRAGMENT_REF.finditer(info.view.masked, match.end(), end):
                    resolved = run.resolver.resolve(info.source, ref.group(1), decl.fqn)
                    target = make_id("fragment", resolved.fqn or "")
                    if resolved.fqn and store.has(target):
                        store.relate(
                            source_id,
                            "hosts_fragment",
                            target,
                            basis="source",
                            status="inferred",
                            evidence=[info.view.evidence(ref.start(1))],
                            note="a fragment is passed to a replace/add/show call; the receiver "
                            "type is not checked",
                        )
