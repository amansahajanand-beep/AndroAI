"""Package renaming (pure functions) and the staged workspace the agent edits."""

import pytest

from androai_codegen.agent import packages
from androai_codegen.agent.staging import StagedFiles, ToolError

OLD, NEW = "com.example.todo", "com.acme.notes"
STRINGS = "app/src/main/res/values/strings.xml"
COLORS = "app/src/main/res/values/colors.xml"
HOME = "app/src/main/java/com/example/todo/ui/TodoApp.kt"
EMPTY = '<string name="empty_list">Nothing to do</string>'


# ---- pure package helpers ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["com.acme.app", "a.b", "org.my_company.app2"])
def test_valid_packages(name):
    assert packages.validate_package(name) is None


@pytest.mark.parametrize(
    "name", ["app", "Com.Acme", "com.1abc", "com.class.x", "com..x", "com.a-b"]
)
def test_invalid_packages(name):
    assert packages.validate_package(name)


def test_rename_text_handles_packages_imports_and_subpackages():
    text = (
        "package com.example.todo.ui\n"
        "import com.example.todo.R\n"
        "import com.example.todo.data.Task\n"
        'val s = "com.example.todo"\n'
    )
    out = packages.rename_text(text, OLD, NEW)
    assert "package com.acme.notes.ui" in out and "import com.acme.notes.R" in out
    assert "import com.acme.notes.data.Task" in out and '"com.acme.notes"' in out
    assert OLD not in out


def test_rename_text_leaves_lookalikes_alone():
    text = "com.example.todolist.X  org.com.example.todo.Y  com.example.to  mycom.example.todo"
    assert packages.rename_text(text, OLD, NEW) == text


def test_rename_path_moves_only_source_folders():
    moved = packages.rename_path("app/src/main/java/com/example/todo/ui/Home.kt", OLD, NEW)
    assert moved == "app/src/main/java/com/acme/notes/ui/Home.kt"
    kotlin = packages.rename_path("app/src/main/kotlin/com/example/todo/A.kt", OLD, NEW)
    assert kotlin.endswith("kotlin/com/acme/notes/A.kt")
    same = "app/src/main/res/values/com/example/todo.xml"
    assert packages.rename_path(same, OLD, NEW) == same
    lookalike = packages.rename_path("app/src/main/java/com/example/todolist/A.kt", OLD, NEW)
    assert lookalike.endswith("todolist/A.kt")


def test_set_application_id_kts_and_groovy():
    kts, n1 = packages.set_application_id('    applicationId = "com.old.app"\n', "com.new.app")
    groovy, n2 = packages.set_application_id("    applicationId 'com.old.app'\n", "com.new.app")
    assert (n1, n2) == (1, 1) and "com.new.app" in kts and "com.new.app" in groovy
    assert packages.set_application_id("nothing here", "a.b")[1] == 0


# ---- staged workspace --------------------------------------------------------------------------


@pytest.fixture
def staged(engine, put):
    from sample_project import good_project

    for path, content in good_project().items():
        put(path, content)
    return StagedFiles(engine)


def test_listing_reading_and_searching(staged):
    assert "app/" in staged.list_dir("")
    assert "TodoApp.kt" in staged.list_dir("app/src/main/java/com/example/todo/ui")
    text = staged.read(STRINGS)
    assert "empty_list" in text and "|" in text
    assert "strings.xml:" in staged.search("empty_list")
    assert staged.search("zzz-not-there") == "no matches"
    with pytest.raises(ToolError):
        staged.read("nope/missing.kt")


def test_reading_slices_and_truncates_long_files(staged):
    lines = "\n".join(f"line {i}" for i in range(1000))
    staged.write("big.txt", lines)
    assert "showing lines 1-400 of 1000" in staged.read("big.txt")
    assert "line 500" in staged.read("big.txt", 500, 502)


def test_edit_is_exact_and_nothing_reaches_the_real_project(staged, ws_root):
    before = (ws_root / STRINGS).read_text()
    staged.edit(STRINGS, EMPTY, '<string name="empty_list">Empty</string>')
    assert "Empty" in staged.read(STRINGS)
    assert (ws_root / STRINGS).read_text() == before
    with pytest.raises(ToolError, match="not found"):
        staged.edit(STRINGS, "zzz", "y")
    with pytest.raises(ToolError, match="appears"):
        staged.edit(STRINGS, "string", "x")  # ambiguous
    assert staged.edit(STRINGS, "string name", "string  name", replace_all=True).startswith(
        "edited"
    )


def test_write_create_and_overwrite_rules(staged):
    assert "created" in staged.write("app/New.kt", "class New")
    assert "rewrote" in staged.write("app/New.kt", "class New2")  # its own file
    with pytest.raises(ToolError, match="read it first"):
        staged.write(STRINGS, "<resources/>")
    staged.read(STRINGS)
    assert "rewrote" in staged.write(STRINGS, "<resources/>")


def test_delete_and_move(staged):
    staged.delete(STRINGS)
    with pytest.raises(ToolError):
        staged.read(STRINGS)
    target = "app/src/main/java/com/example/todo/ui/Moved.kt"
    staged.move(HOME, target)
    assert "package" in staged.read(target)
    with pytest.raises(ToolError, match="already exists"):
        staged.move("app/src/main/AndroidManifest.xml", "app/build.gradle.kts")


