"""Project-type detection: path lists, ZIP archives and directories."""

import zipfile

import pytest

from androai_codegen.detect import ProjectKind, detect_directory, detect_from_files, detect_zip

NATIVE = {
    "settings.gradle.kts": "include(':app')",
    "app/build.gradle.kts": 'plugins { id("org.jetbrains.kotlin.plugin.compose") }',
    "app/src/main/AndroidManifest.xml": "<manifest/>",
    "app/src/main/java/a/Main.kt": "class Main",
}


def _detect(files: dict[str, str]):
    return detect_from_files(files, files.get)


def test_native_compose_kotlin():
    d = _detect(NATIVE)
    assert d.kind is ProjectKind.NATIVE_ANDROID and d.supported
    assert d.android_root == "" and d.languages == ["kotlin"] and d.ui_toolkits == ["compose"]


def test_native_views_java():
    d = _detect(
        {
            "settings.gradle": "",
            "app/src/main/AndroidManifest.xml": "",
            "app/src/main/res/layout/main.xml": "",
            "app/src/main/java/a/Main.java": "",
        }
    )
    assert d.languages == ["java"] and d.ui_toolkits == ["views"]


def test_wrapper_folder_is_stripped_and_reported():
    d = _detect({f"proj-main/{k}": v for k, v in NATIVE.items()})
    assert d.kind is ProjectKind.NATIVE_ANDROID
    assert d.project_root == "proj-main" and d.android_root == "proj-main"


def test_android_in_subfolder():
    d = _detect(
        {
            "README.md": "",
            "mobile/settings.gradle": "",
            "mobile/app/src/main/AndroidManifest.xml": "",
        }
    )
    assert d.kind is ProjectKind.NATIVE_ANDROID and d.android_root == "mobile"


def test_flutter():
    d = _detect(
        {
            "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",
            "android/settings.gradle": "",
            "android/app/src/main/AndroidManifest.xml": "",
        }
    )
    assert d.kind is ProjectKind.FLUTTER and not d.supported and d.android_root == "android"


def test_react_native():
    d = _detect(
        {
            "package.json": '{"dependencies": {"react-native": "0.75"}}',
            "android/settings.gradle": "",
            "android/app/src/main/AndroidManifest.xml": "",
        }
    )
    assert d.kind is ProjectKind.REACT_NATIVE and not d.supported


def test_plain_package_json_is_not_react_native():
    d = _detect({"package.json": '{"dependencies": {"express": "4"}}'})
    assert d.kind is ProjectKind.UNKNOWN


def test_capacitor():
    d = _detect({"capacitor.config.ts": "", "android/settings.gradle": ""})
    assert d.kind is ProjectKind.CAPACITOR_CORDOVA


def test_kotlin_multiplatform():
    files = dict(NATIVE)
    files["shared/build.gradle.kts"] = 'plugins { kotlin("multiplatform") }'
    assert _detect(files).kind is ProjectKind.KOTLIN_MULTIPLATFORM


def test_unknown_and_empty():
    assert _detect({"index.html": "<html/>"}).kind is ProjectKind.UNKNOWN
    d = detect_from_files([])
    assert d.kind is ProjectKind.UNKNOWN and d.android_root is None


def test_hostile_paths_and_failing_reader_do_not_raise():
    def boom(_: str) -> str:
        raise OSError("nope")

    d = detect_from_files(["../../etc/passwd", "/abs/pubspec.yaml", "pubspec.yaml"], boom)
    assert d.kind is ProjectKind.UNKNOWN


def test_without_reader_flutter_markers_are_not_enough():
    assert detect_from_files(["pubspec.yaml"]).kind is ProjectKind.UNKNOWN


def test_zip_and_directory(tmp_path):
    archive = tmp_path / "p.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, text in NATIVE.items():
            z.writestr(f"wrap/{name}", text)
    assert detect_zip(archive).kind is ProjectKind.NATIVE_ANDROID
    root = tmp_path / "dir"
    for name, text in NATIVE.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    assert detect_directory(root).kind is ProjectKind.NATIVE_ANDROID


