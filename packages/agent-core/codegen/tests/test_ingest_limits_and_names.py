"""Limits are enforced on bytes actually read; names are checked before anything is written."""

import io

import pytest

from androai_codegen.editing.workspace import _SKIPPED_DIRS
from androai_codegen.ingest import IngestCode, IngestLimits, IngestRejected
from androai_codegen.ingest.budget import CHUNK, ImportBudget
from androai_codegen.ingest.names import (
    EXCLUDED_DIR_NAMES,
    NameRegistry,
    excluded_reason,
    finalize_name,
    is_nested_archive,
    link_target_is_unsafe,
    split_name,
)

MiB = 1024 * 1024


def code_of(exc_info) -> IngestCode:
    return exc_info.value.code


def copy(budget: ImportBudget, data: bytes, **kwargs):
    return budget.copy(io.BytesIO(data), io.BytesIO(), path="f.bin", **kwargs)


# --- the approved defaults, and that they can be changed -------------------------------------


def test_the_defaults_are_the_approved_limits():
    limits = IngestLimits()
    assert limits.max_files == 20_000
    assert limits.max_total_bytes == 500 * MiB
    assert limits.max_file_bytes == 50 * MiB
    assert limits.max_depth == 64
    assert limits.max_compression_ratio == 100


def test_every_limit_is_configurable():
    limits = IngestLimits(
        max_files=3,
        max_total_bytes=10,
        max_file_bytes=5,
        max_depth=2,
        max_compression_ratio=7,
        ratio_floor_bytes=1,
        max_path_length=20,
        max_seconds=1.5,
        secret_scan_max_bytes=9,
    )
    assert (limits.max_files, limits.max_total_bytes, limits.max_file_bytes) == (3, 10, 5)
    assert (limits.max_depth, limits.max_compression_ratio, limits.max_path_length) == (2, 7, 20)


@pytest.mark.parametrize("field", ["max_files", "max_total_bytes", "max_file_bytes", "max_depth"])
def test_a_limit_must_be_positive(field):
    with pytest.raises(ValueError):
        IngestLimits(**{field: 0})


def test_a_file_limit_above_the_total_limit_is_refused():
    with pytest.raises(ValueError):
        IngestLimits(max_file_bytes=100, max_total_bytes=50)


# --- the byte budget -------------------------------------------------------------------------


def test_a_file_of_exactly_the_limit_is_copied_and_one_byte_more_is_refused():
    limits = IngestLimits(max_file_bytes=1000, max_total_bytes=10_000)
    size, digest = copy(ImportBudget(limits), b"x" * 1000)
    assert size == 1000 and len(digest) == 64
    with pytest.raises(IngestRejected) as refused:
        copy(ImportBudget(limits), b"x" * 1001)
    assert code_of(refused) is IngestCode.FILE_TOO_LARGE


def test_the_total_limit_counts_every_file_and_is_exact():
    limits = IngestLimits(max_file_bytes=600, max_total_bytes=1000)
    budget = ImportBudget(limits)
    copy(budget, b"a" * 600)
    copy(budget, b"b" * 400)  # exactly 1000
    with pytest.raises(IngestRejected) as refused:
        copy(budget, b"c")
    assert code_of(refused) is IngestCode.TOTAL_SIZE_EXCEEDED


def test_an_endless_stream_is_cut_off_at_the_limit_not_read_to_the_end():
    class Endless(io.RawIOBase):
        reads = 0

        def readable(self):
            return True

        def read(self, size=-1):
            Endless.reads += 1
            return b"\0" * size

    limits = IngestLimits(max_file_bytes=4 * CHUNK, max_total_bytes=8 * CHUNK)
    with pytest.raises(IngestRejected) as refused:
        ImportBudget(limits).copy(Endless(), io.BytesIO(), path="endless")
    assert code_of(refused) is IngestCode.FILE_TOO_LARGE
    assert Endless.reads <= 6  # four chunks fit, the fifth crosses the limit


def test_the_data_past_the_limit_is_never_written():
    out = io.BytesIO()
    limits = IngestLimits(max_file_bytes=CHUNK, max_total_bytes=10 * CHUNK)
    with pytest.raises(IngestRejected):
        ImportBudget(limits).copy(io.BytesIO(b"x" * (2 * CHUNK)), out, path="f")
    assert len(out.getvalue()) <= CHUNK


def test_an_entry_that_expands_too_much_is_refused():
    limits = IngestLimits(max_compression_ratio=10, ratio_floor_bytes=100)
    with pytest.raises(IngestRejected) as refused:
        copy(ImportBudget(limits), b"\0" * 5000, compressed_size=10)  # 500:1
    assert code_of(refused) is IngestCode.COMPRESSION_RATIO_EXCEEDED
    copy(ImportBudget(limits), b"\0" * 5000, compressed_size=500)  # exactly 10:1 is fine


