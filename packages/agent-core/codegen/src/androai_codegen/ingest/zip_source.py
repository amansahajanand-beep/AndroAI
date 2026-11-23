"""Importing a ZIP archive: plan it from the entry list, then stream it into the workspace.

An archive is hostile input. Nothing is written until every entry name has been checked; limits are
then enforced on the bytes actually decompressed (see ``ImportBudget``), not on what the archive
claims. Links are never created, nested archives are never opened, and the archive file is hashed
before and after to prove it was not changed.
"""

from __future__ import annotations

import lzma
import stat
import zipfile
import zlib
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Literal

from .errors import IngestCode, IngestRejected, shown
from .models import IngestLimits, SymlinkPolicy
from .names import (
    EXCLUDED_FILE_NAMES,
    NameRegistry,
    excluded_reason,
    finalize_name,
    is_nested_archive,
    link_target_is_unsafe,
    split_name,
)
from .plan import Plan, PlannedEntry

# What a damaged or unsupported archive raises while it is being read.
ARCHIVE_ERRORS: tuple[type[BaseException], ...] = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    lzma.LZMAError,
    NotImplementedError,
    RuntimeError,  # an encrypted entry
)

_SUPPORTED_COMPRESSION = {
    zipfile.ZIP_STORED,
    zipfile.ZIP_DEFLATED,
    zipfile.ZIP_BZIP2,
    zipfile.ZIP_LZMA,
}
_EOCD_SIGNATURE = b"PK\x05\x06"
_MAX_LINK_TARGET = 1024

Kind = Literal["file", "dir", "symlink"]


@dataclass(frozen=True)
class _Raw:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]
    kind: Kind


