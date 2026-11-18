"""False positives found by running the review engine over Google's ``nowinandroid`` (Phase 4a).

Each class of false positive below blocked code that compiles in upstream CI. Every test has a
twin that proves the real error is still reported, so a fix cannot simply switch the rule off.
"""

from sample_project import MAIN, broken, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine, ReviewReport

APP_GRADLE = "app/build.gradle.kts"
CORE_KTX = "    implementation(libs.androidx.core.ktx)\n"


def review(files) -> ReviewReport:
    return ReviewEngine().review(ProjectFiles.from_mapping(files))


def found(files) -> list[tuple[str, str, str]]:
    return sorted((f.rule, f.file.rsplit("/", 1)[-1], f.key) for f in review(files).findings)


def with_files(extra: dict[str, str], base=None) -> dict:
    project = dict(base if base is not None else good_project())
    project.update(extra)
    return project


def kotlin(package: str, *lines: str) -> str:
    return "package " + package + "\n\n" + "\n".join(lines) + "\n"


# --- 1. a project may add files to a library's package ----------------------------------------


def test_project_helper_in_a_framework_package_does_not_hide_the_library():
    # nowinandroid declares `package androidx.test.uiautomator` for extension helpers and also
    # imports the library's own classes from that package.
    files = with_files(
        {
            "app/src/main/java/androidx/test/uiautomator/Helpers.kt": kotlin(
                "androidx.test.uiautomator", "fun helper() {}"
            ),
            f"{MAIN}/UsesLibrary.kt": kotlin(
                "com.example.todo",
                "import androidx.test.uiautomator.By",
                "import androidx.test.uiautomator.UiDevice",
                "",
                "class UsesLibrary",
            ),
        }
    )
    assert found(files) == []


def test_project_helper_in_a_declared_dependencys_package_does_not_hide_the_library():
    files = broken(
        {APP_GRADLE: (CORE_KTX, '    implementation("com.acme.lib:lib:1.0")\n' + CORE_KTX)}
    )
    files = with_files(
        {
            "app/src/main/java/com/acme/lib/Extras.kt": kotlin("com.acme.lib", "fun extra() {}"),
            f"{MAIN}/UsesAcme.kt": kotlin(
                "com.example.todo", "import com.acme.lib.Widget", "", "class UsesAcme"
            ),
        },
        files,
    )
    assert found(files) == []


def test_unknown_import_from_a_project_only_package_is_still_unresolved():
    # Not a framework package and not a declared dependency: nothing else could provide it.
    files = with_files(
        {
            "app/src/main/java/org/mine/helpers/Extras.kt": kotlin(
                "org.mine.helpers", "fun e() {}"
            ),
            f"{MAIN}/UsesMine.kt": kotlin(
                "com.example.todo", "import org.mine.helpers.Missing", "", "class UsesMine"
            ),
        }
    )
    assert found(files) == [
        ("import.unresolved_project", "UsesMine.kt", "org.mine.helpers.Missing")
    ]


def test_typo_inside_the_projects_own_namespace_is_still_unresolved():
    files = with_files(
        {
            f"{MAIN}/Typo.kt": kotlin(
                "com.example.todo", "import com.example.todo.ui.Nope", "class T"
            )
        }
    )
    assert found(files) == [("import.unresolved_project", "Typo.kt", "com.example.todo.ui.Nope")]


# --- 2. members of the generated R class ------------------------------------------------------


def test_importing_a_nested_member_of_the_generated_r_class_is_accepted():
    files = with_files(
        {
            f"{MAIN}/UsesR.kt": kotlin(
                "com.example.todo",
                "import com.example.todo.R.drawable",
                "import com.example.todo.R.string",
                "import com.example.todo.R.string.app_name",
                "",
                "class UsesR",
            )
        }
    )
    assert found(files) == []


def test_import_from_a_misspelled_r_class_is_still_unresolved():
    files = with_files(
        {
            f"{MAIN}/BadR.kt": kotlin(
                "com.example.todo", "import com.example.todo.Rr.string", "class B"
            )
        }
    )
    assert found(files) == [("import.unresolved_project", "BadR.kt", "com.example.todo.Rr.string")]


# --- 3. Kotlin backtick names (test names) ----------------------------------------------------


def test_words_inside_a_backtick_function_name_are_not_code():
    files = with_files(
        {
            "app/src/test/java/com/example/todo/NamesTest.kt": kotlin(
                "com.example.todo",
                "class NamesTest {",
                "    fun `detect replacements of Composable`() {}",
                "    fun `Modifier and Column and Text stay words`() {}",
                "}",
            )
        }
    )
    assert found(files) == []


def test_real_use_of_a_curated_name_next_to_a_backtick_name_is_still_reported():
    files = with_files(
        {
            "app/src/main/java/com/example/todo/Mixed.kt": kotlin(
                "com.example.todo",
                "@Composable",
                "fun `my preview`() {}",
            )
        }
    )
    assert found(files) == [("import.missing", "Mixed.kt", "Composable")]


def test_backtick_names_do_not_unbalance_brackets():
    files = with_files(
        {
            f"{MAIN}/Brackets.kt": kotlin(
                "com.example.todo", "class Brackets {", "    fun `closes ) and } oddly`() {}", "}"
            )
        }
    )
    assert found(files) == []


# --- 4. XML files that are not Android resources ----------------------------------------------

LICENSE_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n<!--\n   Copyright $YEAR Example\n   Licensed under '
    "the Apache License, Version 2.0.\n-->\n"
)


def test_comment_only_xml_outside_resources_is_a_template_not_a_syntax_error():
    # nowinandroid's spotless/copyright.xml is a license-header template with no root element.
    report = review(with_files({"spotless/copyright.xml": LICENSE_HEADER}))
    assert report.findings == [] and not report.has_blocking
    assert report.files_unparsed == []


def test_comment_only_xml_inside_resources_is_still_malformed():
    report = review(with_files({"app/src/main/res/values/empty.xml": LICENSE_HEADER}))
    assert [(f.rule, f.blocking) for f in report.findings] == [("xml.malformed", True)]


def test_comment_only_manifest_is_still_malformed():
    files = with_files({"lib/src/main/AndroidManifest.xml": LICENSE_HEADER})
    assert [f.rule for f in review(files).findings] == ["xml.malformed"]


def test_truncated_xml_outside_resources_is_still_malformed():
    files = with_files({"config/lint.xml": "<lint>\n  <issue id='X'>\n"})
    assert [f.rule for f in review(files).findings] == ["xml.malformed"]
