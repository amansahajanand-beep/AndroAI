"""Change-aware rules (Phase 4b): what a patch removes or alters versus the project before."""

from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine

MANIFEST = "app/src/main/AndroidManifest.xml"
APP = "app/build.gradle.kts"
PACKAGE = "com.example.todo"
INTERNET = '    <uses-permission android:name="android.permission.INTERNET" />\n'
MAIN_ACTIVITY = f"{MAIN}/MainActivity.kt"
UNIT_TEST = "app/src/test/java/com/example/todo/ExampleUnitTest.kt"
SETTINGS_DECL = '        <activity android:name=".Settings" android:exported="false" />\n'
SETTINGS_KT = (
    f"package {PACKAGE}\n\nimport androidx.activity.ComponentActivity\n\n"
    "class Settings : ComponentActivity()\n"
)


def review(before, after, config=None):
    engine = ReviewEngine(config)
    report = engine.review(
        ProjectFiles.from_mapping(after), before=ProjectFiles.from_mapping(before)
    )
    # a rule that crashes becomes this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def changes(before, after, config=None):
    return sorted(
        (f.rule, f.file.rsplit("/", 1)[-1], f.key)
        for f in review(before, after, config).findings
        if f.rule.startswith("change.")
    )


def edit(files, path, old, new):
    out = dict(files)
    assert old in out[path], f"{path}: {old!r}"
    out[path] = out[path].replace(old, new, 1)
    return out


def with_settings():
    files = edit(
        good_project(), MANIFEST, "    </application>", SETTINGS_DECL + "    </application>"
    )
    files[f"{MAIN}/Settings.kt"] = SETTINGS_KT
    return files


def test_an_unchanged_project_and_a_review_without_a_before_state_report_nothing():
    assert changes(good_project(), good_project()) == []
    report = ReviewEngine().review(
        ProjectFiles.from_mapping(edit(good_project(), MANIFEST, INTERNET, ""))
    )
    assert not [f for f in report.findings if f.rule.startswith("change.")]


# --- manifest -----------------------------------------------------------------------------------


def test_removing_a_component_from_the_manifest_is_reported_as_a_warning():
    after = edit(with_settings(), MANIFEST, SETTINGS_DECL, "")
    assert changes(with_settings(), after) == [
        ("change.component_removed", "AndroidManifest.xml", "activity:.Settings")
    ]
    assert not any(
        f.blocking for f in review(with_settings(), after).findings if f.rule.startswith("change.")
    )


def test_removing_a_permission_is_reported():
    after = edit(good_project(), MANIFEST, INTERNET, "")
    assert (
        "change.permission_removed",
        "AndroidManifest.xml",
        "android.permission.INTERNET",
    ) in changes(good_project(), after)


def test_a_component_becoming_exported_is_reported_unless_it_has_an_intent_filter():
    after = edit(
        with_settings(),
        MANIFEST,
        'android:name=".Settings" android:exported="false"',
        'android:name=".Settings" android:exported="true"',
    )
    assert changes(with_settings(), after) == [
        ("change.component_exported", "AndroidManifest.xml", "activity:.Settings")
    ]
    filtered = edit(
        with_settings(),
        MANIFEST,
        SETTINGS_DECL,
        '        <activity android:name=".Settings"><intent-filter>'
        '<action android:name="x.Y" /></intent-filter></activity>\n',
    )
    exposed = edit(
        filtered,
        MANIFEST,
        'android:name=".Settings"',
        'android:name=".Settings" android:exported="true"',
    )
    assert changes(filtered, exposed) == []


# --- build --------------------------------------------------------------------------------------


def test_removing_a_dependency_is_a_warning_but_swapping_how_it_is_declared_is_not():
    room = "    implementation(libs.androidx.room.runtime)\n"
    assert changes(good_project(), edit(good_project(), APP, room, "")) == [
        ("change.dependency_removed", "build.gradle.kts", "androidx.room:room-runtime")
    ]
    inline = edit(
        good_project(), APP, room, '    implementation("androidx.room:room-runtime:2.6.1")\n'
    )
    assert changes(good_project(), inline) == []


def test_removing_a_payment_or_auth_integration_needs_approval():
    stripe = '    implementation("com.stripe:stripe-android:20.0.0")\n'
    before = edit(good_project(), APP, "    testImplementation", stripe + "    testImplementation")
    [item] = [
        f for f in review(before, good_project()).findings if f.rule == "change.integration_removed"
    ]
    assert (
        item.blocking
        and item.approval == "remove_integration"
        and item.key == "com.stripe:stripe-android"
    )
    approved = ReviewConfig(granted_approvals=frozenset({"remove_integration"}))
    [done] = [
        f
        for f in review(before, good_project(), approved).findings
        if f.rule == "change.integration_removed"
    ]
    assert not done.blocking and done.description.endswith("(approved)")