def test_damaged_zip_is_unknown(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert detect_zip(bad).kind is ProjectKind.UNKNOWN
    assert detect_zip(tmp_path / "missing.zip").kind is ProjectKind.UNKNOWN


@pytest.mark.parametrize("name", ["node_modules/x/pubspec.yaml", "__MACOSX/pubspec.yaml"])
def test_vendored_markers_ignored(name):
    assert _detect({name: "flutter"}).kind is ProjectKind.UNKNOWN


def test_import_names_the_framework(tmp_path):
    from ingest_helpers import import_archive, import_dir, make_zip, write_tree

    from androai_codegen.ingest import IngestCode, IngestRejected

    files = {
        "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",
        "android/settings.gradle": "",
        "android/app/src/main/AndroidManifest.xml": "<manifest/>",
    }
    archive = make_zip(tmp_path / "f.zip", list(files.items()))
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(IngestRejected) as zipped:
        import_archive(archive, data)
    assert zipped.value.code is IngestCode.UNSUPPORTED_FRAMEWORK
    assert "Flutter" in zipped.value.problem.message
    with pytest.raises(IngestRejected) as plain:
        import_dir(write_tree(tmp_path / "src", files), data)
    assert plain.value.code is IngestCode.UNSUPPORTED_FRAMEWORK


SUB = {
    "README.md": "docs",
    "backend/server.py": "print(1)",
    "mobile/settings.gradle": "include(':app')",
    "mobile/app/src/main/AndroidManifest.xml": "<manifest/>",
    "mobile/app/src/main/java/a/Main.kt": "class Main",
}


def test_import_reroots_onto_android_subfolder_zip_and_directory(tmp_path):
    from ingest_helpers import import_archive, import_dir, make_zip, workspace_files, write_tree

    data = tmp_path / "data"
    data.mkdir()
    archive = make_zip(tmp_path / "s.zip", [(f"wrap/{k}", v) for k, v in SUB.items()])
    result = import_archive(archive, data)
    assert result.report.project_subdir == "mobile" and result.report.stripped_root == "wrap"
    files = workspace_files(result.workspace.root)
    assert "settings.gradle" in files and "app/src/main/AndroidManifest.xml" in files
    assert not any(f.startswith(("backend", "README")) for f in files)
    assert result.report.android.detected
    assert any("outside 'mobile'" in w for w in result.report.warnings)
    assert result.report.counts.files == 3

    other = tmp_path / "data2"
    other.mkdir()
    directory = import_dir(write_tree(tmp_path / "src", SUB), other)
    assert directory.report.project_subdir == "mobile"
    assert sorted(workspace_files(directory.workspace.root)) == sorted(files)
    # re-opening keeps the record
    from androai_codegen.ingest import reopen_import

    assert reopen_import(directory.project_dir).report.project_subdir == "mobile"


def test_reroot_can_be_turned_off(tmp_path):
    from ingest_helpers import import_dir, write_tree

    from androai_codegen.ingest import IngestCode, IngestRejected

    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(IngestRejected) as err:
        import_dir(write_tree(tmp_path / "src", SUB), data, locate_android_subdir=False)
    assert err.value.code is IngestCode.NOT_AN_ANDROID_PROJECT


def test_flutter_android_folder_is_not_rerooted(tmp_path):
    from ingest_helpers import import_dir, write_tree

    from androai_codegen.ingest import IngestCode, IngestRejected

    data = tmp_path / "data"
    data.mkdir()
    files = {
        "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",
        "android/settings.gradle": "",
        "android/app/src/main/AndroidManifest.xml": "<manifest/>",
    }
    with pytest.raises(IngestRejected) as err:
        import_dir(write_tree(tmp_path / "src", files), data)
    assert err.value.code is IngestCode.UNSUPPORTED_FRAMEWORK
