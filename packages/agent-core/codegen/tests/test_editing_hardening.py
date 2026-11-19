"""Regression tests for three hardening bugs found while reviewing coverage gaps:

1. The redaction-marker guard compared the *inserted* text against the old file, so a patch
   could add markers whenever the file already had one, or via ``replace_all``.
2. ``recover()`` (and ``rollback()``) let one bad journal record abort everything.
3. A ``journal.json`` holding valid JSON that is not an object crashed with AttributeError.
"""

import pytest

from androai_codegen.editing import (
    REDACTION_MARKER,
    JournalError,
    ModifyFile,
    PatchApplyError,
    PatchEngine,
    PatchRejected,
    PathValidationError,
    ProblemCode,
    RollbackConflict,
    TextEdit,
    Workspace,
)
from androai_codegen.editing.journal import Journal

# --- 1. redaction marker guard ----------------------------------------------------------


def codes_of_rejection(engine, patch):
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(patch)
    return [p.code for p in rejected.value.preview.problems]


def test_edit_cannot_add_a_marker_when_the_file_already_has_one(engine, put, read, make_patch):
    source = f'log("{REDACTION_MARKER}")\nval a = 1\n'
    checksum = put("Log.kt", source)
    patch = make_patch(
        ModifyFile(
            path="Log.kt",
            expected_checksum=checksum,
            edits=[TextEdit(old="val a = 1", new=f'val a = "{REDACTION_MARKER}"')],
            description="d",
        )
    )
    assert codes_of_rejection(engine, patch) == [ProblemCode.REDACTION_MARKER]
    assert read("Log.kt") == source.encode()


def test_replace_all_cannot_multiply_a_marker(engine, put, read, make_patch):
    source = f"{REDACTION_MARKER}\nx x x x x\n"
    checksum = put("Many.txt", source)
    patch = make_patch(
        ModifyFile(
            path="Many.txt",
            expected_checksum=checksum,
            edits=[TextEdit(old="x", new=REDACTION_MARKER, replace_all=True)],
            description="d",
        )
    )
    assert codes_of_rejection(engine, patch) == [ProblemCode.REDACTION_MARKER]
    assert read("Many.txt") == source.encode()


def test_full_rewrite_cannot_add_a_marker_when_the_file_already_has_one(
    engine, put, read, make_patch
):
    source = f"{REDACTION_MARKER}\nb\n"
    checksum = put("Full.txt", source)
    patch = make_patch(
        ModifyFile(
            path="Full.txt",
            expected_checksum=checksum,
            content=f"{REDACTION_MARKER}\n{REDACTION_MARKER}\n",
            description="d",
        )
    )
    assert codes_of_rejection(engine, patch) == [ProblemCode.REDACTION_MARKER]


def test_edit_may_keep_or_remove_an_existing_marker(engine, put, read, make_patch):
    source = f"{REDACTION_MARKER}\nx = 1\n"
    checksum = put("Keep.txt", source)
    engine.apply(
        make_patch(
            ModifyFile(
                path="Keep.txt",
                expected_checksum=checksum,
                edits=[TextEdit(old="x = 1", new="x = 2")],
                description="keeps the marker",
            )
        )
    )
    assert read("Keep.txt") == f"{REDACTION_MARKER}\nx = 2\n".encode()


# --- 2. recover() and rollback() isolate bad records ------------------------------------


def _always_fail(*args, **kwargs):
    raise OSError("process died")


def crash_patch(engine, make_patch, put, monkeypatch, name):
    """Leave one patch applied in the workspace but 'applying' in the journal."""
    checksum = put(f"{name}.txt", "v1")
    patch = make_patch(
        ModifyFile(path=f"{name}.txt", expected_checksum=checksum, content="v2", description=name)
    )
    monkeypatch.setattr(PatchEngine, "_undo", lambda self, ops: [])
    monkeypatch.setattr(Journal, "set_status", _always_fail)
    with pytest.raises(PatchApplyError):
        engine.apply(patch)
    monkeypatch.undo()
    [manifest] = [m for m in engine.list_patches() if m.entries[0].path == f"{name}.txt"]
    return manifest.patch_id


def test_recover_survives_a_corrupt_manifest_and_still_recovers_the_rest(
    engine, put, read, make_patch, monkeypatch, journal_dir
):
    good = crash_patch(engine, make_patch, put, monkeypatch, "good")
    bad_id = "a" * 32
    (journal_dir / bad_id).mkdir()
    (journal_dir / bad_id / "manifest.json").write_text("{not json", encoding="utf-8")

    report = engine.recover()

    assert report.recovered == [good]
    assert read("good.txt") == b"v1"
    assert list(report.needs_attention) == [bad_id]
    assert report.needs_attention[bad_id][0].code == ProblemCode.IO_ERROR


def test_recover_survives_a_missing_preimage(engine, put, make_patch, monkeypatch, journal_dir):
    patch_id = crash_patch(engine, make_patch, put, monkeypatch, "pre")
    (journal_dir / patch_id / "pre" / "0").unlink()

    report = engine.recover()

    assert report.recovered == []
    assert list(report.needs_attention) == [patch_id]


def test_recover_isolates_a_path_failure_to_one_patch(engine, put, read, make_patch, monkeypatch):
    first = crash_patch(engine, make_patch, put, monkeypatch, "first")
    second = crash_patch(engine, make_patch, put, monkeypatch, "second")
    real = PatchEngine._current

    def flaky(self, path):
        if path == "first.txt":
            raise PathValidationError("parent became a link")
        return real(self, path)

    monkeypatch.setattr(PatchEngine, "_current", flaky)
    report = engine.recover()
    monkeypatch.undo()

    assert report.recovered == [second]
    assert list(report.needs_attention) == [first]
    assert read("second.txt") == b"v1"
    assert read("first.txt") == b"v2"  # left alone, not guessed at


def test_rollback_reports_an_unreadable_path_as_a_conflict(
    engine, put, read, make_patch, monkeypatch
):
    checksum = put("a.txt", "v1")
    applied = engine.apply(
        make_patch(
            ModifyFile(path="a.txt", expected_checksum=checksum, content="v2", description="d")
        )
    )

    def broken(self, rel_path):
        raise PathValidationError("parent became a link")

    monkeypatch.setattr(Workspace, "kind", broken)
    with pytest.raises(RollbackConflict) as conflict:
        engine.rollback(applied.patch_id)
    monkeypatch.undo()

    assert [c.path for c in conflict.value.conflicts] == ["a.txt"]
    assert read("a.txt") == b"v2"
    assert engine.journal.load(applied.patch_id).status == "applied"


# --- 3. journal marker ------------------------------------------------------------------


@pytest.mark.parametrize("content", ["[]", "null", "123", '"text"', "true", "{not json", ""])
def test_unusable_journal_marker_raises_journal_error(journal_dir, content):
    journal_dir.mkdir()
    (journal_dir / "journal.json").write_text(content, encoding="utf-8")
    with pytest.raises(JournalError):
        Journal(journal_dir, "proj-1")


def test_journal_marker_for_another_project_is_still_rejected(journal_dir):
    Journal(journal_dir, "proj-1")
    with pytest.raises(JournalError, match="belongs to project"):
        Journal(journal_dir, "proj-2")
    Journal(journal_dir, "proj-1")  # same project reopens fine
