"""False positives found by running the review engine over google/iosched (Phase 4a, third project).

iosched uses Hilt, Data Binding, a multi-module Kotlin build and declares its dependencies as
constants in ``buildSrc`` rather than in a version catalog. Every defect below has a twin proving
that the genuine error is still reported.
"""

from sample_project import MAIN, broken, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine, ReviewReport
from androai_codegen.review.analysis import ProjectAnalysis

APP_GRADLE = "app/build.gradle.kts"
CORE_KTX = "    implementation(libs.androidx.core.ktx)\n"
LAYOUT = "app/src/main/res/layout/screen.xml"
LIBS = "buildSrc/src/main/java/Libs.kt"


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


# --- 1. extension properties and functions with a generic receiver ----------------------------

RESULT_KT = kotlin(
    "com.example.todo.result",
    "sealed class Result<out R>",
    "val Result<*>.succeeded get() = this is Result<*>",
    "val <T> List<T>.second get() = this[1]",
    "val Map<String, Int>.total get() = values.sum()",
    "fun Result<*>.isDone() = true",
)


def test_imports_of_extension_members_with_generic_receivers_resolve():
    files = with_files(
        {
            f"{MAIN}/result/Result.kt": RESULT_KT,
            f"{MAIN}/Uses.kt": kotlin(
                "com.example.todo",
                "import com.example.todo.result.isDone",
                "import com.example.todo.result.second",
                "import com.example.todo.result.succeeded",
                "import com.example.todo.result.total",
                "",
                "class Uses",
            ),
        }
    )
    assert found(files) == []


def test_import_of_an_extension_that_does_not_exist_is_still_unresolved():
    files = with_files(
        {
            f"{MAIN}/result/Result.kt": RESULT_KT,
            f"{MAIN}/Uses.kt": kotlin(
                "com.example.todo", "import com.example.todo.result.failed", "", "class Uses"
            ),
        }
    )
    assert found(files) == [
        ("import.unresolved_project", "Uses.kt", "com.example.todo.result.failed")
    ]


# --- 2. importing a function and a class (or two functions) of the same name ------------------


def test_a_project_extension_function_and_a_class_of_the_same_name_do_not_conflict():
    files = with_files(
        {
            f"{MAIN}/testing/Rule.kt": kotlin(
                "com.example.todo.testing",
                "import kotlinx.coroutines.CoroutineScope",
                "class Rule",
                "fun Rule.CoroutineScope(): CoroutineScope = TODO()",
            ),
            f"{MAIN}/Uses.kt": kotlin(
                "com.example.todo",
                "import com.example.todo.testing.CoroutineScope",
                "import kotlinx.coroutines.CoroutineScope",
                "",
                "class Uses",
            ),
        }
    )
    assert found(files) == []


def test_same_named_functions_from_two_packages_are_overloads_not_a_conflict():
    files = with_files(
        {
            f"{MAIN}/Uses.kt": kotlin(
                "com.example.todo",
                "import kotlin.collections.first",
                "import kotlinx.coroutines.flow.first",
                "",
                "class Uses",
            )
        }
    )
    assert found(files) == []


def test_two_project_classes_with_the_same_simple_name_still_conflict():
    files = with_files(
        {
            f"{MAIN}/a/Item.kt": kotlin("com.example.todo.a", "class Item"),
            f"{MAIN}/b/Item.kt": kotlin("com.example.todo.b", "class Item"),
            f"{MAIN}/Uses.kt": kotlin(
                "com.example.todo",
                "import com.example.todo.a.Item",
                "import com.example.todo.b.Item",
                "",
                "class Uses",
            ),
        }
    )
    assert found(files) == [("import.conflicting", "Uses.kt", "Item")]


# --- 3. an extension imported from another package satisfies the call -------------------------

EDIT_CALL = "class Store(private val store: Any) { suspend fun save() { store.edit { } } }"


def test_a_call_is_provided_by_any_import_of_that_name():
    # DataStore's own `edit` extension, not the SharedPreferences one the catalog expects. The app
    # really depends on DataStore here, so only the import resolution is under test.
    with_datastore = broken(
        {
            APP_GRADLE: (
                CORE_KTX,
                CORE_KTX + '    implementation("androidx.datastore:datastore-preferences:1.1.1")\n',
            )
        }
    )
    files = with_files(
        {
            f"{MAIN}/Store.kt": kotlin(
                "com.example.todo", "import androidx.datastore.preferences.core.edit", "", EDIT_CALL
            )
        },
        base=with_datastore,
    )
    assert found(files) == []


def test_a_call_with_no_import_of_that_name_is_still_missing():
    files = with_files({f"{MAIN}/Store.kt": kotlin("com.example.todo", EDIT_CALL)})
    assert found(files) == [("import.missing", "Store.kt", "edit")]


# --- 4. classes generated by Hilt/Dagger ------------------------------------------------------


