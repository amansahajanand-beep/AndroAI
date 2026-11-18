"""Searchable, tenant/project-scoped project index with incremental updates.

The index keeps tokenised text in memory only. What is persisted (see
persistence) is metadata: FileInfo/profile/hashes. Source is re-read through a
FileSource when needed, so the platform never keeps a second copy of tenant code."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Protocol

from ..providers.budget import estimate_tokens
from ..providers.redaction import redact
from .analyzer import analyze_project, analyze_source, normalize_path, sha256
from .models import FileInfo, ProjectProfile, ProjectScope, RetrievedChunk

_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "with", "is", "it", "import", "val", "var", "fun", "class", "return", "this", "that", "package"}


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for word in _SPLIT.split(text):
        if not word:
            continue
        parts = _CAMEL.split(word)
        out.extend(p.lower() for p in parts if len(p) > 1 and p.lower() not in _STOP)
        if len(parts) > 1:
            out.append(word.lower())
    return out


class FileSource(Protocol):
    """Reads project files from wherever Person 4's storage keeps them."""

    def read(self, scope: ProjectScope, path: str) -> bytes: ...


class ProjectIndex:
    def __init__(self, scope: ProjectScope):
        self.scope = scope
        self.profile = ProjectProfile()
        self.files: dict[str, FileInfo] = {}
        self._texts: dict[str, str] = {}
        self._tf: dict[str, Counter[str]] = {}
        self._df: Counter[str] = Counter()
        self._len: dict[str, int] = {}
        self._sym_defs: dict[str, set[str]] = defaultdict(set)  # symbol name -> paths

    # ---- build / update ----------------------------------------------------------
    @classmethod
    def build(cls, scope: ProjectScope, files: dict[str, bytes]) -> "ProjectIndex":
        idx = cls(scope)
        idx.profile, infos, texts = analyze_project(files)
        for info in infos:
            idx.files[info.path] = info
        for path, text in texts.items():
            idx._add_text(path, text)
        return idx

    def update(self, changed: dict[str, bytes], deleted: list[str] | None = None) -> dict[str, list[str]]:
        """Apply file changes. Unchanged content (same sha256) is a no-op. Returns
        {'added','modified','removed','unchanged'} path lists."""
        result: dict[str, list[str]] = {"added": [], "modified": [], "removed": [], "unchanged": []}
        for raw in deleted or []:
            p = normalize_path(raw)
            if p and p in self.files:
                self._remove(p)
                result["removed"].append(p)
        pending: dict[str, bytes] = {}
        for raw, data in changed.items():
            p = normalize_path(raw)
            if p is None:
                continue
            prev = self.files.get(p)
            if prev and prev.sha256 == sha256(data):
                result["unchanged"].append(p)
                continue
            result["modified" if prev else "added"].append(p)
            pending[p] = data
        if pending:
            for p in pending:
                if p in self.files:
                    self._remove(p)
            # Re-analyse changed files together with metadata-bearing existing ones is
            # unnecessary: per-file analysis is independent.
            _profile, infos, texts = analyze_project(pending)
            for info in infos:
                self.files[info.path] = info
            for path, text in texts.items():
                self._add_text(path, text)
        if result["added"] or result["modified"] or result["removed"]:
            self._rebuild_profile()
        return result

    def _rebuild_profile(self) -> None:
        # Profile aggregates manifests/gradle, so recompute from retained text.
        texts = {p: t.encode() for p, t in self._texts.items()}
        profile, _, _ = analyze_project(texts)
        for p, info in self.files.items():
            if info.skipped_reason:
                profile.skipped[p] = info.skipped_reason
        profile.file_count = len(self.files)
        self.profile = profile

    def _add_text(self, path: str, text: str) -> None:
        self._texts[path] = text
        info = self.files[path]
        # Path and symbol names are boosted by repetition.
        boosted = " ".join([path] * 3 + [s.name for s in info.symbols] * 2)
        toks = tokenize(boosted + "\n" + text)
        tf = Counter(toks)
        self._tf[path] = tf
        self._len[path] = max(1, len(toks))
        for t in tf:
            self._df[t] += 1
        for s in info.symbols:
            if s.kind in ("class", "object", "interface", "activity", "fragment", "viewmodel", "entity", "dao"):
                self._sym_defs[s.name].add(path)

    def _remove(self, path: str) -> None:
        for t in self._tf.pop(path, {}):
            self._df[t] -= 1
            if self._df[t] <= 0:
                del self._df[t]
        self._texts.pop(path, None)
        self._len.pop(path, None)
        info = self.files.pop(path, None)
        if info:
            for s in info.symbols:
                self._sym_defs.get(s.name, set()).discard(path)

    # ---- search ----------------------------------------------------------------
    def search(self, query: str, k: int = 8) -> list[tuple[str, float]]:
        q = tokenize(query)
        n = len(self._tf)
        if not q or n == 0:
            return []
        avg = sum(self._len.values()) / n
        k1, b = 1.5, 0.75
        scores: dict[str, float] = {}
        for path, tf in self._tf.items():
            s = 0.0
            for t in set(q):
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self._len[path] / avg))
            if s > 0:
                scores[path] = s
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    def dependencies_of(self, path: str) -> list[str]:
        """Files this file depends on (imports resolving to a symbol defined in the project)."""
        info = self.files.get(path)
        if not info:
            return []
        deps: set[str] = set()
        for imp in info.imports:
            simple = imp.rsplit(".", 1)[-1]
            for p in self._sym_defs.get(simple, ()):
                tgt = self.files[p]
                if p != path and tgt.package and imp.startswith(tgt.package):
                    deps.add(p)
        return sorted(deps)

    def dependents_of(self, path: str) -> list[str]:
        """Reverse edges: files that import something defined in `path` (impact analysis)."""
        return sorted(p for p in self.files if path in self.dependencies_of(p))

    def symbols_named(self, name: str) -> list[str]:
        return sorted(self._sym_defs.get(name, ()))

    # ---- retrieval -------------------------------------------------------------
    def retrieve(self, query: str, token_budget: int = 6000, k: int = 6, include_deps: bool = True) -> list[RetrievedChunk]:
        """Select the files relevant to `query` within `token_budget` (estimated
        tokens). Content is redacted. Never returns the whole project."""
        chunks: list[RetrievedChunk] = []
        seen: set[str] = set()
        used = 0

        def add(path: str, score: float, reason: str) -> None:
            nonlocal used
            if path in seen or path not in self._texts:
                return
            text = redact(self._texts[path])
            lines = text.splitlines()
            excerpt, end = [], 0
            for i, line in enumerate(lines):
                cost = estimate_tokens(line)
                if used + cost > token_budget:
                    break
                excerpt.append(line)
                used += cost
                end = i + 1
            if not excerpt:
                return
            seen.add(path)
            chunks.append(RetrievedChunk(path=path, score=round(score, 4), reason=reason,
                                         content="\n".join(excerpt), start_line=1, end_line=end))

        hits = self.search(query, k)
        for path, score in hits:
            add(path, score, "match")
        if include_deps:
            for path, score in hits:
                for dep in self.dependencies_of(path)[:3]:
                    add(dep, score * 0.5, "dependency")
        return chunks
