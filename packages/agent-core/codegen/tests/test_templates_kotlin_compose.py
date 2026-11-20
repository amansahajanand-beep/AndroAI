"""The Kotlin + Compose template: structure, Gradle files, manifest, resources, Compose code."""

import re
import tomllib
import xml.etree.ElementTree as ET

import pytest

from androai_codegen.templates import (
    PROVISIONAL,
    TOOLCHAIN,
    VERIFIED_BUILD,
    ProjectConfig,
    render_files,
)

ANDROID = "{http://schemas.android.com/apk/res/android}"
PACKAGE = "com.example.notes"
SRC = "app/src/main/java/com/example/notes"
RES = "app/src/main/res"

EXPECTED_PATHS = sorted(
    [
        ".gitignore",
        "app/build.gradle.kts",
        "app/proguard-rules.pro",
        "app/src/main/AndroidManifest.xml",
        f"{RES}/values/colors.xml",
        f"{RES}/values/strings.xml",
        f"{RES}/values/themes.xml",
        f"{RES}/values-night/themes.xml",
        f"{SRC}/MainActivity.kt",
        f"{SRC}/navigation/AppNavHost.kt",
        f"{SRC}/ui/home/HomeScreen.kt",
        f"{SRC}/ui/theme/Color.kt",
        f"{SRC}/ui/theme/Theme.kt",
        f"{SRC}/ui/theme/Type.kt",
        "build.gradle.kts",
        "gradle.properties",
        "gradle/libs.versions.toml",
        "gradle/wrapper/gradle-wrapper.properties",
        "settings.gradle.kts",
    ]
)


def make(**overrides) -> ProjectConfig:
    base = {"project_name": "Notes App", "package_name": PACKAGE}
    base.update(overrides)
    return ProjectConfig(**base)


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return {f.path: f.content for f in render_files(make())}


def kotlin_files(files):
    return {p: c for p, c in files.items() if p.endswith(".kt")}


# --- structure ------------------------------------------------------------------------------


def test_the_project_has_exactly_the_expected_files(files):
    assert sorted(files) == EXPECTED_PATHS


def test_there_is_one_file_per_path_and_every_file_has_a_description():
    rendered = render_files(make())
    assert len({f.path for f in rendered}) == len(rendered)
    assert all(f.description.strip() for f in rendered)


def test_no_file_is_empty_and_all_use_lf_and_end_with_a_newline(files):
    for path, content in files.items():
        assert content.strip(), path
        assert "\r" not in content, path
        assert content.endswith("\n") and not content.endswith("\n\n"), path
        assert "\t" not in content, path
        assert all(line == line.rstrip() for line in content.split("\n")), path


def test_no_placeholder_is_left_in_a_normal_project(files):
    leftover = {p for p, c in files.items() if re.search(r"__[A-Z][A-Z0-9_]*__", c)}
    assert not leftover


def test_there_is_no_binary_or_wrapper_jar_and_no_script(files):
    assert not [p for p in files if p.endswith((".jar", ".png", ".webp", "gradlew", "gradlew.bat"))]


def test_no_secret_or_local_file_is_generated(files):
    assert "local.properties" not in files and "keystore.properties" not in files
    assert not [p for p in files if p.endswith((".jks", ".keystore", ".pem", ".key", ".env"))]
    ignore = files[".gitignore"].split("\n")
    assert {"local.properties", "keystore.properties", "*.jks", "*.keystore"} <= set(ignore)


# --- package declarations and source layout -------------------------------------------------


def test_every_kotlin_file_declares_the_package_of_its_directory(files):
    for path, content in kotlin_files(files).items():
        directory = path.rsplit("/", 1)[0].removeprefix("app/src/main/java/")
        match = re.match(r"package ([\w.]+)\n", content)
        assert match, path
        assert match.group(1) == directory.replace("/", "."), path


