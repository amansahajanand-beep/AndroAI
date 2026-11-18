"""Low-level atomic file writing shared by the workspace and the journal."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write ``data`` so that ``target`` is either fully the old or fully the new content.

    The data goes to a temp file in the same directory (same filesystem), is fsynced, then
    moved over the target with ``os.replace``. An existing file keeps its permission bits
    (e.g. ``gradlew`` stays executable).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".androai-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            shutil.copymode(target, tmp_name)
        else:
            os.chmod(tmp_name, 0o644)  # mkstemp creates 0600; match normal checkout permissions
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