def test_a_dependency_whose_alias_broke_is_not_reported_as_removed():
    after = edit(
        good_project(),
        "gradle/libs.versions.toml",
        'androidx-room-runtime = { group = "androidx.room", name = "room-runtime", '
        'version.ref = "room" }\n',
        "",
    )
    assert [r for r, *_ in changes(good_project(), after)] == []


def test_renaming_the_application_id_namespace_or_manifest_package_needs_approval():
    renamed = edit(
        good_project(),
        APP,
        'applicationId = "com.example.todo"',
        'applicationId = "com.example.other"',
    )
    [item] = [
        f for f in review(good_project(), renamed).findings if f.rule == "change.package_renamed"
    ]
    assert (
        item.blocking and item.approval == "rename_package" and item.key == f"{APP}:applicationId"
    )
    namespace = edit(
        good_project(), APP, 'namespace = "com.example.todo"', 'namespace = "com.example.other"'
    )
    assert [k for _, _, k in changes(good_project(), namespace)] == [f"{APP}:namespace"]
    with_package = edit(good_project(), MANIFEST, "<manifest ", f'<manifest package="{PACKAGE}" ')
    repackaged = edit(with_package, MANIFEST, f'package="{PACKAGE}"', 'package="com.example.other"')
    assert [k for _, _, k in changes(with_package, repackaged)] == [f"{MANIFEST}:package"]


def test_a_package_rename_is_one_finding_whichever_way_components_are_spelled():
    namespace = ('namespace = "com.example.todo"', 'namespace = "com.example.other"')
    relative = edit(good_project(), APP, *namespace)  # ".MainActivity" resolves elsewhere now
    assert [k for _, _, k in changes(good_project(), relative)] == [f"{APP}:namespace"]
    # a fully qualified name still names the same class when only the package changes
    qualified = edit(
        good_project(),
        MANIFEST,
        'android:name=".MainActivity"',
        f'android:name="{PACKAGE}.MainActivity"',
    )
    renamed = edit(qualified, APP, *namespace)
    assert [k for _, _, k in changes(qualified, renamed)] == [f"{APP}:namespace"]


def test_a_component_that_was_already_exported_is_not_reported_again():
    exported = edit(
        with_settings(),
        MANIFEST,
        'android:name=".Settings" android:exported="false"',
        'android:name=".Settings" android:exported="true"',
    )
    touched = edit(exported, f"{MAIN}/Settings.kt", "class Settings", "class Settings  ")
    assert changes(exported, touched) == []


def test_a_coordinated_rename_with_fully_qualified_names_is_one_finding():
    """Classes moved to the new package and the manifest names them in full."""
    qualified = edit(
        good_project(),
        MANIFEST,
        'android:name=".MainActivity"',
        f'android:name="{PACKAGE}.MainActivity"',
    )
    moved = edit(
        qualified, MANIFEST, f'"{PACKAGE}.MainActivity"', '"com.example.other.MainActivity"'
    )
    moved = edit(moved, APP, 'namespace = "com.example.todo"', 'namespace = "com.example.other"')
    assert [k for _, _, k in changes(qualified, moved)] == [f"{APP}:namespace"]


def test_the_manifest_package_attribute_rename_needs_approval_too():
    with_package = edit(good_project(), MANIFEST, "<manifest ", f'<manifest package="{PACKAGE}" ')
    repackaged = edit(with_package, MANIFEST, f'package="{PACKAGE}"', 'package="com.example.other"')
    [item] = [
        f for f in review(with_package, repackaged).findings if f.rule == "change.package_renamed"
    ]
    assert item.blocking and item.approval == "rename_package" and item.key == f"{MANIFEST}:package"


def test_spelling_a_component_name_differently_is_not_a_removal():
    qualified = edit(
        good_project(),
        MANIFEST,
        'android:name=".MainActivity"',
        f'android:name="{PACKAGE}.MainActivity"',
    )
    assert changes(good_project(), qualified) == []
    assert changes(qualified, good_project()) == []