def test_hilt_and_dagger_generated_classes_in_class_literals_are_not_unresolved():
    files = with_files(
        {
            f"{MAIN}/Runner.kt": kotlin(
                "com.example.todo",
                "class Runner {",
                "    val a = CustomTestRunner_Application::class.java.name",
                "    val b = Hilt_MainActivity::class.java.name",
                "    val c = DaggerAppComponent::class.java.name",
                "    val d = MainActivity_GeneratedInjector::class.java.name",
                "}",
            )
        }
    )
    assert found(files) == []


def test_a_class_literal_that_is_not_generated_is_still_unresolved():
    files = with_files(
        {f"{MAIN}/Runner.kt": kotlin("com.example.todo", "val x = Missing_Thing::class.java.name")}
    )
    assert found(files) == [("reference.unresolved_class", "Runner.kt", "Missing_Thing")]


# --- 5. dependencies declared as buildSrc constants -------------------------------------------

LIBS_KT = """object Libs {
    const val CORE_KTX = "androidx.core:core-ktx"
    const val MATERIAL = "com.google.android.material:material"
    const val OKHTTP = "com.squareup.okhttp3:okhttp:4.12.0"
    const val KOTLIN_VERSION = "1.9.0"

    object Fragment {
        const val TESTING = "androidx.fragment:fragment-testing"
    }
}
"""


def constants_project(*lines: str, layout: str = "") -> dict:
    files = broken({APP_GRADLE: (CORE_KTX, "".join(f"    {x}\n" for x in lines) + CORE_KTX)})
    extra = {LIBS: LIBS_KT}
    if layout:
        extra[LAYOUT] = layout
    return with_files(extra, files)


def _layout(ref: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">\n'
        f'    <TextView android:text="{ref}" />\n</LinearLayout>\n'
    )


def test_buildsrc_constants_resolve_to_maven_coordinates():
    a = ProjectAnalysis(
        ProjectFiles.from_mapping(
            constants_project("implementation(Libs.MATERIAL)", "api(Libs.Fragment.TESTING)")
        ),
        ReviewConfig(),
    )
    coordinates = {d.coordinate for d in a.dependencies if d.dep.constant}
    assert coordinates == {
        "com.google.android.material:material",
        "androidx.fragment:fragment-testing",
    }
    assert {"com.google.android.material", "androidx.fragment"} <= a.dependency_groups
    assert [d for d in a.dependencies if d.unresolved_alias] == []


def test_library_resource_is_trusted_when_the_dependency_is_a_buildsrc_constant():
    ref = _layout("@string/appbar_scrolling_view_behavior")
    assert found(constants_project("implementation(Libs.MATERIAL)", layout=ref)) == []
    assert found(constants_project("androidTestImplementation(Libs.Fragment.TESTING)")) == []


def test_library_resource_is_still_unresolved_without_the_providing_dependency():
    ref = _layout("@string/appbar_scrolling_view_behavior")
    # Libs.OKHTTP does not provide it, and a constant that is not a dependency means nothing.
    files = constants_project(
        "implementation(Libs.OKHTTP)", "implementation(Libs.NOPE)", layout=ref
    )
    assert found(files) == [
        ("resource.unresolved", "screen.xml", "string/appbar_scrolling_view_behavior")
    ]


def test_fragment_testing_theme_needs_the_fragment_testing_dependency():
    use = kotlin(
        "com.example.todo",
        "import com.example.todo.R",
        "val t = R.style.FragmentScenarioEmptyFragmentActivityTheme",
    )
    with_dep = constants_project("debugImplementation(Libs.Fragment.TESTING)")
    with_dep[f"{MAIN}/Theme.kt"] = use
    assert found(with_dep) == []
    without = constants_project()
    without[f"{MAIN}/Theme.kt"] = use
    assert [rule for rule, _, _ in found(without)] == ["resource.unresolved"]


# --- 6. buildSrc is an implicit separate build, not a module ----------------------------------


def test_buildsrc_is_not_a_module_and_its_scripts_are_not_checked_against_settings():
    files = with_files(
        {
            "buildSrc/build.gradle.kts": 'dependencies { api(project(":only-in-buildsrc")) }\n',
            LIBS: LIBS_KT,
        }
    )
    a = ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig())
    assert a.modules == frozenset({"app"})
    assert [f.rule for f in review(files).findings if f.rule == "gradle.unknown_project"] == []


def test_a_directory_that_is_included_stays_a_module_even_if_named_like_a_build_dir():
    settings = good_project()["settings.gradle.kts"].replace(
        'include(":app")\n', 'include(":app")\ninclude(":benchmark")\n'
    )
    files = with_files(
        {"settings.gradle.kts": settings, "benchmark/build.gradle.kts": "plugins {}\n"}
    )
    assert ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig()).modules == frozenset(
        {"app", "benchmark"}
    )
