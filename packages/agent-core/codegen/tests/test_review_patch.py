"""Reviewing a patch before it is applied, on a real workspace on disk."""

import os
from pathlib import Path

import pytest
from sample_project import MAIN, good_project

from androai_codegen.editing import (
    CreateFile,
    DeleteFile,
    ModifyFile,
    PatchSet,
    TextEdit,
    Workspace,
)
from androai_codegen.review import ProjectFiles, ReviewConfig, review_patch

VIEW_MODEL = f"{MAIN}/ui/TodoViewModel.kt"
TASK = f"{MAIN}/data/Task.kt"


def materialize(root: Path, files: dict) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


@pytest.fixture
def project(ws_root, engine, sha):
    materialize(ws_root, good_project())

    def checksum(rel: str) -> str:
        return sha((ws_root / rel).read_bytes())

    return engine, checksum


def patch(*changes) -> PatchSet:
    return PatchSet(
        project_id="proj-1",
        run_id="run-1",
        task_id="task-1",
        description="d",
        changes=list(changes),
    )


def snapshot(ws_root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(ws_root).as_posix(): p.read_bytes() for p in ws_root.rglob("*") if p.is_file()
    }


# --- Workspace.iter_files ---------------------------------------------------------------------


def test_iter_files_is_sorted_and_skips_vcs_and_build_dirs(workspace, ws_root):
    materialize(
        ws_root,
        {
            "b.txt": "b",
            "a/z.txt": "z",
            "a/y.txt": "y",
            ".git/config": "x",
            "build/out.txt": "x",
            "app/build/gen/Foo.kt": "x",
            ".gradle/c.bin": "x",
            "src/main/Ok.kt": "ok",
        },
    )
    # globally sorted, not "files of a directory before its subdirectories"
    assert list(workspace.iter_files()) == ["a/y.txt", "a/z.txt", "b.txt", "src/main/Ok.kt"]


@pytest.mark.skipif(os.name == "nt", reason="NTFS cannot create these names")
def test_iter_files_skips_names_the_engine_would_refuse(workspace, ws_root):
    materialize(ws_root, {"ok.txt": "x", "a:b.txt": "x", "trailing.": "x"})
    assert list(workspace.iter_files()) == ["ok.txt"]


