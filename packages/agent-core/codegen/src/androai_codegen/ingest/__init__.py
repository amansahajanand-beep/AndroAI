"""Importing an existing Android project into an isolated workspace (Phase 6, stage M1a).

Local directories and ZIP archives only. The source is never changed and nothing from it is ever
executed; see ``docs/CODE_GENERATION_PROGRESS.md`` for the rules and their limits.
"""

from .errors import IngestCode, IngestProblem, IngestRejected
from .importer import (
    ImportResult,
    import_local_directory,
    import_project,
    import_zip,
    reopen_import,
)
from .models import (
    ImportRequest,
    IngestLimits,
    IngestReport,
    LicenceClass,
    LocalDirectorySource,
    OwnershipAttestation,
    SecretFinding,
    SymlinkPolicy,
    ZipSource,
)
from .secrets import ImportProtection, protection_for

__all__ = [
    "ImportProtection",
    "ImportRequest",
    "ImportResult",
    "IngestCode",
    "IngestLimits",
    "IngestProblem",
    "IngestRejected",
    "IngestReport",
    "LicenceClass",
    "LocalDirectorySource",
    "OwnershipAttestation",
    "SecretFinding",
    "SymlinkPolicy",
    "ZipSource",
    "import_local_directory",
    "import_project",
    "import_zip",
    "protection_for",
    "reopen_import",
]
