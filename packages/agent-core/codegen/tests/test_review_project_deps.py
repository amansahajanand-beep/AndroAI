"""Gradle project dependencies: ``project(":x")``, ``projects.x`` accessors and missing projects."""

from sample_project import good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine
from androai_codegen.review.analysis import ProjectAnalysis

SETTINGS = "settings.gradle.kts"
INCLUDES = 'include(":app")\n'


def settings_with(*projects: str) -> str:
    includes = "".join(f'include("{p}")\n' for p in (":app", *projects))
    return good_project()[SETTINGS].replace(INCLUDES, includes)


def module(*lines: str) -> str:
    return "plugins {}\n\ndependencies {\n" + "\n".join(f"    {line}" for line in lines) + "\n}\n"


def project_with(*projects: str, **gradle: str) -> dict:
    """The known-good project with extra included modules and build scripts (path -> text)."""
    files = dict(good_project())
    files[SETTINGS] = settings_with(*projects)
    for path in (p.strip(":").replace(":", "/") for p in projects):
        files[f"{path}/build.gradle.kts"] = "plugins {}\n"
    files.update({k.replace("__", "/"): v for k, v in gradle.items()})
    return files


def analysis(files) -> ProjectAnalysis:
    return ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig())


def unknown(files) -> list[tuple[str, str, str]]:
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    return sorted(
        (f.rule, f.file, f.key) for f in report.findings if f.rule == "gradle.unknown_project"
    )


def graph(files) -> dict[str, set[str]]:
    return {k: set(v) for k, v in analysis(files).module_graph.items()}


APP = "app/build.gradle.kts"
PROJECTS = (":core:data", ":core:data-test", ":feature:foryou:impl")


def app_depends_on(*lines: str) -> dict:
    """The known-good app, plus the given dependency lines added to app/build.gradle.kts."""
    files = project_with(*PROJECTS)
    files[APP] = files[APP].replace(
        "dependencies {\n", "dependencies {\n" + "".join(f"    {x}\n" for x in lines), 1
    )
    return files


# --- resolving references ---------------------------------------------------------------------


def test_project_call_with_a_string_path_resolves_to_the_module_directory():
    files = app_depends_on('implementation(project(":core:data"))')
    assert graph(files) == {"app": {"core/data"}}
    assert unknown(files) == []


def test_groovy_style_project_references_resolve():
    files = project_with(*PROJECTS, ":lib")
    files["lib/build.gradle"] = (
        "dependencies {\n"
        "    implementation project(':core:data')\n"
        "    api project(path: ':core:data-test')\n"
        "    implementation(project(':feature:foryou:impl', 'default'))\n"
        "}\n"
    )
    assert graph(files)["lib"] == {"core/data", "core/data-test", "feature/foryou/impl"}
    assert unknown(files) == []


def test_typesafe_accessors_resolve_including_kebab_case_and_nesting():
    files = app_depends_on(
        "implementation(projects.core.data)",
        "testImplementation(projects.core.dataTest)",
        "api(projects.feature.foryou.impl)",
    )
    assert graph(files) == {"app": {"core/data", "core/data-test", "feature/foryou/impl"}}
    assert unknown(files) == []


def test_test_fixtures_wrapper_and_other_configurations_resolve():
    files = app_depends_on(
        'testImplementation(testFixtures(project(":core:data")))',
        'androidTestImplementation(project(":core:data-test"))',
        "debugImplementation(projects.core.data)",
    )
    assert graph(files) == {"app": {"core/data", "core/data-test"}}


# --- missing projects -------------------------------------------------------------------------


def test_reference_to_a_project_that_is_not_included_is_reported():
    files = app_depends_on('implementation(project(":core:ghost"))')
    assert unknown(files) == [("gradle.unknown_project", "app/build.gradle.kts", ":core:ghost")]


def test_accessor_to_a_project_that_is_not_included_is_reported():
    files = app_depends_on("implementation(projects.core.ghost)", "api(projects.coreData)")
    assert unknown(files) == [
        ("gradle.unknown_project", "app/build.gradle.kts", "projects.core.ghost"),
        ("gradle.unknown_project", "app/build.gradle.kts", "projects.coreData"),
    ]


