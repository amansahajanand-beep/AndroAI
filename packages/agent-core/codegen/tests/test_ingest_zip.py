"""ZIP import: valid archives import exactly; hostile ones are refused before any write."""

import hashlib
import os
import stat
import warnings
import zipfile
from pathlib import Path

import pytest
from ingest_helpers import (
    entry,
    generated_project,
    import_archive,
    import_dir,
    make_request,
    make_zip,
    minimal_project,
    patch_zip,
    project_zip,
    symlink,
    workspace_files,
    write_tree,
)

from androai_codegen.ingest import (
    IngestCode,
    IngestLimits,
    IngestRejected,
    SymlinkPolicy,
    ZipSource,
    import_project,
)
from androai_codegen.ingest.zip_source import declared_entry_count


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zip_of(tmp_path: Path, entries: list, name: str = "x.zip") -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names are the point of some tests
        return make_zip(tmp_path / name, entries)


def project_entries(**extra) -> list:
    return [(rel, content) for rel, content in minimal_project(**extra).items()]


def refuse(tmp_path: Path, data: Path, archive: Path, **overrides) -> IngestRejected:
    with pytest.raises(IngestRejected) as refused:
        import_archive(archive, data, **overrides)
    assert_nothing_left(tmp_path, data)
    return refused.value


def assert_nothing_left(tmp_path: Path, data: Path) -> None:
    """A refused import leaves no project, no staging area and nothing outside the data root."""
    assert list(data.iterdir()) == []
    extras = {p.name for p in tmp_path.iterdir()} - {"data", "src"}
    assert all(name.endswith(".zip") for name in extras)  # only the archives the test made
    for outside in (tmp_path, tmp_path.parent):
        assert not (outside / "evil.txt").exists()


# --- valid archives --------------------------------------------------------------------------


def test_a_valid_project_zip_imports_into_an_isolated_workspace(tmp_path, data):
    files = generated_project()
    archive = project_zip(tmp_path / "x.zip", files, root="NotesApp-main")
    result = import_archive(archive, data)

    assert result.workspace.root == (data / "tenant1" / "proj1" / "workspace").resolve()
    assert workspace_files(result.workspace.root) == {
        rel: (c.encode() if isinstance(c, str) else c) for rel, c in files.items()
    }
    assert result.report.android.detected
    assert result.report.counts.files == len(files)
    assert result.report.stripped_root == "NotesApp-main"
    assert result.eligible_for_modification


def test_the_archive_is_byte_for_byte_unchanged(tmp_path, data):
    archive = project_zip(tmp_path / "x.zip", generated_project(), root="App")
    before, before_stat = sha(archive), os.stat(archive)
    result = import_archive(archive, data)
    assert sha(archive) == before
    assert os.stat(archive).st_mtime_ns == before_stat.st_mtime_ns
    assert result.report.source.fingerprint == before
    assert result.report.source.fingerprint_of == "archive"


def test_files_keep_their_exact_bytes_including_line_endings_and_bom(tmp_path, data):
    files = minimal_project(
        app__src__Crlf="a\r\nb\r\n",
        app__src__Bom=b"\xef\xbb\xbfhello",
        app__src__Bin=bytes(range(256)),
    )
    result = import_archive(project_zip(tmp_path / "x.zip", files), data)
    got = workspace_files(result.workspace.root)
    assert got["app/src/Crlf"] == b"a\r\nb\r\n"
    assert got["app/src/Bom"] == b"\xef\xbb\xbfhello"
    assert got["app/src/Bin"] == bytes(range(256))


def test_a_zip_and_a_directory_of_the_same_project_have_the_same_content_fingerprint(
    tmp_path, data
):
    files = generated_project()
    from_zip = import_archive(project_zip(tmp_path / "x.zip", files, root="p"), data)
    src = write_tree(tmp_path / "src", files)
    from_dir = import_dir(src, data, project_id="proj2")
    assert from_zip.report.content_fingerprint == from_dir.report.content_fingerprint


@pytest.mark.parametrize(
    ("entries", "stripped"),
    [
        (lambda p: [(f"{p}/{rel}", c) for rel, c in minimal_project().items()], "wrap"),
        (lambda p: [(rel, c) for rel, c in minimal_project().items()], None),
    ],
)
def test_a_single_wrapping_folder_is_stripped_but_a_flat_archive_is_not(
    tmp_path, data, entries, stripped
):
    result = import_archive(zip_of(tmp_path, entries("wrap")), data)
    assert result.report.stripped_root == stripped
    assert "settings.gradle.kts" in workspace_files(result.workspace.root)


