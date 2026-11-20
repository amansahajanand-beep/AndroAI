"""The version-control seam.

``CheckpointManager`` depends only on this protocol. ``ShadowGit`` is the local implementation;
if the platform later provides a shared Git service, implement these methods against it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import (
    ChangeSummary,
    CommitChanges,
    DiffResult,
    HistoryEntry,
    Origin,
    PathChange,
    SnapshotInfo,
)


class VersionControl(Protocol):
    def init(self) -> None: ...

    def head(self) -> str | None:
        """Latest snapshot commit id, or ``None`` if nothing was recorded yet."""

    def snapshot(
        self,
        *,
        origin: Origin,
        description: str,
        run_id: str | None = None,
        task_id: str | None = None,
        patch_id: str | None = None,
        paths: Iterable[str] | None = None,
    ) -> SnapshotInfo | None:
        """Record the workspace (or only ``paths``). ``None`` if there was nothing new."""

    def pending_changes(self) -> list[PathChange]:
        """Workspace changes not yet recorded: by definition, not made by the engine."""

    def commits_between(self, base: str | None, head: str = "HEAD") -> list[CommitChanges]:
        """Commits after ``base`` up to ``head``, oldest first."""

    def read_blob(self, commit: str, path: str) -> bytes | None:
        """Exact bytes of ``path`` at ``commit``, or ``None`` if it did not exist."""

    def diff(
        self,
        base: str,
        head: str | None = None,
        *,
        paths: Iterable[str] | None = None,
        mask: bool = True,
    ) -> DiffResult:
        """Unified diff; ``head=None`` means the current workspace state."""

    def summary(self, base: str, head: str | None = None) -> ChangeSummary: ...

    def file_history(self, path: str, limit: int = 50) -> list[HistoryEntry]:
        """Changes to one file, newest first."""
