"""The set of project files a review looks at."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from androai_codegen.editing.errors import CodegenError
from androai_codegen.editing.paths import normalize_relative_path
from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.workspace import Workspace

from .models import ReviewConfig

TEXT_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".gradle", ".toml", ".proto")


def is_text_path(path: str) -> bool:
    return path.endswith(TEXT_SUFFIXES)


@dataclass(frozen=True)
class ProjectFiles:
    """Reviewable text by path, plus the paths of every other file (images, fonts, ...).

    Binary resources matter only by name: ``R.drawable.logo`` is valid if ``res/drawable/logo.png``
    exists.
    """

    texts: Mapping[str, str] = field(default_factory=dict)
    other_paths: frozenset[str] = frozenset()

    @property
    def paths(self) -> frozenset[str]:
        return frozenset(self.texts) | self.other_paths

    @classmethod
    def from_mapping(cls, files: Mapping[str, str | bytes | None]) -> ProjectFiles:
        """``str`` values are text; bytes/None mean 'a file exists here but is not reviewable'."""
        texts: dict[str, str] = {}
        others: set[str] = set()
        for path, content in files.items():
            normalized = normalize_relative_path(path)
            if isinstance(content, str) and is_text_path(normalized):
                texts[normalized] = content
            else:
                others.add(normalized)
        return cls(texts, frozenset(others))

    @classmethod
    def from_workspace(
        cls,
        workspace: Workspace,
        *,
        protection: ProtectionPolicy = DEFAULT_POLICY,
        config: ReviewConfig | None = None,
    ) -> ProjectFiles:
        """Read the project. Protected files (keys, ``.env``...) are never opened."""
        config = config or ReviewConfig()
        texts: dict[str, str] = {}
        others: set[str] = set()
        for count, rel in enumerate(workspace.iter_files()):
            if count >= config.max_files:
                break
            if protection.is_protected(rel):
                continue
            if not is_text_path(rel):
                others.add(rel)
                continue
            try:
                if os.path.getsize(workspace.resolve(rel)) > config.max_file_bytes:
                    others.add(rel)
                    continue
                texts[rel] = workspace.read_text(rel)
            except (OSError, CodegenError):  # too large, unreadable, or not UTF-8 text
                others.add(rel)
        return cls(texts, frozenset(others))

    def overlay(self, changes: Mapping[str, str | None]) -> ProjectFiles:
        """The project after applying ``changes`` (path -> new text, ``None`` = deleted)."""
        texts = dict(self.texts)
        others = set(self.other_paths)
        for path, content in changes.items():
            normalized = normalize_relative_path(path)
            texts.pop(normalized, None)
            others.discard(normalized)
            if content is None:
                continue
            if is_text_path(normalized):
                texts[normalized] = content
            else:
                others.add(normalized)
        return ProjectFiles(texts, frozenset(others))

    def with_paths(self, extra: Iterable[str]) -> ProjectFiles:
        return ProjectFiles(self.texts, self.other_paths | frozenset(extra))
