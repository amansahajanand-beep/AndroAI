import os

import pytest

from androai_codegen.editing import (
    CreateFile,
    DeleteFile,
    ModifyFile,
    PatchApplyError,
    PatchRejected,
    ProblemCode,
    TextEdit,
    Workspace,
)


def codes(rejected: pytest.ExceptionInfo[PatchRejected]) -> set[ProblemCode]:
    return {p.code for p in rejected.value.preview.problems}


# --- basic operations ------------------------------------------------------------------


def test_create_modify_delete_in_one_patch(engine, put, read, make_patch, sha):
    kept = put("app/Main.kt", "fun main() {\n    println(1)\n}\n")
    doomed = put("app/Old.kt", "// old\n")
    result = engine.apply(
        make_patch(
            CreateFile(path="app/New.kt", content="class New\n", description="add New"),
            ModifyFile(
                path="app/Main.kt",
                expected_checksum=kept,
                edits=[TextEdit(old="println(1)", new="println(2)")],
                description="print 2",
            ),
            DeleteFile(path="app/Old.kt", expected_checksum=doomed, description="drop Old"),
        ),
        approved_deletions=["app/Old.kt"],
    )
    assert read("app/New.kt") == b"class New\n"
    assert read("app/Main.kt") == b"fun main() {\n    println(2)\n}\n"
    assert read("app/Old.kt") is None
    assert [r.change_type for r in result.records] == ["create", "modify", "delete"]


def test_records_link_ids_paths_checksums_and_description(engine, put, make_patch, sha):
    before = put("a.txt", "one")
    result = engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt", expected_checksum=before, content="two", description="rename one"
            ),
            CreateFile(path="b.txt", content="new", description="add b"),
        )
    )
    modify, create = result.records
    assert (modify.project_id, modify.run_id, modify.task_id) == ("proj-1", "run-1", "task-1")
    assert modify.patch_id == result.patch_id
    assert modify.path == "a.txt"
    assert modify.previous_checksum == before
    assert modify.new_checksum == sha("two")
    assert modify.description == "rename one"
    assert modify.origin == "ai"
    assert create.previous_checksum is None
    assert create.new_checksum == sha("new")


def test_diff_shows_changes_and_is_persisted(engine, put, make_patch):
    before = put("a.txt", "keep\nold line\n")
    result = engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                edits=[TextEdit(old="old line", new="new line")],
                description="d",
            ),
            CreateFile(path="n.txt", content="fresh\n", description="d"),
        )
    )
    assert "--- a/a.txt" in result.diff and "+++ b/a.txt" in result.diff
    assert "-old line" in result.diff and "+new line" in result.diff
    assert "--- /dev/null" in result.diff and "+fresh" in result.diff
    assert engine.journal.read_diff(result.patch_id) == result.diff
    assert result.diff_reference == f"journal:{result.patch_id}/diff.patch"


def test_delete_diff_targets_dev_null(engine, put, make_patch):
    digest = put("gone.txt", "bye\n")
    result = engine.apply(
        make_patch(DeleteFile(path="gone.txt", expected_checksum=digest, description="d")),
        approved_deletions=["gone.txt"],
    )
    assert "+++ /dev/null" in result.diff and "-bye" in result.diff


def test_diff_marks_missing_trailing_newline(engine, put, make_patch):
    before = put("a.txt", "last")
    result = engine.apply(
        make_patch(
            ModifyFile(path="a.txt", expected_checksum=before, content="last\n", description="d")
        )
    )
    assert "No newline at end of file" in result.diff


def test_full_content_replacement(engine, put, read, make_patch):
    before = put("a.txt", "old")
    engine.apply(
        make_patch(
            ModifyFile(path="a.txt", expected_checksum=before, content="new", description="d")
        )
    )
    assert read("a.txt") == b"new"


def test_preview_never_writes(engine, put, read, make_patch):
    before = put("a.txt", "old")
    preview = engine.preview(
        make_patch(
            ModifyFile(path="a.txt", expected_checksum=before, content="new", description="d"),
            CreateFile(path="b.txt", content="x", description="d"),
        )
    )
    assert preview.ok and len(preview.planned) == 2 and "+new" in preview.diff
    assert read("a.txt") == b"old" and read("b.txt") is None
    assert engine.list_patches() == []


def test_creates_nested_directories(engine, read, make_patch):
    engine.apply(make_patch(CreateFile(path="a/b/c/d.kt", content="x", description="d")))
    assert read("a/b/c/d.kt") == b"x"


