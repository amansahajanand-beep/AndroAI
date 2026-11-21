"""The on-disk layout of an imported project, and how it is created without half-finished states.

    <data_root>/<tenant_id>/<project_id>/
        workspace/                     the project (what the patch engine edits)
        journal/                       the patch engine's journal (never inside the workspace)
        imports/<import_id>/report.json

An import is built in ``<data_root>/.staging-<import_id>`` and moved into place with one rename
only after every check has passed, so a refused or interrupted import leaves no project behind.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from .copying import remove_tree
from .errors import IngestCode, IngestRejected, shown
from .models import IngestReport


def check_data_root(path: Path) -> Path:
    """The resolved data root. It must already exist: a mistyped root is never created."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IngestRejected(
            IngestCode.DATA_ROOT_MISSING, "the data root does not exist", shown(path)
        ) from exc
    if not resolved.is_dir():
        raise IngestRejected(
            IngestCode.DATA_ROOT_MISSING, "the data root is not a directory", shown(path)
        )
    return resolved


class Staging:
    def __init__(self, data_root: Path, import_id: str) -> None:
        self.root = data_root / f".staging-{import_id}"
        self.workspace = self.root / "workspace"
        self.journal = self.root / "journal"
        self.import_dir = self.root / "imports" / import_id
        self.import_id = import_id

    def create(self) -> None:
        self.root.mkdir(mode=0o700)  # fails if it already exists: a staging area is never reused
        self.workspace.mkdir()
        self.journal.mkdir()
        self.import_dir.mkdir(parents=True)

    def write_report(self, report: IngestReport) -> None:
        (self.import_dir / "report.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )

    def cleanup(self) -> None:
        remove_tree(self.root)


def project_dir(data_root: Path, tenant_id: str, project_id: str) -> Path:
    final = data_root / tenant_id / project_id
    if not final.resolve(strict=False).is_relative_to(data_root):
        raise IngestRejected(
            IngestCode.INVALID_PATH, "the project directory would leave the data root", shown(final)
        )
    return final


def finalize(staging: Staging, final: Path) -> None:
    """Move the finished staging area into place. Never replaces an existing project."""
    tenant_dir = final.parent
    created_tenant = not tenant_dir.exists()
    try:
        tenant_dir.mkdir(exist_ok=True)
        if final.exists():
            raise IngestRejected(
                IngestCode.PROJECT_EXISTS, "this project already exists", shown(final.name)
            )
        try:
            os.rename(staging.root, final)
        except OSError as exc:
            if final.exists():
                raise IngestRejected(
                    IngestCode.PROJECT_EXISTS, "this project already exists", shown(final.name)
                ) from exc
            raise IngestRejected(IngestCode.IO_ERROR, f"cannot create the project: {exc}") from exc
    except BaseException:
        if created_tenant:
            with contextlib.suppress(OSError):
                tenant_dir.rmdir()
        raise