def test_sources_live_under_the_package_path_of_the_config():
    other = {f.path for f in render_files(make(package_name="org.acme.deep.pkg"))}
    assert "app/src/main/java/org/acme/deep/pkg/MainActivity.kt" in other
    assert not [p for p in other if "com/example" in p]
    assert {p for p in other if p.endswith(".kt")} == {
        f"app/src/main/java/org/acme/deep/pkg/{rest}"
        for rest in (
            "MainActivity.kt",
            "navigation/AppNavHost.kt",
            "ui/home/HomeScreen.kt",
            "ui/theme/Color.kt",
            "ui/theme/Theme.kt",
            "ui/theme/Type.kt",
        )
    }


def test_package_and_namespace_agree_everywhere():
    other = {f.path: f.content for f in render_files(make(package_name="org.acme.deep.pkg"))}
    assert 'namespace = "org.acme.deep.pkg"' in other["app/build.gradle.kts"]
    for path, content in kotlin_files(other).items():
        assert "com.example" not in content, path
        assert content.startswith("package org.acme.deep.pkg"), path
    home = other["app/src/main/java/org/acme/deep/pkg/ui/home/HomeScreen.kt"]
    assert "import org.acme.deep.pkg.R\n" in home


def test_every_import_is_used(files):
    # The review engine finds missing imports; nothing in it finds unused ones, so check here.
    for path, content in kotlin_files(files).items():
        body = "\n".join(line for line in content.split("\n") if not line.startswith("import "))
        for line in content.split("\n"):
            if line.startswith("import "):
                simple = line.rsplit(".", 1)[-1]
                assert re.search(rf"\b{re.escape(simple)}\b", body), f"{path}: unused {line}"


def test_imports_are_sorted_and_unique(files):
    for path, content in kotlin_files(files).items():
        imports = [line for line in content.split("\n") if line.startswith("import ")]
        assert imports == sorted(imports), path
        assert len(imports) == len(set(imports)), path


# --- Gradle ---------------------------------------------------------------------------------


def test_settings_gradle(files):
    settings = files["settings.gradle.kts"]
    assert 'rootProject.name = "Notes-App"' in settings
    assert 'include(":app")' in settings
    assert "RepositoriesMode.FAIL_ON_PROJECT_REPOS" in settings
    for repo in ("google()", "mavenCentral()", "gradlePluginPortal()"):
        assert repo in settings


def test_root_build_gradle(files):
    root = files["build.gradle.kts"]
    assert f'classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:{TOOLCHAIN.kotlin}")' in root
    assert "alias(libs.plugins.android.application) apply false" in root
    assert "alias(libs.plugins.kotlin.compose) apply false" in root


def test_the_kotlin_android_plugin_is_not_applied_with_agp_9(files):
    # AGP 9 has Kotlin built in; applying org.jetbrains.kotlin.android there is an error.
    for path, content in files.items():
        assert "org.jetbrains.kotlin.android" not in content, path
        assert "kotlin-android" not in content, path
        assert "kotlinOptions" not in content, path


def test_version_catalog_holds_exactly_the_pinned_versions(files):
    catalog = tomllib.loads(files["gradle/libs.versions.toml"])
    assert catalog["versions"] == {
        "agp": TOOLCHAIN.agp,
        "kotlin": TOOLCHAIN.kotlin,
        "composeBom": TOOLCHAIN.compose_bom,
        "activityCompose": TOOLCHAIN.activity_compose,
        "navigationCompose": TOOLCHAIN.navigation_compose,
    }


def test_version_catalog_is_internally_consistent(files):
    catalog = tomllib.loads(files["gradle/libs.versions.toml"])
    versions = catalog["versions"]
    for table in ("libraries", "plugins"):
        for alias, entry in catalog[table].items():
            ref = entry.get("version.ref") or entry.get("version", {}).get("ref")
            if ref is not None:
                assert ref in versions, f"{alias} -> {ref}"
    for alias, entry in catalog["libraries"].items():
        assert entry["group"] and entry["name"], alias
        if entry["group"].startswith("androidx.compose."):
            # Versions of Compose libraries come from the BOM only.
            assert "version" not in entry, alias
    assert catalog["plugins"]["android-application"]["id"] == "com.android.application"
    assert catalog["plugins"]["kotlin-compose"]["id"] == "org.jetbrains.kotlin.plugin.compose"


