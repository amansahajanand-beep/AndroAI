"""Analysis of imported projects (M1a), of generated projects, and of the review engine's sample."""

from __future__ import annotations

from pathlib import Path

from analysis_fixtures import (
    GOOGLE_KEY,
    analyse,
    edges,
    fact,
    hilt_project,
    ids,
    no_errors,
)
from ingest_helpers import (
    generated_project,
    import_archive,
    import_dir,
    project_zip,
    tree_digest,
    write_tree,
)
from sample_project import FILES as SAMPLE_FILES

from androai_codegen.analysis import analyse_import, analyse_mapping, analyse_workspace


def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir(exist_ok=True)
    return root


def test_a_directory_import_is_analysed_like_the_same_files_in_memory(tmp_path: Path):
    files = hilt_project()
    result = import_dir(write_tree(tmp_path / "src", files), data_root(tmp_path))
    report = analyse_import(result)
    no_errors(report)
    memory = analyse(files)
    assert report.facts == memory.facts
    assert report.relationships == memory.relationships
    assert report.complete is True


def test_a_zip_import_is_analysed_the_same_way(tmp_path: Path):
    files = hilt_project()
    archive = project_zip(tmp_path / "proj.zip", files, root="notes-main")
    result = import_archive(archive, data_root(tmp_path))
    report = analyse_import(result)
    assert report.facts == analyse(files).facts
    assert report.fingerprint == analyse_import(result).fingerprint  # and again


def test_analysing_an_import_leaves_the_imported_project_untouched(tmp_path: Path):
    result = import_dir(write_tree(tmp_path / "src", hilt_project()), data_root(tmp_path))
    before = tree_digest(result.project_dir)
    source_before = tree_digest(tmp_path / "src")
    analyse_import(result)
    assert tree_digest(result.project_dir) == before
    assert tree_digest(tmp_path / "src") == source_before


def test_secret_bearing_files_the_import_protected_are_not_read_by_the_analysis(tmp_path: Path):
    files = hilt_project()
    files["local.properties"] = "sdk.dir=/sdk\napi.key=abc123secret\n"
    files["app/src/main/java/com/example/notes/Keys.kt"] = (
        "package com.example.notes\n"
        "object Keys {\n"
        '    val pem = """-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"""\n'
        "}\n"
    )
    result = import_dir(write_tree(tmp_path / "src", files), data_root(tmp_path))
    assert "app/src/main/java/com/example/notes/Keys.kt" in {
        p.lower() for p in result.protection.extra_paths
    } or result.protection.is_protected("app/src/main/java/com/example/notes/Keys.kt")
    report = analyse_import(result)
    protected = {m.scope for m in report.limitations if m.code == "protected_not_read"}
    assert "local.properties" in protected
    assert "app/src/main/java/com/example/notes/Keys.kt" in protected
    assert "type:com.example.notes.Keys" not in {f.id for f in report.facts}
    text = report.model_dump_json()
    assert "MIIEvQIB" not in text and "abc123secret" not in text


def test_the_generators_own_project_is_read_exactly():
    report = analyse_mapping(generated_project())
    no_errors(report)
    assert report.complete is True
    assert ids(report, "compose_route") == ["about", "home", "settings"]
    assert fact(report, "compose_route:home").attributes["start_destination"] is True
    assert len(ids(report, "compose_screen")) == 3
    assert all(
        fact(report, f"compose_screen:{s}").status == "confirmed"
        for s in ids(report, "compose_screen")
    )
    nav = edges(report, "navigates_to")
    assert ("compose_route:home", "compose_route:about") in nav
    assert ("compose_route:home", "compose_route:settings") in nav
    assert len(edges(report, "renders")) == 3
    assert fact(report, "module:app").attributes["type"] == "android_application"
    activity = fact(report, "activity:com.example.notes.MainActivity")
    assert (
        activity.attributes["launcher"] is True
        and activity.attributes["base"] == "ComponentActivity"
    )
    hosts = edges(report, "hosts_content")
    assert any(s == "type:com.example.notes.MainActivity" and "AppNavHost" in t for s, t in hosts)
    assert report.fingerprint == analyse_mapping(generated_project()).fingerprint


def test_the_generators_project_has_the_same_facts_when_read_from_disk(tmp_path: Path):
    files = generated_project()
    root = write_tree(tmp_path / "proj", files)
    from androai_codegen.editing.workspace import Workspace

    assert analyse_workspace(Workspace(root)).fingerprint == analyse_mapping(files).fingerprint


def test_the_review_engines_known_good_sample_is_read_correctly():
    report = analyse_mapping(SAMPLE_FILES)
    no_errors(report)
    assert report.complete is True
    assert ids(report, "activity") == ["com.example.todo.MainActivity"]
    assert fact(report, "activity:com.example.todo.MainActivity").attributes["launcher"] is True
    assert ids(report, "room_database") == ["com.example.todo.data.AppDatabase"]
    assert ids(report, "retrofit_service") == ["com.example.todo.data.Api"]
    assert ids(report, "compose_route") == ["add", "list"]
    assert fact(report, "compose_route:list").attributes["start_destination"] is True
    assert ids(report, "viewmodel") == ["com.example.todo.ui.TodoViewModel"]
    assert len(ids(report, "compose_screen")) == 2


def test_the_key_planted_in_the_manifest_never_reaches_a_report_read_from_an_import(tmp_path: Path):
    result = import_dir(write_tree(tmp_path / "src", hilt_project()), data_root(tmp_path))
    assert GOOGLE_KEY not in analyse_import(result).model_dump_json()