def test_iter_files_does_not_follow_links_out_of_the_workspace(
    workspace, ws_root, tmp_path, make_dir_link
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    if not make_dir_link(ws_root / "link", outside):
        pytest.skip("cannot create symlinks or junctions on this machine")
    (ws_root / "real.txt").write_text("x")
    assert list(workspace.iter_files()) == ["real.txt"]


# --- PatchEngine.simulate ---------------------------------------------------------------------


def test_simulate_returns_the_result_without_writing(project, ws_root):
    engine, checksum = project
    before = snapshot(ws_root)
    simulation = engine.simulate(
        patch(
            CreateFile(path="new/A.kt", content="package x\n", description="d"),
            ModifyFile(
                path=VIEW_MODEL,
                expected_checksum=checksum(VIEW_MODEL),
                edits=[TextEdit(old="fun add", new="fun addTask")],
                description="d",
            ),
            DeleteFile(path=TASK, expected_checksum=checksum(TASK), description="d"),
        ),
        approved_deletions=[TASK],
    )
    assert simulation.preview.ok
    assert simulation.files["new/A.kt"] == "package x\n"
    assert "fun addTask" in simulation.files[VIEW_MODEL]
    assert simulation.files[TASK] is None  # deleted
    assert snapshot(ws_root) == before  # nothing was written


def test_simulate_reports_problems_of_an_invalid_patch(project):
    engine, _ = project
    simulation = engine.simulate(
        patch(ModifyFile(path=VIEW_MODEL, expected_checksum="0" * 64, content="x", description="d"))
    )
    assert not simulation.preview.ok and simulation.files == {}
    assert [p.code.value for p in simulation.preview.problems] == ["conflict"]


# --- ProjectFiles -----------------------------------------------------------------------------


def test_from_workspace_never_opens_protected_files_and_skips_build_output(workspace, ws_root):
    materialize(
        ws_root,
        {
            "app/keystore.properties": "storePassword=hunter2-SECRET",
            ".env": "TOKEN=abc-SECRET",
            "app/build/gen/Broken.kt": "val x = (",
            "app/src/Main.kt": "package a\n",
        },
    )
    files = ProjectFiles.from_workspace(workspace)
    assert set(files.paths) == {"app/src/Main.kt"}
    assert "SECRET" not in repr(files.texts)


def test_from_workspace_keeps_binaries_by_name_and_skips_oversized_or_non_text(workspace, ws_root):
    materialize(
        ws_root,
        {
            "res/mipmap/icon.webp": b"\x00\x01",
            "big.kt": "x" * 100,
            "latin1.kt": b"caf\xe9 = 1",
            "ok.kt": "package a\n",
        },
    )
    files = ProjectFiles.from_workspace(workspace, config=ReviewConfig(max_file_bytes=50))
    assert set(files.texts) == {"ok.kt"}
    assert {"res/mipmap/icon.webp", "big.kt", "latin1.kt"} <= set(files.other_paths)


def test_overlay_adds_replaces_and_removes():
    base = ProjectFiles.from_mapping({"a.kt": "A", "b.kt": "B", "img.png": b"\x00"})
    after = base.overlay({"a.kt": "A2", "b.kt": None, "c.kt": "C", "d.png": "x", "img.png": None})
    assert dict(after.texts) == {"a.kt": "A2", "c.kt": "C"}
    assert after.paths == {"a.kt", "c.kt", "d.png"}
    assert dict(base.texts) == {"a.kt": "A", "b.kt": "B"}  # the original is untouched


def test_from_mapping_rejects_unsafe_paths():
    with pytest.raises(ValueError):
        ProjectFiles.from_mapping({"../escape.kt": "x"})


# --- review_patch -----------------------------------------------------------------------------


def test_a_correct_patch_is_applicable_and_nothing_is_written(project, ws_root):
    engine, _ = project
    before = snapshot(ws_root)
    review = review_patch(
        engine,
        patch(
            CreateFile(
                path=f"{MAIN}/util/Clock.kt",
                content=(
                    "package com.example.todo.util\n\n"
                    "fun now(): Long = System.currentTimeMillis()\n"
                ),
                description="add clock",
            )
        ),
    )
    assert review.report is not None and review.report.findings == []
    assert review.applicable
    assert snapshot(ws_root) == before


def test_a_patch_that_breaks_the_build_is_caught_before_it_is_applied(project, ws_root):
    engine, checksum = project
    before = snapshot(ws_root)
    review = review_patch(
        engine,
        patch(
            ModifyFile(
                path=VIEW_MODEL,
                expected_checksum=checksum(VIEW_MODEL),
                edits=[TextEdit(old="import kotlinx.coroutines.launch\n", new="")],
                description="tidy imports",
            )
        ),
    )
    [item] = review.report.findings
    assert (item.rule, item.key, item.blocking) == ("import.missing", "launch", True)
    assert not review.applicable
    assert snapshot(ws_root) == before  # the broken patch never touched the project


def test_only_problems_the_patch_introduces_are_reported(project, ws_root):
    engine, checksum = project
    # the project already has a defect...
    original = (ws_root / VIEW_MODEL).read_bytes().decode("utf-8")
    broken_text = original.replace("import kotlinx.coroutines.launch\n", "")
    (ws_root / VIEW_MODEL).write_bytes(broken_text.encode("utf-8"))
    # ...and an unrelated patch must not be blamed for it
    review = review_patch(
        engine,
        patch(
            CreateFile(
                path=f"{MAIN}/util/Other.kt",
                content="package com.example.todo.util\n",
                description="d",
            )
        ),
    )
    assert review.report.findings == [] and review.report.preexisting_suppressed == 1
    assert review.applicable


def test_deleting_a_class_other_files_still_use_is_flagged(project):
    engine, checksum = project
    review = review_patch(
        engine,
        patch(DeleteFile(path=TASK, expected_checksum=checksum(TASK), description="drop Task")),
        approved_deletions=[TASK],
    )
    found = {(f.rule, f.file.rsplit("/", 1)[-1], f.key) for f in review.report.findings}
    assert found == {
        ("import.unresolved_project", "TodoViewModel.kt", "com.example.todo.data.Task"),
        ("reference.unresolved_class", "AppDatabase.kt", "Task"),
    }
    assert not review.applicable


def test_an_invalid_patch_has_no_review_only_its_problems(project):
    engine, _ = project
    review = review_patch(
        engine,
        patch(
            ModifyFile(path=VIEW_MODEL, expected_checksum="0" * 64, content="x", description="d")
        ),
    )
    assert review.report is None and not review.applicable
    assert [p.code.value for p in review.simulation.preview.problems] == ["conflict"]


def test_unapproved_deletion_is_reported_as_needing_approval_not_reviewed(project, ws_root):
    engine, checksum = project
    review = review_patch(
        engine, patch(DeleteFile(path=TASK, expected_checksum=checksum(TASK), description="d"))
    )
    assert review.report is None and review.simulation.preview.requires_approval
    assert (ws_root / TASK).exists()


def test_review_runs_on_the_real_workspace_state_when_a_manual_edit_exists(project, ws_root):
    engine, checksum = project
    stale = checksum(VIEW_MODEL)
    (ws_root / VIEW_MODEL).write_text("// the user rewrote this file\n")
    review = review_patch(
        engine,
        patch(ModifyFile(path=VIEW_MODEL, expected_checksum=stale, content="x", description="d")),
    )
    assert review.report is None  # conflict with the manual edit: nothing to review
    assert [p.code.value for p in review.simulation.preview.problems] == ["conflict"]
    assert os.path.exists(ws_root / VIEW_MODEL)
    assert isinstance(engine.workspace, Workspace)
