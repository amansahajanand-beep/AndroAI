import os
import shutil
import subprocess
import time

import pytest

from androai_codegen.vcs import GitNotAvailableError, ShadowGit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def baseline(shadow):
    return shadow.snapshot(origin="baseline", description="start")


def tracked(shadow) -> list[str]:
    return sorted(shadow._ls())


# --- setup and hardening ---------------------------------------------------------------


def test_init_is_idempotent_and_configures_a_hardened_repository(shadow):
    shadow.init()
    shadow.init()
    config = {
        key: shadow._git("config", "--get", key).stdout.decode().strip()
        for key in ("core.autocrlf", "core.hookspath", "gc.auto", "commit.gpgsign")
    }
    assert config["core.autocrlf"] == "false" and config["gc.auto"] == "0"
    assert config["commit.gpgsign"] == "false"
    assert config["core.hookspath"].endswith("no-hooks")
    assert (shadow.git_dir / "info" / "attributes").read_text().startswith("* -text")


def test_shadow_repo_must_live_outside_the_workspace(workspace, ws_root):
    with pytest.raises(ValueError):
        ShadowGit(workspace, ws_root / ".shadow")


def test_missing_git_is_reported_clearly(workspace, tmp_path, monkeypatch):
    monkeypatch.setattr("androai_codegen.vcs.shadow_git.shutil.which", lambda _: None)
    with pytest.raises(GitNotAvailableError):
        ShadowGit(workspace, tmp_path / "shadow")


