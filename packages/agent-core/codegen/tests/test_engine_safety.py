import os
from pathlib import Path

import pytest

from androai_codegen.editing import (
    REDACTION_MARKER,
    CreateFile,
    DeleteFile,
    JournalError,
    ModifyFile,
    PatchEngine,
    PatchRejected,
    ProblemCode,
    ProtectedFileError,
    TextEdit,
    WorkspaceBusyError,
)


def reject(engine, patch, **kwargs) -> dict[ProblemCode, list[str | None]]:
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(patch, **kwargs)
    result: dict[ProblemCode, list[str | None]] = {}
    for problem in rejected.value.preview.problems:
        result.setdefault(problem.code, []).append(problem.path)
    return result


# --- user changes must never be overwritten --------------------------------------------


def test_snapshot_at_task_start_detects_later_user_edit(engine, put, read, make_patch):
    put("a.txt", "original")
    baseline = engine.snapshot(["a.txt"])  # taken when the AI task starts
    assert baseline["a.txt"] is not None
    put("a.txt", "user edit")  # the user edits by hand while the task is running
    patch = make_patch(
        ModifyFile(
            path="a.txt", expected_checksum=baseline["a.txt"], content="ai edit", description="d"
        )
    )
    assert reject(engine, patch) == {ProblemCode.CONFLICT: ["a.txt"]}
    assert read("a.txt") == b"user edit"


def test_snapshot_records_absent_files_as_none(engine):
    assert engine.snapshot(["not/there.txt"]) == {"not/there.txt": None}


def test_conflict_blocks_the_whole_patch(engine, put, read, make_patch):
    stale = put("a.txt", "v1")
    fresh = put("b.txt", "b1")
    put("a.txt", "v1 edited by user")
    patch = make_patch(
        ModifyFile(path="b.txt", expected_checksum=fresh, content="b2", description="d"),
        ModifyFile(path="a.txt", expected_checksum=stale, content="v2", description="d"),
        CreateFile(path="c.txt", content="c", description="d"),
    )
    assert ProblemCode.CONFLICT in reject(engine, patch)
    assert read("b.txt") == b"b1" and read("c.txt") is None


def test_delete_conflicts_when_file_changed(engine, put, read, make_patch):
    stale = put("a.txt", "v1")
    put("a.txt", "user changed this")
    patch = make_patch(DeleteFile(path="a.txt", expected_checksum=stale, description="d"))
    assert ProblemCode.CONFLICT in reject(engine, patch, approved_deletions=["a.txt"])
    assert read("a.txt") == b"user changed this"


def test_create_refuses_to_overwrite_a_file_the_user_added(engine, put, read, make_patch):
    put("a.txt", "user created this")
    patch = make_patch(CreateFile(path="a.txt", content="ai", description="d"))
    assert reject(engine, patch) == {ProblemCode.ALREADY_EXISTS: ["a.txt"]}
    assert read("a.txt") == b"user created this"


def test_modify_or_delete_of_missing_file(engine, make_patch, sha):
    patch = make_patch(
        ModifyFile(path="a.txt", expected_checksum=sha("x"), content="y", description="d"),
        DeleteFile(path="b.txt", expected_checksum=sha("x"), description="d"),
    )
    assert reject(engine, patch, approved_deletions=["b.txt"]) == {
        ProblemCode.MISSING_FILE: ["a.txt", "b.txt"]
    }


def test_binary_file_cannot_be_edited_as_text(engine, put, make_patch):
    before = put("img.bin", b"\xff\xfe\x00\x01")
    patch = make_patch(
        ModifyFile(path="img.bin", expected_checksum=before, content="x", description="d")
    )
    assert reject(engine, patch) == {ProblemCode.NOT_TEXT: ["img.bin"]}


# --- isolation and path safety ---------------------------------------------------------


def test_patch_for_another_project_is_rejected(engine, make_patch, read):
    patch = make_patch(
        CreateFile(path="a.txt", content="x", description="d"), project_id="someone-else"
    )
    assert reject(engine, patch) == {ProblemCode.PROJECT_MISMATCH: [None]}
    assert read("a.txt") is None


@pytest.mark.parametrize(
    "bad",
    ["../escape.txt", "/abs.txt", "a\\b.txt", ".git/config", "C:/x.txt", "con.txt", "a/../b.txt"],
)
def test_unsafe_paths_in_patches_become_problems(engine, make_patch, tmp_path, bad):
    patch = make_patch(CreateFile(path=bad, content="x", description="d"))
    assert list(reject(engine, patch)) == [ProblemCode.PATH_INVALID]
    assert not (tmp_path / "escape.txt").exists()


def test_directory_target_is_rejected(engine, put, make_patch):
    put("dir/inner.txt", "x")
    patch = make_patch(CreateFile(path="dir", content="x", description="d"))
    assert list(reject(engine, patch)) == [ProblemCode.PATH_INVALID]


def test_symlinked_directory_cannot_be_used_to_escape(engine, ws_root, tmp_path, make_patch):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, ws_root / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this machine")
    patch = make_patch(CreateFile(path="link/pwned.txt", content="x", description="d"))
    assert list(reject(engine, patch)) == [ProblemCode.PATH_INVALID]
    assert not (outside / "pwned.txt").exists()


