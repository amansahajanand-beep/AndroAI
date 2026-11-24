"""M2.3: Gradle build facts: modules, plugins, SDK levels, features, dependencies, libraries."""

from __future__ import annotations

from analysis_fixtures import (
    analyse,
    convention_project,
    d,
    edges,
    fact,
    hilt_project,
    ids,
    java_xml_project,
    koin_project,
    no_errors,
)


def tech(report) -> set[str]:
    return {f.subject for f in report.facts if f.kind == "technology"}


def simple_project(app_script: str, **extra: str) -> dict[str, str]:
    files = {
        "settings.gradle.kts": 'rootProject.name = "x"\ninclude(":app")\n',
        "build.gradle.kts": "",
        "app/build.gradle.kts": d(app_script),
    }
    files.update({k.replace("__", "/"): v for k, v in extra.items()})
    return files


# -- modules ------------------------------------------------------------------------------------


def test_modules_with_type_namespace_and_application_id():
    report = analyse(hilt_project())
    no_errors(report)
    assert ids(report, "module") == ["app", "core/data"]
    app = fact(report, "module:app")
    assert app.attributes["type"] == "android_application"
    assert app.attributes["namespace"] == "com.example.notes"
    assert app.attributes["application_id"] == "com.example.notes"
    assert app.attributes["dependencies_readable"] is True
    assert fact(report, "module:core/data").attributes["type"] == "android_library"
    assert ("module:app", "module:core/data") in edges(report, "depends_on")


def test_a_single_module_project_without_settings_includes_is_the_root_module():
    files = {"build.gradle": "plugins { id 'com.android.application' }\n"}
    report = analyse(files)
    assert ids(report, "module") == ["."]


def test_a_module_listed_in_settings_without_a_build_script_is_reported_with_unknown_dependencies():
    files = {"settings.gradle.kts": 'include(":ghost")\n'}
    report = analyse(files)
    assert ids(report, "module") == ["ghost"]
    unknown = fact(report, "dependencies:ghost")
    assert unknown.status == "unknown" and "no build script" in unknown.reason


def test_an_included_build_is_not_a_module_of_the_main_build():
    report = analyse(convention_project())
    assert "build-logic" not in ids(report, "module")
    assert ids(report, "build_source") == ["build-logic"]


def test_plugins_are_read_from_ids_aliases_apply_and_kotlin_shortcuts():
    files = simple_project(
        """
        plugins {
            id("com.android.application")
            kotlin("android")
            alias(libs.plugins.ksp)
            id("com.google.gms.google-services") apply false
        }
        apply(plugin = "kotlin-parcelize")
        """,
        gradle__libs_versions_toml='[plugins]\nksp = { id = "com.google.devtools.ksp", version = "1.0" }\n',
    )
    files["gradle/libs.versions.toml"] = files.pop("gradle/libs_versions_toml")
    report = analyse(files)
    plugins = ids(report, "gradle_plugin")
    assert "app|com.android.application" in plugins
    assert "app|org.jetbrains.kotlin.android" in plugins
    assert "app|com.google.devtools.ksp" in plugins
    assert (
        "app|com.google.gms.google-services" not in plugins
    )  # `apply false` means not applied here
    assert "ksp" in tech(report)


def test_the_plugin_version_is_recorded_when_written_as_a_literal():
    files = {
        "settings.gradle": "include ':app'\n",
        "build.gradle": "",
        "app/build.gradle": "plugins { id 'com.android.application' version '8.5.2' }\n",
    }
    plugin = fact(analyse(files), "gradle_plugin:app|com.android.application")
    assert plugin.attributes.get("version") == "8.5.2"


def test_kotlin_multiplatform_is_reported_as_not_analysed():
    files = simple_project('plugins { id("org.jetbrains.kotlin.multiplatform") }\n')
    report = analyse(files)
    assert fact(report, "module:app").attributes["type"] == "kotlin_multiplatform"
    assert any(m.code == "kotlin_multiplatform_not_analysed" for m in report.limitations)
    assert report.complete is False


# -- SDK levels ---------------------------------------------------------------------------------


def test_sdk_levels_written_directly_are_confirmed_literals():
    report = analyse(java_xml_project())
    for name, value in (("minSdk", 21), ("targetSdk", 34), ("compileSdk", 34)):
        level = fact(report, f"sdk_level:app|{name}")
        assert level.status == "confirmed"
        assert level.attributes["value"] == value
        assert level.attributes["resolved_via"] == "literal"
        assert level.evidence[0].path == "app/build.gradle"