def accessor(alias: str) -> str:
    return "libs." + re.sub(r"[-_]", ".", alias)


def test_every_catalog_accessor_used_in_a_build_file_exists_and_every_entry_is_used(files):
    catalog = tomllib.loads(files["gradle/libs.versions.toml"])
    defined = {accessor(a) for a in catalog["libraries"]} | {
        "libs.plugins." + re.sub(r"[-_]", ".", a) for a in catalog["plugins"]
    }
    used = set()
    for path in ("build.gradle.kts", "app/build.gradle.kts"):
        code = "\n".join(
            line for line in files[path].split("\n") if not line.lstrip().startswith("//")
        )
        used |= set(re.findall(r"(?<![\w/.])libs(?:\.[A-Za-z0-9]+)+", code))
    assert used <= defined, used - defined
    assert defined <= used, defined - used


def test_app_build_gradle(files):
    app = files["app/build.gradle.kts"]
    assert 'namespace = "com.example.notes"' in app
    assert 'applicationId = "com.example.notes"' in app
    assert "minSdk = 24\n" in app and "targetSdk = 36\n" in app
    # compileSdk is API 37.1, which only the AGP 9 block can say (an integer is API 37.0).
    assert (
        "    compileSdk {\n"
        "        version = release(37) {\n"
        "            minorApiLevel = 1\n"
        "        }\n"
        "    }\n"
    ) in app
    assert "versionCode = 1\n" in app and 'versionName = "1.0"' in app
    assert f"sourceCompatibility = JavaVersion.VERSION_{TOOLCHAIN.jdk}" in app
    assert f"targetCompatibility = JavaVersion.VERSION_{TOOLCHAIN.jdk}" in app
    assert "alias(libs.plugins.android.application)" in app
    assert "alias(libs.plugins.kotlin.compose)" in app
    assert "compose = true" in app
    assert "implementation(platform(libs.androidx.compose.bom))" in app
    assert '"proguard-android-optimize.txt"' in app
    # A release build must not claim to shrink while the rules file is empty.
    assert "isMinifyEnabled = false" in app


def test_an_explicit_application_id_and_version_reach_the_app_module():
    app = {
        f.path: f.content
        for f in render_files(
            make(application_id="com.acme.NotesPro", version_code=42, version_name="3.1.4")
        )
    }["app/build.gradle.kts"]
    assert 'namespace = "com.example.notes"' in app
    assert 'applicationId = "com.acme.NotesPro"' in app
    assert "versionCode = 42\n" in app
    assert 'versionName = "3.1.4"' in app


def test_wrapper_properties(files):
    props = dict(
        line.split("=", 1)
        for line in files["gradle/wrapper/gradle-wrapper.properties"].split("\n")
        if line
    )
    assert props["distributionUrl"] == (
        f"https\\://services.gradle.org/distributions/gradle-{TOOLCHAIN.gradle}-bin.zip"
    )
    assert props["distributionSha256Sum"] == TOOLCHAIN.gradle_sha256
    assert re.fullmatch(r"[0-9a-f]{64}", props["distributionSha256Sum"])
    assert props["validateDistributionUrl"] == "true"
    assert props["distributionBase"] == props["zipStoreBase"] == "GRADLE_USER_HOME"


def test_gradle_properties_are_plain_key_values(files):
    for line in files["gradle.properties"].split("\n"):
        if line and not line.startswith("#"):
            assert re.fullmatch(r"[\w.]+=.+", line), line


def test_the_jdk_meets_what_agp_9_5_requires():
    assert TOOLCHAIN.jdk >= 17


