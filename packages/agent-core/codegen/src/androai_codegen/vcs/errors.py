"""Exception types for the version-control layer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from androai_codegen.editing.errors import CodegenError

if TYPE_CHECKING:
    from androai_codegen.editing.models import ApplyResult

    from .models import RestoreConflictItem


class VcsError(CodegenError):
    """Base class for version-control failures."""


class GitNotAvailableError(VcsError):
    """The ``git`` executable was not found."""


class GitCommandError(VcsError):
    """A git command failed."""

    def __init__(self, args: Sequence[str], returncode: int | None, stderr: str) -> None:
        self.git_args = tuple(args)
        self.returncode = returncode
        self.stderr = stderr[:500]
        verb = args[0] if args else "?"
        super().__init__(f"git {verb} failed (exit {returncode}): {self.stderr}")


class CheckpointNotFoundError(VcsError):
    """No checkpoint exists with the given id."""


class RestoreConflict(VcsError):
    """Files the AI changed were also changed manually; restoring them would lose that work."""

    def __init__(self, conflicts: Sequence[RestoreConflictItem]) -> None:
        self.conflicts = tuple(conflicts)
        detail = "; ".join(f"{c.path}: {c.reason}" for c in conflicts)
        super().__init__(f"restore would discard manual changes: {detail}")


class TrackingError(VcsError):
    """The patch WAS applied, but recording it in version control failed.

    ``apply_result`` identifies the patch so the caller can still roll it back with
    ``PatchEngine.rollback``.
    """

    def __init__(self, message: str, apply_result: ApplyResult) -> None:
        self.apply_result = apply_result
        super().__init__(message)