def test_small_data_may_compress_very_well_the_ratio_has_a_floor():
    limits = IngestLimits(max_compression_ratio=10, ratio_floor_bytes=10_000)
    copy(ImportBudget(limits), b"\0" * 5000, compressed_size=1)


def test_the_whole_archive_is_also_held_to_the_ratio_using_its_real_size():
    limits = IngestLimits(max_compression_ratio=10, ratio_floor_bytes=100)
    with pytest.raises(IngestRejected) as refused:
        copy(ImportBudget(limits, archive_size=50), b"\0" * 5000)
    assert code_of(refused) is IngestCode.COMPRESSION_RATIO_EXCEEDED


def test_a_slow_import_times_out():
    now = [0.0]
    budget = ImportBudget(IngestLimits(max_seconds=5), monotonic=lambda: now[0])
    budget.check_time()
    now[0] = 5.5
    with pytest.raises(IngestRejected) as refused:
        budget.check_time()
    assert code_of(refused) is IngestCode.TIMEOUT
    with pytest.raises(IngestRejected):
        copy(budget, b"x")


def test_the_file_and_directory_counts_stop_at_the_limit():
    budget = ImportBudget(IngestLimits(max_files=2))
    budget.count_file("a")
    budget.count_file("b")
    with pytest.raises(IngestRejected) as refused:
        budget.count_file("c")
    assert code_of(refused) is IngestCode.TOO_MANY_FILES
    directories = ImportBudget(IngestLimits(max_files=1))
    directories.count_directory("a")
    with pytest.raises(IngestRejected):
        directories.count_directory("b")


# --- entry names -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("/etc/passwd", IngestCode.ABSOLUTE_PATH),
        ("\\windows\\x", IngestCode.ABSOLUTE_PATH),
        ("C:/x", IngestCode.ABSOLUTE_PATH),
        ("c:\\x", IngestCode.ABSOLUTE_PATH),
        ("C:x", IngestCode.ABSOLUTE_PATH),
        ("../x", IngestCode.PATH_TRAVERSAL),
        ("a/../x", IngestCode.PATH_TRAVERSAL),
        ("a/b/..", IngestCode.PATH_TRAVERSAL),
        ("a\\b", IngestCode.INVALID_PATH),
        ("a//b", IngestCode.INVALID_PATH),
        ("./a", IngestCode.INVALID_PATH),
        ("a/./b", IngestCode.INVALID_PATH),
        ("a\x00b", IngestCode.INVALID_PATH),
        ("a\nb", IngestCode.INVALID_PATH),
        ("a\x7fb", IngestCode.INVALID_PATH),
    ],
)
def test_an_unsafe_name_is_refused_with_its_own_code(raw, code):
    with pytest.raises(IngestRejected) as refused:
        split_name(raw)
    assert code_of(refused) is code


@pytest.mark.parametrize(
    "raw", ["a", "a/b", "app/src/main/AndroidManifest.xml", "dir/", "ünï/cødé.kt"]
)
def test_an_ordinary_name_is_accepted(raw):
    parts = split_name(raw, is_dir=raw.endswith("/"))
    assert parts and all(parts)


def test_a_trailing_slash_is_only_allowed_on_a_directory():
    assert split_name("a/b/", is_dir=True) == ["a", "b"]
    with pytest.raises(IngestRejected):
        split_name("a/b/", is_dir=False)


@pytest.mark.parametrize(
    "parts",
    [
        ["aux.txt"],
        ["con"],
        ["NUL.kt"],
        ["a", "com1"],
        ["trailing."],
        ["trailing "],
        ["a:b"],
        ["a<b"],
        ["GIT~1", "x"],
    ],
)
def test_the_engines_name_rules_apply_to_imported_names(parts):
    with pytest.raises(IngestRejected) as refused:
        finalize_name(parts, IngestLimits())
    assert code_of(refused) is IngestCode.INVALID_PATH


def test_the_depth_limit_counts_path_segments_and_is_exact():
    limits = IngestLimits(max_depth=4, max_path_length=1000)
    assert finalize_name(["a", "b", "c", "d"], limits) == "a/b/c/d"
    with pytest.raises(IngestRejected) as refused:
        finalize_name(["a", "b", "c", "d", "e"], limits)
    assert code_of(refused) is IngestCode.TOO_DEEP


def test_the_default_depth_limit_is_64_segments():
    names = [f"d{i}" for i in range(64)]
    assert finalize_name(names, IngestLimits(max_path_length=1000)).count("/") == 63
    with pytest.raises(IngestRejected) as refused:
        finalize_name([*names, "x"], IngestLimits(max_path_length=1000))
    assert code_of(refused) is IngestCode.TOO_DEEP


def test_the_path_length_limit_is_exact():
    limits = IngestLimits(max_path_length=10)
    assert finalize_name(["abcdefghij"], limits) == "abcdefghij"
    with pytest.raises(IngestRejected) as refused:
        finalize_name(["abcdefghijk"], limits)
    assert code_of(refused) is IngestCode.PATH_TOO_LONG


