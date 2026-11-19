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


# --- 5. classes generated from .proto files ---------------------------------------------------

PROTO_MULTIPLE = """syntax = "proto3";

option java_package = "com.example.todo.data";
option java_multiple_files = true;

// message Commented { }
message UserPrefs {
  int32 version = 1;
  message Nested {}
}

enum ThemeBrand { DEFAULT = 0; }
"""

PROTO_SINGLE = """syntax = "proto3";
option java_package = "com.example.todo.data";

message Settings { int32 version = 1; }
"""


def imports_of(*names: str) -> str:
    return kotlin("com.example.todo", *[f"import {n}" for n in names], "", "class Uses")


def test_classes_generated_from_a_proto_with_multiple_files_are_accepted():
    files = with_files(
        {
            "app/src/main/proto/user_prefs.proto": PROTO_MULTIPLE,
            f"{MAIN}/Uses.kt": imports_of(
                "com.example.todo.data.UserPrefs",
                "com.example.todo.data.ThemeBrand",
                "com.example.todo.data.UserPrefs.Nested",
            ),
        }
    )
    assert found(files) == []


def test_names_a_proto_does_not_declare_are_still_unresolved():
    files = with_files(
        {
            "app/src/main/proto/user_prefs.proto": PROTO_MULTIPLE,
            f"{MAIN}/Uses.kt": imports_of(
                "com.example.todo.data.Commented",  # only appears in a comment
                "com.example.todo.data.Missing",
            ),
        }
    )
    assert found(files) == [
        ("import.unresolved_project", "Uses.kt", "com.example.todo.data.Commented"),
        ("import.unresolved_project", "Uses.kt", "com.example.todo.data.Missing"),
    ]


def test_without_multiple_files_the_messages_live_inside_the_outer_class():
    files = with_files(
        {
            "app/src/main/proto/settings_store.proto": PROTO_SINGLE,
            f"{MAIN}/Uses.kt": imports_of(
                "com.example.todo.data.SettingsStore",
                "com.example.todo.data.SettingsStore.Settings",
            ),
        }
    )
    assert found(files) == []
    twin = with_files(
        {
            "app/src/main/proto/settings_store.proto": PROTO_SINGLE,
            f"{MAIN}/Uses.kt": imports_of("com.example.todo.data.Settings"),
        }
    )
    assert found(twin) == [
        ("import.unresolved_project", "Uses.kt", "com.example.todo.data.Settings")
    ]


def test_proto_outer_class_name_option_and_package_fallback():
    proto = (
        'syntax = "proto3";\npackage com.example.todo.data;\n'
        'option java_outer_classname = "Wire";\nmessage Ping {}\n'
    )
    files = with_files(
        {
            "app/src/main/proto/ping.proto": proto,
            f"{MAIN}/Uses.kt": imports_of("com.example.todo.data.Wire.Ping"),
        }
    )
    assert found(files) == []


# --- 6. icon imports: extension properties that differ by receiver ----------------------------

ICON_IMPORTS = (
    "import androidx.compose.material.icons.Icons",
    "import androidx.compose.material.icons.outlined.Bookmarks",
    "import androidx.compose.material.icons.rounded.Bookmarks",
)


def test_same_named_icons_from_two_styles_are_not_a_conflict():
    files = with_files(
        {
            f"{MAIN}/Icn.kt": kotlin(
                "com.example.todo",
                *ICON_IMPORTS,
                "",
                "object Icn {",
                "    val a = Icons.Rounded.Bookmarks",
                "    val b = Icons.Outlined.Bookmarks",
                "}",
            )
        }
    )
    assert found(files) == []


def test_icon_of_a_style_that_is_not_imported_is_still_missing():
    files = with_files(
        {
            f"{MAIN}/Icn.kt": kotlin(
                "com.example.todo",
                "import androidx.compose.material.icons.Icons",
                "import androidx.compose.material.icons.rounded.Bookmarks",
                "",
                "object Icn { val b = Icons.Outlined.Bookmarks }",
            )
        }
    )
    assert found(files) == [
        ("import.missing", "Icn.kt", "androidx.compose.material.icons.outlined.Bookmarks")
    ]