def test_the_pins_are_the_ones_that_were_built():
    # Changing a pin without rebuilding must not keep claiming "verified": update VERIFIED_BUILD
    # (and rebuild) together with the pin.
    assert PROVISIONAL is False
    for field in (
        "agp",
        "gradle",
        "kotlin",
        "compose_bom",
        "activity_compose",
        "navigation_compose",
        "jdk",
    ):
        assert VERIFIED_BUILD[field] == getattr(TOOLCHAIN, field), field
    config = make()
    assert (VERIFIED_BUILD["min_sdk"], VERIFIED_BUILD["target_sdk"]) == (
        config.min_sdk,
        config.target_sdk,
    )
    assert VERIFIED_BUILD["compile_sdk"] == config.compile_sdk_full
    assert VERIFIED_BUILD["task"] == ":app:assembleDebug"
    assert TOOLCHAIN.min_sdk_floor <= 24 <= 36 <= TOOLCHAIN.compile_sdk_min


# --- manifest -------------------------------------------------------------------------------


def manifest(files):
    return ET.fromstring(files["app/src/main/AndroidManifest.xml"])


def test_manifest_has_a_launcher_activity(files):
    root = manifest(files)
    assert root.tag == "manifest"
    assert "package" not in root.attrib  # the namespace lives in build.gradle.kts
    (application,) = root.findall("application")
    (activity,) = application.findall("activity")
    assert activity.get(f"{ANDROID}name") == ".MainActivity"
    assert activity.get(f"{ANDROID}exported") == "true"  # required with an intent filter
    (intent_filter,) = activity.findall("intent-filter")
    actions = {e.get(f"{ANDROID}name") for e in intent_filter.findall("action")}
    categories = {e.get(f"{ANDROID}name") for e in intent_filter.findall("category")}
    assert actions == {"android.intent.action.MAIN"}
    assert categories == {"android.intent.category.LAUNCHER"}


def test_the_launcher_activity_class_exists_in_the_sources(files):
    assert "class MainActivity : ComponentActivity()" in files[f"{SRC}/MainActivity.kt"]


def test_manifest_requests_no_permission_and_exposes_nothing_else(files):
    root = manifest(files)
    assert not root.findall("uses-permission") and not root.findall("uses-permission-sdk-23")
    assert not root.findall("uses-feature")
    (application,) = root.findall("application")
    assert [child.tag for child in application] == ["activity"]
    assert application.get(f"{ANDROID}allowBackup") == "false"
    assert application.get(f"{ANDROID}debuggable") is None
    assert application.get(f"{ANDROID}usesCleartextTraffic") is None


def test_manifest_references_resources_that_exist(files):
    (application,) = manifest(files).findall("application")
    assert application.get(f"{ANDROID}label") == "@string/app_name"
    assert application.get(f"{ANDROID}theme") == "@style/Theme.NotesApp"
    strings = ET.fromstring(files[f"{RES}/values/strings.xml"])
    assert "app_name" in {e.get("name") for e in strings}
    for themes in ("values", "values-night"):
        styles = ET.fromstring(files[f"{RES}/{themes}/themes.xml"])
        assert "Theme.NotesApp" in {e.get("name") for e in styles.findall("style")}


# --- every resource reference resolves, and the namespace is valid ---------------------------

RESOURCE_REFERENCE = re.compile(r"@(?P<type>[a-z]+)/(?P<name>[\w.]+)")
VALUES_FILE = re.compile(rf"{RES}/(?P<directory>values[^/]*)/[^/]+\.xml")
CONFIGS = [
    {},
    {"application_id": "com.acme.NotesPro"},
    {"package_name": "org.acme.deep.nested.pkg"},
    {"project_name": "R&D Tracker"},
    {"project_name": "नमस्ते"},
    {"project_name": "2048 Game"},
]


def defined_resources(files: dict[str, str], directory: str | None = None) -> dict[str, set[str]]:
    """Resource names defined by the ``values*`` files (all of them, or one directory)."""
    defined: dict[str, set[str]] = {}
    for path, content in files.items():
        match = VALUES_FILE.fullmatch(path)
        if match and directory in (None, match["directory"]):
            for element in ET.fromstring(content):
                if element.get("name"):
                    defined.setdefault(element.tag, set()).add(element.get("name"))
    return defined


