"""Data models for snapshots, checkpoints, history and summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from androai_codegen.editing.models import ApplyResult

Origin = Literal["baseline", "manual", "ai", "rollback"]
ORIGINS: tuple[str, ...] = ("baseline", "manual", "ai", "rollback")
ChangeStatus = Literal["added", "modified", "deleted"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathChange(_Model):
    path: str
    status: ChangeStatus


class SkippedPath(_Model):
    """A file deliberately left out of tracking."""

    path: str
    reason: str  # protected | too_large | invalid_path | not_regular_file


class SnapshotInfo(_Model):
    commit: str
    origin: Origin
    message: str
    run_id: str | None = None
    task_id: str | None = None
    patch_id: str | None = None
    created_at: datetime
    changes: list[PathChange] = Field(default_factory=list)
    skipped: list[SkippedPath] = Field(default_factory=list)


class CommitChanges(_Model):
    commit: str
    origin: Origin
    run_id: str | None = None
    task_id: str | None = None
    patch_id: str | None = None
    message: str
    created_at: datetime
    changes: list[PathChange] = Field(default_factory=list)


class HistoryEntry(_Model):
    """One change to one file, with who made it."""

    commit: str
    origin: Origin
    status: ChangeStatus
    run_id: str | None = None
    task_id: str | None = None
    patch_id: str | None = None
    message: str
    created_at: datetime


class FileSummary(_Model):
    path: str
    status: ChangeStatus
    additions: int | None  # None for binary files
    deletions: int | None


class ChangeSummary(_Model):
    files: list[FileSummary] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    @property
    def text(self) -> str:
        count = len(self.files)
        noun = "file" if count == 1 else "files"
        return f"{count} {noun} changed, +{self.additions} -{self.deletions}"


class DiffResult(_Model):
    text: str
    truncated: bool = False


class Checkpoint(_Model):
    id: str
    label: str
    commit: str
    run_id: str | None = None
    task_id: str | None = None
    created_at: datetime
    manual_commit: str | None = None  # set if manual changes were recorded to create it


class RestoreConflictItem(_Model):
    path: str
    reason: str


class RestoreResult(_Model):
    checkpoint_id: str
    patch_id: str | None = None  # the engine patch that did the restore, if any
    restored: list[str] = Field(default_factory=list)
    conflicts: list[RestoreConflictItem] = Field(default_factory=list)  # skipped, kept as-is
    snapshot: SnapshotInfo | None = None


class TrackedApply(_Model):
    """Outcome of applying a patch through the tracker."""

    result: ApplyResult
    ai_snapshot: SnapshotInfo | None
    manual_snapshot: SnapshotInfo | None  # manual edits recorded just before the patch
    warnings: list[str] = Field(default_factory=list)
