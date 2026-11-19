"""Protected-file policy: files the engine must never modify or show to an LLM."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

# Matched case-insensitively against the full relative path and against the file name.
DEFAULT_PROTECTED_PATTERNS: tuple[str, ...] = (
    "*.jks",
    "*.keystore",
    "*.p12",
    "*.pfx",
    "*.pem",
    "*.key",
    "keystore.properties",
    "local.properties",
    "secrets.properties",
    ".env",
    ".env.*",
    "*service-account*.json",
)


@dataclass(frozen=True)
class ProtectionPolicy:
    patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS

    def is_protected(self, rel_path: str) -> bool:
        """``rel_path`` must already be normalized (see ``normalize_relative_path``)."""
        full = rel_path.lower()
        name = full.rsplit("/", 1)[-1]
        return any(
            fnmatch.fnmatchcase(full, pat.lower()) or fnmatch.fnmatchcase(name, pat.lower())
            for pat in self.patterns
        )


DEFAULT_POLICY = ProtectionPolicy()