def unresolved_references(files: dict[str, str]) -> list[str]:
    """Every ``@type/name`` in the manifest and in resource files that nothing defines.

    Each is checked against the default ``values`` directory: a name defined only in a qualified
    directory (``values-night``) would crash the app in every other configuration.
    """
    defined = defined_resources(files, "values")
    xml_files = ["app/src/main/AndroidManifest.xml"] + [
        p for p in files if p.startswith(f"{RES}/") and p.endswith(".xml")
    ]
    missing = []
    for path in xml_files:
        for ref in RESOURCE_REFERENCE.finditer(files[path]):
            if ref["name"] not in defined.get(ref["type"], set()):
                missing.append(f"{path}: @{ref['type']}/{ref['name']}")
    for path, content in files.items():
        if VALUES_FILE.fullmatch(path):
            for style in ET.fromstring(content).findall("style"):
                parent = style.get("parent")
                is_platform = parent is not None and parent.startswith(("android:", "@android:"))
                if parent and not is_platform and parent not in defined.get("style", set()):
                    missing.append(f"{path}: parent {parent} of {style.get('name')}")
    return missing


def namespaces_of(files: dict[str, str]) -> list[str]:
    return re.findall(r'^\s*namespace\s*=\s*"([^"]*)"\s*$', files["app/build.gradle.kts"], re.M)


@pytest.mark.parametrize("overrides", CONFIGS)
def test_every_manifest_and_resource_reference_resolves(overrides):
    files = {f.path: f.content for f in render_files(make(**overrides))}
    assert unresolved_references(files) == []
    # The check looked at something: the manifest and the themes do reference resources.
    assert RESOURCE_REFERENCE.search(files["app/src/main/AndroidManifest.xml"])
    assert RESOURCE_REFERENCE.search(files[f"{RES}/values/themes.xml"])


@pytest.mark.parametrize("overrides", CONFIGS)
def test_the_application_theme_is_defined_in_the_default_values_and_in_night(overrides):
    files = {f.path: f.content for f in render_files(make(**overrides))}
    (application,) = manifest(files).findall("application")
    theme = application.get(f"{ANDROID}theme")
    assert theme and theme.startswith("@style/")
    name = theme.removeprefix("@style/")
    assert name in defined_resources(files, "values")["style"]
    assert name in defined_resources(files, "values-night")["style"]


def test_the_reference_check_notices_a_style_that_does_not_exist():
    files = {f.path: f.content for f in render_files(make())}
    files["app/src/main/AndroidManifest.xml"] = files["app/src/main/AndroidManifest.xml"].replace(
        "@style/Theme.NotesApp", "@style/Theme.Missing"
    )
    assert unresolved_references(files) == [
        "app/src/main/AndroidManifest.xml: @style/Theme.Missing"
    ]


def test_the_reference_check_notices_a_resource_only_defined_for_night():
    files = {f.path: f.content for f in render_files(make())}
    files[f"{RES}/values/colors.xml"] = files[f"{RES}/values/colors.xml"].replace(
        "surface_light", "surface_light_renamed"
    )
    assert f"{RES}/values/themes.xml: @color/surface_light" in unresolved_references(files)


def test_the_reference_check_notices_an_unknown_parent_style():
    files = {f.path: f.content for f in render_files(make())}
    files[f"{RES}/values/themes.xml"] = files[f"{RES}/values/themes.xml"].replace(
        "android:Theme.Material.Light.NoActionBar", "Theme.Unknown.Parent"
    )
    assert any("parent Theme.Unknown.Parent" in line for line in unresolved_references(files))


@pytest.mark.parametrize("overrides", CONFIGS)
def test_the_app_module_has_exactly_one_valid_namespace_inside_the_android_block(overrides):
    from androai_codegen.templates import validate_package_name

    config = make(**overrides)
    files = {f.path: f.content for f in render_files(config)}
    (namespace,) = namespaces_of(files)
    assert validate_package_name(namespace) == namespace == config.package_name
    app = files["app/build.gradle.kts"]
    assert app.index("android {") < app.index("namespace") < app.index("defaultConfig {")
    # The namespace is not the application ID unless the config says so.
    assert f'applicationId = "{config.effective_application_id}"' in app