def test_a_target_sdk_taken_from_a_version_catalog_is_resolved_and_says_how():
    level = fact(analyse(hilt_project()), "sdk_level:app|targetSdk")
    assert level.attributes["value"] == 35
    assert level.attributes["resolved_via"] == "catalog_or_constant"
    assert any(e.path == "gradle/libs.versions.toml" for e in level.evidence)


def test_a_target_sdk_from_a_buildsrc_constant_is_resolved():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        android {
            defaultConfig {
                targetSdk = Versions.TARGET_SDK
            }
        }
        """,
    )
    files["buildSrc/src/main/kotlin/Versions.kt"] = (
        "object Versions {\n    const val TARGET_SDK = 33\n}\n"
    )
    level = fact(analyse(files), "sdk_level:app|targetSdk")
    assert level.attributes["value"] == 33
    assert level.attributes["resolved_via"] == "catalog_or_constant"


def test_a_number_that_starts_an_expression_is_not_a_literal():
    """``minSdk = 21 + 3`` is 24, not 21. The reused parser reads 21; this analysis does not."""
    files = simple_project(
        """
        plugins { id("com.android.application") }
        android {
            compileSdk = 34 + 1
            defaultConfig {
                minSdk = 21 + 3
                targetSdk = 30.toInt()
            }
        }
        """
    )
    report = analyse(files)
    for name in ("minSdk", "targetSdk", "compileSdk"):
        assert fact(report, f"sdk_level:app|{name}").status == "unknown"


def test_plain_literals_with_a_trailing_comment_or_semicolon_are_still_literals():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        android {
            compileSdk = 34 // latest
            defaultConfig { minSdk = 21; targetSdk = 34 }
        }
        """
    )
    report = analyse(files)
    assert [
        fact(report, f"sdk_level:app|{n}").attributes["value"]
        for n in ("minSdk", "targetSdk", "compileSdk")
    ] == [21, 34, 34]


def test_an_sdk_expression_that_would_need_evaluation_is_unknown_not_guessed():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        android {
            compileSdk = rootProject.extra["sdk"] as Int
            defaultConfig { minSdk = 21 + 3; targetSdk = project.property("t").toString().toInt() }
        }
        """
    )
    report = analyse(files)
    for name in ("minSdk", "targetSdk", "compileSdk"):
        level = fact(report, f"sdk_level:app|{name}")
        assert level.status == "unknown"
        assert "never run" in level.reason or "not evaluated" in level.reason


def test_an_sdk_that_is_simply_not_written_gives_no_fact_at_all():
    files = simple_project(
        'plugins { id("com.android.application") }\nandroid { namespace = "a.b" }\n'
    )
    report = analyse(files)
    assert [f for f in report.facts if f.kind == "sdk_level"] == []


def test_the_manifest_uses_sdk_is_read_for_old_projects():
    files = {
        "settings.gradle": "include ':app'\n",
        "app/build.gradle": "plugins { id 'com.android.library' }\n",
        "app/src/main/AndroidManifest.xml": (
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
            '<uses-sdk android:minSdkVersion="19" android:targetSdkVersion="28"/></manifest>'
        ),
    }
    report = analyse(files)
    level = fact(report, "sdk_level:app|minSdk")
    assert level.attributes["value"] == 19 and level.basis == "manifest"
    assert fact(report, "sdk_level:app|targetSdk").attributes["value"] == 28


# -- features -----------------------------------------------------------------------------------


def test_build_features_are_read_only_when_switched_on():
    on = analyse(java_xml_project())
    assert "app|viewBinding" in ids(on, "build_feature")
    assert "view_binding" in tech(on)
    off = analyse(
        simple_project(
            'plugins { id("com.android.application") }\n'
            "android { buildFeatures { viewBinding = false; compose = false } }\n"
        )
    )
    assert ids(off, "build_feature") == []
    assert "view_binding" not in tech(off) and "compose" not in tech(off)


def test_compose_is_a_build_feature_from_the_block_or_the_compiler_plugin():
    assert "app|compose" in ids(analyse(hilt_project()), "build_feature")
    files = simple_project('plugins { id("org.jetbrains.kotlin.plugin.compose") }\n')
    assert "app|compose" in ids(analyse(files), "build_feature")


def test_old_style_view_binding_block_is_recognised():
    files = simple_project(
        'plugins { id("com.android.application") }\nandroid { viewBinding { enabled = true } }\n'
    )
    assert "app|viewBinding" in ids(analyse(files), "build_feature")


# -- dependencies -------------------------------------------------------------------------------


def test_literal_catalog_and_platform_dependencies_resolve_to_coordinates():
    report = analyse(hilt_project())
    deps = ids(report, "dependency")
    assert "app|implementation|com.google.dagger:hilt-android" in deps  # catalog module form
    assert "app|implementation|androidx.hilt:hilt-navigation-compose" in deps  # catalog string form
    assert "app|implementation|com.squareup.okhttp3:okhttp" in deps  # literal
    assert "app|implementation|androidx.compose:compose-bom" in deps  # platform(...)
    hilt = fact(report, "dependency:app|implementation|com.google.dagger:hilt-android")
    assert hilt.attributes["via"] == "catalog" and hilt.attributes["version"] == "hilt"
    bom = fact(report, "dependency:app|implementation|androidx.compose:compose-bom")
    assert bom.attributes["platform"] is True
    assert (
        fact(report, "dependency:app|ksp|com.google.dagger:hilt-android-compiler").attributes[
            "config"
        ]
        == "ksp"
    )


def test_dependencies_in_test_configurations_are_marked_and_do_not_create_libraries():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        dependencies {
            testImplementation("androidx.room:room-testing:2.6.1")
            androidTestImplementation("androidx.compose.ui:ui-test:1.7.0")
            testImplementation("junit:junit:4.13.2")
        }
        """
    )
    report = analyse(files)
    room_testing = fact(report, "dependency:app|testImplementation|androidx.room:room-testing")
    assert room_testing.attributes["scope"] == "test"
    assert "scope:test" in room_testing.tags
    assert "room" not in tech(report) and "compose" not in tech(report)
    assert "junit" in tech(report)  # a testing library is a library whatever the configuration


