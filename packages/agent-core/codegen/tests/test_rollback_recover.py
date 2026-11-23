import pytest

from androai_codegen.editing import (
    CreateFile,
    DeleteFile,
    ModifyFile,
    PatchApplyError,
    PatchEngine,
    PatchStateError,
    RollbackConflict,
    UnknownPatchError,
)
from androai_codegen.editing.journal import Journal


def apply_mixed_patch(engine, put, make_patch):
    """Create + modify + delete, so rollback has every case to undo."""
    modified = put("app/Main.kt", "main v1\n")
    deleted = put("app/Old.kt", "old\n")
    return engine.apply(
        make_patch(
            CreateFile(path="new/pkg/Created.kt", content="created\n", description="add"),
            ModifyFile(
                path="app/Main.kt",
                expected_checksum=modified,
                content="main v2\n",
                description="edit",
            ),
            DeleteFile(path="app/Old.kt", expected_checksum=deleted, description="drop"),
        ),
        approved_deletions=["app/Old.kt"],
    )


# --- rollback --------------------------------------------------------------------------


def test_rollback_restores_every_file_and_removes_created_dirs(
    engine, put, read, make_patch, ws_root
):
    result = apply_mixed_patch(engine, put, make_patch)
    restored = engine.rollback(result.patch_id)
    assert read("app/Main.kt") == b"main v1\n"
    assert read("app/Old.kt") == b"old\n"
    assert read("new/pkg/Created.kt") is None
    assert not (ws_root / "new").exists()
    assert sorted(restored.restored_paths) == ["app/Main.kt", "app/Old.kt", "new/pkg/Created.kt"]
    assert engine.journal.load(result.patch_id).status == "rolled_back"
    assert engine.history("app/Main.kt") == []


def test_rolled_back_patch_cannot_be_rolled_back_twice(engine, put, make_patch):
    result = apply_mixed_patch(engine, put, make_patch)
    engine.rollback(result.patch_id)
    with pytest.raises(PatchStateError):
        engine.rollback(result.patch_id)


def test_rollback_never_discards_later_manual_changes(engine, put, read, make_patch):
    result = apply_mixed_patch(engine, put, make_patch)
    put("app/Main.kt", "user kept editing\n")  # manual change after the AI patch
    with pytest.raises(RollbackConflict) as conflict:
        engine.rollback(result.patch_id)
    assert [c.path for c in conflict.value.conflicts] == ["app/Main.kt"]
    # Nothing was touched, not even the files that could have been restored.
    assert read("app/Main.kt") == b"user kept editing\n"
    assert read("new/pkg/Created.kt") == b"created\n"
    assert read("app/Old.kt") is None
    assert engine.journal.load(result.patch_id).status == "applied"


def test_rollback_in_wrong_order_conflicts_then_works_in_right_order(engine, put, read, make_patch):
    v1 = put("a.txt", "v1")
    first = engine.apply(
        make_patch(ModifyFile(path="a.txt", expected_checksum=v1, content="v2", description="1"))
    )
    second = engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=first.records[0].new_checksum,
                content="v3",
                description="2",
            )
        )
    )
    with pytest.raises(RollbackConflict):
        engine.rollback(first.patch_id)
    engine.rollback(second.patch_id)
    assert read("a.txt") == b"v2"
    engine.rollback(first.patch_id)
    assert read("a.txt") == b"v1"


def test_rollback_resumes_after_partial_restore(engine, put, read, make_patch):
    result = apply_mixed_patch(engine, put, make_patch)
    put("app/Main.kt", "main v1\n")  # pretend a previous rollback already restored this one
    engine.rollback(result.patch_id)
    assert read("app/Old.kt") == b"old\n" and read("new/pkg/Created.kt") is None


def test_rollback_failure_midway_restores_applied_state(engine, put, read, make_patch, monkeypatch):
    from androai_codegen.editing import Workspace

    result = apply_mixed_patch(engine, put, make_patch)
    real = Workspace.write_bytes
    state = {"calls": 0}

    def flaky(self, rel_path, data):
        state["calls"] += 1
        if state["calls"] == 2:
            raise OSError("disk full")
        return real(self, rel_path, data)

    monkeypatch.setattr(Workspace, "write_bytes", flaky)
    with pytest.raises(PatchApplyError):
        engine.rollback(result.patch_id)
    monkeypatch.undo()
    assert read("app/Main.kt") == b"main v2\n"  # back in the patched state, not half-restored
    assert read("app/Old.kt") is None
    assert engine.journal.load(result.patch_id).status == "applied"


@pytest.mark.parametrize("bad_id", ["../../etc", "x", "", "0" * 31, "g" * 32, "A" * 32])
def test_rollback_rejects_unknown_or_malicious_ids(engine, bad_id):
    with pytest.raises(UnknownPatchError):
        engine.rollback(bad_id)


def test_rollback_of_unknown_but_well_formed_id(engine):
    with pytest.raises(UnknownPatchError):
        engine.rollback("0" * 32)


# --- crash recovery --------------------------------------------------------------------


def simulate_crash_after_writes(engine, make_patch, put, monkeypatch):
    """Leave the workspace patched while the journal still says 'applying'."""
    modified = put("a.txt", "A1")
    patch = make_patch(
        ModifyFile(path="a.txt", expected_checksum=modified, content="A2", description="d"),
        CreateFile(path="made/b.txt", content="B", description="d"),
    )
    monkeypatch.setattr(PatchEngine, "_undo", lambda self, ops: [])  # nothing cleans up
    monkeypatch.setattr(Journal, "set_status", _always_fail)
    with pytest.raises(PatchApplyError):
        engine.apply(patch)
    monkeypatch.undo()


def _always_fail(*args, **kwargs):
    raise OSError("process died")


def test_recover_undoes_an_interrupted_apply(engine, put, read, make_patch, monkeypatch, ws_root):
    simulate_crash_after_writes(engine, make_patch, put, monkeypatch)
    assert read("a.txt") == b"A2" and read("made/b.txt") == b"B"  # the crash state
    assert [m.status for m in engine.list_patches()] == ["applying"]

    report = engine.recover()

    assert len(report.recovered) == 1 and report.needs_attention == {}
    assert read("a.txt") == b"A1" and read("made/b.txt") is None
    assert not (ws_root / "made").exists()
    assert [m.status for m in engine.list_patches()] == ["rolled_back"]
    assert engine.recover().recovered == []  # idempotent


def test_recover_does_not_overwrite_manual_edits(engine, put, read, make_patch, monkeypatch):
    simulate_crash_after_writes(engine, make_patch, put, monkeypatch)
    put("a.txt", "the user rewrote this")
    report = engine.recover()
    assert report.recovered == []
    [(patch_id, problems)] = report.needs_attention.items()
    assert [p.path for p in problems] == ["a.txt"]
    assert read("a.txt") == b"the user rewrote this"
    assert read("made/b.txt") == b"B"  # untouched: all-or-nothing recovery
    assert engine.journal.load(patch_id).status == "needs_attention"


def test_recover_ignores_applied_and_clean_journals(engine, put, make_patch):
    apply_mixed_patch(engine, put, make_patch)
    report = engine.recover()
    assert report.recovered == [] and report.needs_attention == {}
    assert [m.status for m in engine.list_patches()] == ["applied"]