def test_duplicate_paths_including_aliases_are_rejected(engine, make_patch, read):
    patch = make_patch(
        CreateFile(path="a/b.txt", content="1", description="d"),
        CreateFile(path="a/./b.txt", content="2", description="d"),
    )
    assert list(reject(engine, patch)) == [ProblemCode.DUPLICATE_PATH]
    assert read("a/b.txt") is None


@pytest.mark.parametrize(
    "path", ["app/release.jks", "keystore.properties", "app/local.properties", ".env"]
)
def test_protected_files_cannot_be_created_or_modified(engine, put, make_patch, path, sha):
    put(path, "secret")
    for change in (
        CreateFile(path=path, content="x", description="d"),
        ModifyFile(path=path, expected_checksum=sha("secret"), content="x", description="d"),
        DeleteFile(path=path, expected_checksum=sha("secret"), description="d"),
    ):
        assert list(reject(engine, make_patch(change), approved_deletions=[path])) == [
            ProblemCode.PROTECTED_FILE
        ]


# --- limits ----------------------------------------------------------------------------


def test_file_size_limit(workspace, journal_dir, make_patch):
    small = PatchEngine("proj-1", workspace, journal_dir, max_file_bytes=10)
    patch = make_patch(CreateFile(path="big.txt", content="x" * 11, description="d"))
    assert list(reject(small, patch)) == [ProblemCode.TOO_LARGE]
    small.apply(make_patch(CreateFile(path="ok.txt", content="x" * 10, description="d")))


def test_file_count_limit(workspace, journal_dir, make_patch):
    limited = PatchEngine("proj-1", workspace, journal_dir, max_files=2)
    patch = make_patch(
        *[CreateFile(path=f"f{i}.txt", content="x", description="d") for i in range(3)]
    )
    assert list(reject(limited, patch)) == [ProblemCode.TOO_MANY_FILES]


# --- secrets ---------------------------------------------------------------------------


def test_read_for_llm_refuses_protected_files(engine, put):
    put("keystore.properties", "storePassword=hunter2")
    with pytest.raises(ProtectedFileError):
        engine.read_for_llm("keystore.properties")


def test_read_for_llm_masks_secrets_but_keeps_real_checksum(engine, put, sha):
    source = 'val apiKey = "abc123SECRET"\nval name = "AndroAI"\n'
    real_checksum = put("app/Config.kt", source)
    snapshot = engine.read_for_llm("app/Config.kt")
    assert "abc123SECRET" not in snapshot.content
    assert REDACTION_MARKER in snapshot.content and 'val name = "AndroAI"' in snapshot.content
    assert snapshot.checksum == real_checksum == sha(source)


def test_masked_text_cannot_be_written_back(engine, put, read, make_patch):
    source = 'val apiKey = "abc123SECRET"\n'
    checksum = put("Config.kt", source)
    masked = engine.read_for_llm("Config.kt").content
    # A model that echoes the masked text in a full rewrite would destroy the real secret.
    patch = make_patch(
        ModifyFile(path="Config.kt", expected_checksum=checksum, content=masked, description="d")
    )
    assert list(reject(engine, patch)) == [ProblemCode.REDACTION_MARKER]
    assert read("Config.kt") == source.encode()
    # Same protection for edits and for new files.
    edit = make_patch(
        ModifyFile(
            path="Config.kt",
            expected_checksum=checksum,
            edits=[TextEdit(old="val apiKey", new=f"val apiKey2 = {REDACTION_MARKER}\nval x")],
            description="d",
        )
    )
    assert list(reject(engine, edit)) == [ProblemCode.REDACTION_MARKER]
    created = make_patch(CreateFile(path="n.kt", content=masked, description="d"))
    assert list(reject(engine, created)) == [ProblemCode.REDACTION_MARKER]


def test_marker_already_in_the_file_does_not_block_unrelated_edits(engine, put, read, make_patch):
    source = f'log("{REDACTION_MARKER}")\nval a = 1\n'
    checksum = put("Log.kt", source)
    engine.apply(
        make_patch(
            ModifyFile(
                path="Log.kt",
                expected_checksum=checksum,
                edits=[TextEdit(old="val a = 1", new="val a = 2")],
                description="d",
            )
        )
    )
    assert read("Log.kt") == f'log("{REDACTION_MARKER}")\nval a = 2\n'.encode()


# --- construction and locking ----------------------------------------------------------


def test_journal_must_live_outside_the_workspace(workspace, ws_root):
    with pytest.raises(ValueError):
        PatchEngine("proj-1", workspace, ws_root / ".journal")


def test_workspace_must_not_live_inside_the_journal(workspace, ws_root):
    with pytest.raises(ValueError):
        PatchEngine("proj-1", workspace, Path(ws_root).parent)


def test_journal_cannot_be_shared_across_projects(engine, workspace, journal_dir):
    with pytest.raises(JournalError):
        PatchEngine("another-project", workspace, journal_dir)


def test_second_writer_gets_busy_error_not_corruption(engine, workspace, journal_dir, make_patch):
    other = PatchEngine("proj-1", workspace, journal_dir)
    patch = make_patch(CreateFile(path="a.txt", content="x", description="d"))
    with engine._lock(), pytest.raises(WorkspaceBusyError):
        other.apply(patch)
    other.apply(patch)  # lock released: now it works
