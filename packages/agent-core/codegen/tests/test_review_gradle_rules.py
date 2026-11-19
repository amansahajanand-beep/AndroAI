"""Gradle rules (Phase 4b): catalog aliases, missing dependencies, Compose plugin, SDK order,
duplicates and the approved-dependency plan. Each defect has twins that must stay quiet."""

from sample_project import good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine

APP = "app/build.gradle.kts"
ROOT = "build.gradle.kts"
SETTINGS = "settings.gradle.kts"
CATALOG = "gradle/libs.versions.toml"
RETROFIT = "    implementation(libs.retrofit.core)\n    implementation(libs.retrofit.gson)\n"
ROOM = "    implementation(libs.androidx.room.runtime)\n    ksp(libs.androidx.room.compiler)\n"
COMPOSE_PLUGIN = "    alias(libs.plugins.kotlin.compose)\n"
TEST_DEP = "    testImplementation(libs.junit)\n"


def run(files, config=None):
    report = ReviewEngine(config).review(ProjectFiles.from_mapping(files))
    # a rule that crashes becomes this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def found(files, rule, config=None):
    return sorted(
        (f.rule, f.file.rsplit("/", 1)[-1], f.key)
        for f in run(files, config).findings
        if f.rule == rule or (rule.endswith(".") and f.rule.startswith(rule))
    )


def edit(files, path, old, new):
    out = dict(files)
    assert old in out[path], f"{path}: {old!r}"
    out[path] = out[path].replace(old, new, 1)
    return out


def add_dependency(files, line):
    return edit(files, APP, TEST_DEP, f"    {line}\n" + TEST_DEP)


def test_the_known_good_project_has_no_gradle_findings():
    assert found(good_project(), "gradle.") == []


# --- version catalog references -----------------------------------------------------------------


def test_an_alias_missing_from_the_catalog_is_reported_with_a_hint():
    files = edit(good_project(), APP, "libs.androidx.core.ktx", "libs.androidx.core.ktxx")
    [finding] = [f for f in run(files).findings if f.rule == "gradle.unknown_catalog_alias"]
    assert finding.key == "libs.androidx.core.ktxx"
    assert "libs.androidx.core.ktx" in (finding.suggested_fix or "")


def test_versions_bundles_plugins_and_accessor_methods_resolve():
    files = edit(
        good_project(),
        CATALOG,
        "[plugins]",
        '[bundles]\nui = ["androidx-ui", "androidx-material3"]\n\n[plugins]',
    )
    files = edit(
        files,
        APP,
        TEST_DEP,
        TEST_DEP + "    implementation(libs.bundles.ui)\n    val agp = libs.versions.agp.get()\n"
        "    val core = libs.androidx.core.ktx.get()\n",
    )
    assert found(files, "gradle.unknown_catalog_alias") == []


def test_catalog_lookup_methods_are_not_aliases():
    files = edit(
        good_project(),
        APP,
        TEST_DEP,
        TEST_DEP + '    val lookup = libs.findLibrary("androidx-core-ktx")\n',
    )
    assert found(files, "gradle.unknown_catalog_alias") == []


def test_unknown_plugin_version_and_bundle_aliases_are_reported():
    files = edit(
        good_project(),
        APP,
        TEST_DEP,
        TEST_DEP + "    implementation(libs.bundles.nope)\n    val v = libs.versions.nope.get()\n",
    )
    files = edit(
        files,
        APP,
        "    alias(libs.plugins.ksp)\n",
        "    alias(libs.plugins.ksp)\n    alias(libs.plugins.nope)\n",
    )
    keys = [k for _, _, k in found(files, "gradle.unknown_catalog_alias")]
    assert keys == ["libs.bundles.nope", "libs.plugins.nope", "libs.versions.nope.get"]


def test_catalog_references_are_not_judged_when_the_catalog_is_ambiguous_or_custom():
    typo = edit(good_project(), APP, "libs.androidx.core.ktx", "libs.androidx.core.ktxx")
    twice = dict(typo)
    twice["build-logic/gradle/libs.versions.toml"] = '[versions]\nx = "1"\n'
    assert found(twice, "gradle.unknown_catalog_alias") == []
    custom = edit(
        typo,
        SETTINGS,
        "dependencyResolutionManagement {",
        "dependencyResolutionManagement {\n"
        '    versionCatalogs { create("other") { from(files("o.toml")) } }',
    )
    assert found(custom, "gradle.unknown_catalog_alias") == []
    no_catalog = {k: v for k, v in typo.items() if k != CATALOG}
    assert found(no_catalog, "gradle.unknown_catalog_alias") == []


