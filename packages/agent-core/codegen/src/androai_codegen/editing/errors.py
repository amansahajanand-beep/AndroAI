"""Exception types for the editing engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import PatchPreview, Problem


class CodegenError(Exception):
    """Base class for all errors raised by this package."""


class PathValidationError(CodegenError, ValueError):
    """A path is unsafe (traversal, absolute, symlink, reserved name, ...)."""


class ProtectedFileError(CodegenError):
    """The file is protected (secrets, signing keys, ...) and must not be read for an LLM."""


class NotTextFileError(CodegenError):
    """The file is not valid UTF-8 text."""


class WorkspaceBusyError(CodegenError):
    """Another engine instance holds the workspace lock."""


class JournalError(CodegenError):
    """The journal is inconsistent or belongs to another project."""


class UnknownPatchError(JournalError):
    """No journal entry exists for the given patch id."""


class PatchStateError(CodegenError):
    """The patch is not in a state that allows the requested operation."""


class PatchRejected(CodegenError):
    """Validation found blocking problems (or nothing to do). Nothing was changed."""

    def __init__(self, preview: PatchPreview) -> None:
        self.preview = preview
        super().__init__(preview.summary())


class PatchApplyError(CodegenError):
    """An I/O failure happened while applying or rolling back. See ``rolled_back``."""

    def __init__(
        self, message: str, *, rolled_back: bool, failed_paths: Sequence[str] = ()
    ) -> None:
        self.rolled_back = rolled_back
        self.failed_paths = tuple(failed_paths)
        super().__init__(message)


class RollbackConflict(CodegenError):
    """Files changed after the patch was applied; rollback would discard those changes."""

    def __init__(self, conflicts: Sequence[Problem]) -> None:
        self.conflicts = tuple(conflicts)
        detail = "; ".join(f"{c.path}: {c.message}" for c in conflicts)
        super().__init__(f"rollback would overwrite later changes: {detail}")
