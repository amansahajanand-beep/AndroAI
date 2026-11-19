"""Rule groups. Each module exposes ``check(analysis) -> Iterator[Finding]``."""

from __future__ import annotations

from types import ModuleType

from . import gradle, imports, manifest, resources, syntax

RULE_MODULES: tuple[ModuleType, ...] = (syntax, imports, resources, gradle, manifest)