def declared_entry_count(path: Path) -> int | None:
    """The entry count in the end-of-central-directory record, if one is found. Advisory only.

    It lets a hopeless archive be refused before the standard library loads its whole central
    directory. A forged count only bypasses this early refusal; the real count is checked after.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - 65557))
            tail = handle.read()
    except OSError:
        return None
    position = tail.rfind(_EOCD_SIGNATURE)
    if position < 0 or len(tail) < position + 22:
        return None
    return int.from_bytes(tail[position + 10 : position + 12], "little")


def _kind(info: zipfile.ZipInfo) -> Kind:
    mode = (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0
    file_type = stat.S_IFMT(mode)
    if info.is_dir() or file_type == stat.S_IFDIR:
        return "dir"
    if file_type == stat.S_IFLNK:
        return "symlink"
    if file_type not in (0, stat.S_IFREG):
        raise IngestRejected(
            IngestCode.SPECIAL_FILE,
            "devices, pipes and sockets cannot be imported",
            shown(info.orig_filename),
        )
    return "file"


def _read_link_target(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > _MAX_LINK_TARGET:
        return "/" + "x" * 8  # an absurd target: judged unsafe by the caller
    try:
        with archive.open(info) as handle:
            data = handle.read(_MAX_LINK_TARGET + 1)
    except ARCHIVE_ERRORS as exc:
        raise IngestRejected(
            IngestCode.MALFORMED_ARCHIVE, "a link entry cannot be read", shown(info.orig_filename)
        ) from exc
    return data.decode("utf-8", errors="replace")


def plan_zip(
    archive: zipfile.ZipFile,
    limits: IngestLimits,
    policy: SymlinkPolicy,
    *,
    strip_single_root: bool,
) -> Plan:
    """Check every entry and decide what will be extracted, or refuse the whole archive."""
    infos = archive.infolist()
    if len(infos) > 2 * limits.max_files:
        raise IngestRejected(IngestCode.TOO_MANY_FILES, f"the archive lists {len(infos)} entries")
    if not infos:
        raise IngestRejected(IngestCode.MALFORMED_ARCHIVE, "the archive is empty")

    plan = Plan()
    raws: list[_Raw] = []
    declared = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise IngestRejected(
                IngestCode.ENCRYPTED_ENTRY,
                "encrypted entries are not supported",
                shown(info.orig_filename),
            )
        if info.compress_type not in _SUPPORTED_COMPRESSION:
            raise IngestRejected(
                IngestCode.MALFORMED_ARCHIVE,
                f"unsupported compression method {info.compress_type}",
                shown(info.orig_filename),
            )
        kind = _kind(info)
        # ``orig_filename`` is the name as stored (before the library rewrites separators).
        parts = tuple(split_name(info.orig_filename, is_dir=kind == "dir"))
        if kind == "file":
            # Early refusal on the archive's claims; the real limits are enforced while extracting.
            if info.file_size > limits.max_file_bytes:
                raise IngestRejected(
                    IngestCode.FILE_TOO_LARGE,
                    f"an entry claims more than {limits.max_file_bytes} bytes",
                    shown(info.orig_filename),
                )
            declared += info.file_size
            if declared > limits.max_total_bytes:
                raise IngestRejected(
                    IngestCode.TOTAL_SIZE_EXCEEDED,
                    f"the entries claim more than {limits.max_total_bytes} bytes",
                )
        raws.append(_Raw(info, parts, kind))

    # Entries that are never imported (VCS data, IDE files, macOS junk).
    live: list[_Raw] = []
    for raw in raws:
        reason = excluded_reason(
            raw.parts, is_dir=raw.kind == "dir", build_is_output=lambda _prefix: False
        )
        if reason is None:
            live.append(raw)
        else:
            plan.skip("/".join(raw.parts), _skip_reason(reason))

    # GitHub-style archives hold everything inside one folder; the project root is inside it.
    if strip_single_root and live:
        tops = {raw.parts[0] for raw in live}
        root_file = any(len(raw.parts) == 1 and raw.kind != "dir" for raw in live)
        if len(tops) == 1 and not root_file:
            plan.stripped_root = next(iter(tops))
            live = [replace(raw, parts=raw.parts[1:]) for raw in live if len(raw.parts) > 1]

    # A ``build`` directory is only an output directory beside a Gradle build file.
    names = {"/".join(raw.parts) for raw in live if raw.kind != "dir"}

    def build_is_output(prefix: Sequence[str]) -> bool:
        base = "/".join(prefix)
        return not prefix or f"{base}/build.gradle" in names or f"{base}/build.gradle.kts" in names

    kept: list[_Raw] = []
    for raw in live:
        reason = excluded_reason(
            raw.parts, is_dir=raw.kind == "dir", build_is_output=build_is_output
        )
        if reason is None:
            kept.append(raw)
        else:
            plan.skip("/".join(raw.parts), _skip_reason(reason))

    registry = NameRegistry()
    for raw in kept:
        rel = finalize_name(raw.parts, limits)
        if raw.kind == "dir":
            registry.add_directory(rel)
            plan.directories += 1
            if plan.directories > limits.max_files:
                raise IngestRejected(
                    IngestCode.TOO_MANY_FILES,
                    f"more than {limits.max_files} directories",
                    shown(rel),
                )
            plan.entries.append(PlannedEntry(rel, "dir"))
        elif raw.kind == "symlink":
            _plan_symlink(archive, raw, rel, plan, policy)
        else:
            registry.add_file(rel)
            plan.files += 1
            if plan.files > limits.max_files:
                raise IngestRejected(
                    IngestCode.TOO_MANY_FILES, f"more than {limits.max_files} files", shown(rel)
                )
            plan.declared_bytes += raw.info.file_size
            if is_nested_archive(rel):
                plan.note_nested_archive(rel)
            plan.entries.append(
                PlannedEntry(
                    rel,
                    "file",
                    size=raw.info.file_size,
                    compressed=raw.info.compress_size,
                    source=raw.info,
                )
            )

    if plan.symlinks_skipped_total:
        plan.warnings.append(
            f"{plan.symlinks_skipped_total} link entr(ies) inside the project were not imported "
            "(links are never created in the workspace)"
        )
    if plan.nested_archives_total:
        plan.warnings.append(
            f"{plan.nested_archives_total} nested archive file(s) were kept as ordinary files "
            "and were not opened"
        )
    return plan


def _skip_reason(reason: str) -> Literal["excluded_directory", "excluded_file"]:
    return "excluded_file" if reason in EXCLUDED_FILE_NAMES else "excluded_directory"


def _plan_symlink(
    archive: zipfile.ZipFile, raw: _Raw, rel: str, plan: Plan, policy: SymlinkPolicy
) -> None:
    if policy is SymlinkPolicy.REJECT_ALL:
        raise IngestRejected(
            IngestCode.SYMLINK_NOT_ALLOWED, "links are not allowed by the import policy", shown(rel)
        )
    target = _read_link_target(archive, raw.info)
    if link_target_is_unsafe(rel, target):
        raise IngestRejected(
            IngestCode.UNSAFE_SYMLINK,
            f"a link leads outside the project: {shown(target)}",
            shown(rel),
        )
    plan.skip_symlink(rel)


def open_entry(archive: zipfile.ZipFile):
    """An opener for ``materialize``: the decompressing stream of one entry."""

    def opener(entry: PlannedEntry) -> AbstractContextManager[BinaryIO]:
        return archive.open(entry.source)  # type: ignore[arg-type, return-value]

    return opener