@pytest.mark.parametrize("overrides", CONFIGS)
def test_the_namespace_is_what_the_manifest_and_the_sources_resolve_against(overrides):
    config = make(**overrides)
    files = {f.path: f.content for f in render_files(config)}
    (namespace,) = namespaces_of(files)
    assert "package" not in manifest(files).attrib  # AGP 9 reads the namespace from Gradle only
    # ``android:name=".MainActivity"`` means ``<namespace>.MainActivity`` ...
    activity = manifest(files).find("application/activity").get(f"{ANDROID}name")
    assert activity == ".MainActivity"
    main = f"app/src/main/java/{namespace.replace('.', '/')}/MainActivity.kt"
    # ... which must be the class declared in that package.
    assert files[main].startswith(f"package {namespace}\n")
    assert "class MainActivity : ComponentActivity()" in files[main]
    # and R is generated in the namespace, which is what the screen imports.
    assert (
        f"import {namespace}.R\n"
        in files[f"app/src/main/java/{config.package_path}/ui/home/HomeScreen.kt"]
    )


def test_a_missing_or_duplicated_namespace_is_noticed_by_the_check():
    files = {f.path: f.content for f in render_files(make())}
    no_namespace = dict(files)
    no_namespace["app/build.gradle.kts"] = files["app/build.gradle.kts"].replace(
        'namespace = "com.example.notes"', ""
    )
    assert namespaces_of(no_namespace) == []
    twice = dict(files)
    twice["app/build.gradle.kts"] = files["app/build.gradle.kts"].replace(
        'namespace = "com.example.notes"',
        'namespace = "com.example.notes"\n    namespace = "com.example.other"',
    )
    assert len(namespaces_of(twice)) == 2


# --- resources ------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [p for p in EXPECTED_PATHS if p.endswith(".xml")])
def test_every_xml_file_is_well_formed_and_declares_utf8(files, path):
    assert files[path].startswith('<?xml version="1.0" encoding="utf-8"?>\n')
    ET.fromstring(files[path])


def test_resources_have_unique_names_per_type(files):
    for path in (f"{RES}/values/strings.xml", f"{RES}/values/colors.xml"):
        names = [e.get("name") for e in ET.fromstring(files[path])]
        assert len(names) == len(set(names)), path


def test_colors_are_valid_argb(files):
    for e in ET.fromstring(files[f"{RES}/values/colors.xml"]):
        assert re.fullmatch(r"#[0-9A-F]{8}", e.text), e.attrib


def test_every_resource_the_code_uses_exists(files):
    strings = {e.get("name") for e in ET.fromstring(files[f"{RES}/values/strings.xml"])}
    used = set()
    for content in kotlin_files(files).values():
        used |= set(re.findall(r"R\.string\.(\w+)", content))
    assert used and used <= strings


def test_the_two_themes_differ_only_in_parent_and_background(files):
    day = ET.fromstring(files[f"{RES}/values/themes.xml"]).find("style")
    night = ET.fromstring(files[f"{RES}/values-night/themes.xml"]).find("style")
    assert day.get("name") == night.get("name")
    assert day.get("parent") != night.get("parent")
    assert day.get("parent").startswith("android:Theme.Material")  # no extra library needed
    assert day.find("item").text != night.find("item").text


# --- Compose skeleton -----------------------------------------------------------------------


def test_main_activity_hosts_the_compose_content(files):
    main = files[f"{SRC}/MainActivity.kt"]
    assert "class MainActivity : ComponentActivity()" in main
    assert "setContent {" in main
    assert "enableEdgeToEdge()" in main
    assert "NotesAppTheme {" in main and "AppNavHost()" in main


