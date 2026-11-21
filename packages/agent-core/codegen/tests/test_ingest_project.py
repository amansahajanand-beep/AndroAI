"""The isolated project, its report and attestation, cleanup, and "nothing is executed"."""

import ast
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingest_helpers import (
    generated_project,
    import_dir,
    make_request,
    minimal_project,
    project_zip,
    tree_digest,
    workspace_files,
    write_tree,
)
from pydantic import ValidationError

import androai_codegen.ingest as ingest_package
from androai_codegen.editing import ModifyFile, PatchSet
from androai_codegen.editing.errors import PathValidationError
from androai_codegen.ingest import (
    ImportRequest,
    IngestCode,
    IngestRejected,
    IngestReport,
    LocalDirectorySource,
    OwnershipAttestation,
    ZipSource,
    import_project,
    reopen_import,
)
from androai_codegen.ingest import importer as importer_module
from androai_codegen.ingest import layout as layout_module


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    return root


@pytest.fixture
def src(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "src", minimal_project())


def listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


# --- the layout ------------------------------------------------------------------------------


def test_the_project_has_a_workspace_a_journal_and_a_report_side_by_side(data, src):
    result = import_dir(src, data)
    project = data / "tenant1" / "proj1"
    assert sorted(p.name for p in project.iterdir()) == ["imports", "journal", "workspace"]
    assert result.report_path == project / "imports" / result.report.import_id / "report.json"
    assert IngestReport.model_validate_json(result.report_path.read_text("utf-8")) == result.report
    assert not result.journal_dir.is_relative_to(result.workspace.root)
    assert not result.workspace.root.is_relative_to(result.journal_dir)


def test_no_staging_area_is_left_after_success(data, src):
    import_dir(src, data)
    assert not [p for p in data.iterdir() if p.name.startswith(".staging")]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_the_project_directory_is_private_to_its_owner(data, src):
    import_dir(src, data)
    assert (data / "tenant1" / "proj1").stat().st_mode & 0o077 == 0


def test_the_patch_engine_opens_the_imported_project_and_edits_only_the_copy(tmp_path, data, src):
    before = tree_digest(src)
    result = import_dir(src, data)
    engine = result.open_engine()
    main = "app/src/main/java/com/example/demo/Main.kt"
    snapshot = engine.read_file(main)
    patch = PatchSet(
        project_id="proj1",
        run_id="r1",
        task_id="t1",
        description="edit the copy",
        changes=[
            ModifyFile(
                path=main,
                expected_checksum=snapshot.checksum,
                content=snapshot.content + "\nclass Added\n",
                description="add a class",
            )
        ],
    )
    engine.apply(patch)
    assert "class Added" in (result.workspace.root / main).read_text("utf-8")
    assert tree_digest(src) == before  # the original is not the workspace


def test_the_engine_refuses_paths_outside_the_workspace(data, src):
    engine = import_dir(src, data).open_engine()
    with pytest.raises(PathValidationError):
        engine.read_file("../../tenant2/proj/workspace/secret")


# --- isolation between projects and tenants --------------------------------------------------


def test_two_tenants_may_use_the_same_project_id_without_seeing_each_other(tmp_path, data):
    a = import_dir(
        write_tree(tmp_path / "a", minimal_project(app__only_a="A")), data, tenant_id="ta"
    )
    b = import_dir(
        write_tree(tmp_path / "b", minimal_project(app__only_b="B")), data, tenant_id="tb"
    )
    assert "app/only_a" in workspace_files(a.workspace.root)
    assert "app/only_a" not in workspace_files(b.workspace.root)
    assert "app/only_b" not in workspace_files(a.workspace.root)
    assert a.workspace.root != b.workspace.root and a.journal_dir != b.journal_dir
    with pytest.raises(PathValidationError):
        a.open_engine().read_file("../../../tb/proj1/workspace/app/only_b")


def test_importing_into_an_existing_project_is_refused_and_leaves_it_alone(tmp_path, data, src):
    first = import_dir(src, data)
    before = tree_digest(first.project_dir)
    listing_before = listing(data)
    with pytest.raises(IngestRejected) as refused:
        import_dir(write_tree(tmp_path / "other", minimal_project(app__x="x")), data)
    assert refused.value.code is IngestCode.PROJECT_EXISTS
    assert tree_digest(first.project_dir) == before and listing(data) == listing_before


def test_a_project_that_appears_during_the_import_is_never_replaced(data, src, monkeypatch):
    real = importer_module.scan_workspace

    def scan_then_create_the_project(*args, **kwargs):
        target = data / "tenant1" / "proj1"
        target.mkdir(parents=True)
        (target / "marker.txt").write_text("someone else's project")
        return real(*args, **kwargs)

    monkeypatch.setattr(importer_module, "scan_workspace", scan_then_create_the_project)
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data)
    assert refused.value.code is IngestCode.PROJECT_EXISTS
    assert listing(data) == ["tenant1", "tenant1/proj1", "tenant1/proj1/marker.txt"]


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "..",
        ".",
        "a/b",
        "a\\b",
        "CON",
        "aux",
        "-x",
        "_x",
        " x",
        "x y",
        "é",
        "a" * 65,
        "a.b",
        "a:b",
    ],
)
@pytest.mark.parametrize("field", ["tenant_id", "project_id"])
def test_an_unsafe_tenant_or_project_id_is_refused(tmp_path, data, src, field, bad):
    with pytest.raises(ValidationError):
        make_request(LocalDirectorySource(path=src), data, **{field: bad})


