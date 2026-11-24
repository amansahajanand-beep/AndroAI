"""Request, limits and report of a project import (internal models, not a service contract)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from androai_codegen.editing.errors import PathValidationError
from androai_codegen.editing.paths import normalize_relative_path

MiB = 1024 * 1024
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
REPORT_VERSION = 1
TOOL = "androai-codegen-ingest/1"

# Reports stay bounded however hostile the input: counts are exact, lists are capped.
MAX_LISTED_SKIPPED = 200
MAX_LISTED_FINDINGS = 1000
MAX_LISTED_PATHS = 100


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _clean_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("must not contain control characters")
    return value


# --- limits ----------------------------------------------------------------------------------


class IngestLimits(_Model):
    """What an import may contain. All values are configurable; the defaults are the approved ones.

    Sizes are bytes (``MiB`` = 1,048,576). A directory's depth is the number of path segments of an
    entry (a file in the project root has depth 1). Limits are enforced on the bytes actually
    read and the entries actually walked, never by trusting an archive's own metadata; metadata is
    only used to refuse early.
    """

    max_files: int = Field(default=20_000, ge=1)
    max_total_bytes: int = Field(default=500 * MiB, ge=1)
    max_file_bytes: int = Field(default=50 * MiB, ge=1)
    max_depth: int = Field(default=64, ge=1)
    max_compression_ratio: int = Field(default=100, ge=1)
    # The ratio is only judged above this size: small text legitimately compresses very well.
    ratio_floor_bytes: int = Field(default=1 * MiB, ge=0)
    max_path_length: int = Field(default=240, ge=1)
    max_seconds: float = Field(default=600.0, gt=0)
    secret_scan_max_bytes: int = Field(default=2 * MiB, ge=1)

    @model_validator(mode="after")
    def _file_fits_total(self) -> IngestLimits:
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("max_file_bytes must not exceed max_total_bytes")
        return self


class SymlinkPolicy(StrEnum):
    # An unsafe link (absolute, or leading outside the project) refuses the import; a safe link
    # inside the project is skipped with a warning. Links are never created in the workspace.
    REJECT_UNSAFE = "reject_unsafe"
    REJECT_ALL = "reject_all"


# --- the request -----------------------------------------------------------------------------


class LocalDirectorySource(_Model):
    kind: Literal["local_directory"] = "local_directory"
    path: Path


class ZipSource(_Model):
    kind: Literal["zip"] = "zip"
    path: Path


Source = Annotated[LocalDirectorySource | ZipSource, Field(discriminator="kind")]


class OwnershipAttestation(_Model):
    """The caller's confirmation that the code may be imported and modified.

    Only applications the user owns, or has explicit permission to modify, may be imported. An
    import without this confirmation is not possible: there is no "unconfirmed" import.
    """

    basis: Literal["own", "explicit_permission"]
    statement: str = Field(min_length=1, max_length=500)
    attested_by: str = Field(min_length=1, max_length=128)

    @field_validator("statement", "attested_by")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean_text(value)


class ImportRequest(_Model):
    source: Source
    data_root: Path
    tenant_id: str = Field(pattern=IDENTIFIER_PATTERN)
    project_id: str = Field(pattern=IDENTIFIER_PATTERN)
    attestation: OwnershipAttestation
    limits: IngestLimits = Field(default_factory=IngestLimits)
    symlinks: SymlinkPolicy = SymlinkPolicy.REJECT_UNSAFE
    # GitHub's "Download ZIP" wraps everything in one folder; the project root is inside it.
    strip_single_root: bool = True
    require_android_project: bool = True
    # Use the Android Gradle project found in a subfolder (``mobile/``, ``android-app/``) as the
    # project root when the top level is not one. Only a native Android project is re-rooted.
    locate_android_subdir: bool = True
    # Re-read the source after copying and compare it with what was copied.
    verify_source: bool = True
    label: str | None = Field(default=None, max_length=120)
    import_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("tenant_id", "project_id")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        try:
            ok = normalize_relative_path(value) == value
        except PathValidationError:
            ok = False
        if not ok:
            raise ValueError("must not be a reserved or unsafe name")
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return None if value is None else _clean_text(value)


# --- the report ------------------------------------------------------------------------------


class SourceInfo(_Model):
    kind: Literal["local_directory", "zip"]
    label: str  # a name for people; never the full local path
    fingerprint: str  # sha256: of the archive file (zip) or of the imported tree (directory)
    fingerprint_of: Literal["archive", "tree"]


class ImportCounts(_Model):
    files: int
    directories: int
    bytes: int
    skipped_entries: int
    symlinks_skipped: int
    nested_archives: int


class SkippedItem(_Model):
    path: str
    reason: Literal["excluded_directory", "excluded_file", "symlink"]


class AndroidCheck(_Model):
    detected: bool
    manifests: int
    gradle_files_at_root: list[str]


class SecretFinding(_Model):
    """A likely secret. It names the place and kind, never the value."""

    path: str
    kind: str
    line: int | None = Field(default=None, ge=1)
    length: int | None = Field(default=None, ge=1)


class SecretScan(_Model):
    findings: list[SecretFinding]  # capped at MAX_LISTED_FINDINGS
    total_findings: int
    by_kind: dict[str, int]
    files_scanned: int
    files_not_scanned: int  # binary, or larger than the scan limit
    not_scanned_large: list[str]  # capped at MAX_LISTED_PATHS
    # Files added to the project's protection policy: never shown to an LLM, never modified.
    # (Keystores and similar are protected by the default policy and are not listed again here.)
    protected_paths: list[str]


class LicenceClass(StrEnum):
    PERMISSIVE = "permissive"
    WEAK_COPYLEFT = "weak_copyleft"
    STRONG_COPYLEFT = "strong_copyleft"
    UNKNOWN = "unknown"  # a licence file or header that was not recognised
    NONE = "none"  # no licence file and no SPDX header


class LicenceFile(_Model):
    path: str
    spdx: str | None
    classification: LicenceClass


class LicenceInfo(_Model):
    """Recorded, never decisive: detection is a heuristic and this is not legal advice."""

    files: list[LicenceFile]
    spdx_ids: list[str]
    classification: LicenceClass  # the most restrictive found
    source_headers: int  # files with an SPDX-License-Identifier header
    notes: list[str]


class IngestReport(_Model):
    report_version: int = REPORT_VERSION
    tool: str = TOOL
    import_id: str
    tenant_id: str
    project_id: str
    created_at: datetime
    source: SourceInfo
    attestation: OwnershipAttestation
    # True only because a valid attestation is recorded. Later stages must check this before
    # treating the imported code as eligible for modification.
    eligible_for_modification: bool
    limits: IngestLimits
    counts: ImportCounts
    android: AndroidCheck
    stripped_root: str | None = None
    project_subdir: str | None = None
    skipped: list[SkippedItem]  # capped at MAX_LISTED_SKIPPED
    symlinks_skipped: list[str]  # capped at MAX_LISTED_PATHS
    nested_archives: list[str]  # kept as inert files, never opened; capped at MAX_LISTED_PATHS
    secrets: SecretScan
    licence: LicenceInfo
    content_fingerprint: str  # sha256 over the imported files' paths, sizes and hashes
    warnings: list[str]