def test_macos_junk_does_not_prevent_stripping_the_wrapping_folder(tmp_path, data):
    entries = [(f"App/{rel}", c) for rel, c in minimal_project().items()]
    entries += [("__MACOSX/App/._settings.gradle.kts", b"junk"), ("App/.DS_Store", b"junk")]
    result = import_archive(zip_of(tmp_path, entries), data)
    assert result.report.stripped_root == "App"
    assert result.report.counts.skipped_entries == 2
    assert ".DS_Store" not in workspace_files(result.workspace.root)


def test_a_root_level_file_or_two_top_level_folders_prevent_stripping(tmp_path, data):
    entries = [(f"App/{rel}", c) for rel, c in minimal_project().items()] + [("README.md", "hi")]
    result = import_archive(
        zip_of(tmp_path, entries), data, require_android_project=False, project_id="a"
    )
    assert result.report.stripped_root is None
    assert "App/settings.gradle.kts" in workspace_files(result.workspace.root)
    two = [(f"A/{rel}", c) for rel, c in minimal_project().items()] + [("B/x.txt", "x")]
    other = import_archive(
        zip_of(tmp_path, two, "y.zip"), data, require_android_project=False, project_id="b"
    )
    assert other.report.stripped_root is None


def test_an_archive_holding_one_file_at_its_root_keeps_it(tmp_path, data):
    archive = zip_of(tmp_path, [("only.txt", "x")])
    result = import_archive(archive, data, require_android_project=False)
    assert result.report.stripped_root is None
    assert workspace_files(result.workspace.root) == {"only.txt": b"x"}


def test_stripping_can_be_turned_off(tmp_path, data):
    archive = project_zip(tmp_path / "x.zip", minimal_project(), root="App")
    result = import_archive(archive, data, strip_single_root=False, require_android_project=False)
    assert "App/settings.gradle.kts" in workspace_files(result.workspace.root)


def test_directory_entries_are_created_even_when_empty(tmp_path, data):
    entries = [*project_entries(), ("app/src/main/res/raw/", b"")]
    result = import_archive(zip_of(tmp_path, entries), data)
    assert (result.workspace.root / "app/src/main/res/raw").is_dir()


def test_non_ascii_names_import(tmp_path, data):
    entries = [*project_entries(), ("app/src/main/res/values/strings_é.xml", "<resources/>")]
    result = import_archive(zip_of(tmp_path, entries), data)
    assert "app/src/main/res/values/strings_é.xml" in workspace_files(result.workspace.root)


def test_a_build_directory_is_dropped_only_beside_a_gradle_build_file(tmp_path, data):
    files = minimal_project()
    files.update(
        {
            "build.gradle.kts": "plugins {}\n",
            "build/outputs/app.apk": b"apk",  # the project root: an output directory
            "app/build.gradle.kts": "android {}\n",
            "app/build/generated/Gen.kt": "class Gen",  # beside a module build file: output
            "app/src/main/java/com/example/build/Info.kt": "package com.example.build\n",
            "docs/build/readme.md": "notes",  # no build file beside it: ordinary content
        }
    )
    got = workspace_files(
        import_archive(project_zip(tmp_path / "x.zip", files), data).workspace.root
    )
    assert "build/outputs/app.apk" not in got and "app/build/generated/Gen.kt" not in got
    assert "app/src/main/java/com/example/build/Info.kt" in got and "docs/build/readme.md" in got


def test_vcs_data_inside_the_archive_is_skipped(tmp_path, data):
    entries = [
        *project_entries(),
        (".git/config", "x"),
        (".git/objects/ab/cd", b"1"),
        (".idea/x.xml", "x"),
    ]
    result = import_archive(zip_of(tmp_path, entries), data)
    assert not any(
        p.startswith((".git/", ".idea/")) for p in workspace_files(result.workspace.root)
    )
    assert result.report.counts.skipped_entries == 3


