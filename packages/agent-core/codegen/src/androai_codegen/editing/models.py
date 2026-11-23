"""Data models for patches, previews, change records and the journal.

These are internal to the codegen package. Mapping to the cross-service contracts
(``androai_contracts.CodingResult``) happens in the worker adapter, so the contracts can
evolve without touching the engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChangeType = Literal["create", "modify", "delete"]
PatchStatus = Literal["applying", "applied", "rolled_back", "needs_attention"]

_CHECKSUM = r"^[0-9a-f]{64}$"


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- patch input -----------------------------------------------------------------------


class TextEdit(_Model):
    """Exact-text replacement. ``old`` must match exactly once unless ``replace_all``."""

    old: str = Field(min_length=1)
    new: str
    replace_all: bool = False


class CreateFile(_Model):
    kind: Literal["create"] = "create"
    path: str = Field(min_length=1)
    content: str
    description: str = Field(min_length=1)


class ModifyFile(_Model):
    """Change an existing file, via ``edits`` (preferred) or a full ``content`` replacement.

    ``expected_checksum`` is the checksum of the version the author read. It is mandatory:
    it is how edits made by the user after the task started are detected.
    """

    kind: Literal["modify"] = "modify"
    path: str = Field(min_length=1)
    expected_checksum: str = Field(pattern=_CHECKSUM)
    content: str | None = None
    edits: list[TextEdit] | None = None
    description: str = Field(min_length=1)
    # Full-content replacement normally adopts the file's line endings (LLM output is
    # usually LF). Set False when the bytes must be written exactly, e.g. restoring a file.
    normalize_eol: bool = True

    @model_validator(mode="after")
    def _exactly_one_of_content_or_edits(self) -> ModifyFile:
        if (self.content is not None) == bool(self.edits):
            raise ValueError("provide exactly one of 'content' or a non-empty 'edits' list")
        return self


class DeleteFile(_Model):
    kind: Literal["delete"] = "delete"
    path: str = Field(min_length=1)
    expected_checksum: str = Field(pattern=_CHECKSUM)
    description: str = Field(min_length=1)


FileChange = Annotated[CreateFile | ModifyFile | DeleteFile, Field(discriminator="kind")]


class PatchSet(_Model):
    """One atomic unit of change: either every file change applies, or none does."""

    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1)
    changes: list[FileChange] = Field(min_length=1)


# --- validation output -----------------------------------------------------------------


class ProblemCode(StrEnum):
    PROJECT_MISMATCH = "project_mismatch"
    PATH_INVALID = "path_invalid"
    DUPLICATE_PATH = "duplicate_path"
    PROTECTED_FILE = "protected_file"
    TOO_MANY_FILES = "too_many_files"
    TOO_LARGE = "too_large"
    ALREADY_EXISTS = "already_exists"
    MISSING_FILE = "missing_file"
    CONFLICT = "conflict"
    NOT_TEXT = "not_text"
    EDIT_NOT_FOUND = "edit_not_found"
    EDIT_AMBIGUOUS = "edit_ambiguous"
    REDACTION_MARKER = "redaction_marker"
    APPROVAL_REQUIRED = "approval_required"
    NO_CHANGE = "no_change"
    IO_ERROR = "io_error"


class Problem(_Model):
    code: ProblemCode
    path: str | None = None
    message: str
    blocking: bool = True


class PlannedChange(_Model):
    path: str
    change_type: ChangeType
    previous_checksum: str | None
    new_checksum: str | None
    description: str


class PatchPreview(_Model):
    """Result of a dry run. Nothing has been written when you hold one of these."""

    problems: list[Problem] = Field(default_factory=list)
    planned: list[PlannedChange] = Field(default_factory=list)
    diff: str = ""

    @property
    def blocking_problems(self) -> list[Problem]:
        return [p for p in self.problems if p.blocking]

    @property
    def ok(self) -> bool:
        return bool(self.planned) and not self.blocking_problems

    @property
    def requires_approval(self) -> bool:
        return any(p.code is ProblemCode.APPROVAL_REQUIRED for p in self.problems)

    def summary(self) -> str:
        shown = self.blocking_problems or self.problems
        if not shown:
            return "patch makes no changes"
        return "; ".join(f"[{p.code.value}] {p.path or '<patch>'}: {p.message}" for p in shown)


class Simulation(_Model):
    """What a patch would produce, without writing anything (used by code review)."""

    preview: PatchPreview
    files: dict[str, str | None]  # path -> new text; None means the file would be deleted


# --- audit trail -----------------------------------------------------------------------


class ChangeRecord(_Model):
    """One file change, linked to who/what caused it. This is the audit trail entry."""

    patch_id: str
    project_id: str
    run_id: str
    task_id: str
    path: str
    change_type: ChangeType
    previous_checksum: str | None
    new_checksum: str | None
    description: str
    applied_at: datetime
    origin: Literal["ai"] = "ai"


class ApplyResult(_Model):
    patch_id: str
    records: list[ChangeRecord]
    diff: str
    diff_reference: str


class RollbackResult(_Model):
    patch_id: str
    restored_paths: list[str]


class RecoveryReport(_Model):
    recovered: list[str] = Field(default_factory=list)
    needs_attention: dict[str, list[Problem]] = Field(default_factory=dict)


class FileSnapshot(_Model):
    path: str
    content: str
    checksum: str  # always the checksum of the real file, even when content is masked


# --- journal ---------------------------------------------------------------------------


class JournalEntry(PlannedChange):
    preimage: str | None = None  # relative path inside the patch's journal dir


class JournalManifest(_Model):
    patch_id: str
    project_id: str
    run_id: str
    task_id: str
    description: str
    status: PatchStatus
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    entries: list[JournalEntry]
    created_dirs: list[str] = Field(default_factory=list)
