"""Local directory import: an exact copy in an isolated workspace, and the source never touched."""

import os
from pathlib import Path

import pytest
from ingest_helpers import (
    generated_project,
    import_dir,
    make_request,
    minimal_project,
    tree_digest,
    workspace_files,
    write_tree,
)

from androai_codegen.ingest import (
    IngestCode,
    IngestLimits,
    IngestRejected,
    LocalDirectorySource,
    SymlinkPolicy,
    import_project,
)
from androai_codegen.ingest import budget as budget_module
from androai_codegen.review import ProjectFiles, ReviewEngine

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file system features")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    return root


@pytest.fixture
def src(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "src", minimal_project())


def as_bytes(files) -> dict[str, bytes]:
    return {rel: (c.encode() if isinstance(c, str) else c) for rel, c in files.items()}


def listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def refuse(tmp_path: Path, data: Path, src: Path, **overrides) -> IngestRejected:
    source_before, data_before = tree_digest(src), listing(data)
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data, **overrides)
    assert listing(data) == data_before  # no project, no staging area, nothing new
    assert tree_digest(src) == source_before  # a refused import does not touch the source either
    return refused.value


def link_or_skip(link: Path, target: Path, *, directory: bool = False, make_dir_link=None) -> None:
    if directory and make_dir_link is not None:
        if not make_dir_link(link, target):
            pytest.skip("cannot create directory links here")
        return
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symbolic links here")


# --- a valid project -------------------------------------------------------------------------


def test_a_generated_android_project_imports_into_an_isolated_workspace(tmp_path, data):
    files = generated_project()
    source = write_tree(tmp_path / "src", files)
    result = import_dir(source, data)

    assert result.project_dir == data / "tenant1" / "proj1"
    assert result.workspace.root == (data / "tenant1" / "proj1" / "workspace").resolve()
    assert workspace_files(result.workspace.root) == as_bytes(files)
    assert result.report.android.detected
    assert result.report.counts.files == len(files)
    assert result.report.source.kind == "local_directory"
    assert result.report.source.fingerprint == result.report.content_fingerprint
    assert result.eligible_for_modification


def test_the_imported_workspace_is_a_faithful_project_the_review_engine_accepts(tmp_path, data):
    result = import_dir(write_tree(tmp_path / "src", generated_project()), data)
    project = ProjectFiles.from_workspace(result.workspace)
    report = ReviewEngine().review(project)
    assert not report.has_blocking, [f.rule for f in report.blocking_findings]


def test_the_original_project_is_unchanged_byte_for_byte(tmp_path, data):
    source = write_tree(tmp_path / "src", generated_project())
    before = tree_digest(source)
    import_dir(source, data)
    assert tree_digest(source) == before  # names, modes, sizes, times and hashes


def test_a_read_only_project_imports_and_stays_read_only(tmp_path, data):
    source = write_tree(tmp_path / "src", minimal_project())
    files = [p for p in source.rglob("*") if p.is_file()]
    for path in files:
        os.chmod(path, 0o444)
    try:
        before = tree_digest(source)
        result = import_dir(source, data)
        assert tree_digest(source) == before
        assert result.report.counts.files == len(files)
    finally:
        for path in files:
            os.chmod(path, 0o644)


def test_the_workspace_never_contains_a_link_and_every_file_is_inside_it(tmp_path, data):
    result = import_dir(write_tree(tmp_path / "src", generated_project()), data)
    root = result.workspace.root
    for path in root.rglob("*"):
        assert not path.is_symlink()
        assert path.resolve().is_relative_to(root)


def test_empty_directories_are_kept(tmp_path, data, src):
    (src / "app/src/main/res/raw").mkdir(parents=True)
    result = import_dir(src, data)
    assert (result.workspace.root / "app/src/main/res/raw").is_dir()


def test_non_ascii_names_import(tmp_path, data, src):
    (src / "app/src/main/res/values").mkdir(parents=True)
    (src / "app/src/main/res/values/strings_é.xml").write_text("<resources/>", encoding="utf-8")
    result = import_dir(src, data)
    assert "app/src/main/res/values/strings_é.xml" in workspace_files(result.workspace.root)