# --- dependencies used but not declared ---------------------------------------------------------


def test_an_imported_library_with_no_dependency_is_reported_once():
    files = edit(good_project(), APP, RETROFIT, "")
    assert found(files, "gradle.dependency_missing") == [
        ("gradle.dependency_missing", "Api.kt", "Retrofit")
    ]
    files = edit(good_project(), APP, ROOM, "")
    assert found(files, "gradle.dependency_missing") == [
        ("gradle.dependency_missing", "AppDatabase.kt", "Room")
    ]


def test_declaring_the_dependency_any_way_satisfies_the_rule():
    inline = edit(
        good_project(),
        APP,
        RETROFIT,
        '    implementation("com.squareup.retrofit2:retrofit:2.11.0")\n',
    )
    assert found(inline, "gradle.dependency_missing") == []
    okhttp_only = edit(
        good_project(), APP, RETROFIT, '    implementation("com.squareup.okhttp3:okhttp:4.12.0")\n'
    )
    assert [k for _, _, k in found(okhttp_only, "gradle.dependency_missing")] == ["Retrofit"]


def test_compose_libraries_are_not_in_the_table_because_they_arrive_transitively():
    compose = "".join(
        f"    implementation(libs.androidx.{n})\n"
        for n in ("ui", "ui.graphics", "ui.tooling.preview", "material3", "navigation.compose")
    )
    files = edit(good_project(), APP, compose, "")
    assert found(files, "gradle.dependency_missing") == [
        ("gradle.dependency_missing", "TodoApp.kt", "Navigation")
    ]


def test_nothing_is_claimed_when_the_dependency_list_cannot_be_read():
    base = edit(good_project(), APP, RETROFIT, "")
    convention = edit(base, APP, "plugins {\n", 'plugins {\n    id("myproject.convention")\n')
    assert found(convention, "gradle.dependency_missing") == []
    assert (
        found(
            add_dependency(base, "implementation(libs.nope.nothing)"), "gradle.dependency_missing"
        )
        == []
    )
    assert (
        found(add_dependency(base, 'implementation(fileTree("libs"))'), "gradle.dependency_missing")
        == []
    )
    assert found(add_dependency(base, "implementation(it)"), "gradle.dependency_missing") == []
    shared = edit(
        base,
        ROOT,
        "plugins {",
        'allprojects { dependencies { implementation("x:y:1") } }\nplugins {',
    )
    assert found(shared, "gradle.dependency_missing") == []
    unknown_plugin = edit(
        base,
        APP,
        "    alias(libs.plugins.ksp)\n",
        "    alias(libs.plugins.ksp)\n    alias(libs.plugins.nope)\n",
    )
    assert found(unknown_plugin, "gradle.dependency_missing") == []
    ghost_project = add_dependency(base, 'implementation(project(":ghost"))')
    assert found(ghost_project, "gradle.dependency_missing") == []


def two_modules(core_dependencies: str):
    files = edit(good_project(), APP, RETROFIT, "")
    files = edit(files, SETTINGS, 'include(":app")', 'include(":app")\ninclude(":core")')
    files = add_dependency(files, 'implementation(project(":core"))')
    files["core/build.gradle.kts"] = (
        f'plugins {{ id("com.android.library") }}\ndependencies {{\n{core_dependencies}}}\n'
    )
    return files


def test_a_dependency_provided_by_a_module_this_one_depends_on_counts():
    assert (
        found(
            two_modules('    api("com.squareup.retrofit2:retrofit:2.11.0")\n'),
            "gradle.dependency_missing",
        )
        == []
    )
    assert [k for _, _, k in found(two_modules(""), "gradle.dependency_missing")] == ["Retrofit"]


# --- Compose plugin -----------------------------------------------------------------------------


def test_compose_without_the_compiler_plugin_on_kotlin_2_is_reported():
    files = edit(good_project(), APP, COMPOSE_PLUGIN, "")
    assert found(files, "gradle.compose_plugin_missing") == [
        ("gradle.compose_plugin_missing", "build.gradle.kts", "app")
    ]


