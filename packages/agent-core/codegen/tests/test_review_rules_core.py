"""Syntax, imports and resources rules: break a known-good project one way at a time."""

import pytest
from sample_project import MAIN, broken, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine, ReviewReport

TODO_APP = f"{MAIN}/ui/TodoApp.kt"
VIEW_MODEL = f"{MAIN}/ui/TodoViewModel.kt"
MAIN_ACTIVITY = f"{MAIN}/MainActivity.kt"
STRINGS_JAVA = f"{MAIN}/util/Strings.java"
MANIFEST = "app/src/main/AndroidManifest.xml"
STRINGS_XML = "app/src/main/res/values/strings.xml"


def review(files, **kwargs) -> ReviewReport:
    return ReviewEngine(kwargs.pop("config", None)).review(
        ProjectFiles.from_mapping(files), **kwargs
    )


def found(files, **kwargs) -> list[tuple[str, str, str]]:
    """(rule, file name, key) for every finding, sorted: the whole picture, not a subset."""
    report = review(files, **kwargs)
    return sorted((f.rule, f.file.rsplit("/", 1)[-1], f.key) for f in report.findings)


def drop_line(path: str, line: str) -> dict:
    return broken({path: (line + "\n", "")})


def drop_lines(path: str, *lines: str) -> dict:
    """The good project without several lines of one file (``broken`` allows one edit per path)."""
    project = good_project()
    text = project[path]
    for line in lines:
        assert text.count(line + "\n") == 1, line
        text = text.replace(line + "\n", "")
    project[path] = text
    return project


def test_the_known_good_project_has_no_findings():
    report = review(good_project())
    assert report.findings == [] and not report.has_blocking
    assert report.scope == "static" and report.files_reviewed == 18 and report.files_unparsed == []
    assert any("not compile" in text for text in report.limitations)


# --- missing imports: types ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("import_line", "name"),
    [
        ("import androidx.compose.material3.Text", "Text"),
        ("import androidx.compose.runtime.Composable", "Composable"),
        ("import androidx.compose.ui.Modifier", "Modifier"),
        ("import androidx.compose.foundation.layout.Column", "Column"),
        ("import androidx.compose.foundation.lazy.LazyColumn", "LazyColumn"),
        ("import androidx.compose.material3.Scaffold", "Scaffold"),
        ("import androidx.navigation.compose.NavHost", "NavHost"),
    ],
)
def test_missing_type_imports_are_found(import_line, name):
    assert found(drop_line(TODO_APP, import_line)) == [("import.missing", "TodoApp.kt", name)]


def test_missing_import_message_suggests_the_exact_import():
    report = review(drop_line(TODO_APP, "import androidx.compose.material3.Button"))
    [item] = report.findings
    assert item.blocking and item.severity == "error" and item.line is not None
    assert item.suggested_fix.startswith("Add `import androidx.compose.material3.Button`")
    assert "androidx.compose.material." in item.suggested_fix  # the Material 2 alternative


def test_project_classes_in_other_packages_need_an_import():
    files = drop_line(VIEW_MODEL, "import com.example.todo.data.TaskDao")
    [item] = review(files).findings
    assert (item.rule, item.key) == ("import.missing", "TaskDao")
    assert item.suggested_fix.startswith("Add `import com.example.todo.data.TaskDao`")


def test_classes_in_the_same_package_and_top_level_values_need_no_import():
    # Theme.kt uses Purple80/Pink80 (top-level vals) and Color.kt's package without importing
    assert found(good_project()) == []


def test_wildcard_and_alias_imports_resolve():
    wildcard = broken(
        {
            TODO_APP: (
                "import androidx.compose.material3.Button\n"
                "import androidx.compose.material3.Icon\n"
                "import androidx.compose.material3.Scaffold\n"
                "import androidx.compose.material3.Text\n",
                "import androidx.compose.material3.*\n",
            )
        }
    )
    assert found(wildcard) == []
    aliased = broken(
        {
            VIEW_MODEL: (
                "import com.example.todo.data.Task\n",
                "import com.example.todo.data.Task as Task\n",
            )
        }
    )
    assert found(aliased) == []


