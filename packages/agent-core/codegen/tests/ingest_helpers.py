"""Builders for the import tests: projects on disk, ZIP archives (also hostile ones), digests."""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from collections.abc import Mapping
from pathlib import Path

from androai_codegen.ingest import (
    ImportRequest,
    ImportResult,
    IngestLimits,
    LocalDirectorySource,
    OwnershipAttestation,
    ZipSource,
    import_project,
)
from androai_codegen.templates import ProjectConfig, ProjectSpec, ScreenSpec, render_files

ATTESTATION = OwnershipAttestation(
    basis="own", statement="I wrote this application.", attested_by="user-1"
)

MANIFEST = '<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>\n'


def minimal_project(**extra: str | bytes) -> dict[str, str | bytes]:
    """The smallest tree the importer accepts as an Android project."""
    files: dict[str, str | bytes] = {
        "settings.gradle.kts": 'rootProject.name = "demo"\ninclude(":app")\n',
        "app/src/main/AndroidManifest.xml": MANIFEST,
        "app/src/main/java/com/example/demo/Main.kt": "package com.example.demo\n\nclass Main\n",
    }
    files.update({key.replace("__", "/"): value for key, value in extra.items()})
    return files


def generated_project() -> dict[str, str | bytes]:
    """A real multi-screen project rendered by the generator (21 files)."""
    config = ProjectConfig(project_name="Notes App", package_name="com.example.notes")
    spec = ProjectSpec(
        screens=(
            ScreenSpec(name="Home", title="Home", navigates_to=("Settings", "About")),
            ScreenSpec(name="Settings", title="Settings"),
            ScreenSpec(name="About", title="About"),
        )
    )
    return {item.path: item.content for item in render_files(config, spec)}


def write_tree(root: Path, files: Mapping[str, str | bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        target.write_bytes(data)  # bytes: line endings are exactly what the test wrote
    return root


def tree_digest(root: Path) -> dict[str, tuple]:
    """Everything observable about a tree: names, kinds, modes, sizes, times (files) and hashes.

    Directory modification times are left out: they change with the directory's own children and
    NTFS reports them lazily. Everything else must be identical before and after an import.
    """
    digest: dict[str, tuple] = {}
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                digest[rel] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                digest[rel] = ("dir", stat.S_IMODE(info.st_mode))
            else:
                try:
                    content = path.read_bytes() if stat.S_ISREG(info.st_mode) else b""
                    sha = hashlib.sha256(content).hexdigest()
                except PermissionError:  # an unreadable file (mode 000): its metadata still counts
                    sha = "unreadable"
                digest[rel] = (
                    "file",
                    stat.S_IMODE(info.st_mode),
                    info.st_size,
                    info.st_mtime_ns,
                    sha,
                )
    return digest


def workspace_files(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (path -> bytes); fails if anything is not a plain file or dir."""
    found: dict[str, bytes] = {}
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in [*dirs, *names]:
            assert not (Path(current) / name).is_symlink(), f"link in the workspace: {name}"
        for name in names:
            path = Path(current) / name
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def make_request(source, data_root: Path, **overrides) -> ImportRequest:
    values: dict = {
        "source": source,
        "data_root": data_root,
        "tenant_id": "tenant1",
        "project_id": "proj1",
        "attestation": ATTESTATION,
    }
    values.update(overrides)
    return ImportRequest(**values)


def import_dir(src: Path, data_root: Path, **overrides) -> ImportResult:
    return import_project(make_request(LocalDirectorySource(path=src), data_root, **overrides))


def import_archive(archive: Path, data_root: Path, **overrides) -> ImportResult:
    return import_project(make_request(ZipSource(path=archive), data_root, **overrides))


def small_limits(**overrides) -> IngestLimits:
    return IngestLimits(**overrides)


# --- ZIP builders ------------------------------------------------------------------------------


def entry(
    name: str,
    data: bytes | str = b"",
    *,
    mode: int | None = None,
    compress_type: int = zipfile.ZIP_DEFLATED,
) -> tuple[zipfile.ZipInfo, bytes]:
    """A ZIP entry with exactly this stored name (the library's own cleaning is bypassed).

    ``mode`` is a full Unix mode including the file type, e.g. ``stat.S_IFLNK | 0o777``.
    """
    info = zipfile.ZipInfo("placeholder")
    info.filename = name
    info.orig_filename = name
    info.compress_type = compress_type
    if mode is not None:
        info.create_system = 3
        info.external_attr = (mode & 0xFFFF) << 16
    return info, data.encode("utf-8") if isinstance(data, str) else data


def symlink(name: str, target: str) -> tuple[zipfile.ZipInfo, bytes]:
    return entry(name, target, mode=stat.S_IFLNK | 0o777)


def make_zip(path: Path, entries: list, *, comment: bytes = b"") -> Path:
    """Write a ZIP. Each item is ``(name, data)`` or an ``entry(...)`` pair."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in entries:
            if isinstance(item[0], zipfile.ZipInfo):
                archive.writestr(item[0], item[1])
            else:
                info, data = entry(item[0], item[1])
                archive.writestr(info, data)
        archive.comment = comment
    return path


def project_zip(path: Path, files: Mapping[str, str | bytes], *, root: str | None = None) -> Path:
    prefix = f"{root}/" if root else ""
    return make_zip(path, [(prefix + rel, content) for rel, content in files.items()])


def patch_zip(
    path: Path, *, central_offset: int, value: int, size: int = 2, index: int = 0
) -> None:
    """Overwrite a field of the ``index``-th central-directory header (to build lying archives)."""
    data = bytearray(path.read_bytes())
    start = -1
    for _ in range(index + 1):
        start = data.index(b"PK\x01\x02", start + 1)
    data[start + central_offset : start + central_offset + size] = value.to_bytes(size, "little")
    path.write_bytes(bytes(data))
