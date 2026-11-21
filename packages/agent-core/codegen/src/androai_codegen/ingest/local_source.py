"""Importing a local directory: plan it, copy it, and prove the original was not touched.

The directory is only ever read. Nothing is created, changed or followed inside it; the workspace
is a copy made in a fresh staging area.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO

from .budget import CHUNK
from .copying import FileRecord
from .errors import IngestCode, IngestRejected, shown
from .models import IngestLimits, SymlinkPolicy
from .names import (
    NameRegistry,
    excluded_reason,
    finalize_name,
    is_nested_archive,
    link_target_is_unsafe,
    split_name,
)
from .plan import Plan, PlannedEntry

# Windows: reparse tags of a symbolic link and of a junction (mount point).
_REPARSE_LINK_TAGS = (0xA000000C, 0xA0000003)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_link(entry: os.DirEntry[str]) -> bool:
    """A symbolic link, or on Windows a junction. Anything unclear counts as a link."""
    if entry.is_symlink():
        return True
    if os.name == "nt":
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT) and (
            getattr(info, "st_reparse_tag", 0) in _REPARSE_LINK_TAGS
        )
    return False


def _gradle_file_in(directory: Path) -> bool:
    return (directory / "build.gradle").is_file() or (directory / "build.gradle.kts").is_file()


def plan_directory(source: Path, limits: IngestLimits, policy: SymlinkPolicy) -> Plan:
    """Walk ``source`` (never following links) and decide what will be copied, or refuse."""
    plan = Plan()
    registry = NameRegistry()
    stack: list[tuple[Path, tuple[str, ...]]] = [(source, ())]

    def build_is_output(prefix: Sequence[str]) -> bool:
        return not prefix or _gradle_file_in(source.joinpath(*prefix))

    while stack:
        directory, prefix = stack.pop()
        try:
            with os.scandir(directory) as listing:
                children = sorted(listing, key=lambda item: item.name)
        except OSError as exc:
            raise IngestRejected(
                IngestCode.IO_ERROR,
                f"cannot read a directory: {exc.strerror or exc}",
                shown(directory.name),
            ) from exc
        for child in children:
            parts = [*prefix, child.name]
            display = "/".join(parts)
            split_name(display)  # control characters, backslashes, '..'
            if is_link(child):
                _handle_link(child, display, plan, policy)
                continue
            try:
                # A fresh lstat, not the listing's cached one: on NTFS the cached times of a
                # directory (and sometimes of a just-written file) lag behind the real ones.
                info = os.lstat(child.path)
            except OSError as exc:
                raise IngestRejected(IngestCode.IO_ERROR, str(exc), shown(display)) from exc
            mode = info.st_mode
            if stat.S_ISDIR(mode):
                if excluded_reason(parts, is_dir=True, build_is_output=build_is_output):
                    plan.skip(display, "excluded_directory")
                    continue
                rel = finalize_name(parts, limits)
                registry.add_directory(rel)
                plan.directories += 1
                if plan.directories > limits.max_files:
                    raise IngestRejected(
                        IngestCode.TOO_MANY_FILES,
                        f"more than {limits.max_files} directories",
                        shown(rel),
                    )
                # A directory's own time changes with its children; only its existence is compared.
                plan.entries.append(PlannedEntry(rel, "dir"))
                stack.append((Path(child.path), tuple(parts)))
            elif stat.S_ISREG(mode):
                if excluded_reason(parts, is_dir=False, build_is_output=build_is_output):
                    plan.skip(display, "excluded_file")
                    continue
                rel = finalize_name(parts, limits)
                if info.st_size > limits.max_file_bytes:
                    raise IngestRejected(
                        IngestCode.FILE_TOO_LARGE,
                        f"a file is larger than {limits.max_file_bytes} bytes",
                        shown(rel),
                    )
                plan.files += 1
                if plan.files > limits.max_files:
                    raise IngestRejected(
                        IngestCode.TOO_MANY_FILES, f"more than {limits.max_files} files", shown(rel)
                    )
                plan.declared_bytes += info.st_size
                if plan.declared_bytes > limits.max_total_bytes:
                    raise IngestRejected(
                        IngestCode.TOTAL_SIZE_EXCEEDED,
                        f"the project is larger than {limits.max_total_bytes} bytes",
                        shown(rel),
                    )
                registry.add_file(rel)
                if is_nested_archive(rel):
                    plan.note_nested_archive(rel)
                plan.entries.append(
                    PlannedEntry(
                        rel,
                        "file",
                        size=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                        source=Path(child.path),
                    )
                )
            else:
                raise IngestRejected(
                    IngestCode.SPECIAL_FILE,
                    "devices, pipes and sockets cannot be imported",
                    shown(display),
                )
    if plan.symlinks_skipped_total:
        plan.warnings.append(
            f"{plan.symlinks_skipped_total} link(s) inside the project were not imported "
            "(links are never created in the workspace)"
        )
    if plan.nested_archives_total:
        plan.warnings.append(
            f"{plan.nested_archives_total} nested archive file(s) were kept as ordinary files "
            "and were not opened"
        )
    return plan


def _handle_link(child: os.DirEntry[str], display: str, plan: Plan, policy: SymlinkPolicy) -> None:
    if policy is SymlinkPolicy.REJECT_ALL:
        raise IngestRejected(
            IngestCode.SYMLINK_NOT_ALLOWED,
            "links are not allowed by the import policy",
            shown(display),
        )
    try:
        target = os.readlink(child.path)
    except OSError as exc:
        raise IngestRejected(
            IngestCode.UNSAFE_SYMLINK, "the link's target cannot be read", shown(display)
        ) from exc
    if link_target_is_unsafe(display, target):
        raise IngestRejected(
            IngestCode.UNSAFE_SYMLINK,
            f"a link leads outside the project: {shown(target)}",
            shown(display),
        )
    plan.skip_symlink(display)


def open_regular(path: str | os.PathLike[str]) -> BinaryIO:
    """Open a file for reading, refusing a link swapped in after planning (where the OS can)."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IngestRejected(
            IngestCode.IO_ERROR, f"cannot open a file: {exc.strerror or exc}", shown(path)
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise IngestRejected(IngestCode.SPECIAL_FILE, "not a regular file", shown(path))
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def open_entry(entry: PlannedEntry) -> AbstractContextManager[BinaryIO]:
    return open_regular(entry.source)  # type: ignore[arg-type, return-value]


def snapshot(plan: Plan) -> dict[str, tuple[str, int, int | None]]:
    """What the source looked like when it was walked: kind, size and modification time."""
    return {entry.rel: (entry.kind, entry.size, entry.mtime_ns) for entry in plan.entries}


def verify_source_unchanged(
    before: Plan, after: Plan, records: Mapping[str, FileRecord], *, rehash: bool
) -> None:
    """Refuse if the source changed while it was being imported.

    The source is walked again and compared (names, kinds, sizes, times); with ``rehash`` every
    file is also read again and compared with the bytes that were copied.
    """
    if snapshot(before) != snapshot(after):
        raise IngestRejected(
            IngestCode.SOURCE_CHANGED, "the source directory changed while it was being imported"
        )
    if not rehash:
        return
    for entry in after.entries:
        if entry.kind != "file":
            continue
        digest = hashlib.sha256()
        with open_regular(entry.source) as handle:  # type: ignore[arg-type]
            while block := handle.read(CHUNK):
                digest.update(block)
        if digest.hexdigest() != records[entry.rel].sha256:
            raise IngestRejected(
                IngestCode.SOURCE_CHANGED,
                "a source file changed while it was being imported",
                shown(entry.rel),
            )