# --- hostile names ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("../evil.txt", IngestCode.PATH_TRAVERSAL),
        ("a/../../evil.txt", IngestCode.PATH_TRAVERSAL),
        ("a/b/../../../evil.txt", IngestCode.PATH_TRAVERSAL),
        (".git/../../evil.txt", IngestCode.PATH_TRAVERSAL),  # an excluded name must not hide '..'
        ("/evil.txt", IngestCode.ABSOLUTE_PATH),
        ("C:/evil.txt", IngestCode.ABSOLUTE_PATH),
        ("C:\\evil.txt", IngestCode.ABSOLUTE_PATH),
        ("\\\\server\\share\\evil.txt", IngestCode.ABSOLUTE_PATH),
        ("a\\evil.txt", IngestCode.INVALID_PATH),
        ("a//evil.txt", IngestCode.INVALID_PATH),
        ("./evil.txt", IngestCode.INVALID_PATH),
        ("a/./evil.txt", IngestCode.INVALID_PATH),
        ("a\nevil.txt", IngestCode.INVALID_PATH),
        ("a\x00evil.txt", IngestCode.INVALID_PATH),
        ("aux.txt", IngestCode.INVALID_PATH),
        ("a/trailing./evil.txt", IngestCode.INVALID_PATH),
        ("GIT~1/evil.txt", IngestCode.INVALID_PATH),
        ("a:evil.txt", IngestCode.ABSOLUTE_PATH),  # a drive-relative path on Windows
        ("ab:evil.txt", IngestCode.INVALID_PATH),  # ':' also opens NTFS alternate data streams
    ],
)
def test_a_hostile_entry_name_refuses_the_whole_archive_before_anything_is_written(
    tmp_path, data, name, code
):
    archive = zip_of(tmp_path, [*project_entries(), (name, "pwned")])
    assert refuse(tmp_path, data, archive).code is code


def test_the_error_message_shows_a_hostile_name_escaped_and_short(tmp_path, data):
    name = "a\x1b[31m" + "x" * 500
    refused = refuse(tmp_path, data, zip_of(tmp_path, [*project_entries(), (name, "x")]))
    assert "\x1b" not in str(refused) and len(str(refused)) < 400


# --- links and special entries ---------------------------------------------------------------


@pytest.mark.parametrize("target", ["/etc/passwd", "../../outside", "C:\\Windows\\x", "x" * 2000])
def test_a_link_leading_out_of_the_project_refuses_the_archive(tmp_path, data, target):
    archive = zip_of(tmp_path, [*project_entries(), symlink("app/link", target)])
    assert refuse(tmp_path, data, archive).code is IngestCode.UNSAFE_SYMLINK


def test_a_file_written_through_a_link_is_refused_with_the_link(tmp_path, data):
    entries = [*project_entries(), symlink("link", "/tmp"), ("link/evil.txt", "pwned")]
    assert refuse(tmp_path, data, zip_of(tmp_path, entries)).code is IngestCode.UNSAFE_SYMLINK


def test_a_safe_link_inside_the_project_is_skipped_and_reported_never_created(tmp_path, data):
    entries = [*project_entries(), symlink("app/link", "../settings.gradle.kts")]
    result = import_archive(zip_of(tmp_path, entries), data)
    assert result.report.symlinks_skipped == ["app/link"]
    assert result.report.counts.symlinks_skipped == 1
    assert not (result.workspace.root / "app/link").exists()
    assert any("link" in warning for warning in result.report.warnings)


def test_a_policy_can_refuse_every_link(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), symlink("app/link", "../settings.gradle.kts")])
    refused = refuse(tmp_path, data, archive, symlinks=SymlinkPolicy.REJECT_ALL)
    assert refused.code is IngestCode.SYMLINK_NOT_ALLOWED


@pytest.mark.parametrize("kind", [stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK])
def test_devices_pipes_and_sockets_are_refused(tmp_path, data, kind):
    archive = zip_of(tmp_path, [*project_entries(), entry("app/dev", b"", mode=kind | 0o644)])
    assert refuse(tmp_path, data, archive).code is IngestCode.SPECIAL_FILE


def test_permission_only_mode_bits_are_an_ordinary_file(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), entry("app/ok.txt", b"ok", mode=0o644)])
    assert "app/ok.txt" in workspace_files(import_archive(archive, data).workspace.root)


def test_an_encrypted_entry_is_refused(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), ("secret.bin", b"x")])
    patch_zip(archive, central_offset=8, value=0x1, index=3)  # flag bit 0: the entry is encrypted
    assert refuse(tmp_path, data, archive).code is IngestCode.ENCRYPTED_ENTRY


# --- damaged and fake archives ---------------------------------------------------------------


def test_a_file_that_is_not_a_zip_is_refused(tmp_path, data):
    archive = tmp_path / "x.zip"
    archive.write_bytes(os.urandom(2000))
    assert refuse(tmp_path, data, archive).code is IngestCode.NOT_A_ZIP