def test_default_imports_are_never_reported():
    files = good_project()
    files[f"{MAIN}/ui/Plain.kt"] = (
        "package com.example.todo.ui\n\n"
        "fun f(a: List<String>, m: Map<String, Int>): Pair<Int, Int> {\n"
        "    val s = StringBuilder(); val e = IllegalStateException(); val r: Result<Int>? = null\n"
        "    return Pair(a.size, m.size)\n}\n"
    )
    assert found(files) == []


def crlf(files: dict) -> dict:
    """The same project as Windows would store it: CRLF line endings in every text file."""
    return {
        path: content.replace("\n", "\r\n") if isinstance(content, str) else content
        for path, content in files.items()
    }


def test_crlf_line_endings_make_no_difference():
    # The known-good project must stay clean, and a broken one must give the same findings.
    assert review(crlf(good_project())).findings == []
    broken_lf = drop_line(TODO_APP, "import androidx.compose.material3.Text")
    assert found(crlf(broken_lf)) == found(broken_lf) == [("import.missing", "TodoApp.kt", "Text")]
    # line numbers are those of the file as the user sees it
    [lf] = review(broken_lf).findings
    [windows] = review(crlf(broken_lf)).findings
    assert (windows.line, windows.column) == (lf.line, lf.column)


def test_crlf_gradle_toml_and_xml_are_also_fine():
    files = crlf(
        broken({MANIFEST: ('android:label="@string/app_name"', 'android:label="@string/x"')})
    )
    assert found(files) == [("resource.unresolved", "AndroidManifest.xml", "string/x")]
    assert [f for f in review(crlf(good_project())).findings if f.category == "syntax"] == []


def test_a_project_class_never_shadows_a_default_import():
    files = good_project()
    files[f"{MAIN}/data/Result.kt"] = "package com.example.todo.data\n\nclass Result\n"
    files[f"{MAIN}/ui/Uses.kt"] = (
        "package com.example.todo.ui\n\nfun f(r: Result<Int>): Int = r.getOrDefault(0)\n"
    )
    # kotlin.Result is visible everywhere; the project's Result is in another package
    assert found(files) == []


def test_text_in_comments_and_strings_never_triggers_import_rules():
    files = good_project()
    files[f"{MAIN}/ui/Notes.kt"] = (
        "package com.example.todo.ui\n\n"
        "// uses Text( and Modifier.padding(1.dp) and remember { }\n"
        "/* LazyColumn { items(x) } */\n"
        'val doc = "Scaffold { Text(stringResource(R.string.x)) } 8.dp"\n'
    )
    assert found(files) == []


# --- missing imports: calls and extensions ---------------------------------------------------


@pytest.mark.parametrize(
    ("path", "import_line", "key"),
    [
        (TODO_APP, "import androidx.compose.runtime.remember", "remember"),
        (TODO_APP, "import androidx.compose.runtime.mutableStateOf", "mutableStateOf"),
        (TODO_APP, "import androidx.navigation.compose.composable", "composable"),
        (
            TODO_APP,
            "import androidx.navigation.compose.rememberNavController",
            "rememberNavController",
        ),
        (TODO_APP, "import androidx.compose.foundation.lazy.items", "items"),
        (TODO_APP, "import androidx.compose.ui.res.stringResource", "stringResource"),
        (TODO_APP, "import androidx.compose.foundation.layout.padding", "padding"),
        (TODO_APP, "import androidx.compose.foundation.layout.fillMaxSize", "fillMaxSize"),
        (TODO_APP, "import androidx.compose.foundation.layout.height", "height"),
        (TODO_APP, "import androidx.compose.ui.unit.dp", "dp"),
        (TODO_APP, "import androidx.compose.runtime.getValue", "getValue"),
        (TODO_APP, "import androidx.compose.runtime.setValue", "setValue"),
        (
            TODO_APP,
            "import androidx.compose.material.icons.filled.Add",
            "androidx.compose.material.icons.filled.Add",
        ),
        (MAIN_ACTIVITY, "import androidx.activity.compose.setContent", "setContent"),
        (VIEW_MODEL, "import androidx.lifecycle.viewModelScope", "viewModelScope"),
        (VIEW_MODEL, "import kotlinx.coroutines.launch", "launch"),
        (VIEW_MODEL, "import kotlinx.coroutines.flow.stateIn", "stateIn"),
    ],
)
def test_missing_call_and_extension_imports_are_found(path, import_line, key):
    assert found(drop_line(path, import_line)) == [("import.missing", path.rsplit("/", 1)[-1], key)]


