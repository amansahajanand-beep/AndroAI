"""Collecting facts while the extractors run, and freezing them into a deterministic report.

Facts and relationships are keyed by id, so two extractors that see the same thing (a manifest
entry and the class it names, a dependency line and an import of the same library) add evidence
to one fact instead of producing two. Merging is order-independent where it matters:

* the stronger status wins (``confirmed`` > ``inferred`` > ``unknown``);
* evidence and tags are unions;
* a tuple attribute is a union, a scalar attribute keeps the smaller of two different values.

Everything that leaves the store is sorted, so the report depends only on the project's files.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field

from .config import AnalysisConfig
from .model import (
    ANALYSIS_VERSION,
    SUBJECT_MAX,
    AnalysisReport,
    AnalysisStats,
    AttrValue,
    Basis,
    Evidence,
    Fact,
    FactStatus,
    Limitation,
    LimitationCode,
    Relationship,
)
from .text import clip, scrub

_STRENGTH = {"unknown": 0, "inferred": 1, "confirmed": 2}
# Kinds dropped first when the fact cap is reached: bulk detail before structure.
_DROP_ORDER = ("member", "dependency", "reference", "type")


def make_id(kind: str, subject: str) -> str:
    return f"{kind}:{scrub(clip(subject, SUBJECT_MAX))}"


def _scrub_attr(value: AttrValue) -> AttrValue:
    if isinstance(value, str):
        return scrub(clip(value, 400))
    if isinstance(value, tuple):
        return tuple(scrub(clip(item, 200)) for item in value[:200])
    return value


def _smaller(a: str | None, b: str | None) -> str | None:
    """The smaller of two optional texts, ignoring a missing one."""
    return min((x for x in (a, b) if x), default=None)


def _merge_attr(old: AttrValue, new: AttrValue) -> AttrValue:
    if isinstance(old, tuple) and isinstance(new, tuple):
        return tuple(sorted(set(old) | set(new)))
    if old == new:
        return old
    return min(old, new, key=lambda v: (type(v).__name__, str(v)))


@dataclass
class _Draft:
    kind: str
    subject: str
    status: FactStatus
    basis: Basis
    attributes: dict[str, AttrValue] = field(default_factory=dict)
    evidence: dict[tuple[str, int, str], Evidence] = field(default_factory=dict)
    note: str | None = None
    reason: str | None = None
    tags: set[str] = field(default_factory=set)

    def absorb(self, other: _Draft, limit: int) -> None:
        if _STRENGTH[other.status] > _STRENGTH[self.status]:
            self.status, self.basis = other.status, other.basis
            self.note, self.reason = other.note, other.reason
        elif other.status == self.status:
            # equal strength: take the smaller of each, so the result never depends on order
            self.basis = min(self.basis, other.basis)
            self.note = _smaller(self.note, other.note)
            self.reason = _smaller(self.reason, other.reason)
        self.evidence.update(other.evidence)
        _trim(self.evidence, limit)
        self.tags |= other.tags
        for key, value in other.attributes.items():
            self.attributes[key] = (
                _merge_attr(self.attributes[key], value) if key in self.attributes else value
            )


@dataclass
class _RelDraft:
    source: str
    target: str
    kind: str
    status: FactStatus
    basis: Basis
    evidence: dict[tuple[str, int, str], Evidence] = field(default_factory=dict)
    note: str | None = None
    reason: str | None = None

    def absorb(self, other: _RelDraft, limit: int) -> None:
        if _STRENGTH[other.status] > _STRENGTH[self.status]:
            self.status, self.basis = other.status, other.basis
            self.note, self.reason = other.note, other.reason
        elif other.status == self.status:
            # equal strength: take the smaller of each, so the result never depends on order
            self.basis = min(self.basis, other.basis)
            self.note = _smaller(self.note, other.note)
            self.reason = _smaller(self.reason, other.reason)
        self.evidence.update(other.evidence)
        _trim(self.evidence, limit)


def _trim(evidence: dict[tuple[str, int, str], Evidence], limit: int) -> None:
    """Keep the ``limit`` smallest entries. The smallest K of a union equals the smallest K of
    (the smallest K of one side, plus the other), so doing this at every merge gives the same
    result in any order while keeping memory bounded."""
    if len(evidence) > limit:
        for key in sorted(evidence)[limit:]:
            del evidence[key]


def _evidence_map(
    items: tuple[Evidence, ...] | list[Evidence],
) -> dict[tuple[str, int, str], Evidence]:
    return {item.sort_key: item for item in items}


# What a claim says when the code that made it forgot to say why. A report never fails over
# this, but it is never right either: the tests assert that no fact or edge carries it.
UNEXPLAINED_NOTE = "no reason was recorded for this inference"
UNEXPLAINED_REASON = "no reason was recorded for this unknown"


def _finish(
    status: FactStatus, note: str | None, reason: str | None
) -> tuple[str | None, str | None]:
    """Repair a merged claim so it satisfies the status rules (an upgraded fact keeps no stale
    reason; a downgraded-by-merge one never lacks a note)."""
    if status == "confirmed":
        return note, None
    if status == "inferred":
        return note or UNEXPLAINED_NOTE, None
    return note, reason or UNEXPLAINED_REASON


class FactStore:
    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config
        self._facts: dict[str, _Draft] = {}
        self._rels: dict[tuple[str, str, str], _RelDraft] = {}
        self._limitations: dict[tuple[str, str], Limitation] = {}

    # -- adding ---------------------------------------------------------------------------

    def fact(
        self,
        kind: str,
        subject: str,
        *,
        basis: Basis,
        status: FactStatus = "confirmed",
        evidence: tuple[Evidence, ...] | list[Evidence] = (),
        attrs: dict[str, AttrValue] | None = None,
        note: str | None = None,
        reason: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> str:
        subject = scrub(clip(subject, SUBJECT_MAX))
        fact_id = f"{kind}:{subject}"
        draft = _Draft(
            kind=kind,
            subject=subject,
            status=status,
            basis=basis,
            attributes={k: _scrub_attr(v) for k, v in (attrs or {}).items()},
            evidence=_evidence_map(evidence),
            note=scrub(note) if note else None,
            reason=scrub(reason) if reason else None,
            tags=set(tags),
        )
        existing = self._facts.get(fact_id)
        if existing is None:
            self._facts[fact_id] = draft
        else:
            existing.absorb(draft, self.config.max_evidence_per_fact)
        return fact_id

    def relate(
        self,
        source: str,
        kind: str,
        target: str,
        *,
        basis: Basis,
        status: FactStatus = "confirmed",
        evidence: tuple[Evidence, ...] | list[Evidence] = (),
        note: str | None = None,
        reason: str | None = None,
    ) -> None:
        key = (source, kind, target)
        draft = _RelDraft(
            source, target, kind, status, basis, _evidence_map(evidence), note, reason
        )
        existing = self._rels.get(key)
        if existing is None:
            self._rels[key] = draft
        else:
            existing.absorb(draft, self.config.max_evidence_per_fact)

    def tag(self, fact_id: str, *tags: str) -> None:
        draft = self._facts.get(fact_id)
        if draft is not None:
            draft.tags.update(tags)

    def annotate(
        self,
        fact_id: str,
        *,
        attrs: dict[str, AttrValue] | None = None,
        evidence: tuple[Evidence, ...] | list[Evidence] = (),
        tags: tuple[str, ...] | list[str] = (),
    ) -> bool:
        """Add attributes, evidence or tags to an existing fact **without touching its status**.

        Use this for a detail about a fact (an Activity also calls ``setContent``), as opposed to
        :meth:`fact`, which states the fact again and so may strengthen it.
        """
        draft = self._facts.get(fact_id)
        if draft is None:
            return False
        draft.tags.update(tags)
        draft.evidence.update(_evidence_map(evidence))
        for key, value in (attrs or {}).items():
            value = _scrub_attr(value)
            draft.attributes[key] = (
                _merge_attr(draft.attributes[key], value) if key in draft.attributes else value
            )
        return True

    def limit(
        self,
        code: LimitationCode,
        scope: str,
        message: str,
        *,
        affects_completeness: bool = True,
    ) -> None:
        key = (code, scope)
        if key not in self._limitations:
            self._limitations[key] = Limitation(
                code=code,
                scope=scrub(clip(scope, SUBJECT_MAX)),
                message=clip(message, 300),
                affects_completeness=affects_completeness,
            )

    # -- reading --------------------------------------------------------------------------

    def has(self, fact_id: str) -> bool:
        return fact_id in self._facts

    def ids_of_kind(self, kind: str) -> list[str]:
        return sorted(fid for fid, draft in self._facts.items() if draft.kind == kind)

    def attribute(self, fact_id: str, key: str) -> AttrValue | None:
        draft = self._facts.get(fact_id)
        return draft.attributes.get(key) if draft else None

    def status_of(self, fact_id: str) -> FactStatus | None:
        draft = self._facts.get(fact_id)
        return draft.status if draft else None

    def attributes_of(self, fact_id: str) -> dict[str, AttrValue]:
        draft = self._facts.get(fact_id)
        return dict(draft.attributes) if draft else {}

    def tags_of(self, fact_id: str) -> frozenset[str]:
        draft = self._facts.get(fact_id)
        return frozenset(draft.tags) if draft else frozenset()

    def evidence_of(self, fact_id: str) -> tuple[Evidence, ...]:
        """The evidence collected for a fact so far, in report order."""
        draft = self._facts.get(fact_id)
        if draft is None:
            return ()
        return tuple(sorted(draft.evidence.values(), key=lambda e: e.sort_key))

    def relation_items(self, kind: str) -> list[tuple[str, str, FactStatus, tuple[Evidence, ...]]]:
        """``(source, target, status, evidence)`` of every relationship of ``kind``, sorted."""
        return [
            (
                s,
                t,
                draft.status,
                tuple(sorted(draft.evidence.values(), key=lambda e: e.sort_key)),
            )
            for (s, k, t), draft in sorted(self._rels.items())
            if k == kind
        ]

    def relation_pairs(self, kind: str) -> list[tuple[str, str]]:
        """``(source, target)`` of every relationship of ``kind`` added so far, sorted."""
        return sorted((s, t) for (s, k, t) in self._rels if k == kind)

    @property
    def limitations(self) -> list[Limitation]:
        return list(self._limitations.values())

    # -- freezing -------------------------------------------------------------------------

    def freeze(self, stats: AnalysisStats) -> AnalysisReport:
        dropped = self._apply_caps()
        limit = self.config.max_evidence_per_fact
        facts: list[Fact] = []
        for fact_id in sorted(self._facts):
            draft = self._facts[fact_id]
            note, reason = _finish(draft.status, draft.note, draft.reason)
            evidence = tuple(sorted(draft.evidence.values(), key=lambda e: e.sort_key)[:limit])
            if draft.status == "confirmed" and not evidence:  # pragma: no cover - defensive
                raise ValueError(f"confirmed fact {fact_id} has no evidence")
            facts.append(
                Fact(
                    id=fact_id,
                    kind=draft.kind,
                    subject=draft.subject,
                    status=draft.status,
                    basis=draft.basis,
                    attributes=draft.attributes,
                    evidence=evidence,
                    note=note,
                    reason=reason,
                    tags=tuple(sorted(draft.tags)),
                )
            )
        present = {f.id for f in facts}
        relationships: list[Relationship] = []
        for key in sorted(self._rels):
            draft = self._rels[key]
            if draft.source not in present or draft.target not in present:
                continue  # an edge to a fact the cap removed is removed with it
            note, reason = _finish(draft.status, draft.note, draft.reason)
            relationships.append(
                Relationship(
                    source=draft.source,
                    target=draft.target,
                    kind=draft.kind,
                    status=draft.status,
                    basis=draft.basis,
                    evidence=tuple(
                        sorted(draft.evidence.values(), key=lambda e: e.sort_key)[:limit]
                    ),
                    note=note,
                    reason=reason,
                )
            )
        if dropped:
            self.limit(
                "fact_cap_reached",
                "project",
                f"{dropped} facts were left out to stay within the report size limit",
            )
        limitations = sorted(self._limitations.values(), key=lambda m: (m.code, m.scope))
        stats = stats.model_copy(
            update={
                "facts_by_kind": dict(sorted(Counter(f.kind for f in facts).items())),
                "relationships_by_kind": dict(
                    sorted(Counter(r.kind for r in relationships).items())
                ),
                "facts_by_status": dict(sorted(Counter(f.status for f in facts).items())),
            }
        )
        complete = not any(item.affects_completeness for item in limitations)
        return AnalysisReport(
            complete=complete,
            facts=tuple(facts),
            relationships=tuple(relationships),
            limitations=tuple(limitations),
            stats=stats,
            fingerprint=_fingerprint(facts, relationships, limitations),
        )

    def _apply_caps(self) -> int:
        """Drop the bulkiest kinds first until the cap holds. Returns how many were dropped."""
        excess = len(self._facts) - self.config.max_facts
        if excess <= 0:
            return 0
        dropped = 0
        order = [*_DROP_ORDER]
        order += sorted({d.kind for d in self._facts.values()} - set(order))
        for kind in order:
            if dropped >= excess:
                break
            for fact_id in sorted(
                (i for i, d in self._facts.items() if d.kind == kind), reverse=True
            ):
                if dropped >= excess:
                    break
                del self._facts[fact_id]
                dropped += 1
        return dropped


def report_fingerprint(report: AnalysisReport) -> str:
    """The fingerprint a report should carry, recomputed from its content (a consistency check)."""
    return _fingerprint(
        list(report.facts),
        list(report.relationships),
        list(report.limitations),
        report.analysis_version,
    )


def _fingerprint(
    facts: list[Fact],
    relationships: list[Relationship],
    limitations: list[Limitation],
    version: str = ANALYSIS_VERSION,
) -> str:
    payload = {
        "version": version,
        "facts": [f.model_dump(mode="json") for f in facts],
        "relationships": [r.model_dump(mode="json") for r in relationships],
        "limitations": [m.model_dump(mode="json") for m in limitations],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
