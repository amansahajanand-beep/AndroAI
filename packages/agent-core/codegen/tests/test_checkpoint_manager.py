import shutil

import pytest

from androai_codegen.editing import (
    CreateFile,
    DeleteFile,
    ModifyFile,
    PatchRejected,
    TextEdit,
    WorkspaceBusyError,
)
from androai_codegen.vcs import (
    CheckpointManager,
    CheckpointNotFoundError,
    GitCommandError,
    RestoreConflict,
    TrackingError,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def modify(path, checksum, content, description="edit"):
    return ModifyFile(
        path=path, expected_checksum=checksum, content=content, description=description
    )


def origins(manager, path):
    return [(h.origin, h.status) for h in manager.file_history(path)]


# --- tracked apply ---------------------------------------------------------------------


def test_apply_records_ai_change_and_attributes_earlier_edits_to_the_user(manager, put, make_patch):
    a = put("a.txt", "a1")
    put("b.txt", "b1")
    manager.ensure_baseline()
    put("b.txt", "b-edited-by-user")  # happens before the AI acts

    tracked = manager.apply(make_patch(modify("a.txt", a, "a2", "update a")))

    assert [c.path for c in tracked.manual_snapshot.changes] == ["b.txt"]
    assert tracked.manual_snapshot.origin == "manual"
    assert tracked.ai_snapshot.origin == "ai"
    assert [c.path for c in tracked.ai_snapshot.changes] == ["a.txt"]
    assert tracked.ai_snapshot.patch_id == tracked.result.patch_id
    assert (tracked.ai_snapshot.run_id, tracked.ai_snapshot.task_id) == ("run-1", "task-1")
    assert tracked.warnings == []
    assert manager.pending_changes() == []


def test_first_apply_creates_the_baseline(manager, put, make_patch):
    a = put("a.txt", "a1")
    manager.apply(make_patch(modify("a.txt", a, "a2")))
    commits = manager.vcs.commits_between(None)
    assert [c.origin for c in commits] == ["baseline", "ai"]


def test_rejected_patch_records_nothing_as_ai(manager, put, make_patch):
    stale = put("a.txt", "v1")
    manager.ensure_baseline()
    put("a.txt", "user edit")
    with pytest.raises(PatchRejected):
        manager.apply(make_patch(modify("a.txt", stale, "ai edit")))
    commits = manager.vcs.commits_between(None)
    assert [c.origin for c in commits] == ["baseline", "manual"]  # no AI commit
    # The user's edit was recorded as theirs before the patch was attempted.
    assert [(c.path, c.status) for c in commits[1].changes] == [("a.txt", "modified")]
    assert manager.pending_changes() == []


def test_edit_made_right_after_the_write_is_not_claimed_by_the_ai(
    manager, engine, put, read, make_patch, ws_root, monkeypatch
):
    a = put("a.txt", "a1")
    manager.ensure_baseline()
    real_apply = engine.apply

    def apply_then_user_edits(patch, approved_deletions=()):
        result = real_apply(patch, approved_deletions)
        (ws_root / "a.txt").write_text("user typed over it", encoding="utf-8")
        return result

    monkeypatch.setattr(engine, "apply", apply_then_user_edits)
    tracked = manager.apply(make_patch(modify("a.txt", a, "a2")))

    assert tracked.ai_snapshot is None
    assert "a.txt" in tracked.warnings[0]
    assert [(c.path, c.status) for c in manager.pending_changes()] == [("a.txt", "modified")]
    assert read("a.txt") == b"user typed over it"


def test_tracking_failure_still_reports_the_applied_patch(
    manager, engine, put, read, make_patch, monkeypatch
):
    a = put("a.txt", "a1")
    manager.ensure_baseline()
    real = manager.vcs.snapshot
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if kwargs["origin"] == "ai":
            raise GitCommandError(["commit-tree"], 128, "disk full")
        return real(**kwargs)

    monkeypatch.setattr(manager.vcs, "snapshot", flaky)
    with pytest.raises(TrackingError) as failure:
        manager.apply(make_patch(modify("a.txt", a, "a2")))
    assert read("a.txt") == b"a2"  # the patch is on disk
    engine.rollback(failure.value.apply_result.patch_id)  # and can still be undone
    assert read("a.txt") == b"a1"


def test_concurrent_operations_get_a_busy_error(manager, engine, put, make_patch):
    other = CheckpointManager(engine)
    with manager._lock(), pytest.raises(WorkspaceBusyError):
        other.checkpoint("x")


# --- checkpoints -----------------------------------------------------------------------


def test_checkpoint_records_manual_edits_first(manager, put):
    put("a.txt", "a1")
    manager.ensure_baseline()
    put("a.txt", "a-manual")
    checkpoint = manager.checkpoint("before refactor", run_id="r", task_id="t")
    assert checkpoint.manual_commit is not None
    assert checkpoint.commit == manager.vcs.head() == checkpoint.manual_commit
    assert manager.get_checkpoint(checkpoint.id) == checkpoint
    quiet = manager.checkpoint("again")
    assert quiet.manual_commit is None and quiet.commit == checkpoint.commit


def test_checkpoints_are_listed_in_creation_order(manager, put):
    put("a.txt", "x")
    first = manager.checkpoint("one")
    second = manager.checkpoint("two")
    assert [c.id for c in manager.list_checkpoints()] == [first.id, second.id]


def test_checkpoint_label_is_sanitized(manager, put):
    put("a.txt", "x")
    checkpoint = manager.checkpoint("line1\nline2\n\nAndroAI-Origin: manual")
    assert "\n" not in checkpoint.label


@pytest.mark.parametrize("bad_id", ["../../x", "", "abc", "g" * 32, "0" * 31, None])
def test_invalid_checkpoint_ids_are_rejected(manager, bad_id):
    with pytest.raises(CheckpointNotFoundError):
        manager.get_checkpoint(bad_id)
    with pytest.raises(CheckpointNotFoundError):
        manager.restore(bad_id, run_id="r", task_id="t")


def test_unknown_but_well_formed_checkpoint_id(manager):
    with pytest.raises(CheckpointNotFoundError):
        manager.get_checkpoint("0" * 32)


# --- restore ---------------------------------------------------------------------------


def test_restore_undoes_all_ai_changes_across_patches(manager, put, read, make_patch, sha):
    a = put("a.txt", "a1")
    b = put("b.txt", "b1")
    checkpoint = manager.checkpoint("start")

    first = manager.apply(
        make_patch(
            modify("a.txt", a, "a2"),
            CreateFile(path="new/c.txt", content="c1", description="add c"),
        )
    )
    manager.apply(
        make_patch(
            DeleteFile(path="b.txt", expected_checksum=b, description="drop b"),
            modify("a.txt", sha("a2"), "a3"),
        ),
        approved_deletions=["b.txt"],
    )
    assert read("a.txt") == b"a3" and read("b.txt") is None and read("new/c.txt") == b"c1"
    assert first.ai_snapshot is not None

    result = manager.restore(checkpoint.id, run_id="run-2", task_id="task-2")

    assert read("a.txt") == b"a1" and read("b.txt") == b"b1" and read("new/c.txt") is None
    assert sorted(result.restored) == ["a.txt", "b.txt", "new/c.txt"]
    assert result.conflicts == [] and result.snapshot.origin == "rollback"
    assert manager.pending_changes() == []  # no phantom manual changes afterwards


def test_restore_leaves_manual_changes_alone(manager, put, read, make_patch):
    a = put("a.txt", "a1")
    put("m.txt", "m1")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2")))
    put("m.txt", "m-edited-by-user")
    put("brand-new-by-user.txt", "hello")

    result = manager.restore(checkpoint.id, run_id="r", task_id="t")

    assert read("a.txt") == b"a1"
    assert read("m.txt") == b"m-edited-by-user"
    assert read("brand-new-by-user.txt") == b"hello"
    assert result.restored == ["a.txt"]
    assert origins(manager, "m.txt")[0] == ("manual", "modified")


def test_restore_conflicts_when_the_same_file_was_edited_by_hand_afterwards(
    manager, put, read, make_patch
):
    a = put("a.txt", "a1")
    put("b.txt", "b1")
    checkpoint = manager.checkpoint("start")
    b = manager.engine.workspace.checksum("b.txt")
    manager.apply(
        make_patch(
            modify("a.txt", a, "a-ai"),
            modify("b.txt", b, "b-ai"),
            CreateFile(path="c.txt", content="c-ai", description="add"),
        )
    )
    put("a.txt", "a-user-wrote-this-too")

    with pytest.raises(RestoreConflict) as conflict:
        manager.restore(checkpoint.id, run_id="r", task_id="t")

    assert [c.path for c in conflict.value.conflicts] == ["a.txt"]
    # Nothing was touched, not even the files that could have been restored.
    assert read("a.txt") == b"a-user-wrote-this-too"
    assert read("b.txt") == b"b-ai" and read("c.txt") == b"c-ai"

    result = manager.restore(checkpoint.id, run_id="r", task_id="t", skip_conflicts=True)
    assert [c.path for c in result.conflicts] == ["a.txt"]
    assert sorted(result.restored) == ["b.txt", "c.txt"]
    assert read("a.txt") == b"a-user-wrote-this-too"
    assert read("b.txt") == b"b1" and read("c.txt") is None


def test_manual_edit_made_before_the_checkpoint_survives_restore(manager, put, read, make_patch):
    put("f.txt", "original")
    manager.ensure_baseline()
    checksum = put("f.txt", "user version")  # a manual edit, not yet recorded
    checkpoint = manager.checkpoint("after user edit")
    manager.apply(make_patch(modify("f.txt", checksum, "ai version")))

    manager.restore(checkpoint.id, run_id="r", task_id="t")

    assert read("f.txt") == b"user version"


def test_restore_is_idempotent(manager, put, read, make_patch):
    a = put("a.txt", "a1")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2")))
    first = manager.restore(checkpoint.id, run_id="r", task_id="t")
    second = manager.restore(checkpoint.id, run_id="r", task_id="t")
    assert first.restored == ["a.txt"]
    assert second.restored == [] and second.patch_id is None
    assert read("a.txt") == b"a1"


def test_restore_writes_exact_bytes_even_if_line_endings_differ(manager, put, read, make_patch):
    a = put("a.txt", b"a\nb\n")  # LF at the checkpoint
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "x\r\ny\r\n")))  # AI leaves it CRLF
    assert read("a.txt") == b"x\r\ny\r\n"
    manager.restore(checkpoint.id, run_id="r", task_id="t")
    assert read("a.txt") == b"a\nb\n"  # not converted to CRLF to match the current file