def test_modifier_extensions_are_only_checked_in_modifier_files():
    files = good_project()
    files[f"{MAIN}/util/Geometry.kt"] = (
        "package com.example.todo.util\n\n"
        "class Rect(val w: Int) { fun width() = w }\n"
        "fun f(r: Rect) = r.width() + listOf(1).size\n"
    )
    assert found(files) == []
    # A Compose file that never mentions Modifier: `.padding(4)` here is some other type's
    # member (it looks exactly like the Modifier extension) and must not demand an import.
    files[f"{MAIN}/util/Spacing.kt"] = (
        "package com.example.todo.util\n\n"
        "import androidx.compose.material3.Text\n\n"
        "fun f(text: StringBuilder) = text.padding(4)\n"
    )
    assert found(files) == []
    # The same call in a file that does use Modifier is checked.
    files[f"{MAIN}/util/Spacing.kt"] = (
        "package com.example.todo.util\n\n"
        "import androidx.compose.ui.Modifier\n\n"
        "fun f(m: Modifier) = m.padding(4)\n"
    )
    assert found(files) == [("import.missing", "Spacing.kt", "padding")]


def test_a_project_function_with_the_same_name_is_not_flagged():
    files = good_project()
    files[f"{MAIN}/util/Own.kt"] = (
        "package com.example.todo.util\n\nfun delay(ms: Int) = ms\nfun use() = delay(5)\n"
    )
    assert found(files) == []


def test_compose_only_helpers_are_not_demanded_in_plain_kotlin():
    files = good_project()
    files[f"{MAIN}/util/Plain.kt"] = "package com.example.todo.util\n\nfun f() { remember { 1 } }\n"
    assert found(files) == []


# --- missing R, unresolved project imports, duplicates, literals ----------------------------


def test_missing_r_import_in_a_subpackage():
    [item] = review(drop_line(TODO_APP, "import com.example.todo.R")).findings
    assert (item.rule, item.key) == ("import.missing_r", "R")
    assert item.suggested_fix == "Add `import com.example.todo.R`."


def test_r_needs_no_import_in_the_namespace_package_or_with_android_r():
    files = good_project()
    files[f"{MAIN}/Util.kt"] = "package com.example.todo\n\nval x = R.string.app_name\n"
    files[f"{MAIN}/ui/Framework.kt"] = (
        "package com.example.todo.ui\n\nimport android.R\n\nval x = R.id.content\n"
    )
    assert found(files) == []


def test_import_of_a_project_class_that_does_not_exist():
    files = broken(
        {
            VIEW_MODEL: (
                "import com.example.todo.data.Task\n",
                "import com.example.todo.data.Task\nimport com.example.todo.data.Missing\n",
            )
        }
    )
    assert found(files) == [
        ("import.unresolved_project", "TodoViewModel.kt", "com.example.todo.data.Missing")
    ]


def test_import_of_a_package_inside_the_app_namespace_that_has_no_sources():
    files = broken(
        {
            VIEW_MODEL: (
                "import com.example.todo.data.Task\n",
                "import com.example.todo.data.Task\nimport com.example.todo.nowhere.Thing\n",
            )
        }
    )
    assert found(files) == [
        ("import.unresolved_project", "TodoViewModel.kt", "com.example.todo.nowhere.Thing")
    ]


