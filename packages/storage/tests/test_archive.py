import io
import stat
import zipfile

import pytest

from androai_storage import ArchiveError, ArchiveLimits, build_zip, iter_zip_files, validate_apk


def make_zip(entries, *, setup=None) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
        if setup:
            setup(zf)
    buf.seek(0)
    return buf


def extract(buf, **kw):
    return dict(iter_zip_files(buf, **kw))


def test_extracts_and_strips_single_root():
    z = make_zip([("proj/app/build.gradle", "x"), ("proj/settings.gradle", "y"), ("proj/", "")])
    assert extract(z) == {"app/build.gradle": b"x", "settings.gradle": b"y"}


def test_keeps_layout_without_common_root():
    z = make_zip([("a.txt", "1"), ("d/b.txt", "2")])
    assert set(extract(z)) == {"a.txt", "d/b.txt"}


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "a/../../evil.txt", "/etc/passwd", "C:/win.ini", "a\\..\\b.txt"],
)
def test_rejects_traversal_and_bad_names(name):
    with pytest.raises(ArchiveError):
        extract(make_zip([("ok.txt", "1"), (name, "x")]))


def test_rejects_symlink():
    def add_link(zf):
        zi = zipfile.ZipInfo("link")
        zi.create_system = 3
        zi.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(zi, "/etc/passwd")

    with pytest.raises(ArchiveError, match="symlink"):
        extract(make_zip([("ok.txt", "1")], setup=add_link))


def test_rejects_duplicates_and_case_collisions():
    with pytest.raises(ArchiveError):
        extract(make_zip([("A.txt", "1"), ("a.txt", "2")]))


def test_rejects_file_dir_conflict():
    with pytest.raises(ArchiveError, match="conflict"):
        extract(make_zip([("a", "1"), ("a/b", "2")]))


def test_rejects_too_many_files():
    with pytest.raises(ArchiveError, match="too many"):
        extract(make_zip([(f"f{i}", "x") for i in range(5)]), limits=ArchiveLimits(max_files=3))


def test_rejects_oversized_file_and_total():
    z = make_zip([("big", b"a" * 5000)])
    with pytest.raises(ArchiveError):
        extract(z, limits=ArchiveLimits(max_file_bytes=1000))
    z = make_zip([("a", b"a" * 600), ("b", b"b" * 600)])
    with pytest.raises(ArchiveError, match="total"):
        extract(z, limits=ArchiveLimits(max_total_bytes=1000))


def test_zip_bomb_ratio_rejected():
    z = make_zip([("bomb", b"\0" * (20 * 1024 * 1024))])  # compresses ~1000:1
    with pytest.raises(ArchiveError, match="ratio"):
        extract(z)


def test_lying_header_is_caught_on_actual_bytes():
    # Declared size is forged small; real decompressed size exceeds the limit.
    z = make_zip([("x", b"a" * 4000), ("y", b"b")])
    raw = bytearray(z.getvalue())
    # forge file_size in the central directory for entry "x" (offset found via signature)
    cd = raw.rfind(b"PK\x01\x02")
    raw[cd + 24 : cd + 28] = (10).to_bytes(4, "little")
    with pytest.raises(ArchiveError):
        extract(io.BytesIO(bytes(raw)), limits=ArchiveLimits(max_file_bytes=1000, max_ratio=10_000))


def test_encrypted_rejected():
    z = make_zip([("a", "1")])
    raw = bytearray(z.getvalue())
    cd = raw.rfind(b"PK\x01\x02")
    raw[cd + 8] |= 0x1  # general-purpose flag: encrypted
    with pytest.raises(ArchiveError, match="encrypted"):
        extract(io.BytesIO(bytes(raw)))


def test_not_a_zip_and_empty():
    with pytest.raises(ArchiveError):
        extract(io.BytesIO(b"not a zip"))
    with pytest.raises(ArchiveError, match="no files"):
        extract(make_zip([("only/", "")]))


def test_archive_size_limit():
    with pytest.raises(ArchiveError, match="too large"):
        extract(make_zip([("a", "x" * 100)]), limits=ArchiveLimits(max_archive_bytes=50))


def test_junk_skipped():
    z = make_zip([("__MACOSX/._a", "j"), (".DS_Store", "j"), (".git/config", "j"), ("a.txt", "1")])
    assert extract(z) == {"a.txt": b"1"}


def test_apk_validation():
    good = make_zip([("AndroidManifest.xml", b"x"), ("classes.dex", b"d"), ("classes2.dex", b"d")])
    info = validate_apk(good)
    assert info.dex_files == 2 and info.has_manifest
    with pytest.raises(ArchiveError, match="Manifest"):
        validate_apk(make_zip([("a.txt", "1")]))
    with pytest.raises(ArchiveError):
        validate_apk(make_zip([("../AndroidManifest.xml", "1")]))


def test_build_zip_is_deterministic_and_roundtrips():
    entries = [("b.txt", b"2"), ("a/x.txt", b"1")]
    a, b = build_zip(entries).read(), build_zip(list(reversed(entries))).read()
    assert a == b
    assert extract(io.BytesIO(a), strip_common_root=False) == {"a/x.txt": b"1", "b.txt": b"2"}


def test_normalize_rejects_nul_and_control_chars():
    from androai_storage import normalize_member_path

    for bad in ["a/\x00b", "a\nb", ""]:
        with pytest.raises(ArchiveError):
            normalize_member_path(bad)