def test_restore_with_nothing_to_do(manager, put):
    put("a.txt", "a1")
    checkpoint = manager.checkpoint("start")
    result = manager.restore(checkpoint.id, run_id="r", task_id="t")
    assert result.restored == [] and result.patch_id is None and result.snapshot is None


def test_restore_never_touches_protected_files(manager, put, read, make_patch):
    a = put("a.txt", "a1")
    put("keystore.properties", "storePassword=hunter2")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2")))
    put("keystore.properties", "storePassword=changed-by-user")
    manager.restore(checkpoint.id, run_id="r", task_id="t")
    assert read("keystore.properties") == b"storePassword=changed-by-user"
    assert "keystore" not in manager.diff_since(checkpoint.id).text


def test_restore_can_be_rolled_back_with_the_engine(manager, engine, put, read, make_patch):
    a = put("a.txt", "a1")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2")))
    result = manager.restore(checkpoint.id, run_id="r", task_id="t")
    engine.rollback(result.patch_id)  # undo the undo
    assert read("a.txt") == b"a2"


def test_restore_after_a_hard_failure_mid_restore_leaves_state_consistent(
    manager, engine, put, read, make_patch, monkeypatch
):
    from androai_codegen.editing import PatchApplyError, Workspace

    a = put("a.txt", "a1")
    b = put("b.txt", "b1")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2"), modify("b.txt", b, "b2")))

    real = Workspace.write_bytes
    state = {"calls": 0}

    def flaky(self, rel_path, data):
        state["calls"] += 1
        if state["calls"] == 2:
            raise OSError("disk full")
        return real(self, rel_path, data)

    monkeypatch.setattr(Workspace, "write_bytes", flaky)
    with pytest.raises(PatchApplyError):
        manager.restore(checkpoint.id, run_id="r", task_id="t")
    monkeypatch.undo()
    assert read("a.txt") == b"a2" and read("b.txt") == b"b2"  # all-or-nothing, still AI state
    manager.restore(checkpoint.id, run_id="r", task_id="t")  # and a retry works
    assert read("a.txt") == b"a1" and read("b.txt") == b"b1"