def test_members_generated_code_and_libraries_are_not_unresolved_imports():
    files = good_project()
    files[f"{MAIN}/data/Const.kt"] = (
        "package com.example.todo.data\n\nobject Const { const val BASE = 1 }\n"
    )
    files[f"{MAIN}/ui/Uses.kt"] = (
        "package com.example.todo.ui\n\n"
        "import com.example.todo.data.Const.BASE\n"  # member of a project object
        "import com.example.todo.databinding.ActivityMainBinding\n"  # generated
        "import com.example.todo.BuildConfig\n"  # generated
        "import com.example.todo.ui.theme.Purple80\n"  # top-level val
        "import okhttp3.OkHttpClient\n"  # library
        "import com.thirdparty.Whatever\n\nval x = BASE\n"
    )
    assert found(files) == []


def test_duplicate_top_level_class_across_files():
    files = good_project()
    files[f"{MAIN}/data/Aaa.kt"] = "package com.example.todo.data\n\nclass Task\n"
    report = review(files)
    assert sorted((f.file.rsplit("/", 1)[-1], f.rule, f.key) for f in report.findings) == [
        ("Aaa.kt", "class.duplicate", "com.example.todo.data.Task"),
        ("Task.kt", "class.duplicate", "com.example.todo.data.Task"),
    ]  # the newly added file sorts first, yet the original is named as well
    assert all("also in" in f.description for f in report.findings)


def test_same_name_in_different_source_sets_or_private_is_not_a_duplicate():
    files = good_project()
    files["app/src/debug/java/com/example/todo/data/Task.kt"] = (
        "package com.example.todo.data\n\nclass Task\n"
    )
    files[f"{MAIN}/data/A.kt"] = "package com.example.todo.data\n\nprivate class Helper\n"
    files[f"{MAIN}/data/B.kt"] = "package com.example.todo.data\n\nprivate class Helper\n"
    assert found(files) == []


def test_conflicting_and_duplicate_imports():
    files = broken(
        {
            VIEW_MODEL: (
                "import com.example.todo.data.Task\n",
                "import com.example.todo.data.Task\n"
                "import com.example.todo.data.Task\n"
                "import other.pkg.Task\n",
            )
        }
    )
    assert found(files) == [
        ("import.conflicting", "TodoViewModel.kt", "Task"),
        ("import.duplicate", "TodoViewModel.kt", "com.example.todo.data.Task"),
    ]


def test_unresolved_class_literal():
    files = broken(
        {VIEW_MODEL: ("fun add(", "val ghost = GhostActivity::class.java\n\n    fun add(")}
    )
    assert found(files) == [("reference.unresolved_class", "TodoViewModel.kt", "GhostActivity")]


def test_class_literal_is_not_reported_when_it_could_come_from_a_wildcard_we_cannot_see():
    files = broken(
        {VIEW_MODEL: ("fun add(", "val ghost = GhostActivity::class.java\n\n    fun add(")}
    )
    files[VIEW_MODEL] = files[VIEW_MODEL].replace(
        "import com.example.todo.data.Task\n",
        "import com.example.todo.data.Task\nimport com.thirdparty.widgets.*\n",
    )
    assert found(files) == []


def test_class_literal_of_a_known_class_is_an_import_problem_not_an_unresolved_one():
    files = broken({VIEW_MODEL: ("import com.example.todo.data.Task\n", "")})
    files[VIEW_MODEL] = files[VIEW_MODEL].replace(
        "fun add(", "val k = Task::class.java\n\n    fun add("
    )
    assert {r for r, _, _ in found(files)} == {"import.missing"}


def test_java_missing_import():
    assert found(drop_line(STRINGS_JAVA, "import java.util.List;")) == [
        ("import.missing", "Strings.java", "List")
    ]
    assert found(drop_line(STRINGS_JAVA, "import java.util.Locale;")) == [
        ("import.missing", "Strings.java", "Locale")
    ]


# --- resources ---------------------------------------------------------------------------------


