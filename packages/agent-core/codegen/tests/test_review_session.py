"""ReviewSession: reuse the parsed project and the 'before' review across patch reviews, safely.

The contract being tested: a session gives exactly the answers the stateless ``review_patch``
gives, does less work when nothing changed, and never answers from stale state.
"""

import hashlib
import os
import time
from pathlib import Path

import pytest
from sample_project import FILES, MAIN

from androai_codegen.editing import ModifyFile, PatchEngine, PatchSet, TextEdit, Workspace
from androai_codegen.review import ReviewConfig, ReviewSession, review_patch

PROJECT = "proj-1"
VIEW_MODEL = f"{MAIN}/ui/TodoViewModel.kt"
TODO_APP = f"{MAIN}/ui/TodoApp.kt"
MAIN_ACTIVITY = f"{MAIN}/MainActivity.kt"


def populate(root: Path, extra: dict[str, str] | None = None) -> None:
    for rel, content in {**FILES, **(extra or {})}.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def age(root: Path, seconds: int = 60) -> None:
    """Make every file look old, so the 'recently modified' safety margin is not in play."""
    stamp = time.time_ns() - seconds * 1_000_000_000
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(stamp, stamp))


def make_engine(
    tmp_path: Path, name: str = "ws", project: str = PROJECT, extra=None
) -> PatchEngine:
    root = tmp_path / name
    root.mkdir()
    populate(root, extra)
    age(root)
    return PatchEngine(project, Workspace(root), tmp_path / f"{name}-journal")


@pytest.fixture
def eng(tmp_path: Path) -> PatchEngine:
    return make_engine(tmp_path)


def root_of(engine: PatchEngine) -> Path:
    return engine.workspace.root


def checksum(engine: PatchEngine, rel: str) -> str:
    return hashlib.sha256((root_of(engine) / rel).read_bytes()).hexdigest()


def rewrite(path: Path, old: str, new: str) -> None:
    """Replace text in a file byte-exactly (``write_text`` would turn LF into CRLF on Windows)."""
    text = path.read_bytes().decode("utf-8")
    assert old in text
    path.write_bytes(text.replace(old, new).encode("utf-8"))


def edit(
    engine: PatchEngine, rel: str, old: str, new: str, expected: str | None = None
) -> PatchSet:
    return PatchSet(
        project_id=PROJECT,
        run_id="run-1",
        task_id="task-1",
        description="p",
        changes=[
            ModifyFile(
                path=rel,
                expected_checksum=expected or checksum(engine, rel),
                edits=[TextEdit(old=old, new=new)],
                description="e",
            )
        ],
    )


def comment(engine, rel=VIEW_MODEL) -> PatchSet:
    return edit(engine, rel, "package ", "// reviewed\npackage ")


def drop_import(engine, rel=TODO_APP) -> PatchSet:
    return edit(engine, rel, "import androidx.compose.material3.Text\n", "")


def shape(review):
    report = review.report
    return (
        review.applicable,
        None if report is None else sorted((f.rule, f.file, f.key) for f in report.findings),
        None if report is None else (report.files_reviewed, report.preexisting_suppressed),
    )


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- same answers as the stateless function ---------------------------------------------------


def test_session_gives_the_same_answers_as_stateless_review_patch(eng):
    session = ReviewSession(eng)
    patches = [comment(eng), drop_import(eng), comment(eng, MAIN_ACTIVITY), drop_import(eng)]
    for patch in patches:
        assert shape(session.review_patch(patch)) == shape(review_patch(eng, patch))


def test_review_patch_function_accepts_a_session_and_agrees(eng):
    session = ReviewSession(eng)
    patch = drop_import(eng)
    assert shape(review_patch(eng, patch, session=session)) == shape(review_patch(eng, patch))
    assert session.stats.reviews == 1


def test_invalid_patch_is_rejected_without_a_report_and_without_touching_the_cache(eng):
    session = ReviewSession(eng)
    stale = edit(eng, VIEW_MODEL, "package ", "x", expected="0" * 64)
    result = session.review_patch(stale)
    assert result.report is None and not result.applicable
    assert session.stats.files_read == 0 and session.stats.baseline_builds == 0


# --- doing less work when nothing changed -----------------------------------------------------


def test_unchanged_workspace_is_read_and_analysed_once(eng):
    session = ReviewSession(eng)
    session.review_patch(comment(eng))
    first = (session.stats.files_read, session.stats.baseline_builds)
    assert first[0] > 15 and first[1] == 1
    for _ in range(4):
        session.review_patch(drop_import(eng))
    assert (session.stats.files_read, session.stats.baseline_builds) == first
    assert session.stats.reviews == 5


def test_reviews_never_write_to_the_workspace_or_mutate_cached_files(eng):
    before_tree = tree(root_of(eng))
    session = ReviewSession(eng)
    original = (root_of(eng) / TODO_APP).read_text(encoding="utf-8")
    session.review_patch(drop_import(eng))
    session.review_patch(comment(eng))
    assert tree(root_of(eng)) == before_tree
    assert session.project_files().texts[TODO_APP] == original  # the overlay was a copy


def test_a_patch_is_judged_against_the_project_not_against_the_previous_patch(eng):
    session = ReviewSession(eng)
    broken = session.review_patch(drop_import(eng))
    assert not broken.applicable
    clean = session.review_patch(comment(eng, TODO_APP))
    assert clean.applicable and clean.report.findings == []  # nothing carried over