def test_compose_plugin_rule_stays_quiet_when_it_cannot_be_sure():
    missing = edit(good_project(), APP, COMPOSE_PLUGIN, "")
    old_kotlin = edit(missing, CATALOG, 'kotlin = "2.0.21"', 'kotlin = "1.9.24"')
    assert found(old_kotlin, "gradle.compose_plugin_missing") == []
    unknown_version = edit(
        missing,
        CATALOG,
        'kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }',
        'kotlin-android = { id = "org.jetbrains.kotlin.android" }',
    )
    assert found(unknown_version, "gradle.compose_plugin_missing") == []
    convention = edit(missing, APP, "plugins {\n", 'plugins {\n    id("myproject.compose")\n')
    assert found(convention, "gradle.compose_plugin_missing") == []
    shared = edit(missing, ROOT, "plugins {", "subprojects { }\nplugins {")
    assert found(shared, "gradle.compose_plugin_missing") == []


# --- SDK levels ---------------------------------------------------------------------------------


def test_sdk_levels_out_of_order_are_reported_as_warnings():
    high_min = edit(good_project(), APP, "minSdk = 24", "minSdk = 36")
    assert found(high_min, "gradle.sdk_order") == [
        ("gradle.sdk_order", "build.gradle.kts", "min>target")
    ]
    high_target = edit(good_project(), APP, "targetSdk = 35", "targetSdk = 36")
    assert found(high_target, "gradle.sdk_order") == [
        ("gradle.sdk_order", "build.gradle.kts", "target>compile")
    ]
    assert all(not f.blocking for f in run(high_min).findings if f.rule == "gradle.sdk_order")


# --- duplicates ---------------------------------------------------------------------------------


def test_a_dependency_declared_twice_is_a_duplicate_and_two_versions_conflict():
    twice = add_dependency(good_project(), "implementation(libs.androidx.core.ktx)")
    assert found(twice, "gradle.duplicate_dependency") == [
        ("gradle.duplicate_dependency", "build.gradle.kts", "implementation:androidx.core:core-ktx")
    ]
    conflict = add_dependency(
        good_project(), 'implementation("com.squareup.retrofit2:retrofit:2.9.0")'
    )
    assert found(conflict, "gradle.conflicting_versions") == [
        ("gradle.conflicting_versions", "build.gradle.kts", "com.squareup.retrofit2:retrofit")
    ]


def test_the_same_library_in_different_configurations_is_fine():
    both = add_dependency(good_project(), "testImplementation(libs.androidx.core.ktx)")
    assert found(both, "gradle.") == []


# --- the approved plan --------------------------------------------------------------------------

PLAN = (
    "androidx.core",
    "androidx.lifecycle",
    "androidx.activity",
    "androidx.compose",
    "androidx.compose.ui",
    "androidx.compose.material3",
    "androidx.navigation",
    "androidx.room",
    "junit",
)


def test_without_a_plan_nothing_is_unplanned():
    assert found(good_project(), "gradle.unplanned_dependency") == []


def test_dependencies_outside_the_plan_need_approval():
    config = ReviewConfig(permitted_dependencies=PLAN)
    findings = [
        f for f in run(good_project(), config).findings if f.rule == "gradle.unplanned_dependency"
    ]
    assert sorted(f.key for f in findings) == [
        "com.squareup.retrofit2:converter-gson",
        "com.squareup.retrofit2:retrofit",
    ]
    assert all(f.blocking and f.approval == "other_high_impact" for f in findings)


def test_plan_entries_may_be_a_group_a_coordinate_or_a_group_wildcard():
    for entry in ("com.squareup.retrofit2", "com.squareup.retrofit2:*"):
        assert (
            found(
                good_project(),
                "gradle.unplanned_dependency",
                ReviewConfig(permitted_dependencies=(*PLAN, entry)),
            )
            == []
        )
    exact = (*PLAN, "com.squareup.retrofit2:retrofit")
    assert [
        k
        for _, _, k in found(
            good_project(),
            "gradle.unplanned_dependency",
            ReviewConfig(permitted_dependencies=exact),
        )
    ] == ["com.squareup.retrofit2:converter-gson"]


def test_a_granted_approval_downgrades_the_finding():
    config = ReviewConfig(
        permitted_dependencies=PLAN, granted_approvals=frozenset({"other_high_impact"})
    )
    findings = [
        f for f in run(good_project(), config).findings if f.rule == "gradle.unplanned_dependency"
    ]
    assert findings and all(
        not f.blocking and f.description.endswith("(approved)") for f in findings
    )