def test_a_typo_of_an_included_project_is_reported_with_a_suggestion():
    files = app_depends_on('implementation(project(":core:dta"))')
    [finding] = [
        f
        for f in ReviewEngine().review(ProjectFiles.from_mapping(files)).findings
        if f.rule == "gradle.unknown_project"
    ]
    assert finding.blocking and finding.category == "dependencies"
    assert ":core:data" in (finding.suggested_fix or "")


def test_valid_and_invalid_references_side_by_side_only_report_the_invalid_one():
    files = app_depends_on(
        'implementation(project(":core:data"))',
        "implementation(projects.core.dataTest)",
        'implementation(project(":nope"))',
    )
    assert unknown(files) == [("gradle.unknown_project", "app/build.gradle.kts", ":nope")]


def test_missing_project_is_new_only_when_the_change_introduces_it():
    before = ProjectFiles.from_mapping(app_depends_on('implementation(project(":core:data"))'))
    after = ProjectFiles.from_mapping(app_depends_on('implementation(project(":core:ghost"))'))
    engine = ReviewEngine()
    introduced = [f.rule for f in engine.review(after, before=before).findings]
    assert introduced == ["gradle.unknown_project"]
    assert (
        engine.review(after, before=after).findings == []
    )  # already there: not this change's fault


# --- when we cannot know, we do not guess -----------------------------------------------------


def test_no_missing_project_findings_when_settings_include_dynamically():
    files = app_depends_on('implementation(project(":core:ghost"))')
    files[SETTINGS] += 'listOf("a", "b").forEach { include(it) }\n'
    assert unknown(files) == []


def test_no_missing_project_findings_when_a_project_dir_is_remapped():
    files = app_depends_on('implementation(project(":core:ghost"))')
    files[SETTINGS] += 'project(":core:ghost").projectDir = file("elsewhere/ghost")\n'
    assert unknown(files) == []


def test_no_missing_project_findings_without_a_settings_script_or_includes():
    files = dict(good_project())
    del files[SETTINGS]
    files[APP] = files[APP].replace(
        "dependencies {\n", 'dependencies {\n    implementation(project(":x"))\n', 1
    )
    assert unknown(files) == []
    files[SETTINGS] = 'rootProject.name = "x"\n'
    assert unknown(files) == []


def test_scripts_of_an_included_build_are_not_checked_against_the_main_settings():
    files = app_depends_on()
    files[SETTINGS] = files[SETTINGS].replace(
        "pluginManagement {\n", 'pluginManagement {\n    includeBuild("build-logic")\n', 1
    )
    files["build-logic/convention/build.gradle.kts"] = module(
        'implementation(project(":only-in-build-logic"))'
    )
    assert unknown(files) == []


# --- existing dependency behaviour is preserved ----------------------------------------------


def test_catalog_and_string_dependencies_are_unchanged_by_project_dependencies():
    plain = analysis(good_project())
    files = app_depends_on(
        'implementation(project(":core:data"))', 'implementation("com.acme:lib:1.0")'
    )
    mixed = analysis(files)
    coords = lambda a: {d.coordinate for d in a.dependencies if d.coordinate}  # noqa: E731
    assert coords(mixed) == coords(plain) | {"com.acme:lib"}
    assert [d for d in mixed.dependencies if d.unresolved_alias] == []
    assert "com.acme" in mixed.dependency_groups
    assert not any(d.dep.project or d.dep.project_accessor for d in plain.dependencies)


def test_project_dependencies_do_not_count_as_maven_groups_or_unresolved_aliases():
    a = analysis(app_depends_on('implementation(project(":core:data"))', "api(projects.core.data)"))
    projects = [d for d in a.dependencies if d.dep.project or d.dep.project_accessor]
    assert len(projects) == 2
    assert all(d.group is None and not d.unresolved_alias for d in projects)