# --- never stale ------------------------------------------------------------------------------


def test_a_file_changed_on_disk_is_seen_by_the_next_review(eng):
    session = ReviewSession(eng)
    session.review_patch(comment(eng))
    reads, builds = session.stats.files_read, session.stats.baseline_builds
    rewrite(root_of(eng) / TODO_APP, "import androidx.compose.material3.Text\n", "")
    result = session.review_patch(comment(eng, VIEW_MODEL))
    assert session.stats.files_read == reads + 1  # exactly the changed file
    assert session.stats.baseline_builds == builds + 1
    # The break is now part of the project: it existed before this patch, so it is not blamed on it.
    assert result.applicable and result.report.preexisting_suppressed == 1


def test_created_and_deleted_files_change_the_picture(eng):
    session = ReviewSession(eng)
    count = session.review_patch(comment(eng)).report.files_reviewed
    extra = root_of(eng) / f"{MAIN}/Extra.kt"
    extra.write_bytes(b"package com.example.todo\n\nclass Extra\n")
    assert session.review_patch(comment(eng)).report.files_reviewed == count + 1
    extra.unlink()
    assert session.review_patch(comment(eng)).report.files_reviewed == count


def test_same_size_rewrite_with_the_same_timestamp_is_still_seen_when_recent(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    populate(root)  # deliberately NOT aged: every file was modified moments ago
    engine = PatchEngine(PROJECT, Workspace(root), tmp_path / "j")
    session = ReviewSession(engine)
    path = root / TODO_APP
    session.review_patch(comment(engine))
    old = path.stat()
    rewrite(
        path, "import androidx.compose.material3.Text\n", "import androidx.compose.material3.Texx\n"
    )
    assert path.stat().st_size == old.st_size
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))  # same size AND same mtime
    result = session.review_patch(comment(engine, VIEW_MODEL))
    # The typo'd import was read from disk, not trusted from the cache.
    assert result.report.preexisting_suppressed >= 1


def test_changes_made_by_applying_a_patch_are_seen(eng):
    session = ReviewSession(eng)
    session.review_patch(comment(eng))
    eng.apply(comment(eng, TODO_APP))  # the engine writes the file; its mtime is brand new
    after_apply = session.project_files().texts[TODO_APP]
    assert after_apply.startswith("// reviewed\n")
    assert session.review_patch(
        drop_import(eng)
    ).report.findings  # judged against the applied state


def test_invalidate_forces_a_full_reload(eng):
    session = ReviewSession(eng)
    session.review_patch(comment(eng))
    reads = session.stats.files_read
    session.invalidate()
    session.review_patch(comment(eng))
    assert session.stats.files_read == 2 * reads
    assert session.stats.baseline_builds == 2


# --- sessions never mix projects --------------------------------------------------------------


def test_a_session_refuses_an_engine_for_another_workspace(tmp_path):
    a = make_engine(tmp_path, "a")
    b = make_engine(tmp_path, "b")
    session = ReviewSession(a)
    with pytest.raises(ValueError, match="another workspace"):
        review_patch(b, comment(b), session=session)


def test_a_session_refuses_an_engine_for_another_project_id(tmp_path):
    a = make_engine(tmp_path, "a")
    twin = PatchEngine("proj-2", Workspace(root_of(a)), tmp_path / "other-journal")
    with pytest.raises(ValueError, match="another project"):
        review_patch(twin, comment(a), session=ReviewSession(a))


def test_a_session_refuses_a_different_config(eng):
    session = ReviewSession(eng)
    with pytest.raises(ValueError, match="config"):
        review_patch(eng, comment(eng), session=session, config=ReviewConfig(max_findings=1))


def test_two_sessions_on_two_projects_do_not_leak_findings(tmp_path):
    a = make_engine(tmp_path, "a")
    b = make_engine(tmp_path, "b")
    rewrite(root_of(a) / TODO_APP, "import androidx.compose.material3.Text\n", "")
    sa, sb = ReviewSession(a), ReviewSession(b)
    ra, rb = sa.review_patch(comment(a)), sb.review_patch(comment(b))
    assert ra.report.preexisting_suppressed == 1  # a's own break
    assert rb.report.preexisting_suppressed == 0 and rb.report.findings == []
    assert sa.project_files() is not sb.project_files()


# --- performance ------------------------------------------------------------------------------


def _big(n: int) -> dict[str, str]:
    return {
        f"app/src/main/java/com/example/todo/gen/Gen{i}.kt": (
            "package com.example.todo.gen\n\nimport com.example.todo.R\n\n"
            + "".join(f"fun f{i}_{j}(x: Int): Int = x + {j}\n" for j in range(40))
            + f"class Gen{i}\n"
        )
        for i in range(n)
    }


def test_later_reviews_are_clearly_faster_than_stateless_ones(tmp_path):
    engine = make_engine(tmp_path, extra=_big(500))
    session = ReviewSession(engine)
    patch = comment(engine)
    session.review_patch(patch)  # warm-up: the first review pays for the load and the baseline
    stateless = min(_timed(lambda: review_patch(engine, patch)) for _ in range(3))
    cached = min(_timed(lambda: session.review_patch(patch)) for _ in range(3))
    assert session.stats.files_read < 600  # read once, never again
    assert cached < stateless * 0.75, (cached, stateless)


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start