def test_a_second_import_of_the_same_unchanged_source_gives_the_same_fingerprint(
    tmp_path, data, src
):
    first = import_dir(src, data)
    second = import_dir(src, data, project_id="proj2")
    assert first.report.content_fingerprint == second.report.content_fingerprint


# --- what is left out ------------------------------------------------------------------------


def test_vcs_ide_and_build_output_directories_are_not_imported(tmp_path, data):
    files = minimal_project()
    files["build.gradle.kts"] = "plugins {}\n"
    files.update(
        {
            ".git/config": "x",
            ".gradle/cache.bin": b"1",
            ".idea/workspace.xml": "x",
            "build/outputs/app.apk": b"apk",
            "app/build.gradle.kts": "android {}\n",
            "app/build/generated/Gen.kt": "class Gen",
            "node_modules/x/index.js": "x",
            ".DS_Store": b"junk",
            "app/.DS_Store": b"junk",
        }
    )
    source = write_tree(tmp_path / "src", files)
    result = import_dir(source, data)
    got = workspace_files(result.workspace.root)
    assert not any(
        p.startswith((".git/", ".gradle/", ".idea/", "build/", "app/build/", "node_modules/"))
        or p.endswith(".DS_Store")
        for p in got
    )
    assert "build.gradle.kts" in got and "app/build.gradle.kts" in got
    assert result.report.counts.skipped_entries == 8


def test_a_source_package_named_build_is_kept(tmp_path, data):
    files = minimal_project()
    files["app/src/main/java/com/example/build/Info.kt"] = "package com.example.build\n"
    files["docs/build/readme.md"] = (
        "notes"  # no Gradle build file beside it: not an output directory
    )
    result = import_dir(write_tree(tmp_path / "src", files), data)
    got = workspace_files(result.workspace.root)
    assert "app/src/main/java/com/example/build/Info.kt" in got
    assert "docs/build/readme.md" in got


# --- limits ----------------------------------------------------------------------------------


def test_the_file_count_limit_is_exact(tmp_path, data):
    source = write_tree(tmp_path / "src", minimal_project(**{f"app__f{i}": "x" for i in range(7)}))
    assert import_dir(source, data, limits=IngestLimits(max_files=10)).report.counts.files == 10
    (source / "app/extra").write_text("x")
    with pytest.raises(IngestRejected) as refused:
        import_dir(source, data, limits=IngestLimits(max_files=10), project_id="p2")
    assert refused.value.code is IngestCode.TOO_MANY_FILES


def test_the_depth_limit_is_exact(tmp_path, data, src):
    limits = IngestLimits(max_depth=8)
    deep = src / "/".join(["d"] * 7)
    deep.mkdir(parents=True)
    (deep / "x.txt").write_text("x")  # 8 segments
    assert import_dir(src, data, limits=limits)
    (deep / "d").mkdir()
    (deep / "d" / "y.txt").write_text("y")  # 9 segments
    assert refuse(tmp_path, data, src, limits=limits, project_id="p2").code is IngestCode.TOO_DEEP


def test_the_default_depth_limit_refuses_65_segments(tmp_path, data, src):
    path = src
    for i in range(64):
        path = path / f"d{i}"
    path.mkdir(parents=True)
    (path / "x.txt").write_text("x")
    refused = refuse(tmp_path, data, src, limits=IngestLimits(max_path_length=4000))
    assert refused.code is IngestCode.TOO_DEEP


def test_the_per_file_and_total_size_limits_are_exact(tmp_path, data, src):
    base = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
    limits = IngestLimits(max_file_bytes=1000, max_total_bytes=base + 1000)
    (src / "app/a.bin").write_bytes(b"a" * 1000)
    assert import_dir(src, data, limits=limits)
    (src / "app/b.bin").write_bytes(b"b")  # one byte over the total
    assert (
        refuse(tmp_path, data, src, limits=limits, project_id="p2").code
        is IngestCode.TOTAL_SIZE_EXCEEDED
    )
    (src / "app/b.bin").unlink()
    (src / "app/a.bin").write_bytes(b"a" * 1001)  # one byte over the per-file limit
    assert (
        refuse(tmp_path, data, src, limits=limits, project_id="p3").code
        is IngestCode.FILE_TOO_LARGE
    )