def test_theme_is_a_composable_that_wraps_material_theme(files):
    theme = files[f"{SRC}/ui/theme/Theme.kt"]
    assert re.search(r"@Composable\nfun NotesAppTheme\(", theme)
    assert "content: @Composable () -> Unit" in theme
    assert "MaterialTheme(" in theme and "typography = Typography" in theme
    # Dynamic colour needs API 31, the minSdk is lower: it has to be guarded.
    assert "Build.VERSION.SDK_INT >= Build.VERSION_CODES.S" in theme


def test_theme_uses_colors_and_typography_that_are_defined(files):
    color = files[f"{SRC}/ui/theme/Color.kt"]
    theme = files[f"{SRC}/ui/theme/Theme.kt"]
    for name in re.findall(r"\b(Purple\w+|Pink\w+)\b", theme):
        assert f"val {name} = Color(" in color, name
    assert "val Typography = Typography(" in files[f"{SRC}/ui/theme/Type.kt"]


def test_navigation_host(files):
    nav = files[f"{SRC}/navigation/AppNavHost.kt"]
    assert "rememberNavController()" in nav
    assert "NavHost(" in nav and "startDestination = Routes.HOME" in nav
    assert 'const val HOME = "home"' in nav
    assert "composable(Routes.HOME)" in nav and "HomeScreen()" in nav
    assert re.search(r"@Composable\nfun AppNavHost\(", nav)


def test_sample_screen(files):
    screen = files[f"{SRC}/ui/home/HomeScreen.kt"]
    assert re.search(r"@Composable\nfun HomeScreen\(modifier: Modifier = Modifier\)", screen)
    assert "Scaffold(" in screen and "innerPadding" in screen
    assert "stringResource(R.string.app_name)" in screen
    assert re.search(r"@Preview\(showBackground = true\)\n@Composable\nprivate fun", screen)


def test_ui_tooling_is_a_debug_only_dependency(files):
    app = files["app/build.gradle.kts"]
    assert "debugImplementation(libs.androidx.compose.ui.tooling)" in app
    assert "\n    implementation(libs.androidx.compose.ui.tooling)" not in app


def test_the_navigation_route_is_a_string_constant_not_navigation_3(files):
    nav = files[f"{SRC}/navigation/AppNavHost.kt"]
    assert "androidx.navigation3" not in nav
    assert "androidx.navigation.compose.NavHost" in nav


# --- names that need care -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, identifier",
    [
        ("My Notes", "MyNotes"),
        ("2048 Game", "App2048Game"),
        ("नमस्ते", "App"),
        ("R&D", "RD"),
        ("Bob's", "BobS"),
    ],
)
def test_the_derived_theme_names_are_used_consistently(name, identifier):
    files = {f.path: f.content for f in render_files(make(project_name=name))}
    theme_fn = f"{identifier}Theme"
    assert f"fun {theme_fn}(" in files[f"{SRC}/ui/theme/Theme.kt"]
    assert f"ui.theme.{theme_fn}\n" in files[f"{SRC}/MainActivity.kt"]
    assert f"ui.theme.{theme_fn}\n" in files[f"{SRC}/ui/home/HomeScreen.kt"]
    assert f"@style/Theme.{identifier}" in files["app/src/main/AndroidManifest.xml"]
    for themes in ("values", "values-night"):
        assert f'name="Theme.{identifier}"' in files[f"{RES}/{themes}/themes.xml"]
    for path in files:
        if path.endswith(".xml"):
            ET.fromstring(files[path])


@pytest.mark.parametrize(
    "name", ["Notes", "R&D Tracker", "Bob's Notes", "Café", "नमस्ते", "メモ帳", "C++ (beta)!"]
)
def test_any_valid_name_gives_well_formed_xml_and_a_stable_file_set(name):
    files = {f.path: f.content for f in render_files(make(project_name=name))}
    assert sorted(files) == EXPECTED_PATHS
    for path, content in files.items():
        if path.endswith(".xml"):
            ET.fromstring(content)
    assert "$" not in "".join(c for p, c in files.items() if p.endswith(".kt"))