def test_an_empty_file_is_refused(tmp_path, data):
    archive = tmp_path / "x.zip"
    archive.write_bytes(b"")
    assert refuse(tmp_path, data, archive).code is IngestCode.NOT_A_ZIP


def test_a_zip_with_no_entries_is_refused(tmp_path, data):
    archive = zip_of(tmp_path, [])
    assert refuse(tmp_path, data, archive).code is IngestCode.MALFORMED_ARCHIVE


def test_a_truncated_zip_is_refused(tmp_path, data):
    archive = zip_of(tmp_path, project_entries())
    archive.write_bytes(archive.read_bytes()[:-30])
    assert refuse(tmp_path, data, archive).code in (
        IngestCode.NOT_A_ZIP,
        IngestCode.MALFORMED_ARCHIVE,
    )


def test_corrupt_entry_data_is_refused_not_a_crash(tmp_path, data):
    stored = entry("app/Marker.kt", b"MARKER-CONTENT-0123456789", compress_type=zipfile.ZIP_STORED)
    archive = zip_of(tmp_path, [*project_entries(), stored])
    raw = bytearray(archive.read_bytes())
    raw[raw.index(b"MARKER-CONTENT")] ^= 0xFF  # the stored bytes no longer match their CRC
    archive.write_bytes(bytes(raw))
    assert refuse(tmp_path, data, archive).code is IngestCode.MALFORMED_ARCHIVE


def test_an_unsupported_compression_method_is_refused(tmp_path, data):
    archive = zip_of(tmp_path, project_entries())
    patch_zip(archive, central_offset=10, value=99)
    assert refuse(tmp_path, data, archive).code is IngestCode.MALFORMED_ARCHIVE


def test_a_directory_or_a_missing_path_is_not_an_archive(tmp_path, data):
    folder = tmp_path / "x.zip"
    folder.mkdir()
    assert refuse(tmp_path, data, folder).code is IngestCode.SOURCE_NOT_FILE
    folder.rmdir()
    assert refuse(tmp_path, data, folder).code is IngestCode.SOURCE_NOT_FOUND


def test_a_link_as_the_archive_path_follows_the_policy(tmp_path, data):
    real = zip_of(tmp_path, project_entries(), "real.zip")
    link = tmp_path / "x.zip"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symbolic links here")
    refused = refuse(tmp_path, data, link, symlinks=SymlinkPolicy.REJECT_ALL)
    assert refused.code is IngestCode.SOURCE_IS_LINK
    assert import_archive(link, data).report.counts.files == 3  # allowed by the default policy


# --- collisions ------------------------------------------------------------------------------


def test_a_duplicate_entry_name_is_refused(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), ("app/Dup.kt", "1"), ("app/Dup.kt", "2")])
    assert refuse(tmp_path, data, archive).code is IngestCode.NAME_COLLISION


def test_names_that_differ_only_in_case_are_refused(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), ("app/Foo.kt", "1"), ("app/foo.kt", "2")])
    assert refuse(tmp_path, data, archive).code is IngestCode.NAME_COLLISION


def test_names_that_differ_only_in_unicode_composition_are_refused(tmp_path, data):
    archive = zip_of(
        tmp_path, [*project_entries(), ("app/caf\u00e9.kt", "1"), ("app/cafe\u0301.kt", "2")]
    )
    assert refuse(tmp_path, data, archive).code is IngestCode.NAME_COLLISION


def test_a_name_used_as_file_and_directory_is_refused(tmp_path, data):
    archive = zip_of(
        tmp_path, [*project_entries(), ("app/thing", "1"), ("app/thing/inner.kt", "2")]
    )
    assert refuse(tmp_path, data, archive).code is IngestCode.PATH_CONFLICT


# --- limits: counted on what is actually extracted -------------------------------------------


def numbered(count: int, size: int = 1) -> list:
    return [(f"app/f{i}.txt", "x" * size) for i in range(count)]


def test_the_file_count_limit_is_exact(tmp_path, data):
    base = project_entries()  # 3 files
    ok = zip_of(tmp_path, [*base, *numbered(7)])  # 10 files
    assert import_archive(ok, data, limits=IngestLimits(max_files=10)).report.counts.files == 10
    too_many = zip_of(tmp_path, [*base, *numbered(8)], "y.zip")  # 11 files
    with pytest.raises(IngestRejected) as refused:
        import_archive(too_many, data, limits=IngestLimits(max_files=10), project_id="p2")
    assert refused.value.code is IngestCode.TOO_MANY_FILES


