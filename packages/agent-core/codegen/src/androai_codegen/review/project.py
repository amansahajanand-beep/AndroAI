"""The set of project files a review looks at."""

from __future__ import annotations

import os
import time
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


class FileCache:
    """Texts of files already read, with the size and modification time they had.

    A cached text is reused only if the file's size and mtime still match **and** the file was
    last modified more than ``RACY_NS`` ago. A file touched more recently is always read again:
    timestamps are coarse on some file systems, so a same-size rewrite within the same tick would
    otherwise look unchanged (the "racily clean" problem git solves the same way). What this cannot
    see is an edit that keeps both size and mtime and is older than the margin, e.g. ``touch -r``.
    """

    RACY_NS = 2_000_000_000

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, int, str]] = {}
        self.reads = 0  # how many files were actually read from disk

    def lookup(self, rel: str, stat: os.stat_result, now_ns: int) -> str | None:
        hit = self._entries.get(rel)
        if (
            hit is not None
            and hit[0] == stat.st_size
            and hit[1] == stat.st_mtime_ns
            and now_ns - stat.st_mtime_ns > self.RACY_NS
        ):
            return hit[2]
        return None

    def store(self, rel: str, stat: os.stat_result, text: str) -> None:
        self._entries[rel] = (stat.st_size, stat.st_mtime_ns, text)
        self.reads += 1

    def keep_only(self, present: Mapping[str, str]) -> None:
        for rel in [r for r in self._entries if r not in present]:
            del self._entries[rel]

    def clear(self) -> None:
        self._entries.clear()


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
        cache: FileCache | None = None,
    ) -> ProjectFiles:
        """Read the project. Protected files (keys, ``.env``...) are never opened.

        With a ``cache``, a file whose size and modification time are unchanged (and old enough
        to trust, see :class:`FileCache`) is not read again.
        """
        config = config or ReviewConfig()
        texts: dict[str, str] = {}
        others: set[str] = set()
        now = time.time_ns()
        for count, rel in enumerate(workspace.iter_files()):
            if count >= config.max_files:
                break
            if protection.is_protected(rel):
                continue
            if not is_text_path(rel):
                others.add(rel)
                continue
            try:
                stat = os.stat(workspace.resolve(rel))
                if stat.st_size > config.max_file_bytes:
                    others.add(rel)
                    continue
                if cache is not None and (hit := cache.lookup(rel, stat, now)) is not None:
                    texts[rel] = hit
                    continue
                text = workspace.read_text(rel)
                texts[rel] = text
                if cache is not None:
                    cache.store(rel, stat, text)
            except (OSError, CodegenError):  # too large, unreadable, or not UTF-8 text
                others.add(rel)
        if cache is not None:
            cache.keep_only(texts)
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