def test_unicode_content_round_trips(engine, read, make_patch):
    text = 'val s = "café ☃ \U0001f600"\n'
    engine.apply(make_patch(CreateFile(path="u.kt", content=text, description="d")))
    assert read("u.kt") == text.encode("utf-8")


# --- text edit semantics ---------------------------------------------------------------


def test_edit_must_match_exactly_once(engine, put, make_patch):
    before = put("a.txt", "x\nx\n")
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(
            make_patch(
                ModifyFile(
                    path="a.txt",
                    expected_checksum=before,
                    edits=[TextEdit(old="x", new="y")],
                    description="d",
                )
            )
        )
    assert codes(rejected) == {ProblemCode.EDIT_AMBIGUOUS}


def test_replace_all(engine, put, read, make_patch):
    before = put("a.txt", "x\nx\n")
    engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                edits=[TextEdit(old="x", new="y", replace_all=True)],
                description="d",
            )
        )
    )
    assert read("a.txt") == b"y\ny\n"


def test_edits_apply_in_order_and_see_earlier_results(engine, put, read, make_patch):
    before = put("a.txt", "one")
    engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                edits=[TextEdit(old="one", new="two"), TextEdit(old="two", new="three")],
                description="d",
            )
        )
    )
    assert read("a.txt") == b"three"


def test_edit_not_found_rejects_whole_patch(engine, put, read, make_patch):
    first = put("a.txt", "alpha")
    second = put("b.txt", "beta")
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(
            make_patch(
                ModifyFile(
                    path="a.txt",
                    expected_checksum=first,
                    edits=[TextEdit(old="alpha", new="ALPHA")],
                    description="d",
                ),
                ModifyFile(
                    path="b.txt",
                    expected_checksum=second,
                    edits=[TextEdit(old="missing", new="x")],
                    description="d",
                ),
            )
        )
    assert codes(rejected) == {ProblemCode.EDIT_NOT_FOUND}
    assert read("a.txt") == b"alpha"  # the valid half was not applied either


def test_edits_adapt_to_crlf_files(engine, put, read, make_patch):
    before = put("a.txt", b"one\r\ntwo\r\nthree\r\n")
    engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                edits=[TextEdit(old="two\nthree", new="2\nthree")],
                description="d",
            )
        )
    )
    assert read("a.txt") == b"one\r\n2\r\nthree\r\n"


def test_full_replacement_keeps_crlf(engine, put, read, make_patch):
    before = put("a.txt", b"a\r\nb\r\n")
    engine.apply(
        make_patch(
            ModifyFile(path="a.txt", expected_checksum=before, content="x\ny\n", description="d")
        )
    )
    assert read("a.txt") == b"x\r\ny\r\n"


def test_normalize_eol_false_writes_exact_bytes(engine, put, read, make_patch):
    before = put("a.txt", b"a\r\nb\r\n")
    engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                content="x\ny\n",
                normalize_eol=False,
                description="d",
            )
        )
    )
    assert read("a.txt") == b"x\ny\n"  # not converted to the file's CRLF


def test_utf8_bom_is_preserved(engine, put, read, make_patch):
    before = put("a.txt", b"\xef\xbb\xbfhello\n")
    engine.apply(
        make_patch(
            ModifyFile(
                path="a.txt",
                expected_checksum=before,
                edits=[TextEdit(old="hello", new="bye")],
                description="d",
            )
        )
    )
    assert read("a.txt") == b"\xef\xbb\xbfbye\n"


def test_noop_edit_is_not_applied(engine, put, make_patch):
    before = put("a.txt", "same")
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(
            make_patch(
                ModifyFile(path="a.txt", expected_checksum=before, content="same", description="d")
            )
        )
    assert codes(rejected) == {ProblemCode.NO_CHANGE}
    assert engine.list_patches() == []


def test_noop_next_to_real_change_is_only_a_warning(engine, put, read, make_patch):
    same = put("same.txt", "x")
    other = put("other.txt", "old")
    result = engine.apply(
        make_patch(
            ModifyFile(path="same.txt", expected_checksum=same, content="x", description="d"),
            ModifyFile(path="other.txt", expected_checksum=other, content="new", description="d"),
        )
    )
    assert [r.path for r in result.records] == ["other.txt"]
    assert read("other.txt") == b"new"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_modify_keeps_executable_bit(engine, ws_root, put, make_patch):
    before = put("gradlew", "#!/bin/sh\n")
    (ws_root / "gradlew").chmod(0o755)
    engine.apply(
        make_patch(
            ModifyFile(
                path="gradlew", expected_checksum=before, content="#!/bin/sh\nx\n", description="d"
            )
        )
    )
    assert (ws_root / "gradlew").stat().st_mode & 0o111


