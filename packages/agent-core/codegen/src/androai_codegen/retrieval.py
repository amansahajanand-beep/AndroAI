"""Context retrieval for a change request (Phase 6, after analysis).

Given an analysis report and the user's prompt, pick the facts and files the planner should read
first, say why, and say what else a change would touch. Deterministic and read-only: no LLM, no
file access (everything comes from the report), the same inputs give the same bundle.

The report is data read from untrusted project files and the prompt is user text. Neither is
treated as instructions; the bundle holds only ids, kinds, names, paths and scores.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from androai_codegen.analysis import AnalysisReport, Fact, ReportIndex

FileRole = Literal["primary", "related", "impact", "build", "overview"]
Confidence = Literal["high", "medium", "low", "none"]

# Facts that describe plumbing, not things a user would ask to change by name.
_NOISE_KINDS = frozenset(
    {
        "member",
        "file",
        "convention",
        "technology",
        "sdk_level",
        "gradle_plugin",
        "version_catalog",
        "build_feature",
        "meta_data",
        "room_policy",
        "app_flow",
    }
)
# Edges that fan out to everything in a module and say nothing about this request.
_BROAD_EDGES = frozenset({"contains", "declares", "role_of", "entry_point_for"})
_BUILD_FILE = re.compile(
    r"(?:^|/)(?:build\.gradle(?:\.kts)?|settings\.gradle(?:\.kts)?|libs\.versions\.toml|AndroidManifest\.xml)$"
)

_STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from has have how i in into is it its make me "
    "my new of on or our please so that the their then there these this to use using want we "
    "what when which will with without would you your add change update modify create fix "
    "should need needs like also just all any some more less app application project code "
    "feature thing".split()
)
# Words that point at a kind of thing rather than a name: they boost matching fact kinds/tags.
_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "screen": ("compose_screen", "composable", "activity", "fragment"),
    "page": ("compose_screen", "activity", "fragment"),
    "activity": ("activity",),
    "fragment": ("fragment",),
    "viewmodel": ("viewmodel", "hilt_viewmodel"),
    "layout": ("layout",),
    "database": ("room_database", "room_entity", "room_dao", "room_migration"),
    "db": ("room_database", "room_entity", "room_dao"),
    "table": ("room_entity",),
    "dao": ("room_dao",),
    "entity": ("room_entity",),
    "api": ("retrofit_service", "http_endpoint", "base_url"),
    "network": ("retrofit_service", "http_endpoint", "base_url"),
    "endpoint": ("http_endpoint", "retrofit_service"),
    "permission": ("permission",),
    "service": ("service", "retrofit_service"),
    "receiver": ("receiver",),
    "dependency": ("dependency",),
    "library": ("dependency",),
    "navigation": ("compose_route", "compose_screen"),
    "route": ("compose_route",),
    "injection": ("di_module", "di_binding", "di_injectable"),
}
_BUILD_WORDS = frozenset(
    "dependency dependencies library libraries gradle build version sdk permission permissions "
    "manifest plugin minsdk targetsdk".split()
)

_SPLIT_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def tokens(text: str) -> list[str]:
    """Lower-case words of a text, splitting camelCase, snake_case and dotted names."""
    out: list[str] = []
    for chunk in _WORD.findall(text):
        for part in _SPLIT_CAMEL.split(chunk):
            word = part.lower()
            if len(word) > 1:
                out.append(word)
    return out


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s", "ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrievalConfig(_Model):
    max_seeds: int = Field(default=12, ge=1, le=100)
    max_files: int = Field(default=20, ge=1, le=200)
    max_impact: int = Field(default=20, ge=0, le=200)
    hops: int = Field(default=2, ge=0, le=4)
    min_score: float = Field(default=0.8, gt=0)
    relative_cutoff: float = Field(default=0.3, ge=0, le=1)  # keep seeds this close to the best


class Reason(_Model):
    kind: str
    detail: str


class Seed(_Model):
    fact_id: str
    kind: str
    subject: str
    score: float
    matched_terms: tuple[str, ...]


class ContextFile(_Model):
    path: str
    role: FileRole
    score: float
    fact_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class ContextBundle(_Model):
    terms: tuple[str, ...]
    unmatched_terms: tuple[str, ...]
    confidence: Confidence
    seeds: tuple[Seed, ...]
    files: tuple[ContextFile, ...]
    impact: tuple[ContextFile, ...]
    conventions: tuple[str, ...]
    notes: tuple[str, ...]
    report_complete: bool
    report_fingerprint: str


def retrieve_context(
    report: AnalysisReport, prompt: str, config: RetrievalConfig | None = None
) -> ContextBundle:
    cfg = config or RetrievalConfig()
    index = ReportIndex(report)
    prompt_tokens = [t for t in tokens(prompt) if t not in _STOPWORDS]
    terms = tuple(dict.fromkeys(prompt_tokens))
    stems = {t: _stem(t) for t in terms}

    candidates = [f for f in report.facts if f.kind not in _NOISE_KINDS and f.status != "unknown"]
    document_frequency: dict[str, int] = defaultdict(int)
    for fact in candidates:
        strong, weak = _fact_words(fact)
        for word in {_stem(w) for w in strong | weak}:
            document_frequency[word] += 1
    weights = {t: 1 / (1 + document_frequency.get(stems[t], 0) / 5) for t in terms}
    identifiers = _identifiers(prompt)

    scored: dict[str, tuple[float, set[str]]] = {}
    for fact in candidates:
        score, matched = _score_fact(fact, terms, stems, weights, identifiers)
        if score >= cfg.min_score:
            scored[fact.id] = (score, matched)

    best = max((v[0] for v in scored.values()), default=0.0)
    seed_ids = sorted(
        (i for i in scored if scored[i][0] >= best * cfg.relative_cutoff),
        key=lambda i: (-scored[i][0], i),
    )[: cfg.max_seeds]
    seeds = tuple(
        Seed(
            fact_id=i,
            kind=index.get(i).kind,  # type: ignore[union-attr]
            subject=index.get(i).subject[:200],  # type: ignore[union-attr]
            score=round(scored[i][0], 2),
            matched_terms=tuple(sorted(scored[i][1])),
        )
        for i in seed_ids
    )
    matched_terms = {t for i in seed_ids for t in scored[i][1]}
    unmatched = tuple(t for t in terms if t not in matched_terms)

    related = _expand(index, seed_ids, scored, cfg.hops, outgoing=True)
    dependants = _expand(index, seed_ids, scored, cfg.hops, outgoing=False)

    file_scores: dict[str, float] = defaultdict(float)
    file_roles: dict[str, FileRole] = {}
    file_facts: dict[str, set[str]] = defaultdict(set)
    file_reasons: dict[str, set[str]] = defaultdict(set)

    def add(fact_id: str, weight: float, role: FileRole, why: str) -> None:
        fact = index.get(fact_id)
        if fact is None:
            return
        for path in sorted({e.path for e in fact.evidence}):
            if _BUILD_FILE.search(path) and role != "build":
                continue
            file_scores[path] += weight
            file_facts[path].add(fact_id)
            file_reasons[path].add(why)
            if _RANK[role] < _RANK.get(file_roles.get(path, "overview"), 9):
                file_roles[path] = role

    for i in seed_ids:
        add(i, scored[i][0], "primary", f"matches {', '.join(sorted(scored[i][1]))}")
    for i, (weight, via) in related.items():
        if i not in scored or i not in seed_ids:
            add(i, weight, "related", f"linked to {via}")
    impact_scores: dict[str, float] = defaultdict(float)
    impact_facts: dict[str, set[str]] = defaultdict(set)
    impact_reasons: dict[str, set[str]] = defaultdict(set)
    for i, (weight, via) in dependants.items():
        if i in seed_ids:
            continue
        fact = index.get(i)
        if fact is None:
            continue
        for path in sorted({e.path for e in fact.evidence}):
            if _BUILD_FILE.search(path) or path in file_roles and file_roles[path] == "primary":
                continue
            impact_scores[path] += weight
            impact_facts[path].add(i)
            impact_reasons[path].add(f"depends on {via}")

    notes: list[str] = []
    wants_build = bool(set(terms) & _BUILD_WORDS)
    if wants_build or seeds:
        for fact in report.facts:
            if fact.kind in ("module", "dependency", "permission") and (
                wants_build or fact.id in related
            ):
                for path in sorted({e.path for e in fact.evidence}):
                    if _BUILD_FILE.search(path):
                        file_scores[path] += 0.5
                        file_facts[path].add(fact.id)
                        file_reasons[path].add("build or manifest file for this change")
                        file_roles.setdefault(path, "build")

    confidence = _confidence(seeds, terms, unmatched)
    if not seeds:
        notes.append(
            "no part of the project matched the request; the overview below is a fallback "
            "and the request may need clarifying"
        )
        for fact in report.facts:
            if fact.kind in ("compose_screen", "activity", "application"):
                add(fact.id, 0.1, "overview", "entry point or screen of the project")  # type: ignore[arg-type]
    if unmatched and seeds:
        notes.append("some request terms matched nothing: " + ", ".join(unmatched[:10]))
    if not report.complete:
        notes.append("the analysis is incomplete; some files may have been missed")

    files = _files(file_scores, file_roles, file_facts, file_reasons)[: cfg.max_files]
    primary_paths = {f.path for f in files}
    impact = [
        f
        for f in _files(
            impact_scores, dict.fromkeys(impact_scores, "impact"), impact_facts, impact_reasons
        )
        if f.path not in primary_paths
    ][: cfg.max_impact]

    conventions = tuple(
        sorted({f.subject[:160] for f in index.of_kind("convention") if f.status == "confirmed"})
    )[:12]
    return ContextBundle(
        terms=terms,
        unmatched_terms=unmatched,
        confidence=confidence,
        seeds=seeds,
        files=tuple(files),
        impact=tuple(impact),
        conventions=conventions,
        notes=tuple(notes),
        report_complete=report.complete,
        report_fingerprint=report.fingerprint,
    )


_RANK: dict[str, int] = {"primary": 0, "related": 1, "build": 2, "overview": 3, "impact": 4}


def _files(
    scores: dict[str, float],
    roles: dict[str, FileRole],
    facts: dict[str, set[str]],
    reasons: dict[str, set[str]],
) -> list[ContextFile]:
    ordered = sorted(scores, key=lambda p: (_RANK[roles.get(p, "overview")], -scores[p], p))
    return [
        ContextFile(
            path=p,
            role=roles.get(p, "overview"),
            score=round(scores[p], 2),
            fact_ids=tuple(sorted(facts[p]))[:10],
            reasons=tuple(sorted(reasons[p]))[:5],
        )
        for p in ordered
    ]


def _fact_words(fact: Fact) -> tuple[set[str], set[str]]:
    """Name words (strong) and other words (weak) that describe a fact."""
    subject = fact.subject.split("(")[0]
    strong = set(tokens(subject.rsplit("#", 1)[-1].rsplit(".", 1)[-1]))
    for key in ("name", "route", "table", "tableName", "class", "layout", "file"):
        value = fact.attributes.get(key)
        if isinstance(value, str):
            strong |= set(tokens(value.rsplit(".", 1)[-1]))
    if fact.evidence:
        stem = fact.evidence[0].path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        strong |= set(tokens(stem))
    weak = set(tokens(subject))
    for value in fact.attributes.values():
        if isinstance(value, str) and len(value) < 80:
            weak |= set(tokens(value))
    return strong, weak - strong


def _identifiers(prompt: str) -> tuple[str, ...]:
    """CamelCase names written in the prompt (``AddNote``, ``loginViewModel``), lower-cased."""
    found = re.findall(r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+", prompt)
    return tuple(dict.fromkeys(i.lower() for i in found))


def _name_of(fact: Fact) -> str:
    subject = fact.subject.split("(")[0]
    return subject.rsplit("#", 1)[-1].rsplit(".", 1)[-1].lower()


def _score_fact(
    fact: Fact,
    terms: Iterable[str],
    stems: dict[str, str],
    weights: dict[str, float],
    identifiers: tuple[str, ...],
) -> tuple[float, set[str]]:
    """A name match selects a fact; a kind hint ("the screen") only boosts one."""
    strong, weak = _fact_words(fact)
    strong_stems = {_stem(w) for w in strong}
    weak_stems = {_stem(w) for w in weak}
    score = 0.0
    matched: set[str] = set()
    boost = 0.0
    for term in terms:
        stem = stems[term]
        hinted = _KIND_HINTS.get(term) or _KIND_HINTS.get(stem)
        if hinted:
            if fact.kind in hinted:
                boost += 1.5
            continue  # a kind word ("screen") never selects a fact by itself
        if term in strong or stem in strong_stems:
            score += 3.0 * weights[term]
            matched.add(term)
        elif term in weak or stem in weak_stems:
            score += 1.0 * weights[term]
            matched.add(term)
    name = _name_of(fact)
    for ident in identifiers:
        if name == ident:
            score += 8.0
            matched.add(ident)
        elif (
            len(name) >= 5
            and len(ident) >= 5
            and (name.startswith(ident) or ident.startswith(name))
        ):
            score += 5.0
            matched.add(ident)
    if not score:
        return 0.0, set()
    return score + boost, matched


def _expand(
    index: ReportIndex,
    seeds: list[str],
    scored: dict[str, tuple[float, set[str]]],
    hops: int,
    *,
    outgoing: bool,
) -> dict[str, tuple[float, str]]:
    """Facts reachable from the seeds (forwards) or that reach them (backwards), with a score."""
    found: dict[str, tuple[float, str]] = {}
    frontier = [(s, scored[s][0], s) for s in seeds]
    seen = set(seeds)
    for depth in range(1, hops + 1):
        weight_factor = 0.5**depth
        nxt: list[tuple[str, float, str]] = []
        for fact_id, base, origin in sorted(frontier):
            edges = index.outgoing(fact_id) if outgoing else index.incoming(fact_id)
            for edge in sorted(edges, key=lambda e: (e.kind, e.source, e.target)):
                if edge.kind in _BROAD_EDGES or edge.status == "unknown":
                    continue
                other = edge.target if outgoing else edge.source
                if other in seen:
                    continue
                seen.add(other)
                fact = index.get(other)
                if fact is None or fact.kind in _NOISE_KINDS:
                    continue
                found[other] = (base * weight_factor, _short(origin))
                nxt.append((other, base, origin))
        frontier = nxt
    return found


def _short(fact_id: str) -> str:
    return fact_id.split(":", 1)[-1].rsplit("#", 1)[-1][:80]


def _confidence(
    seeds: tuple[Seed, ...], terms: tuple[str, ...], unmatched: tuple[str, ...]
) -> Confidence:
    if not seeds:
        return "none"
    top = seeds[0].score
    covered = 1 - (len(unmatched) / len(terms)) if terms else 0
    if top >= 3.0 and covered >= 0.6:
        return "high"
    if top >= 3.0 or covered >= 0.5:
        return "medium"
    return "low"
