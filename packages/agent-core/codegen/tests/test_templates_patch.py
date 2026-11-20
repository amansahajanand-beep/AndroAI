"""Determinism, PatchSet compatibility and compatibility with the static review engine."""

import json
import random
import re

import pytest

from androai_codegen.editing import (
    CreateFile,
    PatchRejected,
    PatchSet,
    ProblemCode,
    ProtectionPolicy,
    normalize_relative_path,
)
from androai_codegen.review import ProjectFiles, ReviewEngine, review_patch
from androai_codegen.templates import (
    ProjectConfig,
    Template,
    TemplateFile,
    TemplateRenderError,
    get_template,
    render_files,
    render_patch,
    render_template,
)
from androai_codegen.templates.renderer import placeholder_values

IDS = {"project_id": "proj-1", "run_id": "run-1", "task_id": "task-1"}
SRC = "app/src/main/java/com/example/notes"


def make(**overrides) -> ProjectConfig:
    base = {"project_name": "Notes App", "package_name": "com.example.notes"}
    base.update(overrides)
    return ProjectConfig(**base)


def patch_of(config: ProjectConfig | None = None, **kwargs) -> PatchSet:
    return render_patch(config or make(), **IDS, **kwargs)


def mapping(config: ProjectConfig | None = None) -> dict[str, str]:
    return {f.path: f.content for f in render_files(config or make())}


# --- determinism ----------------------------------------------------------------------------


def test_rendering_twice_gives_identical_files():
    assert render_files(make()) == render_files(make())


def test_rendering_does_not_depend_on_how_the_config_was_built():
    a = make(application_id="com.acme.Notes", version_code=3)
    b = ProjectConfig.model_validate_json(json.dumps(a.model_dump(mode="json")))
    c = ProjectConfig(**dict(reversed(list(a.model_dump().items()))))
    assert render_files(a) == render_files(b) == render_files(c)


def test_the_patch_is_deterministic_and_sorted():
    first, second = patch_of(), patch_of()
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    paths = [change.path for change in first.changes]
    assert paths == sorted(paths)


def test_the_order_of_the_template_files_does_not_change_the_output():
    template = get_template(make().language, make().ui_toolkit)
    shuffled = list(template.files)
    random.Random(7).shuffle(shuffled)
    other = Template(template.language, template.ui_toolkit, "x", tuple(shuffled))
    values = placeholder_values(make())
    assert render_template(other, values) == render_template(template, values)


def test_output_contains_nothing_from_the_environment():
    # No dates, host or user names, absolute paths or random ids.
    blob = "\n".join(mapping().values())
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", blob)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", blob)
    for needle in ("/Users/", "C:\\", "/home/", "localhost", "DREAMWORLD"):
        assert needle not in blob, needle


def test_a_changed_input_changes_only_the_files_that_use_it():
    base = mapping()
    changed = mapping(make(version_name="2.0"))
    assert {p for p in base if base[p] != changed[p]} == {"app/build.gradle.kts"}
    changed = mapping(make(project_name="Other App"))
    assert {p for p in base if base[p] != changed[p]} >= {"app/src/main/res/values/strings.xml"}
    assert "settings.gradle.kts" in {p for p in base if base[p] != changed[p]}


def test_different_projects_do_not_share_generated_names():
    a, b = mapping(make()), mapping(make(project_name="Tasks", package_name="org.acme.tasks"))
    assert not set(a) & {p for p in b if p.startswith("app/src/main/java")}


# --- PatchSet compatibility -----------------------------------------------------------------


def test_the_patch_creates_every_file_and_nothing_else():
    patch = patch_of()
    assert all(isinstance(change, CreateFile) for change in patch.changes)
    assert {change.path: change.content for change in patch.changes} == mapping()
    assert all(change.description for change in patch.changes)


def test_the_patch_carries_the_ids_and_a_description():
    patch = patch_of()
    assert (patch.project_id, patch.run_id, patch.task_id) == ("proj-1", "run-1", "task-1")
    assert "Notes App" in patch.description
    assert patch_of(description="Bootstrap").description == "Bootstrap"


def test_the_ids_are_validated_by_the_patchset():
    with pytest.raises(ValueError):
        render_patch(make(), project_id="", run_id="r", task_id="t")


def test_every_path_is_already_canonical_and_safe():
    for change in patch_of().changes:
        assert normalize_relative_path(change.path) == change.path
        assert not ProtectionPolicy().is_protected(change.path)


def test_the_patch_stays_inside_the_engine_limits():
    patch = patch_of()
    assert len(patch.changes) <= 500
    assert sum(len(c.content.encode("utf-8")) for c in patch.changes) < 2 * 1024 * 1024


def test_the_patch_previews_cleanly_on_an_empty_workspace(engine):
    preview = engine.preview(patch_of())
    assert preview.ok, preview.problems
    assert {p.change_type for p in preview.planned} == {"create"}
    assert len(preview.planned) == len(render_files(make()))


def test_applying_writes_exactly_the_rendered_bytes(engine, ws_root):
    result = engine.apply(patch_of())
    assert len(result.records) == len(render_files(make()))
    written = {
        p.relative_to(ws_root).as_posix(): p.read_bytes() for p in ws_root.rglob("*") if p.is_file()
    }
    assert written == {path: text.encode("utf-8") for path, text in mapping().items()}
    assert all(b"\r" not in data for data in written.values())