def test_the_path_length_limit_is_exact(tmp_path, data, src):
    limits = IngestLimits(max_path_length=50)
    (src / ("app/" + "a" * 46)).write_text("x")  # 50 characters
    assert import_dir(src, data, limits=limits)
    (src / ("app/" + "b" * 47)).write_text("x")
    refused = refuse(tmp_path, data, src, limits=limits, project_id="p2")
    assert refused.code is IngestCode.PATH_TOO_LONG


def test_a_slow_import_is_stopped_by_the_time_limit(tmp_path, data, src):
    clock = iter(range(0, 1000, 10))
    request = make_request(LocalDirectorySource(path=src), data, limits=IngestLimits(max_seconds=5))
    with pytest.raises(IngestRejected) as refused:
        import_project(request, monotonic=lambda: float(next(clock)))
    assert refused.value.code is IngestCode.TIMEOUT
    assert list(data.iterdir()) == []


# --- links and special files -----------------------------------------------------------------


def test_a_file_link_leading_outside_the_project_refuses_the_import(tmp_path, data, src):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link_or_skip(src / "app/link.txt", outside)
    assert refuse(tmp_path, data, src).code is IngestCode.UNSAFE_SYMLINK


def test_a_relative_link_that_climbs_out_of_the_project_refuses_the_import(tmp_path, data, src):
    (tmp_path / "outside.txt").write_text("secret")
    link_or_skip(src / "app/link.txt", Path("../../outside.txt"))
    assert refuse(tmp_path, data, src).code is IngestCode.UNSAFE_SYMLINK


def test_a_directory_link_leading_outside_refuses_the_import(tmp_path, data, src, make_dir_link):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("secret")
    link_or_skip(src / "app/ext", outside, directory=True, make_dir_link=make_dir_link)
    assert refuse(tmp_path, data, src).code is IngestCode.UNSAFE_SYMLINK


def test_a_safe_link_inside_the_project_is_skipped_and_reported(tmp_path, data, src):
    link_or_skip(src / "app/link.kts", Path("../settings.gradle.kts"))
    result = import_dir(src, data)
    assert result.report.symlinks_skipped == ["app/link.kts"]
    assert not (result.workspace.root / "app/link.kts").exists()
    assert any("link" in warning for warning in result.report.warnings)


def test_a_policy_can_refuse_every_link(tmp_path, data, src):
    link_or_skip(src / "app/link.kts", Path("../settings.gradle.kts"))
    refused = refuse(tmp_path, data, src, symlinks=SymlinkPolicy.REJECT_ALL)
    assert refused.code is IngestCode.SYMLINK_NOT_ALLOWED


def test_a_link_as_the_source_root_follows_the_policy(tmp_path, data, src):
    root_link = tmp_path / "linked-src"
    link_or_skip(root_link, src)
    assert import_dir(root_link, data).report.counts.files == 3
    refused = refuse(tmp_path, data, root_link, symlinks=SymlinkPolicy.REJECT_ALL, project_id="p2")
    assert refused.code is IngestCode.SOURCE_IS_LINK


@POSIX_ONLY
def test_a_pipe_is_refused(tmp_path, data, src):
    os.mkfifo(src / "app/pipe")
    assert refuse(tmp_path, data, src).code is IngestCode.SPECIAL_FILE


@POSIX_ONLY
def test_an_unreadable_file_refuses_the_import_with_a_clear_error(tmp_path, data, src):
    if os.geteuid() == 0:
        pytest.skip("root can read any file")
    target = src / "app/locked.kt"
    target.write_text("x")
    os.chmod(target, 0)
    try:
        assert refuse(tmp_path, data, src).code is IngestCode.IO_ERROR
    finally:
        os.chmod(target, 0o644)


# --- names the engine cannot represent -------------------------------------------------------


@POSIX_ONLY
@pytest.mark.parametrize("name", ["app/a\\b.kt", "app/aux.txt", "app/trailing.", "app/col:on.kt"])
def test_a_name_the_engine_would_refuse_refuses_the_import(tmp_path, data, src, name):
    (src / name).write_text("x")
    assert refuse(tmp_path, data, src).code is IngestCode.INVALID_PATH


