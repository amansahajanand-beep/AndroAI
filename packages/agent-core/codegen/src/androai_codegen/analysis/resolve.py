"""Resolving a name written in a source file to a fully qualified name.

How a name was resolved decides how strongly a fact built on it can be stated:

``qualified``     written with its package (``dagger.hilt.android.AndroidEntryPoint``)
``explicit``      an ``import`` names it (aliases included)
``same_package``  a project type of the file's own package (or nested in an enclosing type)
``wildcard``      a ``pkg.*`` import whose package really contains that name
``by_name``       only the simple name matches; no import shows where it comes from
``unresolved``    nothing matched

The first four are *exact*: the project's own text says what the name is. ``by_name`` is a
guess and facts built on it are ``inferred``.

Cost. A file can carry thousands of imports and be asked about thousands of names, so a lookup
must not walk the import list: every file gets an ``ImportIndex`` (built once, on first use) and
each lookup is a few dictionary probes. A lookup that finds nothing costs the same as one that
does, and a repeated question is answered from a memo.
"""

from __future__ import annotations

import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from androai_codegen.review.source import SourceFile

How = Literal["qualified", "explicit", "same_package", "wildcard", "by_name", "unresolved"]
EXACT = frozenset({"qualified", "explicit", "same_package", "wildcard"})
MAX_TAIL = 6


@dataclass(frozen=True)
class Resolution:
    fqn: str | None
    how: How

    @property
    def exact(self) -> bool:
        return self.how in EXACT


UNRESOLVED = Resolution(None, "unresolved")


def _split(written: str) -> tuple[str, str]:
    first, _, rest = written.partition(".")
    return first, rest


class ImportIndex:
    """The imports of one file, arranged for constant-time questions.

    ``explicit``   simple name (alias included) -> the imported FQN; the first import of a name
                   wins, exactly as a front-to-back scan would have it
    ``wildcards``  package of every non-static ``pkg.*`` import -> its position, so "which
                   wildcard comes first" is still answerable; a package imported twice counts once
    """

    __slots__ = ("_all", "_prefixes", "explicit", "wildcards")

    def __init__(self, source: SourceFile) -> None:
        self.explicit: dict[str, str] = {}
        self.wildcards: dict[str, int] = {}
        self._all = tuple(imp.fqn for imp in source.imports)
        self._prefixes: dict[str, bool] = {}
        for position, imp in enumerate(source.imports):
            if imp.static:
                continue
            if imp.wildcard:
                self.wildcards.setdefault(imp.fqn, position)
            else:
                name = imp.simple_name
                if name is not None:
                    self.explicit.setdefault(name, imp.fqn)

    def imports_from(self, prefix: str) -> bool:
        """Whether any import (static and wildcard included) starts with ``prefix``; each prefix
        is scanned for once per file, however often it is asked."""
        found = self._prefixes.get(prefix)
        if found is None:
            found = self._prefixes[prefix] = any(fqn.startswith(prefix) for fqn in self._all)
        return found


_INDEXES: weakref.WeakKeyDictionary[SourceFile, ImportIndex] = weakref.WeakKeyDictionary()


def import_index(source: SourceFile) -> ImportIndex:
    """The (cached) ``ImportIndex`` of ``source``."""
    index = _INDEXES.get(source)
    if index is None:
        index = _INDEXES[source] = ImportIndex(source)
    return index


def resolve_known(
    source: SourceFile, written: str, known: Mapping[str, tuple[str, ...]]
) -> Resolution:
    """Resolve ``written`` against a table of well-known names (simple name -> accepted FQNs)."""
    first, rest = _split(written)
    if rest and first[:1].islower():
        return Resolution(written, "qualified")
    index = import_index(source)
    imported = index.explicit.get(first)
    if imported is not None:
        return Resolution(f"{imported}.{rest}" if rest else imported, "explicit")
    # A wildcard names the thing only if its package really contains a known name: look the
    # known FQNs up, not the imports (``accepted`` is a handful of entries, imports are not).
    suffix = "." + written
    best: tuple[int, str] | None = None
    for fqn in {*known.get(written, ()), *known.get(first, ())}:
        if fqn.endswith(suffix):
            package = fqn[: -len(suffix)]
            position = index.wildcards.get(package)
            if position is not None and (best is None or position < best[0]):
                best = (position, fqn)
    if best is not None:
        return Resolution(best[1], "wildcard")
    if written in known or first in known:
        return Resolution(None, "by_name")
    return UNRESOLVED