@pytest.mark.parametrize("good", ["a", "A1", "tenant-1", "proj_2", "x" * 64])
def test_safe_identifiers_are_accepted(tmp_path, data, src, good):
    result = import_dir(src, data, tenant_id=good, project_id=good)
    assert result.report.tenant_id == good


def test_a_missing_data_root_is_refused_and_not_created(tmp_path, src):
    root = tmp_path / "nowhere"
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, root)
    assert refused.value.code is IngestCode.DATA_ROOT_MISSING
    assert not root.exists()


def test_a_data_root_that_is_a_file_is_refused(tmp_path, src):
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, file)
    assert refused.value.code is IngestCode.DATA_ROOT_MISSING


# --- ownership and permission ----------------------------------------------------------------


def test_an_import_cannot_be_requested_without_an_attestation(src, data):
    with pytest.raises(ValidationError):
        ImportRequest(
            source=LocalDirectorySource(path=src), data_root=data, tenant_id="t", project_id="p"
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"basis": "unknown", "statement": "x", "attested_by": "u"},
        {"basis": "own", "statement": "   ", "attested_by": "u"},
        {"basis": "own", "statement": "x\x00y", "attested_by": "u"},
        {"basis": "own", "statement": "x", "attested_by": ""},
        {"basis": "own", "statement": "x" * 501, "attested_by": "u"},
        {"basis": "own", "statement": "x", "attested_by": "u", "extra": 1},
    ],
)
def test_an_invalid_attestation_is_refused(bad):
    with pytest.raises(ValidationError):
        OwnershipAttestation(**bad)


@pytest.mark.parametrize("basis", ["own", "explicit_permission"])
def test_both_kinds_of_confirmation_make_the_import_eligible_and_are_recorded(data, src, basis):
    attestation = OwnershipAttestation(
        basis=basis, statement="The owner agreed in writing.", attested_by="user-7"
    )
    result = import_dir(src, data, attestation=attestation)
    assert result.eligible_for_modification and result.report.eligible_for_modification
    assert result.report.attestation == attestation


def test_a_report_that_is_not_eligible_cannot_be_reopened_for_modification(data, src):
    result = import_dir(src, data)
    document = json.loads(result.report_path.read_text("utf-8"))
    document["eligible_for_modification"] = False
    result.report_path.write_text(json.dumps(document), "utf-8")
    with pytest.raises(IngestRejected) as refused:
        reopen_import(result.project_dir)
    assert refused.value.code is IngestCode.ATTESTATION_REQUIRED


def test_a_report_without_an_attestation_is_not_a_valid_report(data, src):
    result = import_dir(src, data)
    document = json.loads(result.report_path.read_text("utf-8"))
    del document["attestation"]
    result.report_path.write_text(json.dumps(document), "utf-8")
    with pytest.raises(ValidationError):
        reopen_import(result.project_dir)


def test_a_project_can_be_reopened_from_its_report(data, src):
    original = import_dir(src, data)
    reopened = reopen_import(original.project_dir)
    assert reopened.report == original.report
    assert reopened.workspace.root == original.workspace.root
    assert reopened.eligible_for_modification


def test_the_newest_report_is_the_one_a_project_is_reopened_from(data, src):
    original = import_dir(src, data)
    older = json.loads(original.report_path.read_text("utf-8"))
    older["created_at"] = "1999-01-01T00:00:00Z"
    older["import_id"] = "f" * 32  # sorts after the real id, so only the time can decide
    folder = original.project_dir / "imports" / ("f" * 32)
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps(older), "utf-8")
    reopened = reopen_import(original.project_dir)
    assert reopened.report.import_id == original.report.import_id


def test_reopening_a_directory_that_is_not_an_import_is_refused(tmp_path):
    with pytest.raises(IngestRejected) as refused:
        reopen_import(tmp_path)
    assert refused.value.code is IngestCode.SOURCE_NOT_FOUND


# --- the report ------------------------------------------------------------------------------


def test_the_report_says_where_the_code_came_from_without_revealing_local_paths(
    tmp_path, data, src
):
    result = import_dir(src, data)
    text = result.report_path.read_text("utf-8")
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    assert result.report.source.label == "src"
    custom = import_dir(src, data, project_id="p2", label="My Notes App")
    assert custom.report.source.label == "My Notes App"


def test_the_report_records_the_limits_it_was_made_under_and_a_tool_version(data, src):
    report = import_dir(src, data).report
    assert report.limits.max_files == 20_000 and report.limits.max_depth == 64
    assert report.tool.startswith("androai-codegen-ingest/") and report.report_version == 1