def test_names_that_differ_only_in_case_refuse_the_import(tmp_path, data, src):
    (src / "app/Foo.kt").write_text("1")
    (src / "app/foo.kt").write_text("2")
    if len(list((src / "app").glob("[Ff]oo.kt"))) < 2:
        pytest.skip("this file system is case-insensitive")
    assert refuse(tmp_path, data, src).code is IngestCode.NAME_COLLISION


# --- the request -----------------------------------------------------------------------------


def test_a_missing_source_or_a_file_is_not_a_project(tmp_path, data):
    with pytest.raises(IngestRejected) as missing:
        import_dir(tmp_path / "nope", data)
    assert missing.value.code is IngestCode.SOURCE_NOT_FOUND
    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(IngestRejected) as not_dir:
        import_dir(file, data)
    assert not_dir.value.code is IngestCode.SOURCE_NOT_DIRECTORY


def test_a_source_inside_the_data_root_is_refused(tmp_path):
    data = tmp_path / "data"
    inside = write_tree(data / "other", minimal_project())
    with pytest.raises(IngestRejected) as refused:
        import_dir(inside, data)
    assert refused.value.code is IngestCode.SOURCE_OVERLAPS_DATA_ROOT


def test_a_source_that_contains_the_data_root_is_refused(tmp_path):
    source = write_tree(tmp_path / "src", minimal_project())
    data = source / "data"
    data.mkdir()
    with pytest.raises(IngestRejected) as refused:
        import_dir(source, data)
    assert refused.value.code is IngestCode.SOURCE_OVERLAPS_DATA_ROOT
    assert list(data.iterdir()) == []


def test_something_that_is_not_an_android_project_is_refused_unless_allowed(tmp_path, data):
    source = write_tree(tmp_path / "src", {"README.md": "hello", "script.py": "print(1)"})
    refused = refuse(tmp_path, data, source)
    assert refused.code is IngestCode.NOT_AN_ANDROID_PROJECT
    result = import_dir(source, data, require_android_project=False)
    assert not result.report.android.detected


def test_a_subfolder_of_a_project_is_not_mistaken_for_the_project(tmp_path, data, src):
    refused = refuse(tmp_path, data, src / "app")
    assert refused.code is IngestCode.NOT_AN_ANDROID_PROJECT


# --- the source is checked again at the end --------------------------------------------------


def _mutate_after_first_copy(monkeypatch, src: Path, mutate) -> None:
    original = budget_module.ImportBudget.copy
    state = {"done": False}

    def wrapper(self, source, target, **kwargs):
        result = original(self, source, target, **kwargs)
        if not state["done"]:
            state["done"] = True
            mutate(src / kwargs["path"])
        return result

    monkeypatch.setattr(budget_module.ImportBudget, "copy", wrapper)


def test_a_file_that_grows_during_the_import_is_detected(tmp_path, data, src, monkeypatch):
    def grow(path: Path) -> None:
        with open(path, "ab") as handle:
            handle.write(b"more")

    _mutate_after_first_copy(monkeypatch, src, grow)
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data)
    assert refused.value.code is IngestCode.SOURCE_CHANGED
    assert list(data.iterdir()) == []


def test_a_same_size_edit_with_the_old_modification_time_is_caught_by_the_re_read(
    tmp_path, data, src, monkeypatch
):
    def sneaky(path: Path) -> None:
        info = path.stat()
        raw = bytearray(path.read_bytes())
        raw[0] ^= 0x01  # same size, different content
        path.write_bytes(bytes(raw))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))  # and the time is put back

    _mutate_after_first_copy(monkeypatch, src, sneaky)
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data)
    assert refused.value.code is IngestCode.SOURCE_CHANGED


def test_a_file_added_during_the_import_is_detected(tmp_path, data, src, monkeypatch):
    _mutate_after_first_copy(monkeypatch, src, lambda _path: (src / "late.txt").write_text("new"))
    with pytest.raises(IngestRejected) as refused:
        import_dir(src, data)
    assert refused.value.code is IngestCode.SOURCE_CHANGED


def test_the_re_read_can_be_turned_off(tmp_path, data, src, monkeypatch):
    def grow(path: Path) -> None:
        with open(path, "ab") as handle:
            handle.write(b"more")

    _mutate_after_first_copy(monkeypatch, src, grow)
    assert import_dir(src, data, verify_source=False).report.counts.files == 3
