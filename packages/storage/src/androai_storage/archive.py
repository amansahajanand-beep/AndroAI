"""Secure ZIP / APK handling for untrusted uploads.

Nothing is ever written to the host filesystem by this module: entries are validated
and streamed to the caller as (normalised path, bytes), so path traversal / symlink
escape cannot touch the disk, and the caller decides where bytes go (object storage).

Defences:
  * path traversal (`..`, absolute, drive letters, backslashes, NUL / control chars)
  * symlinks and any non-regular entry (devices, fifos) are rejected
  * encrypted entries rejected
  * zip bombs: entry count, per-file size, total size and compression ratio limits,
    enforced on the bytes actually decompressed (headers are attacker-controlled)
  * duplicate / case-colliding paths and file-vs-directory conflicts
  * single-file size and path depth/length limits
File modes are discarded (nothing is executable until a build worker decides so).
"""

from __future__ import annotations

import io
import stat
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO

MB = 1024 * 1024


class ArchiveError(ValueError):
    """The archive is malformed, unsafe, or exceeds limits. Message is safe to show users."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 200 * MB
    max_total_bytes: int = 1024 * MB  # total uncompressed
    max_file_bytes: int = 50 * MB
    max_files: int = 20_000
    max_ratio: int = 100  # uncompressed / compressed, applied to entries above min_ratio_bytes
    min_ratio_bytes: int = 1 * MB
    max_depth: int = 40
    max_path_len: int = 1024
    max_component_len: int = 255


_SKIP_PREFIXES = ("__MACOSX/", ".git/")
_SKIP_NAMES = {".DS_Store", "Thumbs.db"}
_CHUNK = 64 * 1024


def normalize_member_path(name: str, limits: ArchiveLimits = ArchiveLimits()) -> str:
    """Return a safe relative POSIX path or raise ArchiveError."""
    if not name or "\x00" in name or any(ord(c) < 32 for c in name):
        raise ArchiveError("invalid entry name")
    if "\\" in name:
        raise ArchiveError(f"backslash in entry name: {name[:80]!r}")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ArchiveError(f"absolute path in archive: {name[:80]!r}")
    parts = name.split("/")
    out: list[str] = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            raise ArchiveError(f"path traversal in archive: {name[:80]!r}")
        if len(p) > limits.max_component_len:
            raise ArchiveError("path component too long")
        out.append(p)
    if not out:
        raise ArchiveError("empty entry name")
    if len(out) > limits.max_depth:
        raise ArchiveError("path too deep")
    path = "/".join(out)
    if len(path) > limits.max_path_len:
        raise ArchiveError("path too long")
    return path


def _open_zip(fileobj: BinaryIO, limits: ArchiveLimits) -> zipfile.ZipFile:
    fileobj.seek(0, io.SEEK_END)
    size = fileobj.tell()
    fileobj.seek(0)
    if size > limits.max_archive_bytes:
        raise ArchiveError("archive too large")
    try:
        return zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, NotImplementedError, EOFError) as e:
        raise ArchiveError("not a valid ZIP archive") from e


def _check_info(info: zipfile.ZipInfo, limits: ArchiveLimits) -> None:
    if info.flag_bits & 0x1:
        raise ArchiveError(f"encrypted entry not allowed: {info.filename[:80]!r}")
    mode = info.external_attr >> 16
    if mode:
        fmt = stat.S_IFMT(mode)
        if fmt not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ArchiveError(f"symlink or special file not allowed: {info.filename[:80]!r}")
    if info.file_size > limits.max_file_bytes:
        raise ArchiveError(f"file too large: {info.filename[:80]!r}")
    if (
        info.file_size > limits.min_ratio_bytes
        and info.compress_size > 0
        and info.file_size / info.compress_size > limits.max_ratio
    ):
        raise ArchiveError("suspicious compression ratio")


def _read_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: ArchiveLimits, budget: list[int]) -> bytes:
    """Decompress one entry, enforcing limits on actual output."""
    buf = bytearray()
    try:
        with zf.open(info) as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                buf += chunk
                budget[0] -= len(chunk)
                if len(buf) > limits.max_file_bytes:
                    raise ArchiveError(f"file too large: {info.filename[:80]!r}")
                if budget[0] < 0:
                    raise ArchiveError("archive expands beyond allowed total size")
                if (
                    len(buf) > limits.min_ratio_bytes
                    and info.compress_size > 0
                    and len(buf) / info.compress_size > limits.max_ratio * 2
                ):
                    raise ArchiveError("suspicious compression ratio")
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError) as e:
        raise ArchiveError(f"corrupt or unsupported entry: {info.filename[:80]!r}") from e
    return bytes(buf)


def iter_zip_files(
    fileobj: BinaryIO,
    limits: ArchiveLimits = ArchiveLimits(),
    *,
    strip_common_root: bool = True,
) -> Iterator[tuple[str, bytes]]:
    """Validate the whole archive up-front, then yield (safe_path, content) for regular files.

    All structural checks happen before the first yield, so a hostile archive is rejected
    without producing partial output; size checks on actual bytes may still fail mid-stream,
    so callers must treat any ArchiveError as "discard everything written so far".
    """
    zf = _open_zip(fileobj, limits)
    infos = zf.infolist()
    if len(infos) > limits.max_files:
        raise ArchiveError("too many files in archive")

    selected: list[tuple[str, zipfile.ZipInfo]] = []
    seen_lower: set[str] = set()
    dirs: set[str] = set()
    declared_total = 0
    for info in infos:
        _check_info(info, limits)
        path = normalize_member_path(info.filename, limits)
        if any(path.startswith(p) or f"/{p}" in f"/{path}/" for p in _SKIP_PREFIXES) or path.rsplit("/", 1)[-1] in _SKIP_NAMES:
            continue
        if info.is_dir():
            dirs.add(path.lower())
            continue
        key = path.lower()
        if key in seen_lower:
            raise ArchiveError(f"duplicate or case-colliding path: {path[:80]!r}")
        seen_lower.add(key)
        declared_total += info.file_size
        selected.append((path, info))
    if declared_total > limits.max_total_bytes:
        raise ArchiveError("archive expands beyond allowed total size")
    if not selected:
        raise ArchiveError("archive contains no files")

    # file-vs-directory conflicts ("a" is a file and "a/b" exists)
    for path, _ in selected:
        parts = path.lower().split("/")
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in seen_lower:
                raise ArchiveError(f"file/directory conflict at {path[:80]!r}")

    prefix = ""
    if strip_common_root:
        tops = {p.split("/", 1)[0] for p, _ in selected}
        if len(tops) == 1 and all("/" in p for p, _ in selected):
            prefix = tops.pop() + "/"

    budget = [limits.max_total_bytes]
    for path, info in selected:
        data = _read_bounded(zf, info, limits, budget)
        yield (path[len(prefix):] if prefix else path), data


@dataclass(frozen=True)
class ApkInfo:
    entry_count: int
    dex_files: int
    has_manifest: bool


def validate_apk(fileobj: BinaryIO, limits: ArchiveLimits = ArchiveLimits()) -> ApkInfo:
    """Structural validation of an uploaded APK without extracting it. An APK is never
    executed or unpacked on the control plane."""
    zf = _open_zip(fileobj, limits)
    infos = zf.infolist()
    if len(infos) > limits.max_files:
        raise ArchiveError("too many entries in APK")
    declared = 0
    names: set[str] = set()
    for info in infos:
        normalize_member_path(info.filename, limits)
        if info.flag_bits & 0x1:
            raise ArchiveError("encrypted APK entries not allowed")
        if info.file_size > limits.max_file_bytes * 4:
            raise ArchiveError("APK entry too large")
        declared += info.file_size
        names.add(info.filename)
    if declared > limits.max_total_bytes:
        raise ArchiveError("APK expands beyond allowed total size")
    has_manifest = "AndroidManifest.xml" in names
    dex = sum(1 for n in names if n.startswith("classes") and n.endswith(".dex"))
    if not has_manifest:
        raise ArchiveError("not an Android APK (AndroidManifest.xml missing)")
    return ApkInfo(entry_count=len(infos), dex_files=dex, has_manifest=has_manifest)


def build_zip(entries: Iterable[tuple[str, bytes | Callable[[], bytes]]]) -> tempfile.SpooledTemporaryFile:
    """Deterministic ZIP (fixed timestamps, sorted, no modes) in a spooled temp file, rewound.

    Entry content may be bytes or a zero-argument callable returning bytes, so large
    projects can be streamed from object storage one file at a time."""
    out = tempfile.SpooledTemporaryFile(max_size=64 * MB)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, data in sorted(entries, key=lambda e: e[0]):
            zi = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, data() if callable(data) else data)
    out.seek(0)
    return out