def test_unresolved_code_resource_with_a_suggestion():
    files = broken({TODO_APP: ("R.string.app_name", "R.string.app_nam")})
    [item] = review(files).findings
    assert (item.rule, item.key) == ("resource.unresolved", "string/app_nam")
    assert "Did you mean: app_name" in item.suggested_fix and item.blocking


def test_unresolved_xml_resource_references():
    files = broken(
        {MANIFEST: ('android:label="@string/app_name"', 'android:label="@string/no_such"')}
    )
    assert found(files) == [("resource.unresolved", "AndroidManifest.xml", "string/no_such")]
    files = broken(
        {
            MANIFEST: (
                'android:theme="@style/Theme.Todo">\n        <activity',
                'android:theme="@style/Theme.Missing">\n        <activity',
            )
        }
    )
    assert ("resource.unresolved", "AndroidManifest.xml", "style/Theme.Missing") in found(files)


def test_library_framework_and_attribute_references_are_not_unresolved():
    files = good_project()
    files["app/src/main/res/layout/screen.xml"] = (
        '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android" '
        'xmlns:app="http://schemas.android.com/apk/res-auto" '
        'android:layout_width="match_parent" android:layout_height="match_parent" '
        'android:background="@android:color/white" '
        'android:theme="@style/Theme.Material3.DayNight">\n'
        '  <TextView android:id="@+id/title" android:textColor="?attr/colorPrimary" '
        'android:text="@string/app_name" '
        'android:drawableStart="@drawable/abc_ic_menu_overflow_material"/>\n'
        '  <TextView android:id="@+id/other" app:layout_constraintTop_toBottomOf="@id/title" '
        'android:textColor="@color/purple_500"/>\n'
        "</LinearLayout>\n"
    )
    assert found(files) == []


def test_reference_to_an_undefined_id_and_a_defined_one():
    files = good_project()
    files["app/src/main/res/layout/screen.xml"] = (
        '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <View android:id="@+id/title"/>\n  <View android:labelFor="@id/title"/>\n'
        '  <View android:labelFor="@id/ghost"/>\n</FrameLayout>\n'
    )
    assert found(files) == [("resource.unresolved", "screen.xml", "id/ghost")]


def test_code_can_use_ids_and_layouts_defined_in_xml():
    files = good_project()
    files["app/src/main/res/layout/screen.xml"] = (
        '<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android">'
        '<View android:id="@+id/title"/></FrameLayout>\n'
    )
    files[f"{MAIN}/Legacy.kt"] = (
        "package com.example.todo\n\n"
        "fun f() = listOf(R.layout.screen, R.id.title, R.mipmap.ic_launcher)\n"
    )
    assert found(files) == []


def test_duplicate_resources_in_one_directory_only():
    files = good_project()
    files["app/src/main/res/values/more.xml"] = (
        '<resources><string name="app_name">Again</string></resources>\n'
    )
    files["app/src/main/res/values-night/strings.xml"] = (
        '<resources><string name="app_name">Night</string></resources>\n'
    )
    files["app/src/debug/res/values/strings.xml"] = (
        '<resources><string name="app_name">Debug</string></resources>\n'
    )
    # both definitions are reported (the new file may sort before the original); the
    # values-night and debug-source-set definitions are legitimate overrides
    assert found(files) == [
        ("resource.duplicate", "more.xml", "string/app_name"),
        ("resource.duplicate", "strings.xml", "string/app_name"),
    ]


def test_invalid_resource_names():
    files = good_project()
    files["app/src/main/res/drawable/MyIcon.png"] = b"\x89PNG"
    files["app/src/main/res/values/bad.xml"] = (
        '<resources><string name="my-string">x</string></resources>\n'
    )
    assert found(files) == [
        ("resource.invalid_name", "MyIcon.png", "drawable/MyIcon.png"),
        ("resource.invalid_name", "bad.xml", "string/my-string"),
    ]


def test_a_sources_only_snapshot_does_not_flood_with_resource_errors():
    files = {f"{MAIN}/ui/A.kt": "package com.example.todo.ui\n\nval a = R.string.anything\n"}
    assert [f for f in review(files).findings if f.category == "resources"] == []


