"""Reviewing the workspace against a checkpoint (needs git on PATH, like the other vcs tests)."""

from sample_project import MAIN, good_project

from androai_codegen.editing import DeleteFile, ModifyFile, TextEdit
from androai_codegen.review import ReviewConfig, project_at_checkpoint, review_since_checkpoint
from androai_codegen.review.project import ProjectFiles

MANIFEST = "app/src/main/AndroidManifest.xml"
UNIT_TEST = "app/src/test/java/com/example/todo/ExampleUnitTest.kt"
INTERNET = '    <uses-permission android:name="android.permission.INTERNET" />\n'


def materialize(put, files=None):
    return {path: put(path, content) for path, content in (files or good_project()).items()}


def rules(report):
    return sorted(f.rule for f in report.findings)


def drop_internet(make_patch, sums):
    return make_patch(
        ModifyFile(
            path=MANIFEST,
            expected_checksum=sums[MANIFEST],
            edits=[TextEdit(old=INTERNET, new="")],
            description="remove the permission",
        )
    )


def test_nothing_changed_since_the_checkpoint_means_nothing_to_report(manager, put):
    materialize(put)
    checkpoint = manager.checkpoint("start")
    report = review_since_checkpoint(manager, checkpoint.id)
    assert report.findings == [] and report.preexisting_suppressed == 0


def test_what_the_patches_since_the_checkpoint_changed_is_reported(manager, put, make_patch):
    sums = materialize(put)
    checkpoint = manager.checkpoint("start")
    manager.apply(drop_internet(make_patch, sums))
    manager.apply(
        make_patch(
            DeleteFile(path=UNIT_TEST, expected_checksum=sums[UNIT_TEST], description="drop test")
        ),
        approved_deletions=[UNIT_TEST],
    )
    report = review_since_checkpoint(manager, checkpoint.id)
    assert rules(report) == [
        "change.permission_removed",
        "change.tests_removed",
        "manifest.permission_missing",
    ]


def test_edits_nobody_recorded_are_part_of_the_review(manager, put, ws_root):
    materialize(put)
    checkpoint = manager.checkpoint("start")
    manifest = ws_root / MANIFEST
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(INTERNET, ""), encoding="utf-8"
    )
    assert "change.permission_removed" in rules(review_since_checkpoint(manager, checkpoint.id))


def test_problems_that_were_already_there_are_not_blamed_on_what_came_after(
    manager, put, make_patch
):
    broken = good_project()
    broken[MANIFEST] = broken[MANIFEST].replace("@style/Theme.Todo", "@style/Theme.Nope")
    sums = materialize(put, broken)
    checkpoint = manager.checkpoint("start")
    manager.apply(
        make_patch(
            ModifyFile(
                path=f"{MAIN}/data/Task.kt",
                expected_checksum=sums[f"{MAIN}/data/Task.kt"],
                edits=[TextEdit(old="val done: Boolean = false", new="val done: Boolean = true")],
                description="unrelated edit",
            )
        )
    )
    report = review_since_checkpoint(manager, checkpoint.id)
    assert report.findings == [] and report.preexisting_suppressed >= 1


def test_the_project_is_rebuilt_exactly_as_it_was_at_the_checkpoint(
    manager, put, make_patch, ws_root
):
    sums = materialize(put)
    original = ProjectFiles.from_mapping(good_project())
    checkpoint = manager.checkpoint("start")
    manager.apply(drop_internet(make_patch, sums))
    manager.apply(
        make_patch(
            DeleteFile(path=UNIT_TEST, expected_checksum=sums[UNIT_TEST], description="drop test")
        ),
        approved_deletions=[UNIT_TEST],
    )
    (ws_root / f"{MAIN}/New.kt").write_text("package com.example.todo\n", encoding="utf-8")
    now = ProjectFiles.from_workspace(
        manager.engine.workspace, protection=manager.engine.protection
    )
    then = project_at_checkpoint(manager, checkpoint.id, now)
    assert dict(then.texts) == dict(original.texts)
    assert f"{MAIN}/New.kt" not in then.paths  # created after the checkpoint
    assert then.other_paths == original.other_paths  # images are present by name


def test_a_review_since_a_checkpoint_honours_the_config(manager, put, make_patch):
    sums = materialize(put)
    checkpoint = manager.checkpoint("start")
    manager.apply(drop_internet(make_patch, sums))
    config = ReviewConfig(disabled_rules=frozenset({"change.permission_removed"}))
    assert "change.permission_removed" not in rules(
        review_since_checkpoint(manager, checkpoint.id, config=config)
    )