def level_for(
    resolution: Resolution, accepted: tuple[str, ...]
) -> Literal["confirmed", "inferred"] | None:
    """How strongly ``resolution`` says "this is one of ``accepted``".

    ``None`` when the name resolved to something else (a project class that happens to share the
    simple name, a different library).
    """
    if resolution.exact:
        return "confirmed" if resolution.fqn in accepted else None
    if resolution.how == "by_name":
        return "inferred"
    return None


class TypeResolver:
    """Resolves names to project types. Built once all types are known (see ``members``)."""

    def __init__(self, fqns: set[str]) -> None:
        self.fqns = fqns
        self.by_simple: dict[str, list[str]] = {}
        # tail -> packages: for ``a.b.Outer.Inner`` the tails are ``Inner`` (package
        # ``a.b.Outer``), ``Outer.Inner`` (package ``a.b``) and so on; a wildcard import of that
        # package is what makes the tail a usable name. Only the last ``MAX_TAIL`` segments are
        # indexed: nobody writes a longer name relative to a wildcard, and it keeps the index
        # linear however deeply a hostile file nests its types.
        self.by_tail: dict[str, list[str]] = {}
        for fqn in sorted(fqns):
            self.by_simple.setdefault(fqn.rsplit(".", 1)[-1], []).append(fqn)
            parts = fqn.split(".")
            for cut in range(max(1, len(parts) - MAX_TAIL), len(parts)):
                self.by_tail.setdefault(".".join(parts[cut:]), []).append(".".join(parts[:cut]))
        self._memo: weakref.WeakKeyDictionary[
            SourceFile, dict[tuple[str, str | None], Resolution]
        ] = weakref.WeakKeyDictionary()

    def resolve(self, source: SourceFile, written: str, owner: str | None = None) -> Resolution:
        memo = self._memo.get(source)
        if memo is None:
            memo = self._memo[source] = {}
        key = (written, owner)
        cached = memo.get(key)
        if cached is None:
            cached = memo[key] = self._resolve(source, written, owner)
        return cached

    def _wildcard_hits(self, index: ImportIndex, written: str) -> list[str]:
        """FQNs of ``written`` reachable through a wildcard import, in import order.

        Walks whichever side is shorter: the project packages that hold this tail, or the file's
        wildcard imports - never the product of the two.
        """
        packages = self.by_tail.get(written, ())
        if not packages or not index.wildcards:
            return []
        if len(packages) <= len(index.wildcards):
            found = [(index.wildcards[p], p) for p in set(packages) if p in index.wildcards]
        else:
            found = [
                (position, package)
                for package, position in index.wildcards.items()
                if f"{package}.{written}" in self.fqns
            ]
        return [f"{package}.{written}" for _, package in sorted(found)]

    def _resolve(self, source: SourceFile, written: str, owner: str | None) -> Resolution:
        first, rest = _split(written)
        if rest and first[:1].islower() and written in self.fqns:
            return Resolution(written, "qualified")
        index = import_index(source)
        imported = index.explicit.get(first)
        if imported is not None:
            target = f"{imported}.{rest}" if rest else imported
            return Resolution(target, "explicit") if target in self.fqns else UNRESOLVED
        scope = owner
        while scope:  # a type nested in the same (or an enclosing) type
            candidate = f"{scope}.{written}"
            if candidate in self.fqns:
                return Resolution(candidate, "same_package")
            scope = scope.rsplit(".", 1)[0] if "." in scope else None
        package = source.package
        candidate = f"{package}.{written}" if package else written
        if candidate in self.fqns:
            return Resolution(candidate, "same_package")
        hits = self._wildcard_hits(index, written)
        if len(hits) == 1:
            return Resolution(hits[0], "wildcard")
        if not rest:
            options = self.by_simple.get(first, [])
            if len(options) == 1 and not hits:
                return Resolution(options[0], "by_name")
        return UNRESOLVED