def test_changes_are_the_net_difference_with_checksums(staged):
    staged.edit(STRINGS, "Nothing to do", "Empty")
    staged.write("app/Tmp.kt", "x")
    staged.delete("app/Tmp.kt")  # created then deleted: no net change
    staged.delete(COLORS)
    got = {(c.action, c.path) for c in staged.changes()}
    assert got == {("modify", STRINGS), ("delete", COLORS)}
    assert all(c.base_checksum for c in staged.changes())
    staged.edit(STRINGS, "Empty", "Nothing to do")  # reverted: no net change any more
    assert {c.path for c in staged.changes()} == {COLORS}


def test_protected_and_unsafe_paths_are_refused(staged, put):
    put(".env", "TOKEN=secret")
    for bad in (".env", "../escape.txt", "/etc/passwd"):
        with pytest.raises(ToolError):
            staged.read(bad)
        with pytest.raises(ToolError):
            staged.write(bad, "x")
    assert ".env" not in staged.list_dir("")


def test_secrets_are_masked_in_what_the_model_reads(staged, put):
    put("app/Keys.kt", 'const val KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    fresh = StagedFiles(staged.engine)
    assert "AKIAIOSFODNN7EXAMPLE" not in fresh.read("app/Keys.kt")
    assert "AKIAIOSFODNN7EXAMPLE" not in fresh.search("KEY")


def test_rename_package_rewrites_moves_and_never_touches_the_real_project(staged, ws_root):
    before = (ws_root / HOME).read_text()
    result = staged.rename_package(OLD, NEW)
    assert "files rewritten" in result and "moved" in result
    changes = {c.path: c for c in staged.changes()}
    new_home = "app/src/main/java/com/acme/notes/ui/TodoApp.kt"
    assert new_home in changes and changes[HOME].action == "delete"
    assert "package com.acme.notes.ui" in changes[new_home].content
    assert OLD not in changes[new_home].content
    assert (ws_root / HOME).read_text() == before
    assert not any(OLD in (c.content or "") for c in changes.values())


def test_rename_package_validates_and_reports_leftovers(staged, put):
    with pytest.raises(ToolError, match="at least two"):
        staged.rename_package(OLD, "app")
    with pytest.raises(ToolError, match="reserved"):
        staged.rename_package(OLD, "com.class.x")
    with pytest.raises(ToolError, match="same"):
        staged.rename_package(OLD, OLD)
    with pytest.raises(ToolError, match="inside the old one"):
        staged.rename_package(OLD, OLD + ".sub")
    with pytest.raises(ToolError, match="no file mentions"):
        staged.rename_package("org.nothing.here", "org.other.thing")
    put("app/google-services.json", '{"package_name": "com.example.todo"}')
    fresh = StagedFiles(staged.engine)
    assert "google-services.json" in fresh.rename_package(OLD, NEW)


def test_set_application_id_changes_only_gradle(staged):
    gradle = next(
        p for p in staged.ws.iter_files() if p.endswith("build.gradle.kts") and "app/" in p
    )
    assert "applicationId" in staged.read(gradle)
    assert "applicationId" in staged.set_application_id("com.acme.notes")
    assert {c.path for c in staged.changes()} == {gradle}
    with pytest.raises(ToolError, match="at least two"):
        staged.set_application_id("x")


# ---- Firebase config after a rename ------------------------------------------------------------

import json  # noqa: E402

FIREBASE = {
    "project_info": {"project_number": "123", "project_id": "demo"},
    "client": [
        {
            "client_info": {
                "mobilesdk_app_id": "1:123:android:abc",
                "android_client_info": {"package_name": OLD},
            },
            "api_key": [{"current_key": "AIzaSyDEMO-not-a-real-key-000000000000000"}],
        }
    ],
    "configuration_version": "1",
}


def _clients(text):
    return [c["client_info"]["android_client_info"]["package_name"] for c in json.loads(text)["client"]]


def test_add_firebase_client_copies_the_old_entry_for_the_new_package():
    text = json.dumps(FIREBASE, indent=2) + "\n"
    out = packages.add_firebase_client(text, NEW, [OLD])
    assert _clients(out) == [OLD, NEW] and out.endswith("\n")
    copied = json.loads(out)["client"][1]
    assert copied["api_key"] == FIREBASE["client"][0]["api_key"]  # real keys are kept, not masked
    assert out.startswith('{\n  "project_info"')  # the file's own indent is kept
    assert packages.add_firebase_client(out, NEW, [OLD]) is None  # already there: nothing to add


def test_add_firebase_client_ignores_other_json():
    for text in ('{"package_name": "com.example.todo"}', "not json", '{"client": []}', '{"client": [{}]}'):
        assert packages.add_firebase_client(text, NEW, [OLD]) is None


def test_rename_package_keeps_the_firebase_config_buildable(staged, put):
    put("app/google-services.json", json.dumps(FIREBASE, indent=2))
    fresh = StagedFiles(staged.engine)
    result = fresh.rename_package(OLD, NEW)
    assert "added a Firebase client entry" in result and "register the new package" in result
    assert "still mentioning" not in result or "google-services.json" not in result.split("still mentioning")[1]
    change = next(c for c in fresh.changes() if c.path == "app/google-services.json")
    assert _clients(change.content) == [OLD, NEW]
    assert "AIzaSyDEMO" in change.content and "REDACT" not in change.content.upper()


def test_set_application_id_also_registers_the_new_id_with_firebase(staged, put):
    put("app/google-services.json", json.dumps(FIREBASE, indent=2))
    fresh = StagedFiles(staged.engine)
    result = fresh.set_application_id("com.acme.notes")
    assert "Firebase client entry" in result
    change = next(c for c in fresh.changes() if c.path == "app/google-services.json")
    assert _clients(change.content) == [OLD, "com.acme.notes"]