# --- syntax ----------------------------------------------------------------------------------


def test_unterminated_string_and_unbalanced_braces():
    files = broken(
        {VIEW_MODEL: ("fun add(title: String) {", 'fun add(title: String) { val s = "oops')}
    )
    assert found(files)[0] == (
        "syntax.unterminated_string",
        "TodoViewModel.kt",
        "unterminated_string",
    )
    files = broken(
        {
            VIEW_MODEL: (
                "        viewModelScope.launch { dao.insert(Task(title = title)) }\n",
                "        viewModelScope.launch { dao.insert(Task(title = title)) \n",
            )
        }
    )
    assert found(files) == [("syntax.unbalanced_brackets", "TodoViewModel.kt", "unclosed:{")]


def test_unbalanced_brackets_in_strings_and_comments_are_fine():
    files = broken({VIEW_MODEL: ("fun add(", '// ((( {{{\n    val s = "}}} ))))"\n\n    fun add(')})
    assert found(files) == []


def test_a_malformed_resource_file_does_not_cause_a_cascade_of_unresolved_references():
    files = broken({STRINGS_XML: ("</resources>", "</wrong>")})
    report = review(files)
    # app_name/add_task live in the broken file: blaming every @string/R.string user would be noise
    assert [(f.rule, f.file.rsplit("/", 1)[-1]) for f in report.findings] == [
        ("xml.malformed", "strings.xml")
    ]
    assert report.files_unparsed == [STRINGS_XML]
    # other resource types are still checked
    files[f"{MAIN}/ui/Colors.kt"] = (
        "package com.example.todo.ui\n\nval c = com.example.todo.R.color.ghost\n"
    )
    files[f"{MAIN}/ui/Colors.kt"] = "package com.example.todo\n\nval c = R.color.ghost\n"
    assert ("resource.unresolved", "Colors.kt", "color/ghost") not in found(
        files
    )  # color is a value type
    files[f"{MAIN}/Layouts.kt"] = "package com.example.todo\n\nval l = R.layout.ghost\n"
    assert ("resource.unresolved", "Layouts.kt", "layout/ghost") in found(files)


def test_malformed_xml_toml_and_gradle():
    files = broken({STRINGS_XML: ("</resources>", "</wrong>")})
    report = review(files)
    assert report.files_unparsed == [STRINGS_XML]
    files = broken({"gradle/libs.versions.toml": ("[plugins]", "[plugins")})
    report = review(files)
    assert [f.rule for f in report.findings][0] == "toml.malformed" and report.files_unparsed
    files = broken(
        {"app/build.gradle.kts": ("dependencies {", 'dependencies {\n    implementation("a:b:1"')}
    )
    [item] = [f for f in review(files).findings if f.category == "syntax"]
    assert item.key == "mismatched:}"
    # the message names the bracket that is actually unclosed and where it is
    open_line = files["app/build.gradle.kts"].splitlines().index('    implementation("a:b:1"') + 1
    assert "does not match '('" in item.description and f"line {open_line}" in item.description


def test_doctype_in_xml_is_reported_not_expanded():
    files = broken({STRINGS_XML: ("<resources>", '<!DOCTYPE r [<!ENTITY x "y">]><resources>')})
    [item] = review(files).findings
    assert item.rule == "xml.malformed" and "not allowed" in item.description


def test_groovy_gradle_scripts_are_lexed_as_groovy():
    files = good_project()
    files["lib/build.gradle"] = (
        "plugins { id 'com.android.library' }\nandroid { namespace 'com.example.lib' }\n"
        "dependencies { implementation 'androidx.core:core-ktx:1.15.0' // a dep\n}\n"
    )
    assert [f for f in review(files).findings if f.category == "syntax"] == []


# --- engine behaviour -------------------------------------------------------------------------


