"""What an import will copy, decided before a single byte is written."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from .models import (
    MAX_LISTED_PATHS,
    MAX_LISTED_SKIPPED,
    AndroidCheck,
    SkippedItem,
)

_GRADLE_ROOT_FILES = ("settings.gradle.kts", "settings.gradle", "build.gradle.kts", "build.gradle")


@dataclass(frozen=True)
class PlannedEntry:
    rel: str  # canonical project-relative path
    kind: Literal["file", "dir"]
    size: int = 0  # the file system's size (directory) or the archive's claim (ZIP)
    compressed: int | None = None  # the archive's claim; only used as a hint
    mtime_ns: int | None = None
    source: object = None  # a Path (directory import) or a ZipInfo (archive)


@dataclass
class Plan:
    entries: list[PlannedEntry] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    skipped_total: int = 0
    symlinks_skipped: list[str] = field(default_factory=list)
    symlinks_skipped_total: int = 0
    nested_archives: list[str] = field(default_factory=list)
    nested_archives_total: int = 0
    stripped_root: str | None = None
    warnings: list[str] = field(default_factory=list)
    files: int = 0
    directories: int = 0
    declared_bytes: int = 0

    def skip(self, path: str, reason: Literal["excluded_directory", "excluded_file"]) -> None:
        self.skipped_total += 1
        if len(self.skipped) < MAX_LISTED_SKIPPED:
            self.skipped.append(SkippedItem(path=path, reason=reason))

    def skip_symlink(self, path: str) -> None:
        self.skipped_total += 1
        self.symlinks_skipped_total += 1
        if len(self.skipped) < MAX_LISTED_SKIPPED:
            self.skipped.append(SkippedItem(path=path, reason="symlink"))
        if len(self.symlinks_skipped) < MAX_LISTED_PATHS:
            self.symlinks_skipped.append(path)

    def note_nested_archive(self, path: str) -> None:
        self.nested_archives_total += 1
        if len(self.nested_archives) < MAX_LISTED_PATHS:
            self.nested_archives.append(path)

    def file_paths(self) -> list[str]:
        return [entry.rel for entry in self.entries if entry.kind == "file"]


def android_check(paths: Iterable[str]) -> AndroidCheck:
    """A shallow structural check: a Gradle build file at the root and a manifest somewhere.

    This is not project analysis. It only catches an import of the wrong folder.
    """
    names = set(paths)
    root_gradle = [name for name in _GRADLE_ROOT_FILES if name in names]
    manifests = sum(1 for name in names if name.rsplit("/", 1)[-1] == "AndroidManifest.xml")
    return AndroidCheck(
        detected=bool(root_gradle) and manifests > 0,
        manifests=manifests,
        gradle_files_at_root=root_gradle,
    )
