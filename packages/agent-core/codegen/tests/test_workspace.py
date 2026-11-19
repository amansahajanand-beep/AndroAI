import os
import subprocess
from pathlib import Path

import pytest

from androai_codegen.editing import NotTextFileError, PathValidationError, Workspace


def test_root_must_be_a_directory(tmp_path):
    with pytest.raises(ValueError):
        Workspace(tmp_path / "missing")


def test_resolve_stays_inside_root(workspace, ws_root):
    resolved = workspace.resolve("app/src/Main.kt")
    assert resolved.is_relative_to(ws_root)
    assert resolved.name == "Main.kt"


def test_resolve_rejects_traversal(workspace):
    with pytest.raises(PathValidationError):
        workspace.resolve("../outside.txt")


def test_kind_and_checksum(workspace, put, sha):
    digest = put("a/b.txt", "hello")
    assert workspace.kind("a/b.txt") == "file"
    assert workspace.kind("a") == "dir"
    assert workspace.kind("nope.txt") == "missing"
    assert workspace.checksum("a/b.txt") == digest == sha("hello")
    assert workspace.checksum("nope.txt") is None
    assert workspace.checksum("a") is None


def test_snapshot_keys_are_normalized(workspace, put):
    digest = put("a/b.txt", "x")
    assert workspace.snapshot(["a/./b.txt", "missing.txt"]) == {
        "a/b.txt": digest,
        "missing.txt": None,
    }


def test_read_text_rejects_binary(workspace, put):
    put("bin.dat", b"\xff\xfe\x00\x01")
    with pytest.raises(NotTextFileError):
        workspace.read_text("bin.dat")


def test_write_creates_parents_and_leaves_no_temp_files(workspace, ws_root):
    workspace.write_bytes("x/y/z.txt", b"data")
    assert (ws_root / "x/y/z.txt").read_bytes() == b"data"
    leftovers = [p for p in ws_root.rglob("*") if p.name.startswith(".androai-")]
    assert leftovers == []


def test_write_replaces_existing_content(workspace, ws_root, put):
    put("f.txt", "old")
    workspace.write_bytes("f.txt", b"new")
    assert (ws_root / "f.txt").read_bytes() == b"new"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_write_preserves_executable_bit(workspace, ws_root, put):
    put("gradlew", "#!/bin/sh\n")
    (ws_root / "gradlew").chmod(0o755)
    workspace.write_bytes("gradlew", b"#!/bin/sh\necho hi\n")
    assert (ws_root / "gradlew").stat().st_mode & 0o111


def test_missing_dirs_lists_only_what_does_not_exist(workspace, put):
    put("a/exists.txt", "x")
    assert workspace.missing_dirs("a/b/c/new.txt") == ["a/b", "a/b/c"]
    assert workspace.missing_dirs("a/new.txt") == []
    assert workspace.missing_dirs("top.txt") == []


def test_remove_empty_dirs_keeps_non_empty_ones(workspace, ws_root, put):
    put("a/b/keep.txt", "x")
    (ws_root / "a/b/c").mkdir()
    workspace.remove_empty_dirs(["a", "a/b", "a/b/c"])
    assert not (ws_root / "a/b/c").exists()
    assert (ws_root / "a/b/keep.txt").exists()


def test_symlink_inside_workspace_is_rejected(workspace, ws_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    try:
        os.symlink(outside, ws_root / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this machine")
    with pytest.raises(PathValidationError):
        workspace.resolve("link/secret.txt")


def _make_directory_link(link, target) -> bool:
    """Symlink, or an NTFS junction on Windows without symlink rights. False if neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        return created.returncode == 0
    return False


def test_containment_check_stops_escapes_even_if_link_detection_fails(
    workspace, ws_root, tmp_path, monkeypatch
):
    """Second layer: path resolution must catch a redirect that link detection misses."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    if not _make_directory_link(ws_root / "link", outside):
        pytest.skip("cannot create symlinks or junctions on this machine")
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(Path, "is_junction", lambda self: False, raising=False)
    with pytest.raises(PathValidationError, match="escapes the workspace"):
        workspace.resolve("link/secret.txt")


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_junction_escaping_workspace_is_rejected(workspace, ws_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(ws_root / "junction"), str(outside)],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("cannot create junctions on this machine")
    with pytest.raises(PathValidationError):
        workspace.resolve("junction/secret.txt")