# --- what is never imported ------------------------------------------------------------------


def never(_prefix):
    return False


def always(_prefix):
    return True


@pytest.mark.parametrize(
    "parts",
    [
        [".git"],
        [".GIT", "config"],
        ["app", ".git", "HEAD"],
        [".gradle", "x"],
        [".idea", "workspace.xml"],
        ["node_modules", "x"],
        [".cxx", "x"],
        [".externalNativeBuild", "x"],
        ["__MACOSX", "._x"],
    ],
)
def test_vcs_ide_and_tooling_directories_are_excluded(parts):
    assert excluded_reason(parts, is_dir=len(parts) == 1, build_is_output=never)


@pytest.mark.parametrize("parts", [[".DS_Store"], ["a", "Thumbs.db"]])
def test_operating_system_junk_files_are_excluded(parts):
    assert excluded_reason(parts, is_dir=False, build_is_output=never)


def test_a_build_directory_is_only_excluded_where_it_holds_gradle_outputs():
    assert excluded_reason(["build", "x.apk"], is_dir=False, build_is_output=always) == "build"
    assert excluded_reason(["app", "build"], is_dir=True, build_is_output=always) == "build"
    # a source package named "build" is part of the project
    assert (
        excluded_reason(["java", "build", "Info.kt"], is_dir=False, build_is_output=never) is None
    )


def test_a_file_named_like_an_excluded_directory_is_not_excluded():
    assert excluded_reason(["docs", "build"], is_dir=False, build_is_output=always) is None
    assert excluded_reason(["x", ".gradle"], is_dir=False, build_is_output=always) is None


def test_the_importer_excludes_at_least_what_the_workspace_does_not_list():
    # The workspace never lists these directories, so importing them would only create files the
    # engine cannot see. ("build" and ".git" are handled by the dedicated rules.)
    assert (set(_SKIPPED_DIRS) - {".git", "build"}) <= EXCLUDED_DIR_NAMES


@pytest.mark.parametrize(
    ("name", "expected"),
    [("lib/x.jar", True), ("a.ZIP", True), ("b.aar", True), ("c.tar.gz", True), ("d.kt", False)],
)
def test_nested_archives_are_recognised_by_suffix(name, expected):
    assert is_nested_archive(name) is expected


# --- links -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("link", "target", "unsafe"),
    [
        ("a/link", "../b", False),
        ("a/link", "b/c", False),
        ("link", "a", False),
        ("a/b/link", "../../c", False),
        ("link", "..", True),
        ("link", "../x", True),
        ("a/link", "../../x", True),
        ("link", "/etc/passwd", True),
        ("link", "C:/x", True),
        ("link", "C:\\x", True),
        ("link", "\\\\server\\share", True),
        ("link", "", True),
        ("link", "a\x00b", True),
        ("a/link", "b/../../..", True),
    ],
)
def test_a_link_target_is_unsafe_when_it_can_leave_the_project(link, target, unsafe):
    assert link_target_is_unsafe(link, target) is unsafe


# --- collisions ------------------------------------------------------------------------------


def test_names_that_differ_only_in_case_collide():
    registry = NameRegistry()
    registry.add_file("app/Main.kt")
    with pytest.raises(IngestRejected) as refused:
        registry.add_file("app/main.kt")
    assert code_of(refused) is IngestCode.NAME_COLLISION


def test_the_same_name_composed_two_ways_collides():
    registry = NameRegistry()
    registry.add_file("caf\u00e9.kt")  # é as one character
    with pytest.raises(IngestRejected) as refused:
        registry.add_file("cafe\u0301.kt")  # e + combining acute
    assert code_of(refused) is IngestCode.NAME_COLLISION


def test_a_duplicate_entry_is_refused():
    registry = NameRegistry()
    registry.add_file("a.kt")
    with pytest.raises(IngestRejected) as refused:
        registry.add_file("a.kt")
    assert code_of(refused) is IngestCode.NAME_COLLISION


def test_a_name_cannot_be_both_a_file_and_a_directory():
    registry = NameRegistry()
    registry.add_file("a")
    with pytest.raises(IngestRejected) as refused:
        registry.add_file("a/b")
    assert code_of(refused) is IngestCode.PATH_CONFLICT
    other = NameRegistry()
    other.add_file("x/y")
    with pytest.raises(IngestRejected):
        other.add_file("x")


def test_directories_that_differ_only_in_case_collide_but_a_repeated_directory_is_fine():
    registry = NameRegistry()
    registry.add_directory("Res")
    registry.add_directory("Res")
    with pytest.raises(IngestRejected) as refused:
        registry.add_file("res/x.xml")
    assert code_of(refused) is IngestCode.NAME_COLLISION