def test_an_archive_listing_far_too_many_entries_is_refused_up_front(tmp_path, data):
    archive = zip_of(tmp_path, numbered(50))
    refused = refuse(tmp_path, data, archive, limits=IngestLimits(max_files=10))
    assert refused.code is IngestCode.TOO_MANY_FILES


def test_the_depth_limit_is_exact(tmp_path, data):
    # The baseline project already reaches 7 segments (app/src/main/java/com/example/demo/Main.kt).
    deep_ok = "/".join(["d"] * 7) + "/x.txt"  # 8 segments
    deep_bad = "/".join(["d"] * 8) + "/x.txt"  # 9 segments
    limits = IngestLimits(max_depth=8)
    assert import_archive(
        zip_of(tmp_path, [*project_entries(), (deep_ok, "x")]), data, limits=limits
    )
    with pytest.raises(IngestRejected) as err:
        import_archive(
            zip_of(tmp_path, [*project_entries(), (deep_bad, "x")], "y.zip"),
            data,
            limits=limits,
            project_id="p2",
        )
    assert err.value.code is IngestCode.TOO_DEEP


def test_the_default_depth_limit_refuses_65_segments(tmp_path, data):
    name = "/".join(f"d{i}" for i in range(64)) + "/x.txt"  # 65 segments
    archive = zip_of(tmp_path, [*project_entries(), (name, "x")])
    assert (
        refuse(tmp_path, data, archive, limits=IngestLimits(max_path_length=2000)).code
        is IngestCode.TOO_DEEP
    )


def test_the_path_length_limit_is_exact(tmp_path, data):
    # The longest baseline path is 42 characters.
    limits = IngestLimits(max_path_length=50)
    ok = "app/" + "a" * 46  # 50 characters
    assert import_archive(zip_of(tmp_path, [*project_entries(), (ok, "x")]), data, limits=limits)
    bad = zip_of(tmp_path, [*project_entries(), ("app/" + "a" * 47, "x")], "y.zip")
    with pytest.raises(IngestRejected) as err:
        import_archive(bad, data, limits=limits, project_id="p2")
    assert err.value.code is IngestCode.PATH_TOO_LONG


def test_the_per_file_size_limit_is_exact(tmp_path, data):
    limits = IngestLimits(max_file_bytes=1000, max_total_bytes=100_000)
    ok = zip_of(tmp_path, [*project_entries(), ("app/big.bin", b"a" * 1000)])
    assert import_archive(ok, data, limits=limits)
    bad = zip_of(tmp_path, [*project_entries(), ("app/big.bin", b"a" * 1001)], "y.zip")
    with pytest.raises(IngestRejected) as err:
        import_archive(bad, data, limits=limits, project_id="p2")
    assert err.value.code is IngestCode.FILE_TOO_LARGE


def test_the_total_size_limit_is_exact(tmp_path, data):
    base = sum(len(c.encode()) for _, c in project_entries())
    limits = IngestLimits(max_file_bytes=500, max_total_bytes=base + 1000)
    ok = zip_of(
        tmp_path, [*project_entries(), ("app/a.bin", b"a" * 500), ("app/b.bin", b"b" * 500)]
    )
    assert import_archive(ok, data, limits=limits)
    bad = zip_of(
        tmp_path,
        [*project_entries(), ("app/a.bin", b"a" * 500), ("app/b.bin", b"b" * 500), ("app/c", b"c")],
        "y.zip",
    )
    with pytest.raises(IngestRejected) as err:
        import_archive(bad, data, limits=limits, project_id="p2")
    assert err.value.code is IngestCode.TOTAL_SIZE_EXCEEDED


def test_a_decompression_bomb_is_refused_by_the_expansion_ratio(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), ("app/bomb.bin", b"\0" * 300_000)])
    limits = IngestLimits(ratio_floor_bytes=1024, max_compression_ratio=100)
    assert (
        refuse(tmp_path, data, archive, limits=limits).code is IngestCode.COMPRESSION_RATIO_EXCEEDED
    )


def test_many_small_entries_that_together_expand_too_much_are_refused(tmp_path, data):
    entries = [(f"app/z{i}.bin", b"\0" * 60_000) for i in range(20)]
    archive = zip_of(tmp_path, [*project_entries(), *entries])
    limits = IngestLimits(ratio_floor_bytes=100 * 1024, max_compression_ratio=100)
    assert (
        refuse(tmp_path, data, archive, limits=limits).code is IngestCode.COMPRESSION_RATIO_EXCEEDED
    )


