"""Why an import was refused.

A refusal is a normal, structured outcome: the importer leaves nothing behind and says which rule
was broken. Archive entry names and link targets come from untrusted input, so everything that
reaches a message goes through :func:`shown` (escaped, short).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from androai_codegen.editing.errors import CodegenError

_MAX_SHOWN = 120


def shown(value: object, limit: int = _MAX_SHOWN) -> str:
    """A short, printable, escaped form of untrusted text (an entry name, a link target)."""
    text = ascii(str(value))
    return text if len(text) <= limit else text[: limit - 3] + "..."


class IngestCode(StrEnum):
    # the request
    DATA_ROOT_MISSING = "data_root_missing"
    PROJECT_EXISTS = "project_exists"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_NOT_DIRECTORY = "source_not_directory"
    SOURCE_NOT_FILE = "source_not_file"
    SOURCE_IS_LINK = "source_is_link"
    SOURCE_OVERLAPS_DATA_ROOT = "source_overlaps_data_root"
    ATTESTATION_REQUIRED = "attestation_required"
    # the archive
    NOT_A_ZIP = "not_a_zip"
    MALFORMED_ARCHIVE = "malformed_archive"
    ENCRYPTED_ENTRY = "encrypted_entry"
    # names and layout
    ABSOLUTE_PATH = "absolute_path"
    PATH_TRAVERSAL = "path_traversal"
    INVALID_PATH = "invalid_path"
    PATH_TOO_LONG = "path_too_long"
    TOO_DEEP = "too_deep"
    NAME_COLLISION = "name_collision"
    PATH_CONFLICT = "path_conflict"
    # links and special files
    UNSAFE_SYMLINK = "unsafe_symlink"
    SYMLINK_NOT_ALLOWED = "symlink_not_allowed"
    SPECIAL_FILE = "special_file"
    # limits
    TOO_MANY_FILES = "too_many_files"
    FILE_TOO_LARGE = "file_too_large"
    TOTAL_SIZE_EXCEEDED = "total_size_exceeded"
    COMPRESSION_RATIO_EXCEEDED = "compression_ratio_exceeded"
    TIMEOUT = "timeout"
    # integrity and content
    SOURCE_CHANGED = "source_changed_during_import"
    NOT_AN_ANDROID_PROJECT = "not_an_android_project"
    UNSUPPORTED_FRAMEWORK = "unsupported_framework"
    IO_ERROR = "io_error"


class IngestProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: IngestCode
    message: str
    path: str | None = None


class IngestRejected(CodegenError):
    """The import was refused and nothing was left behind."""

    def __init__(self, code: IngestCode, message: str, path: str | None = None) -> None:
        self.problem = IngestProblem(code=code, message=message, path=path)
        super().__init__(f"{code.value}: {message}" + (f" [{path}]" if path else ""))

    @property
    def code(self) -> IngestCode:
        return self.problem.code