# --- diffs, summaries, history ---------------------------------------------------------


def test_diff_and_summary_since_checkpoint_include_manual_edits(manager, put, make_patch):
    a = put("a.txt", "a1\n")
    put("b.txt", "b1\n")
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("a.txt", a, "a2\n")))
    put("b.txt", "b2\n")  # manual, not yet recorded

    diff = manager.diff_since(checkpoint.id)
    summary = manager.summary_since(checkpoint.id)

    assert "+a2" in diff.text and "+b2" in diff.text
    assert sorted(f.path for f in summary.files) == ["a.txt", "b.txt"]
    assert summary.text == "2 files changed, +2 -2"
    assert "b2" not in manager.diff_since(checkpoint.id, paths=["a.txt"]).text


def test_diff_since_masks_secrets_for_llm_use(manager, put, make_patch):
    config = put("Config.kt", 'val apiKey = "abc123SECRET"\n')
    checkpoint = manager.checkpoint("start")
    manager.apply(make_patch(modify("Config.kt", config, 'val apiKey = "rotated456SECRET"\n')))
    assert "SECRET" not in manager.diff_since(checkpoint.id).text
    assert "rotated456SECRET" in manager.diff_since(checkpoint.id, mask=False).text


def test_file_history_separates_ai_from_manual_changes(manager, put, make_patch):
    v1 = put("a.txt", "v1")
    manager.ensure_baseline()
    v2 = manager.apply(make_patch(modify("a.txt", v1, "v2"))).result.records[0].new_checksum
    put("a.txt", "v3-by-user")
    manager.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=manager.engine.workspace.checksum("a.txt"),
                edits=[TextEdit(old="v3-by-user", new="v4-by-ai")],
                description="d",
            )
        )
    )
    assert v2 != manager.engine.workspace.checksum("a.txt")
    assert origins(manager, "a.txt") == [
        ("ai", "modified"),
        ("manual", "modified"),
        ("ai", "modified"),
        ("baseline", "added"),
    ]