def test_ordinary_text_that_compresses_well_is_not_a_bomb(tmp_path, data):
    text = "val x = 1\n" * 2000  # 20 KB, a high ratio but below the floor
    archive = zip_of(tmp_path, [*project_entries(), ("app/Big.kt", text)])
    assert import_archive(archive, data).report.counts.files == 4


def test_an_archive_claiming_a_huge_entry_is_refused_by_its_claim(tmp_path, data):
    archive = zip_of(tmp_path, project_entries())
    patch_zip(archive, central_offset=24, size=4, value=2_000_000_000)
    assert refuse(tmp_path, data, archive).code is IngestCode.FILE_TOO_LARGE


def test_an_archive_understating_an_entry_is_refused_not_trusted(tmp_path, data):
    archive = zip_of(tmp_path, [*project_entries(), ("app/Big.kt", "x" * 5000)])
    patch_zip(archive, central_offset=24, size=4, value=1, index=3)
    assert refuse(tmp_path, data, archive).code is IngestCode.MALFORMED_ARCHIVE


def test_an_archive_understating_compressed_sizes_is_refused_not_a_crash(tmp_path, data):
    archive = zip_of(tmp_path, project_entries())
    patch_zip(archive, central_offset=20, size=4, value=1)
    assert refuse(tmp_path, data, archive).code is IngestCode.MALFORMED_ARCHIVE


def test_a_slow_import_is_stopped_by_the_time_limit(tmp_path, data):
    clock = iter(range(0, 1000, 10))
    request = make_request(
        ZipSource(path=zip_of(tmp_path, project_entries())),
        data,
        limits=IngestLimits(max_seconds=5),
    )
    with pytest.raises(IngestRejected) as refused:
        import_project(request, monotonic=lambda: float(next(clock)))
    assert refused.value.code is IngestCode.TIMEOUT
    assert_nothing_left(tmp_path, data)


def test_the_entry_count_in_the_end_record_is_read_without_loading_the_archive(tmp_path):
    archive = zip_of(tmp_path, numbered(7))
    assert declared_entry_count(archive) == 7
    junk = tmp_path / "junk.bin"
    junk.write_bytes(os.urandom(500))
    assert declared_entry_count(junk) is None
    assert declared_entry_count(tmp_path / "missing.zip") is None


# --- nested archives are inert ---------------------------------------------------------------


def test_a_nested_archive_is_kept_as_a_file_and_never_opened(tmp_path, data):
    inner = zip_of(tmp_path, [("../evil.txt", "pwned"), ("/abs.txt", "x")], "inner.zip")
    inner_bytes = inner.read_bytes()
    archive = zip_of(
        tmp_path,
        [*project_entries(), ("libs/inner.zip", inner_bytes), ("libs/x.jar", b"PK\x03\x04junk")],
    )
    result = import_archive(archive, data)
    files = workspace_files(result.workspace.root)
    assert files["libs/inner.zip"] == inner_bytes
    assert "evil.txt" not in files and "abs.txt" not in files
    assert result.report.nested_archives == ["libs/inner.zip", "libs/x.jar"]
    assert result.report.counts.nested_archives == 2
    assert not (tmp_path / "evil.txt").exists() and not (data / "evil.txt").exists()


# --- the archive is checked again at the end -------------------------------------------------


def test_an_archive_changed_during_the_import_is_refused(tmp_path, data, monkeypatch):
    from androai_codegen.ingest import importer

    archive = zip_of(tmp_path, project_entries())
    real = importer.materialize

    def materialize_then_touch(*args, **kwargs):
        records = real(*args, **kwargs)
        with open(archive, "ab") as handle:
            handle.write(b"\0")  # someone appends to the archive meanwhile
        return records

    monkeypatch.setattr(importer, "materialize", materialize_then_touch)
    assert refuse(tmp_path, data, archive).code is IngestCode.SOURCE_CHANGED


def test_the_archive_check_can_be_turned_off_but_nothing_else_changes(tmp_path, data, monkeypatch):
    from androai_codegen.ingest import importer

    archive = zip_of(tmp_path, project_entries())
    real = importer.materialize

    def materialize_then_touch(*args, **kwargs):
        records = real(*args, **kwargs)
        with open(archive, "ab") as handle:
            handle.write(b"\0")
        return records

    monkeypatch.setattr(importer, "materialize", materialize_then_touch)
    assert import_archive(archive, data, verify_source=False).report.counts.files == 3