def test_a_catalog_bundle_expands_to_its_libraries():
    files = simple_project(
        'plugins { id("com.android.application") }\ndependencies { implementation(libs.bundles.net) }\n',
        gradle__x="",
    )
    files["gradle/libs.versions.toml"] = d("""
        [libraries]
        okhttp = "com.squareup.okhttp3:okhttp:4.12.0"
        retrofit = "com.squareup.retrofit2:retrofit:2.11.0"

        [bundles]
        net = ["okhttp", "retrofit"]
        """)
    del files["gradle/x"]
    deps = ids(analyse(files), "dependency")
    assert "app|implementation|com.squareup.okhttp3:okhttp" in deps
    assert "app|implementation|com.squareup.retrofit2:retrofit" in deps


def test_a_buildsrc_constant_dependency_is_resolved():
    files = simple_project(
        'plugins { id("com.android.application") }\ndependencies { implementation(Libs.MATERIAL) }\n'
    )
    files["buildSrc/src/main/kotlin/Libs.kt"] = (
        'object Libs { const val MATERIAL = "com.google.android.material:material:1.12.0" }\n'
    )
    report = analyse(files)
    dep = fact(report, "dependency:app|implementation|com.google.android.material:material")
    assert dep.attributes["via"] == "build_constant"


def test_an_alias_the_catalog_does_not_define_is_an_unknown_fact():
    files = simple_project(
        'plugins { id("com.android.application") }\ndependencies { implementation(libs.missing.thing) }\n'
    )
    report = analyse(files)
    unknown = fact(report, "dependency:app|implementation|libs.missing.thing")
    assert unknown.status == "unknown" and unknown.reason


def test_a_computed_dependency_makes_the_dependency_list_unreadable_and_says_so():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        dependencies {
            implementation("a:b:1")
            listOf("x", "y").forEach { implementation(it) }
        }
        """
    )
    report = analyse(files)
    assert fact(report, "module:app").attributes["dependencies_readable"] is False
    assert fact(report, "dependencies:app").status == "unknown"
    assert any(
        m.code == "unparsed_dependency_calls" and m.scope == "app" for m in report.limitations
    )
    assert report.complete is False


def test_a_ksp_configuration_block_is_not_mistaken_for_an_unreadable_dependency():
    report = analyse(hilt_project())
    assert fact(report, "module:core/data").attributes["dependencies_readable"] is True
    assert [m for m in report.limitations if m.code == "unparsed_dependency_calls"] == []


def test_project_dependencies_become_module_edges_and_unresolvable_ones_are_unknown():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        dependencies {
            implementation(project(":lib"))
            implementation(project(":nowhere"))
        }
        """
    )
    files["settings.gradle.kts"] = 'include(":app", ":lib")\n'
    files["lib/build.gradle.kts"] = 'plugins { id("com.android.library") }\n'
    report = analyse(files)
    assert ("module:app", "module:lib") in edges(report, "depends_on")
    assert fact(report, "module_dependency:app|:nowhere").status == "unknown"