def test_a_project_cannot_be_created_over_an_existing_one(engine):
    engine.apply(patch_of())
    with pytest.raises(PatchRejected) as raised:
        engine.apply(patch_of())
    assert {p.code for p in raised.value.preview.problems} == {ProblemCode.ALREADY_EXISTS}


def test_a_project_is_not_created_over_one_existing_file(engine, ws_root):
    (ws_root / "settings.gradle.kts").write_text("// mine\n", encoding="utf-8")
    with pytest.raises(PatchRejected):
        engine.apply(patch_of())
    # All or nothing: no other file was written.
    assert [p.name for p in ws_root.rglob("*") if p.is_file()] == ["settings.gradle.kts"]
    assert (ws_root / "settings.gradle.kts").read_text(encoding="utf-8") == "// mine\n"


def test_the_created_project_can_be_rolled_back(engine, ws_root):
    applied = engine.apply(patch_of())
    engine.rollback(applied.patch_id)
    assert not [p for p in ws_root.rglob("*") if p.is_file()]


def test_the_project_can_be_created_with_a_checkpoint(manager, ws_root):
    tracked = manager.apply(patch_of())
    assert len(tracked.result.records) == len(render_files(make()))
    assert tracked.ai_snapshot is not None
    assert (ws_root / "app/build.gradle.kts").is_file()


# --- static review compatibility ------------------------------------------------------------


def test_the_rendered_project_has_no_review_findings_at_all():
    report = ReviewEngine().review(ProjectFiles.from_mapping(mapping()))
    assert report.scope == "static"
    assert report.files_reviewed >= 14  # the review really looked at the sources and Gradle files
    assert not report.files_unparsed
    assert report.findings == [], [(f.rule, f.file) for f in report.findings]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"application_id": "com.acme.NotesPro"},
        {"package_name": "org.acme.deep.nested.pkg"},
        {"project_name": "R&D Tracker"},
        {"project_name": "नमस्ते"},
        {"min_sdk": 31, "target_sdk": 37},
        {"min_sdk": 36, "target_sdk": 36},
    ],
)
def test_review_is_clean_for_varied_configs(overrides):
    files = {f.path: f.content for f in render_files(make(**overrides))}
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    assert report.findings == [], [(f.rule, f.file) for f in report.findings]


def test_review_patch_accepts_the_project_before_it_is_applied(engine, ws_root):
    review = review_patch(engine, patch_of())
    assert review.applicable, review.report and review.report.findings
    assert review.report is not None and review.report.findings == []
    # Reviewing writes nothing.
    assert not [p for p in ws_root.rglob("*") if p.is_file()]


def test_review_patch_still_reports_after_the_project_exists(engine):
    engine.apply(patch_of())
    review = review_patch(engine, patch_of())
    assert not review.applicable  # creating over existing files is rejected by the patch layer
    assert review.report is None


# The rules are alive on this project: a breakage in one generated file is found. (If a rule
# stopped analysing this project, the clean result above would mean nothing.)
SENTINELS = [
    (
        "missing import",
        f"{SRC}/MainActivity.kt",
        "import com.example.notes.navigation.AppNavHost\n",
        "",
        "import.missing",
    ),
    (
        "missing string resource",
        "app/src/main/res/values/strings.xml",
        '    <string name="home_message">Your app is ready to build on.</string>\n',
        "",
        "resource.unresolved",
    ),
    (
        "unknown resource name",
        f"{SRC}/ui/home/HomeScreen.kt",
        "R.string.app_name",
        "R.string.nope",
        "resource.unresolved",
    ),
    (
        "manifest names a missing class",
        "app/src/main/AndroidManifest.xml",
        ".MainActivity",
        ".Missing",
        "manifest.class_missing",
    ),
    (
        "launcher activity not exported",
        "app/src/main/AndroidManifest.xml",
        '            android:exported="true">',
        ">",
        "manifest.exported_missing",
    ),
    (
        "unbalanced brackets",
        f"{SRC}/ui/home/HomeScreen.kt",
        "private fun HomeScreenPreview() {",
        "private fun HomeScreenPreview() {{",
        "syntax.unbalanced_brackets",
    ),
    (
        "package does not match the project",
        f"{SRC}/ui/home/HomeScreen.kt",
        "package com.example.notes.ui.home",
        "package com.example.other",
        "import.unresolved_project",
    ),
]


@pytest.mark.parametrize("label, path, old, new, rule", SENTINELS, ids=[s[0] for s in SENTINELS])
def test_the_review_still_catches_a_broken_generated_project(label, path, old, new, rule):
    files = mapping()
    assert old in files[path]
    files[path] = files[path].replace(old, new)
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    assert rule in {f.rule for f in report.findings}, (
        label,
        [(f.rule, f.file) for f in report.findings],
    )


def test_removing_a_generated_file_is_caught_by_the_review():
    files = mapping()
    del files[f"{SRC}/ui/theme/Theme.kt"]
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    assert "import.unresolved_project" in {f.rule for f in report.findings}


def test_a_template_with_an_unknown_placeholder_never_produces_a_patch():
    template = get_template(make().language, make().ui_toolkit)
    broken = Template(
        template.language,
        template.ui_toolkit,
        "broken",
        template.files + (TemplateFile("x.txt", "__UNKNOWN__\n", "d"),),
    )
    with pytest.raises(TemplateRenderError, match="UNKNOWN"):
        render_template(broken, placeholder_values(make()))
