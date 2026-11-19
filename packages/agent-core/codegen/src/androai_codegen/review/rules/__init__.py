"""Rule groups. Each module exposes ``check(analysis) -> Iterator[Finding]``."""

from __future__ import annotations

from types import ModuleType

from . import auth, deeplinks, gradle, imports, manifest, navigation, resources, security, syntax

RULE_MODULES: tuple[ModuleType, ...] = (
    syntax,
    imports,
    resources,
    gradle,
    manifest,
    navigation,
    deeplinks,
    security,
    auth,
)