def test_allprojects_dependencies_make_every_module_dependency_list_incomplete():
    files = simple_project('plugins { id("com.android.application") }\n')
    files["build.gradle.kts"] = 'allprojects { dependencies { implementation("x:y:1") } }\n'
    report = analyse(files)
    assert any(m.code == "shared_dependency_scope" for m in report.limitations)
    assert fact(report, "dependencies:app").status == "unknown"


# -- libraries ----------------------------------------------------------------------------------


def test_libraries_are_recognised_from_coordinates_with_the_longest_prefix():
    report = analyse(hilt_project())
    found = tech(report)
    assert {"hilt", "room", "retrofit", "retrofit_converter", "compose", "okhttp"} <= found
    assert "navigation_compose" in found
    assert fact(report, "technology:room").attributes["category"] == "storage"
    assert fact(report, "technology:retrofit_converter").attributes["category"] == "network"


def test_libraries_are_also_recognised_from_imports_when_the_build_is_unreadable():
    report = analyse(convention_project())
    assert "appcompat" in tech(report)
    assert fact(report, "technology:appcompat").basis == "source"


def test_a_library_seen_in_build_and_source_is_one_fact_with_both_pieces_of_evidence():
    report = analyse(koin_project())
    koin = fact(report, "technology:koin")
    paths = {e.path for e in koin.evidence}
    assert "app/build.gradle.kts" in paths
    assert any(p.endswith(".kt") for p in paths)
    assert koin.basis == "gradle"


# -- limits of reading the build ----------------------------------------------------------------


def test_a_convention_plugin_makes_settings_and_dependencies_unknown_and_the_report_incomplete():
    report = analyse(convention_project())
    assert report.complete is False
    codes = {(m.code, m.scope) for m in report.limitations}
    assert ("convention_plugin_dependencies_unknown", "app") in codes
    assert fact(report, "module_type:app").status == "unknown"
    assert fact(report, "dependencies:app").status == "unknown"
    assert fact(report, "sdk_level:app|minSdk").status == "unknown"
    assert fact(report, "sdk_level:feature/home|compileSdk").status == "unknown"
    assert fact(report, "module:app").attributes["dependencies_readable"] is False


def test_groovy_scripts_are_read_with_a_partial_limitation_that_does_not_block_completeness():
    report = analyse(java_xml_project())
    groovy = [m for m in report.limitations if m.code == "groovy_dsl_partial"]
    assert {m.scope for m in groovy} == {"app/build.gradle", "build.gradle", "settings.gradle"}
    assert all(not m.affects_completeness for m in groovy)
    assert report.complete is True


def test_an_applied_script_file_is_not_followed():
    files = simple_project(
        'plugins { id("com.android.application") }\napply(from = "extra.gradle")\n'
    )
    report = analyse(files)
    assert any(m.code == "applied_script_not_followed" for m in report.limitations)
    assert report.complete is False


def test_a_broken_version_catalog_is_reported_not_ignored():
    files = simple_project('plugins { id("com.android.application") }\n')
    files["gradle/libs.versions.toml"] = "[versions\nbroken = \n"
    report = analyse(files)
    assert fact(report, "version_catalog:gradle/libs.versions.toml").status == "unknown"
    assert any(m.code == "malformed_build_file" for m in report.limitations)


def test_a_build_script_with_unbalanced_brackets_is_a_limitation():
    files = simple_project('plugins { id("com.android.application") }\nandroid {\n')
    report = analyse(files)
    assert any(
        m.code == "malformed_build_file" and m.scope == "app/build.gradle.kts"
        for m in report.limitations
    )
    assert report.complete is False


def test_the_scripts_are_read_never_run():
    files = simple_project(
        """
        plugins { id("com.android.application") }
        println("this would run if scripts were executed")
        Runtime.getRuntime().exec("touch /tmp/pwned")
        """
    )
    no_errors(analyse(files))
