"""Read-only questions over an :class:`AnalysisReport`.

All answers are deterministic (sorted) and never invent facts. The one question that could mislead
is "is X not there?": :meth:`ReportIndex.observation` answers ``not_observed`` only when the report
is complete for the scope asked about, and says ``unknown`` otherwise. Even ``not_observed`` means
"the analyser found no such fact", never "the project cannot do this".
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Literal

from .model import AnalysisReport, Fact, FactStatus, Limitation, Relationship

Observation = Literal["observed", "not_observed", "unknown"]


class ReportIndex:
    def __init__(self, report: AnalysisReport) -> None:
        self.report = report
        self._by_id: dict[str, Fact] = {f.id: f for f in report.facts}
        self._by_kind: dict[str, list[Fact]] = defaultdict(list)
        self._by_tag: dict[str, list[Fact]] = defaultdict(list)
        self._by_path: dict[str, list[Fact]] = defaultdict(list)
        for fact in report.facts:
            self._by_kind[fact.kind].append(fact)
            for tag in fact.tags:
                self._by_tag[tag].append(fact)
            for path in sorted({e.path for e in fact.evidence}):
                self._by_path[path].append(fact)
        self._out: dict[str, list[Relationship]] = defaultdict(list)
        self._in: dict[str, list[Relationship]] = defaultdict(list)
        for rel in report.relationships:
            self._out[rel.source].append(rel)
            self._in[rel.target].append(rel)

    # -- facts ----------------------------------------------------------------------------

    def get(self, fact_id: str) -> Fact | None:
        return self._by_id.get(fact_id)

    def kinds(self) -> list[str]:
        return sorted(self._by_kind)

    def of_kind(self, kind: str, *, status: FactStatus | None = None) -> list[Fact]:
        facts = self._by_kind.get(kind, [])
        return [f for f in facts if status is None or f.status == status]

    def with_tag(self, tag: str) -> list[Fact]:
        return list(self._by_tag.get(tag, []))

    def tags(self) -> list[str]:
        return sorted(self._by_tag)

    def in_file(self, path: str) -> list[Fact]:
        """Facts that cite ``path`` as evidence."""
        return list(self._by_path.get(path, []))

    def in_module(self, module: str) -> list[Fact]:
        return self.with_tag(f"module:{module or '.'}")

    def named(self, simple_name: str) -> list[Fact]:
        """Facts whose subject is, or ends in, ``simple_name`` (``HomeViewModel``)."""
        suffixes = (f".{simple_name}", f"#{simple_name}", f"|{simple_name}", f"/{simple_name}")
        return [
            f for f in self.report.facts if f.subject == simple_name or f.subject.endswith(suffixes)
        ]

    def members_of(self, type_fqn: str) -> list[Fact]:
        return [f for f in self._by_kind.get("member", []) if f.attributes.get("owner") == type_fqn]

    def unknowns(self) -> list[Fact]:
        return [f for f in self.report.facts if f.status == "unknown"]

    def inferred(self) -> list[Fact]:
        return [f for f in self.report.facts if f.status == "inferred"]

    # -- relationships --------------------------------------------------------------------

    def outgoing(self, fact_id: str, kinds: Iterable[str] | None = None) -> list[Relationship]:
        wanted = set(kinds) if kinds is not None else None
        return [r for r in self._out.get(fact_id, []) if wanted is None or r.kind in wanted]

    def incoming(self, fact_id: str, kinds: Iterable[str] | None = None) -> list[Relationship]:
        wanted = set(kinds) if kinds is not None else None
        return [r for r in self._in.get(fact_id, []) if wanted is None or r.kind in wanted]

    def targets(self, fact_id: str, kind: str) -> list[Fact]:
        return [f for r in self.outgoing(fact_id, [kind]) if (f := self._by_id.get(r.target))]

    def sources(self, fact_id: str, kind: str) -> list[Fact]:
        return [f for r in self.incoming(fact_id, [kind]) if (f := self._by_id.get(r.source))]

    def reachable(
        self, fact_id: str, kinds: Iterable[str] | None = None, *, max_depth: int = 10
    ) -> list[str]:
        """Ids reachable by following outgoing edges (of ``kinds``), nearest first."""
        seen = {fact_id}
        order: list[str] = []
        queue: deque[tuple[str, int]] = deque([(fact_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for rel in self.outgoing(current, kinds):
                if rel.target not in seen:
                    seen.add(rel.target)
                    order.append(rel.target)
                    queue.append((rel.target, depth + 1))
        return order

    def path(
        self, source: str, target: str, kinds: Iterable[str] | None = None, *, max_depth: int = 12
    ) -> list[Relationship] | None:
        """The shortest chain of edges from ``source`` to ``target`` (ties broken by edge id), or
        ``None`` when there is none within ``max_depth`` edges."""
        if source == target:
            return []
        previous: dict[str, Relationship] = {}
        seen = {source}
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for rel in sorted(self.outgoing(current, kinds), key=lambda r: r.id):
                if rel.target in seen:
                    continue
                seen.add(rel.target)
                previous[rel.target] = rel
                if rel.target == target:
                    chain: list[Relationship] = []
                    node = target
                    while node != source:
                        chain.append(previous[node])
                        node = previous[node].source
                    return list(reversed(chain))
                queue.append((rel.target, depth + 1))
        return None

    # -- trust ----------------------------------------------------------------------------

    def limitations_for(self, fact: Fact) -> list[Limitation]:
        """Limitations that bear on ``fact``: project-wide ones, its module's, its files'."""
        paths = {e.path for e in fact.evidence}
        modules = {t.split(":", 1)[1] for t in fact.tags if t.startswith("module:")}
        return [
            lim
            for lim in self.report.limitations
            if lim.scope == "project" or lim.scope in paths or lim.scope in modules
        ]

    def explain(self, fact_id: str) -> dict | None:
        """Everything that supports a fact: its status, evidence, edges and limitations."""
        fact = self._by_id.get(fact_id)
        if fact is None:
            return None
        return {
            "fact": fact,
            "evidence": list(fact.evidence),
            "outgoing": self.outgoing(fact_id),
            "incoming": self.incoming(fact_id),
            "limitations": self.limitations_for(fact),
        }

    def observation(
        self, kind: str, subject: str | None = None, *, module: str | None = None
    ) -> Observation:
        """Was a fact of ``kind`` (and ``subject``) observed?

        ``observed``      a confirmed or inferred fact of that kind exists;
        ``unknown``       none exists but an ``unknown`` fact of that kind does, or the report is
                          incomplete for the scope (the project, or ``module`` when given);
        ``not_observed``  none exists and nothing the analyser could not read could hide one.

        ``not_observed`` is **not** a claim of absence.
        """
        matching = [
            f
            for f in self._by_kind.get(kind, [])
            if (subject is None or f.subject == subject)
            and (module is None or f"module:{module or '.'}" in f.tags)
        ]
        if any(f.status != "unknown" for f in matching):
            return "observed"
        if matching:
            return "unknown"
        if any(self._blocks(lim, module) for lim in self.report.limitations):
            return "unknown"
        return "not_observed"

    @staticmethod
    def _blocks(limitation: Limitation, module: str | None) -> bool:
        if not limitation.affects_completeness:
            return False
        label = module or "."
        if module is None or label == "." or limitation.scope == "project":
            return True  # the whole project (or a single-module root) is in scope
        return limitation.scope == label or limitation.scope.startswith(f"{label}/")