def test_sdk_levels_changing_in_the_risky_direction_are_warnings():
    raised = edit(good_project(), APP, "minSdk = 24", "minSdk = 26")
    assert [k for _, _, k in changes(good_project(), raised)] == [f"{APP}:minSdk"]
    lowered = edit(
        edit(good_project(), APP, "targetSdk = 35", "targetSdk = 34"),
        APP,
        "compileSdk = 35",
        "compileSdk = 34",
    )
    assert [k for _, _, k in changes(good_project(), lowered)] == [
        f"{APP}:compileSdk",
        f"{APP}:targetSdk",
    ]
    safe = edit(
        edit(good_project(), APP, "minSdk = 24", "minSdk = 23"),
        APP,
        "targetSdk = 35",
        "targetSdk = 36",
    )
    assert changes(good_project(), safe) == []


# --- source -------------------------------------------------------------------------------------

JAVA = f"{MAIN}/util/Strings.java"
KOTLIN = f"{MAIN}/util/Strings.kt"
STRINGS_KT = f"package {PACKAGE}.util\n\nobject Strings\n"


def test_replacing_a_java_file_with_a_kotlin_one_needs_approval_and_so_does_the_reverse():
    after = {k: v for k, v in good_project().items() if k != JAVA} | {KOTLIN: STRINGS_KT}
    [item] = [
        f for f in review(good_project(), after).findings if f.rule == "change.language_converted"
    ]
    assert item.blocking and item.approval == "convert_language" and item.key == "java -> kotlin"
    [back] = [
        f for f in review(after, good_project()).findings if f.rule == "change.language_converted"
    ]
    assert back.key == "kotlin -> java"


def test_adding_kotlin_next_to_java_or_deleting_java_alone_is_not_a_conversion():
    assert changes(good_project(), good_project() | {KOTLIN: STRINGS_KT}) == []
    assert changes(good_project(), {k: v for k, v in good_project().items() if k != JAVA}) == []


XML_ACTIVITY = (
    f"package {PACKAGE}\n\nimport android.os.Bundle\nimport androidx.activity.ComponentActivity\n"
    f"import {PACKAGE}.R\n\nclass MainActivity : ComponentActivity() {{\n"
    "    override fun onCreate(savedInstanceState: Bundle?) {\n"
    "        super.onCreate(savedInstanceState)\n"
    "        setContentView(R.layout.activity_main)\n    }\n}\n"
)
BOTH_ACTIVITY = XML_ACTIVITY.replace(
    "setContentView(R.layout.activity_main)",
    "setContentView(R.layout.activity_main)\n        setContent { }",
)


def test_a_screen_converted_between_xml_and_compose_needs_approval():
    xml = good_project() | {MAIN_ACTIVITY: XML_ACTIVITY}
    [item] = [
        f for f in review(xml, good_project()).findings if f.rule == "change.ui_toolkit_converted"
    ]
    assert (
        item.blocking
        and item.approval == "convert_ui_toolkit"
        and "XML layouts -> Compose" in item.description
    )
    [back] = [
        f for f in review(good_project(), xml).findings if f.rule == "change.ui_toolkit_converted"
    ]
    assert "Compose -> XML layouts" in back.description


def test_a_screen_that_still_uses_both_toolkits_is_not_a_conversion():
    xml = good_project() | {MAIN_ACTIVITY: XML_ACTIVITY}
    assert changes(xml, good_project() | {MAIN_ACTIVITY: BOTH_ACTIVITY}) == []


EXTRA_TEST = (
    f"package {PACKAGE}\n\nimport org.junit.Test\n\n"
    "class MoreTest {\n    @Test fun a() { }\n}\n"
)


def test_fewer_tests_than_before_is_reported_but_moving_or_adding_tests_is_not():
    deleted = {k: v for k, v in good_project().items() if k != UNIT_TEST}
    assert changes(good_project(), deleted) == [
        ("change.tests_removed", "ExampleUnitTest.kt", UNIT_TEST)
    ]
    moved = deleted | {"app/src/test/java/com/example/todo/MoreTest.kt": EXTRA_TEST}
    assert changes(good_project(), moved) == []
    grown = good_project() | {"app/src/test/java/com/example/todo/MoreTest.kt": EXTRA_TEST}
    assert changes(good_project(), grown) == []


def test_disabled_rules_and_only_changed_files_are_respected():
    after = edit(good_project(), MANIFEST, INTERNET, "")
    config = ReviewConfig(disabled_rules=frozenset({"change.permission_removed"}))
    assert "change.permission_removed" not in [
        r for r, *_ in changes(good_project(), after, config)
    ]