def test_two_classes_with_the_same_simple_name_still_conflict():
    files = with_files(
        {
            f"{MAIN}/Dates.kt": kotlin(
                "com.example.todo", "import java.sql.Date", "import java.util.Date", "", "class D"
            )
        }
    )
    assert found(files) == [("import.conflicting", "Dates.kt", "Date")]


# --- 7. calls that may be members of an implicit receiver -------------------------------------


def _call_in(body: str) -> dict:
    return with_files(
        {f"{MAIN}/Receiver.kt": kotlin("com.example.todo", "class R(val rule: Any) {", body, "}")}
    )


def test_call_inside_apply_run_or_with_may_be_a_member_of_the_receiver():
    for body in (
        "    fun a() { rule.apply { setContent { } } }",
        "    fun b() { rule.run { setContent { } } }",
        "    fun c() { with(rule) { setContent { } } }",
        "    fun d() = rule.apply {\n        helper()\n        setContent {\n        }\n    }",
    ):
        assert found(_call_in(body)) == [], body


def test_bare_call_without_a_receiver_scope_is_still_missing():
    for body in (
        "    fun a() { setContent { } }",
        "    fun b() { rule.let { setContent { } } }",
        "    fun c() { rule.apply { } ; setContent { } }",
    ):
        assert found(_call_in(body)) == [("import.missing", "Receiver.kt", "setContent")], body


# --- 8. Gradle facts that later rules will rely on --------------------------------------------


def analysis(files):
    from androai_codegen.review import ReviewConfig
    from androai_codegen.review.analysis import ProjectAnalysis

    return ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig())


BUNDLE = '[bundles]\nui = ["androidx-ui", "androidx-material3"]\n\n[plugins]'


def test_catalog_bundle_resolves_to_its_libraries():
    files = broken(
        {
            "gradle/libs.versions.toml": ("[plugins]", BUNDLE),
            APP_GRADLE: (CORE_KTX, CORE_KTX + "    implementation(libs.bundles.ui)\n"),
        }
    )
    a = analysis(files)
    assert [d for d in a.dependencies if d.unresolved_alias] == []
    members = {d.coordinate for d in a.dependencies if d.dep.alias == "libs.bundles.ui"}
    assert members == {"androidx.compose.ui:ui", "androidx.compose.material3:material3"}


def test_unknown_bundle_is_still_unresolved():
    files = broken({APP_GRADLE: (CORE_KTX, CORE_KTX + "    implementation(libs.bundles.nope)\n")})
    assert [d.dep.alias for d in analysis(files).dependencies if d.unresolved_alias] == [
        "libs.bundles.nope"
    ]


def _catalog_settings(body: str) -> dict:
    return with_files(
        {
            "build-logic/settings.gradle.kts": "dependencyResolutionManagement {\n"
            f"    versionCatalogs {{\n{body}\n    }}\n}}\n"
        }
    )


def test_pointing_libs_at_the_default_catalog_file_is_not_a_custom_catalog():
    body = '    create("libs") {\n        from(files("../gradle/libs.versions.toml"))\n    }'
    assert analysis(_catalog_settings(body)).custom_catalogs is False


def test_a_second_or_remote_catalog_is_custom():
    other = '    create("testLibs") {\n        from(files("../gradle/test.versions.toml"))\n    }'
    remote = '    create("libs") {\n        from("com.example:catalog:1.0")\n    }'
    assert analysis(_catalog_settings(other)).custom_catalogs is True
    assert analysis(_catalog_settings(remote)).custom_catalogs is True


def test_included_build_and_the_root_are_not_modules_of_a_multi_module_project():
    settings = good_project()["settings.gradle.kts"]
    files = with_files(
        {
            "settings.gradle.kts": settings.replace(
                "pluginManagement {\n", 'pluginManagement {\n    includeBuild("build-logic")\n', 1
            ),
            "build-logic/settings.gradle.kts": 'rootProject.name = "build-logic"\n',
            "build-logic/convention/build.gradle.kts": "plugins { `kotlin-dsl` }\n",
        }
    )
    assert analysis(files).modules == frozenset({"app"})


def test_single_module_project_keeps_the_root_as_its_module():
    files = {"settings.gradle.kts": 'rootProject.name = "x"\n', "build.gradle.kts": "plugins {}\n"}
    assert analysis(files).modules == frozenset({""})
