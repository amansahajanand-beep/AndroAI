"""Safe multi-file editing: patches, atomic apply, conflict detection, rollback."""

from .engine import PatchEngine
from .errors import (
    CodegenError,
    JournalError,
    NotTextFileError,
    PatchApplyError,
    PatchRejected,
    PatchStateError,
    PathValidationError,
    ProtectedFileError,
    RollbackConflict,
    UnknownPatchError,
    WorkspaceBusyError,
)
from .models import (
    ApplyResult,
    ChangeRecord,
    CreateFile,
    DeleteFile,
    FileSnapshot,
    ModifyFile,
    PatchPreview,
    PatchSet,
    PlannedChange,
    Problem,
    ProblemCode,
    RecoveryReport,
    RollbackResult,
    TextEdit,
)
from .paths import normalize_relative_path
from .policy import DEFAULT_PROTECTED_PATTERNS, ProtectionPolicy
from .redact import REDACTION_MARKER, mask_secrets
from .workspace import Workspace

__all__ = [
    "DEFAULT_PROTECTED_PATTERNS",
    "REDACTION_MARKER",
    "ApplyResult",
    "ChangeRecord",
    "CodegenError",
    "CreateFile",
    "DeleteFile",
    "FileSnapshot",
    "JournalError",
    "ModifyFile",
    "NotTextFileError",
    "PatchApplyError",
    "PatchEngine",
    "PatchPreview",
    "PatchRejected",
    "PatchSet",
    "PatchStateError",
    "PathValidationError",
    "PlannedChange",
    "Problem",
    "ProblemCode",
    "ProtectedFileError",
    "ProtectionPolicy",
    "RecoveryReport",
    "RollbackConflict",
    "RollbackResult",
    "TextEdit",
    "UnknownPatchError",
    "Workspace",
    "WorkspaceBusyError",
    "mask_secrets",
    "normalize_relative_path",
]