def test_the_report_is_deterministic_for_the_same_source(tmp_path, src):
    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    texts = []
    for name in ("d1", "d2"):
        root = tmp_path / name
        root.mkdir()
        result = import_project(
            make_request(LocalDirectorySource(path=src), root, import_id="ab" * 16),
            clock=lambda: fixed,
        )
        texts.append(result.report_path.read_text("utf-8"))
    assert texts[0] == texts[1]


def test_the_report_stays_bounded_whatever_the_input(tmp_path, data):
    files = minimal_project()
    for i in range(300):
        files[f"app/skipme/node_modules/x{i}.js"] = (
            "x"  # excluded: counted, listed only up to a cap
        )
    result = import_dir(write_tree(tmp_path / "src", files), data)
    assert result.report.counts.skipped_entries >= 1
    assert len(result.report.skipped) <= 200


# --- cleanup on failure ----------------------------------------------------------------------


def test_an_unexpected_error_leaves_nothing_behind_and_is_not_swallowed(data, src, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(importer_module, "scan_workspace", boom)
    with pytest.raises(RuntimeError):
        import_dir(src, data)
    assert listing(data) == []


def test_an_interrupted_import_leaves_nothing_behind(data, src, monkeypatch):
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(importer_module, "materialize", interrupted)
    with pytest.raises(KeyboardInterrupt):
        import_dir(src, data)
    assert listing(data) == []


def test_a_failure_while_writing_the_report_leaves_nothing_behind(data, src, monkeypatch):
    monkeypatch.setattr(
        importer_module.Staging,
        "write_report",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        import_dir(src, data)
    assert listing(data) == []


def test_a_new_tenant_directory_does_not_survive_a_refused_import(data, src, monkeypatch):
    def cannot_rename(*_args, **_kwargs):
        raise OSError("simulated: the final move failed")

    monkeypatch.setattr(layout_module.os, "rename", cannot_rename)  # after the tenant is created
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data, tenant_id="brand-new")
    assert refused.value.code is IngestCode.IO_ERROR
    assert listing(data) == []  # neither the staging area nor the empty tenant directory


# --- nothing is executed ---------------------------------------------------------------------

FORBIDDEN_MODULES = {
    "subprocess",
    "multiprocessing",
    "ctypes",
    "runpy",
    "importlib",
    "pty",
    "pickle",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_OS = {
    "system",
    "popen",
    "startfile",
    "execv",
    "execve",
    "execl",
    "execvp",
    "spawnl",
    "spawnv",
}


def test_the_import_code_cannot_start_a_process_or_run_code():
    package_dir = Path(ingest_package.__file__).parent
    problems = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.split(".")[0] in FORBIDDEN_MODULES
                ]
            elif (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] in FORBIDDEN_MODULES
            ):
                problems.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                    problems.append(f"{path.name}: {func.id}()")
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                    and (func.attr in FORBIDDEN_OS or func.attr.startswith(("spawn", "exec")))
                ):
                    problems.append(f"{path.name}: os.{func.attr}()")
    assert problems == []


def test_importing_a_project_full_of_scripts_runs_none_of_them(tmp_path, data, monkeypatch):
    def refuse_to_run(*_args, **_kwargs):
        raise AssertionError("the importer tried to run a program")

    for target in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, target, refuse_to_run)
    monkeypatch.setattr(os, "system", refuse_to_run)
    files = minimal_project()
    files.update(
        {
            "gradlew": "#!/bin/sh\ntouch /tmp/pwned\n",
            "gradlew.bat": "@echo pwned > %TEMP%\\pwned\r\n",
            "gradle/wrapper/gradle-wrapper.jar": b"PK\x03\x04not a real jar",
            "build.gradle.kts": 'Runtime.getRuntime().exec("touch /tmp/pwned")\n',
            "buildSrc/src/main/kotlin/Evil.kt": 'object Evil { init { error("ran") } }\n',
            "app/proguard-rules.pro": "-dontwarn\n",
            "install.sh": "rm -rf /\n",
            "setup.py": "import os; os.system('x')\n",
        }
    )
    for kind, project in (
        ("dir", write_tree(tmp_path / "src", files)),
        ("zip", project_zip(tmp_path / "x.zip", files)),
    ):
        source = LocalDirectorySource(path=project) if kind == "dir" else ZipSource(path=project)
        result = import_project(make_request(source, data, project_id=f"p-{kind}"))
        assert "gradlew" in workspace_files(result.workspace.root)


def test_the_imported_files_keep_their_text_and_are_never_marked_executable(tmp_path, data):
    if os.name == "nt":
        pytest.skip("POSIX permissions")
    source = write_tree(tmp_path / "src", {**minimal_project(), "gradlew": "#!/bin/sh\n"})
    os.chmod(source / "gradlew", 0o755)
    result = import_dir(source, data)
    assert (result.workspace.root / "gradlew").stat().st_mode & 0o111 == 0


def test_generated_projects_import_with_every_file_intact(tmp_path, data):
    files = generated_project()
    result = import_dir(write_tree(tmp_path / "src", files), data)
    got = workspace_files(result.workspace.root)
    assert set(got) == set(files)
    assert all(got[rel] == files[rel].encode() for rel in files)