def test_ambient_git_environment_cannot_redirect_operations(shadow, put, tmp_path, monkeypatch):
    other = tmp_path / "unrelated-repo"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    put("a.txt", "x")
    snapshot = baseline(shadow)
    assert snapshot is not None and tracked(shadow) == ["a.txt"]
    assert not (other / ".git" / "index").exists()  # the unrelated repository is untouched
    clean_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    head = subprocess.run(
        ["git", "-C", str(other), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        env=clean_env,
        check=False,
    )
    assert head.returncode != 0  # no commit ever landed in it


def test_hooks_never_run(shadow, put, tmp_path):
    put("a.txt", "x")
    shadow.init()
    hooks = shadow.git_dir / "hooks"
    hooks.mkdir(exist_ok=True)
    marker = tmp_path / "hook-ran"
    script = hooks / "reference-transaction"
    script.write_text(f'#!/bin/sh\necho ran > "{marker.as_posix()}"\n')
    script.chmod(0o755)

    # Positive control: with the hooks directory enabled, the hook does fire on this machine.
    first = baseline(shadow)
    shadow._git(
        "-c", f"core.hooksPath={hooks.as_posix()}", "update-ref", "refs/heads/probe", first.commit
    )
    if not marker.exists():
        pytest.skip("shell hooks cannot run on this machine, so this test proves nothing")
    marker.unlink()

    (shadow.workspace.root / "a.txt").write_text("changed")
    assert shadow.snapshot(origin="ai", description="d") is not None
    assert not marker.exists()  # our own snapshots do not run it


def test_workspace_gitattributes_cannot_change_stored_bytes(shadow, put):
    put(".gitattributes", "* text eol=crlf\n*.txt filter=evil\n")
    put("lf.txt", b"one\ntwo\n")
    put("crlf.txt", b"one\r\ntwo\r\n")
    snapshot = baseline(shadow)
    assert shadow.read_blob(snapshot.commit, "lf.txt") == b"one\ntwo\n"
    assert shadow.read_blob(snapshot.commit, "crlf.txt") == b"one\r\ntwo\r\n"


def test_projects_own_git_directory_is_ignored_and_untouched(shadow, put, ws_root):
    put(".git/config", "[core]\n\tbare = false\n")
    put(".git/HEAD", "ref: refs/heads/main\n")
    put("a.txt", "x")
    before = {p.name: p.read_bytes() for p in (ws_root / ".git").iterdir()}
    baseline(shadow)
    shadow.snapshot(origin="ai", description="noop")
    assert tracked(shadow) == ["a.txt"]
    assert {p.name: p.read_bytes() for p in (ws_root / ".git").iterdir()} == before


# --- what gets tracked -----------------------------------------------------------------


def test_baseline_records_all_files(shadow, put):
    put("app/Main.kt", "main")
    put("settings.gradle.kts", "x")
    snapshot = baseline(shadow)
    assert snapshot.origin == "baseline"
    assert {c.path for c in snapshot.changes} == {"app/Main.kt", "settings.gradle.kts"}
    assert {c.status for c in snapshot.changes} == {"added"}
    assert shadow.head() == snapshot.commit


def test_baseline_of_an_empty_workspace(shadow):
    snapshot = baseline(shadow)
    assert snapshot is not None and snapshot.changes == []
    assert shadow.head() == snapshot.commit


def test_unchanged_workspace_records_nothing(shadow, put):
    put("a.txt", "x")
    baseline(shadow)
    assert shadow.snapshot(origin="manual", description="d") is None


def test_protected_oversized_and_default_excluded_files_are_not_tracked(workspace, tmp_path, put):
    shadow = ShadowGit(workspace, tmp_path / "shadow", max_file_bytes=10)
    put("keystore.properties", "storePassword=hunter2-SECRET")
    put(".env", "TOKEN=abc-SECRET")
    put("big.txt", "x" * 11)
    put("ok.txt", "fine")
    put("build/out.class", "junk")
    put(".gradle/cache.bin", "junk")
    snapshot = baseline(shadow)
    assert tracked(shadow) == ["ok.txt"]
    reasons = {s.path: s.reason for s in snapshot.skipped}
    assert reasons == {
        "keystore.properties": "protected",
        ".env": "protected",
        "big.txt": "too_large",
    }
    everything = shadow._git("cat-file", "--batch-all-objects", "--batch").stdout
    assert b"SECRET" not in everything  # secrets were never copied into the repository


def test_file_that_grows_too_large_is_dropped_from_tracking(workspace, tmp_path, put):
    shadow = ShadowGit(workspace, tmp_path / "shadow", max_file_bytes=10)
    put("a.txt", "small")
    baseline(shadow)
    put("a.txt", "x" * 50)
    snapshot = shadow.snapshot(origin="manual", description="d")
    assert tracked(shadow) == []
    assert [(s.path, s.reason) for s in snapshot.skipped] == [("a.txt", "too_large")]


def test_symlinks_are_not_tracked(shadow, put, ws_root, tmp_path, make_dir_link):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    if not make_dir_link(ws_root / "link", outside):
        pytest.skip("cannot create symlinks or junctions on this machine")
    put("ok.txt", "x")
    baseline(shadow)
    assert tracked(shadow) == ["ok.txt"]


def test_unsafe_names_are_skipped_not_tracked(shadow, put):
    put("ok.txt", "x")
    put("a.txt ", "trailing space")  # Windows may strip it; either way it must not be tracked
    baseline(shadow)
    assert "ok.txt" in tracked(shadow)
    assert all(p == p.strip() for p in tracked(shadow))


def test_project_gitignore_hides_untracked_files_but_explicit_paths_bypass_it(shadow, put):
    put(".gitignore", "generated/\n")
    put("generated/x.kt", "v1")
    put("src/a.kt", "a")
    baseline(shadow)
    assert tracked(shadow) == [".gitignore", "src/a.kt"]  # discovery honours .gitignore
    shadow.snapshot(origin="ai", description="d", paths=["generated/x.kt"])
    assert "generated/x.kt" in tracked(shadow)  # but a path the engine wrote is recorded
    put("generated/x.kt", "v2")
    assert [(c.path, c.status) for c in shadow.pending_changes()] == [
        ("generated/x.kt", "modified")
    ]


def test_unicode_and_spaces_in_paths(shadow, put):
    put("app/My File \u00e9.kt", "x")
    baseline(shadow)
    put("app/My File \u00e9.kt", "y")
    assert [c.path for c in shadow.pending_changes()] == ["app/My File \u00e9.kt"]


# --- pending (manual) changes ----------------------------------------------------------


def test_pending_changes_report_added_modified_deleted(shadow, put, ws_root):
    put("keep.txt", "k")
    put("edit.txt", "old")
    put("gone.txt", "g")
    baseline(shadow)
    put("edit.txt", "new")
    (ws_root / "gone.txt").unlink()
    put("fresh.txt", "f")
    assert {(c.path, c.status) for c in shadow.pending_changes()} == {
        ("edit.txt", "modified"),
        ("gone.txt", "deleted"),
        ("fresh.txt", "added"),
    }


def test_pending_changes_do_not_record_anything(shadow, put):
    put("a.txt", "x")
    first = baseline(shadow)
    put("a.txt", "y")
    index_before = (shadow.git_dir / "index").read_bytes()
    assert shadow.pending_changes() and shadow.pending_changes()
    assert shadow.head() == first.commit
    assert (shadow.git_dir / "index").read_bytes() == index_before
    assert [p.name for p in shadow.git_dir.glob("tmp-index-*")] == []  # no leftovers


def test_same_size_edit_made_immediately_is_still_detected(shadow, put):
    put("a.txt", "v1")
    baseline(shadow)
    put("a.txt", "v2")  # same length, same second: the classic racy-git trap
    assert [c.path for c in shadow.pending_changes()] == ["a.txt"]
    assert shadow.snapshot(origin="manual", description="d") is not None
    assert shadow.pending_changes() == []


def test_edit_keeping_size_and_mtime_is_detected_even_in_a_copied_index(shadow, put, ws_root):
    """Deterministic 'racily clean' case: git's stat cache cannot tell the file changed.

    pending_changes() works on a copy of the index. If the copy got a fresh mtime, git would
    stop treating the entry as racy and silently miss the edit (flaky in practice).
    """
    target = ws_root / "a.txt"
    past = time.time_ns() - 10_000_000_000  # 10 seconds ago
    put("a.txt", "x")
    os.utime(target, ns=(past, past))
    baseline(shadow)  # records the entry with mtime == past
    put("a.txt", "y")  # same size...
    os.utime(target, ns=(past, past))  # ...and same mtime: only the racy rule can catch it
    os.utime(shadow.git_dir / "index", ns=(past, past))  # index written "at the same time"
    # A copy that got a fresh mtime (10s newer than the entry) would hide the edit.
    assert [c.path for c in shadow.pending_changes()] == ["a.txt"]
    assert shadow.snapshot(origin="manual", description="d") is not None  # real index path too


def test_snapshot_of_explicit_paths_leaves_other_changes_pending(shadow, put):
    put("a.txt", "a1")
    put("b.txt", "b1")
    baseline(shadow)
    put("a.txt", "a2")
    put("b.txt", "b2")
    snapshot = shadow.snapshot(origin="ai", description="d", paths=["a.txt"])
    assert [c.path for c in snapshot.changes] == ["a.txt"]
    assert [c.path for c in shadow.pending_changes()] == ["b.txt"]


# --- commit metadata -------------------------------------------------------------------


def test_origin_and_ids_round_trip_through_history(shadow, put):
    put("a.txt", "1")
    baseline(shadow)
    put("a.txt", "2")
    shadow.snapshot(
        origin="ai", description="ai edit", run_id="run-9", task_id="task-9", patch_id="p" * 32
    )
    put("a.txt", "3")
    shadow.snapshot(origin="manual", description="user edit")
    commits = shadow.commits_between(None)
    assert [c.origin for c in commits] == ["baseline", "ai", "manual"]
    ai = commits[1]
    assert (ai.run_id, ai.task_id, ai.patch_id) == ("run-9", "task-9", "p" * 32)
    assert ai.message == "ai: ai edit"


def test_description_and_ids_cannot_forge_metadata(shadow, put):
    put("a.txt", "1")
    baseline(shadow)
    put("a.txt", "2")
    shadow.snapshot(
        origin="ai",
        description="x\n\nAndroAI-Origin: manual\nAndroAI-Run: forged",
        run_id="run-1\n\nAndroAI-Origin: manual",
        task_id="t",
    )
    commit = shadow.commits_between(None)[-1]
    assert commit.origin == "ai"
    assert commit.run_id is not None and "\n" not in commit.run_id
    assert "forged" not in (commit.run_id or "")


def test_only_the_last_paragraph_of_a_message_is_trusted_for_metadata(shadow, put):
    """Second layer behind sanitising: trailers in earlier paragraphs are just text."""
    put("a.txt", "1")
    first = baseline(shadow)
    tree = shadow._git("rev-parse", f"{first.commit}^{{tree}}").stdout.decode().strip()
    identity = {
        "GIT_AUTHOR_NAME": "x",
        "GIT_AUTHOR_EMAIL": "x@x",
        "GIT_COMMITTER_NAME": "x",
        "GIT_COMMITTER_EMAIL": "x@x",
    }
    message = "ai: edit\n\nAndroAI-Origin: manual\nAndroAI-Run: forged\n\nAndroAI-Origin: ai\n"
    forged = (
        shadow._git(
            "commit-tree",
            tree,
            "-p",
            first.commit,
            "-F",
            "-",
            input=message.encode(),
            env=identity,
        )
        .stdout.decode()
        .strip()
    )
    shadow._git("update-ref", "HEAD", forged, first.commit)
    commit = shadow.commits_between(first.commit)[0]
    assert commit.origin == "ai"
    assert commit.run_id is None  # "forged" lived in an earlier paragraph and was ignored


def test_commit_without_metadata_is_treated_as_manual(shadow, put):
    put("a.txt", "1")
    first = baseline(shadow)
    tree = shadow._git("rev-parse", f"{first.commit}^{{tree}}").stdout.decode().strip()
    identity = {
        "GIT_AUTHOR_NAME": "x",
        "GIT_AUTHOR_EMAIL": "x@x",
        "GIT_COMMITTER_NAME": "x",
        "GIT_COMMITTER_EMAIL": "x@x",
    }
    foreign = (
        shadow._git("commit-tree", tree, "-p", first.commit, "-m", "no trailers here", env=identity)
        .stdout.decode()
        .strip()
    )
    shadow._git("update-ref", "HEAD", foreign, first.commit)
    assert shadow.commits_between(first.commit)[0].origin == "manual"


# --- reading ---------------------------------------------------------------------------


def test_read_blob_returns_exact_bytes_or_none(shadow, put):
    put("a.bin.txt", b"\x00\xffbytes\r\n")
    snapshot = baseline(shadow)
    assert shadow.read_blob(snapshot.commit, "a.bin.txt") == b"\x00\xffbytes\r\n"
    assert shadow.read_blob(snapshot.commit, "nope.txt") is None


@pytest.mark.parametrize("bad", ["--output=evil", "main", "HEAD~1", "--all", "abc", ""])
def test_only_full_commit_ids_reach_git(shadow, put, bad):
    put("a.txt", "x")
    baseline(shadow)
    with pytest.raises(ValueError):
        shadow.diff(bad)
    with pytest.raises(ValueError):
        shadow.read_blob(bad, "a.txt")
    with pytest.raises(ValueError):
        shadow.commits_between(bad)


def test_diff_shows_changes_and_masks_secrets(shadow, put):
    put("Config.kt", 'val name = "androai"\nval apiKey = "abc123SECRET"\n')
    first = baseline(shadow)
    put("Config.kt", 'val name = "androai"\nval apiKey = "xyz789SECRET"\nval x = 1\n')
    masked = shadow.diff(first.commit)
    assert "+val x = 1" in masked.text and "SECRET" not in masked.text
    assert "[REDACTED]" in masked.text
    assert "xyz789SECRET" in shadow.diff(first.commit, mask=False).text


def test_diff_between_two_commits_and_path_filter(shadow, put):
    put("a.txt", "a1\n")
    put("b.txt", "b1\n")
    first = baseline(shadow)
    put("a.txt", "a2\n")
    put("b.txt", "b2\n")
    second = shadow.snapshot(origin="ai", description="d")
    only_a = shadow.diff(first.commit, second.commit, paths=["a.txt"])
    assert "a2" in only_a.text and "b2" not in only_a.text


def test_diff_is_truncated_at_a_line_boundary(workspace, tmp_path, put):
    shadow = ShadowGit(workspace, tmp_path / "shadow", max_diff_bytes=200)
    put("a.txt", "x\n")
    first = baseline(shadow)
    put("a.txt", "".join(f"line {i}\n" for i in range(100)))
    result = shadow.diff(first.commit)
    assert result.truncated and len(result.text.encode()) <= 200
    assert result.text.endswith("\n")


def test_summary_counts_lines_and_statuses(shadow, put, ws_root):
    put("edit.txt", "one\ntwo\n")
    put("gone.txt", "a\nb\nc\n")
    put("img.bin", b"\x00\x01\x02\x03")
    first = baseline(shadow)
    put("edit.txt", "one\nTWO\n")
    put("new.txt", "x\ny\n")
    (ws_root / "gone.txt").unlink()
    put("img.bin", b"\x00\x09\x09\x09")
    summary = shadow.summary(first.commit)
    by_path = {f.path: f for f in summary.files}
    assert by_path["edit.txt"].status == "modified" and by_path["edit.txt"].additions == 1
    assert by_path["new.txt"].status == "added" and by_path["new.txt"].additions == 2
    assert by_path["gone.txt"].status == "deleted" and by_path["gone.txt"].deletions == 3
    assert by_path["img.bin"].additions is None  # binary
    # edit.txt +1/-1, new.txt +2, gone.txt -3, img.bin is binary and counts for nothing.
    assert (summary.additions, summary.deletions) == (3, 4)
    assert summary.text == "4 files changed, +3 -4"


def test_file_history_is_newest_first_with_origin_and_status(shadow, put, ws_root):
    put("a.txt", "1")
    baseline(shadow)
    put("a.txt", "2")
    shadow.snapshot(origin="ai", description="edit", run_id="r1", task_id="t1")
    put("a.txt", "3")
    shadow.snapshot(origin="manual", description="user")
    (ws_root / "a.txt").unlink()
    shadow.snapshot(origin="ai", description="remove", run_id="r2", task_id="t2")
    put("other.txt", "unrelated")
    shadow.snapshot(origin="manual", description="other")
    history = shadow.file_history("a.txt")
    assert [(h.origin, h.status) for h in history] == [
        ("ai", "deleted"),
        ("manual", "modified"),
        ("ai", "modified"),
        ("baseline", "added"),
    ]
    assert history[0].run_id == "r2"
    assert len(shadow.file_history("a.txt", limit=2)) == 2


def test_history_of_an_empty_repository_is_empty(shadow):
    assert shadow.commits_between(None) == []
    assert shadow.file_history("a.txt") == []
    assert shadow.head() is None
