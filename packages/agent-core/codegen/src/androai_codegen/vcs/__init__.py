"""Checkpoints, diffs, change summaries and file history via a shadow git repository."""

from .errors import (
    CheckpointNotFoundError,
    GitCommandError,
    GitNotAvailableError,
    RestoreConflict,
    TrackingError,
    VcsError,
)
from .manager import CheckpointManager
from .models import (
    ChangeSummary,
    Checkpoint,
    CommitChanges,
    DiffResult,
    FileSummary,
    HistoryEntry,
    Origin,
    PathChange,
    RestoreConflictItem,
    RestoreResult,
    SkippedPath,
    SnapshotInfo,
    TrackedApply,
)
from .protocol import VersionControl
from .shadow_git import ShadowGit

__all__ = [
    "ChangeSummary",
    "Checkpoint",
    "CheckpointManager",
    "CheckpointNotFoundError",
    "CommitChanges",
    "DiffResult",
    "FileSummary",
    "GitCommandError",
    "GitNotAvailableError",
    "HistoryEntry",
    "Origin",
    "PathChange",
    "RestoreConflict",
    "RestoreConflictItem",
    "RestoreResult",
    "ShadowGit",
    "SkippedPath",
    "SnapshotInfo",
    "TrackedApply",
    "TrackingError",
    "VcsError",
    "VersionControl",
]