# --- approval --------------------------------------------------------------------------


def test_delete_without_approval_is_rejected_and_flagged(engine, put, read, make_patch):
    digest = put("a.txt", "keep me")
    patch = make_patch(DeleteFile(path="a.txt", expected_checksum=digest, description="d"))
    with pytest.raises(PatchRejected) as rejected:
        engine.apply(patch)
    assert rejected.value.preview.requires_approval
    assert codes(rejected) == {ProblemCode.APPROVAL_REQUIRED}
    assert read("a.txt") == b"keep me"


def test_approval_is_per_path(engine, put, read, make_patch):
    a = put("a.txt", "A")
    b = put("b.txt", "B")
    patch = make_patch(
        DeleteFile(path="a.txt", expected_checksum=a, description="d"),
        DeleteFile(path="b.txt", expected_checksum=b, description="d"),
    )
    with pytest.raises(PatchRejected):
        engine.apply(patch, approved_deletions=["a.txt"])
    assert read("a.txt") == b"A" and read("b.txt") == b"B"
    engine.apply(patch, approved_deletions=["a.txt", "./b.txt"])  # normalized before matching
    assert read("a.txt") is None and read("b.txt") is None


# --- atomicity under failure -----------------------------------------------------------


def _fail_from_nth_write(monkeypatch, n, exc_type=OSError):
    real = Workspace.write_bytes
    state = {"calls": 0}

    def flaky(self, rel_path, data):
        state["calls"] += 1
        if state["calls"] >= n:
            raise exc_type("injected failure")
        return real(self, rel_path, data)

    monkeypatch.setattr(Workspace, "write_bytes", flaky)
    return state


def test_io_failure_midway_restores_everything(engine, put, read, make_patch, monkeypatch):
    a = put("a.txt", "A")
    b = put("b.txt", "B")
    patch = make_patch(
        ModifyFile(path="a.txt", expected_checksum=a, content="A2", description="d"),
        CreateFile(path="new/dir/c.txt", content="C", description="d"),
        ModifyFile(path="b.txt", expected_checksum=b, content="B2", description="d"),
    )
    real = Workspace.write_bytes
    state = {"calls": 0}

    def flaky(self, rel_path, data):
        state["calls"] += 1
        if state["calls"] == 3:  # fails on b.txt; the restore calls afterwards succeed
            raise OSError("disk full")
        return real(self, rel_path, data)

    monkeypatch.setattr(Workspace, "write_bytes", flaky)

    with pytest.raises(PatchApplyError) as failure:
        engine.apply(patch)

    assert failure.value.rolled_back is True
    assert read("a.txt") == b"A" and read("b.txt") == b"B"
    assert read("new/dir/c.txt") is None
    assert not (engine.workspace.root / "new").exists()  # directories we created are gone
    assert [m.status for m in engine.list_patches()] == ["rolled_back"]
    assert engine.history("a.txt") == []


def test_failed_restore_is_reported_not_hidden(engine, put, read, make_patch, monkeypatch):
    a = put("a.txt", "A")
    patch = make_patch(
        ModifyFile(path="a.txt", expected_checksum=a, content="A2", description="d"),
        CreateFile(path="c.txt", content="C", description="d"),
    )
    _fail_from_nth_write(monkeypatch, 2)  # second write fails and so does every restore
    with pytest.raises(PatchApplyError) as failure:
        engine.apply(patch)
    assert failure.value.rolled_back is False
    assert "a.txt" in failure.value.failed_paths
    assert [m.status for m in engine.list_patches()] == ["needs_attention"]


def test_keyboard_interrupt_restores_files_and_propagates(
    engine, put, read, make_patch, monkeypatch
):
    a = put("a.txt", "A")
    patch = make_patch(
        ModifyFile(path="a.txt", expected_checksum=a, content="A2", description="d"),
        CreateFile(path="c.txt", content="C", description="d"),
    )
    real = Workspace.write_bytes
    state = {"calls": 0}

    def interrupted(self, rel_path, data):
        state["calls"] += 1
        if state["calls"] == 2:
            raise KeyboardInterrupt
        return real(self, rel_path, data)

    monkeypatch.setattr(Workspace, "write_bytes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        engine.apply(patch)
    assert read("a.txt") == b"A" and read("c.txt") is None


# --- history ---------------------------------------------------------------------------


def test_history_chains_checksums_across_patches(engine, put, make_patch):
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
    history = engine.history("a.txt")
    assert [h.description for h in history] == ["1", "2"]
    assert history[1].previous_checksum == history[0].new_checksum
    assert history[1].patch_id == second.patch_id
    assert engine.history("untouched.txt") == []