def test_only_new_findings_are_reported_when_a_before_state_exists():
    before = broken({TODO_APP: ("import androidx.compose.material3.Button\n", "")})
    after = broken({TODO_APP: ("import androidx.compose.material3.Button\n", "")})
    report = review(after, before=ProjectFiles.from_mapping(before))
    assert report.findings == [] and report.preexisting_suppressed == 1
    worse = drop_lines(
        TODO_APP,
        "import androidx.compose.material3.Button",
        "import androidx.compose.material3.Text",
    )
    report = review(worse, before=ProjectFiles.from_mapping(before))
    assert [f.key for f in report.findings] == ["Text"] and report.preexisting_suppressed == 1


def test_findings_that_move_to_another_line_are_still_the_same_finding():
    before = broken({TODO_APP: ("import androidx.compose.material3.Button\n", "")})
    shifted = dict(before)
    shifted[TODO_APP] = "// added comment\n// another\n" + before[TODO_APP]
    report = review(shifted, before=ProjectFiles.from_mapping(before))
    assert report.findings == [] and report.preexisting_suppressed == 1


def test_report_is_sorted_capped_and_filterable():
    files = good_project()
    names = "".join(f"import com.example.todo.ghost.G{i}\n" for i in range(60))
    files[VIEW_MODEL] = files[VIEW_MODEL].replace(
        "import com.example.todo.data.Task\n", "import com.example.todo.data.Task\n" + names
    )
    report = review(files, config=ReviewConfig(max_findings_per_rule=10))
    assert len(report.findings) == 10 and report.omitted == 50
    assert "50 further findings omitted" in report.summary()
    assert (
        review(
            files, config=ReviewConfig(disabled_rules=frozenset({"import.unresolved_project"}))
        ).findings
        == []
    )


def test_blocking_findings_sort_before_non_blocking_ones_whatever_their_severity():
    from androai_codegen.review.models import Severity, finding

    warning_but_blocking = finding(
        Severity.WARNING, "x.warn", "t", "a.kt", "w", line=1, blocking=True
    )
    error_but_not_blocking = finding(
        Severity.ERROR, "x.err", "t", "a.kt", "e", line=2, blocking=False
    )
    ordered = ReviewEngine._sorted([error_but_not_blocking, warning_but_blocking])
    assert [f.rule for f in ordered] == ["x.warn", "x.err"]
    # among equals: higher severity first, then file and line
    info = finding(Severity.INFO, "x.info", "t", "a.kt", "i", line=1)
    error = finding(Severity.ERROR, "x.error", "t", "b.kt", "e", line=1)
    assert [f.rule for f in ReviewEngine._sorted([info, error])] == ["x.error", "x.info"]


def test_real_reports_list_blocking_findings_first():
    files = drop_line(TODO_APP, "import androidx.compose.material3.Button")
    files[VIEW_MODEL] = files[VIEW_MODEL].replace(
        "import com.example.todo.data.Task\n",
        "import com.example.todo.data.Task\nimport com.example.todo.data.Task\n",
    )  # a non-blocking duplicate-import warning next to the blocking missing import
    report = review(files)
    assert [f.blocking for f in report.findings] == [True, False]


def test_a_crashing_rule_group_is_reported_not_fatal(monkeypatch):
    from androai_codegen.review import engine as engine_module
    from androai_codegen.review.rules import resources

    def boom(_analysis):
        raise RuntimeError("bug in a rule")

    monkeypatch.setattr(resources, "check", boom)
    files = drop_line(TODO_APP, "import androidx.compose.material3.Text")
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    rules = {f.rule for f in report.findings}
    assert "import.missing" in rules  # other groups still ran
    assert "review.internal_error" in rules
    assert any("could not be fully evaluated" in text for text in report.limitations)
    assert engine_module  # silence unused import


def test_review_is_fast_on_a_large_project():
    import time

    files = good_project()
    for i in range(1500):
        files[f"{MAIN}/gen/C{i}.kt"] = (
            f"package com.example.todo.gen\n\nimport com.example.todo.data.Task\n\n"
            f'class Gen{i}(val t: Task) {{ fun f() = "v${{t.id}}" }}\n'
        )
    started = time.perf_counter()
    report = review(files)
    assert report.findings == []
    assert time.perf_counter() - started < 20
