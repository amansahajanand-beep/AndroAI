"""A project workspace: one local directory the engine is allowed to touch."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from .checksum import sha256_hex
from .errors import NotTextFileError, PathValidationError
from .fsio import atomic_write_bytes
from .paths import normalize_relative_path

PathKind = Literal["missing", "file", "dir", "other"]

_SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".gradle",
        ".idea",
        "build",
        "node_modules",
        ".cxx",
        ".externalNativeBuild",
        ".claude",
        ".cursor",
        ".windsurf",
    }
)


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (is_junction is not None and is_junction())


class Workspace:
    """All file access for a project goes through here; every path is validated first.

    Assumes a single writer at a time (``PatchEngine`` enforces this with a lock). Between
    validation and use there is an unavoidable TOCTOU window if something else races the
    filesystem; see the known limitations in docs/CODE_GENERATION_PROGRESS.md.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        path = Path(root)
        if not path.is_dir():
            raise ValueError(f"workspace root is not a directory: {root}")
        self.root = path.resolve()

    def resolve(self, rel_path: str) -> Path:
        """Validate ``rel_path`` and return its absolute path inside the workspace.

        Rejects traversal, symlinks/junctions along the path, and anything that resolves
        outside the root.
        """
        normalized = normalize_relative_path(rel_path)
        candidate = self.root.joinpath(*normalized.split("/"))
        if not candidate.resolve(strict=False).is_relative_to(self.root):
            raise PathValidationError(f"path escapes the workspace: {rel_path!r}")
        current = self.root
        for part in normalized.split("/"):
            current = current / part
            if not os.path.lexists(current):
                break  # nothing deeper exists yet, so nothing deeper can be a link
            is_junction = getattr(current, "is_junction", None)
            if current.is_symlink() or (is_junction is not None and is_junction()):
                raise PathValidationError(f"symlinks are not allowed: {rel_path!r}")
        return candidate

    def kind(self, rel_path: str) -> PathKind:
        path = self.resolve(rel_path)
        if path.is_file():
            return "file"
        if path.is_dir():
            return "dir"
        return "other" if os.path.lexists(path) else "missing"

    def read_bytes(self, rel_path: str) -> bytes:
        return self.resolve(rel_path).read_bytes()

    def read_text(self, rel_path: str) -> str:
        data = self.read_bytes(rel_path)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotTextFileError(f"{rel_path} is not valid UTF-8 text") from exc

    def checksum(self, rel_path: str) -> str | None:
        """SHA-256 of the file, or ``None`` if it does not exist."""
        if self.kind(rel_path) != "file":
            return None
        return sha256_hex(self.read_bytes(rel_path))

    def snapshot(self, rel_paths: list[str]) -> dict[str, str | None]:
        """Checksums keyed by normalized path. Capture this when a task starts."""
        return {normalize_relative_path(p): self.checksum(p) for p in rel_paths}

    def write_bytes(self, rel_path: str, data: bytes) -> None:
        atomic_write_bytes(self.resolve(rel_path), data)

    def delete(self, rel_path: str) -> None:
        self.resolve(rel_path).unlink()

    def iter_files(self) -> Iterator[str]:
        """Relative paths of regular files in sorted order, skipping VCS/build directories.

        Symlinks and junctions are never followed or listed, so a link cannot make the walk
        escape the workspace. Paths this engine would refuse to touch are not listed either.
        """
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = [
                d for d in dirnames if d not in _SKIPPED_DIRS and not _is_link(current / d)
            ]
            for name in filenames:
                full = current / name
                if _is_link(full):
                    continue
                rel = full.relative_to(self.root).as_posix()
                try:
                    normalize_relative_path(rel)
                except PathValidationError:
                    continue
                found.append(rel)
        yield from sorted(found)

    def missing_dirs(self, rel_path: str) -> list[str]:
        """Parent directories of ``rel_path`` that do not exist yet, outermost first."""
        parts = normalize_relative_path(rel_path).split("/")[:-1]
        missing: list[str] = []
        current = self.root
        for index, part in enumerate(parts):
            current = current / part
            if not current.exists():
                missing.append("/".join(parts[: index + 1]))
        return missing

    def remove_empty_dirs(self, rel_dirs: list[str]) -> None:
        """Remove the given directories (innermost first) if they are empty."""
        for rel_dir in reversed(rel_dirs):
            with contextlib.suppress(OSError, PathValidationError):
                self.resolve(rel_dir).rmdir()
