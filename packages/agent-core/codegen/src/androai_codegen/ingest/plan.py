"""What an import will copy, decided before a single byte is written."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
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
    project_subdir: str | None = None
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


def reroot(plan: Plan, subdir: str) -> Plan:
    """The same plan restricted to ``subdir``, which becomes the project root.

    Everything outside the folder is left out (and counted as skipped); the folder's own entry
    disappears. The sources of the kept entries are untouched, so they open as before.
    """
    prefix = subdir.strip("/") + "/"
    entries: list[PlannedEntry] = []
    outside = 0
    for entry in plan.entries:
        if entry.rel.startswith(prefix):
            entries.append(replace(entry, rel=entry.rel[len(prefix) :]))
        elif entry.rel != prefix.rstrip("/"):
            outside += 1
    kept_files = [e for e in entries if e.kind == "file"]
    warnings = list(plan.warnings)
    if outside:
        warnings.append(
            f"{outside} entr(ies) outside '{subdir}' were not imported; "
            f"'{subdir}' is the project root"
        )
    return replace(
        plan,
        entries=entries,
        skipped_total=plan.skipped_total + outside,
        nested_archives=[p[len(prefix) :] for p in plan.nested_archives if p.startswith(prefix)],
        nested_archives_total=sum(1 for e in kept_files if _is_archive(e.rel)),
        project_subdir=subdir.strip("/"),
        warnings=warnings,
        files=len(kept_files),
        directories=len(entries) - len(kept_files),
        declared_bytes=sum(e.size for e in kept_files),
    )


def _is_archive(rel: str) -> bool:
    from .names import is_nested_archive

    return is_nested_archive(rel)
