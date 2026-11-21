"""Writing a plan into the isolated workspace, and cleaning up when an import does not finish."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from androai_codegen.editing.errors import PathValidationError
from androai_codegen.editing.workspace import Workspace

from .budget import ImportBudget
from .errors import IngestCode, IngestRejected, shown
from .plan import Plan, PlannedEntry

OpenSource = Callable[[PlannedEntry], AbstractContextManager[BinaryIO]]

# Windows refuses paths of 260 characters or more unless long paths are enabled.
_WINDOWS_PATH_LIMIT = 259


@dataclass(frozen=True)
class FileRecord:
    size: int
    sha256: str


def tree_fingerprint(records: Mapping[str, FileRecord]) -> str:
    """A hash of the imported files' paths, sizes and content hashes (independent of the source)."""
    digest = hashlib.sha256()
    for rel in sorted(records):
        record = records[rel]
        digest.update(f"{rel}\0{record.size}\0{record.sha256}\n".encode())
    return digest.hexdigest()


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def materialize(
    plan: Plan,
    open_source: OpenSource,
    workspace: Workspace,
    budget: ImportBudget,
    *,
    read_errors: tuple[type[BaseException], ...] = (),
) -> dict[str, FileRecord]:
    """Create the planned directories and files in ``workspace``.

    Every path goes through ``Workspace.resolve`` (containment, no links on the way), every file is
    created exclusively (an existing file is never overwritten or followed), and every byte
    through the budget. ``read_errors`` are the errors of the source format that mean "this
    archive is damaged".
    """
    records: dict[str, FileRecord] = {}
    for entry in plan.entries:
        budget.check_time()
        try:
            target = workspace.resolve(entry.rel)
            if os.name == "nt" and len(str(target)) > _WINDOWS_PATH_LIMIT:
                raise IngestRejected(
                    IngestCode.PATH_TOO_LONG,
                    "the path is too long for this file system",
                    shown(entry.rel),
                )
            if entry.kind == "dir":
                budget.count_directory(entry.rel)
                target.mkdir(parents=True, exist_ok=True)
                continue
            budget.count_file(entry.rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open_source(entry) as source, open(target, "xb") as out:
                size, digest = budget.copy(
                    source, out, path=entry.rel, compressed_size=entry.compressed
                )
            records[entry.rel] = FileRecord(size, digest)
        except IngestRejected:
            raise
        except (FileExistsError, NotADirectoryError) as exc:
            raise IngestRejected(
                IngestCode.PATH_CONFLICT, "a file and a directory share a name", shown(entry.rel)
            ) from exc
        except PathValidationError as exc:
            raise IngestRejected(IngestCode.INVALID_PATH, str(exc), shown(entry.rel)) from exc
        except read_errors as exc:
            raise IngestRejected(
                IngestCode.MALFORMED_ARCHIVE,
                f"the archive is damaged or unsupported ({type(exc).__name__})",
                shown(entry.rel),
            ) from exc
        except (OSError, ValueError) as exc:
            raise IngestRejected(
                IngestCode.IO_ERROR, f"{type(exc).__name__}: {exc}", shown(entry.rel)
            ) from exc
    return records


def _retry_writable(func: Callable[[str], object], target: str, _error: object) -> None:
    try:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        func(target)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    """Delete a directory tree, best effort (read-only files included). Used for cleanup."""
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry_writable)
    else:  # pragma: no cover - python 3.11
        shutil.rmtree(path, onerror=_retry_writable)
