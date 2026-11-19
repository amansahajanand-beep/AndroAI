"""Manifest rules (Phase 4b). Each defect has twins proving the rule stays quiet when it should."""

from sample_project import MAIN, broken, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine

MANIFEST = "app/src/main/AndroidManifest.xml"
APP_GRADLE = "app/build.gradle.kts"
PACKAGE = "com.example.todo"
TOOLS = 'xmlns:tools="http://schemas.android.com/tools"'
ACTIVITY_BLOCK = """        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:theme="@style/Theme.Todo">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
"""
INTERNET = '    <uses-permission android:name="android.permission.INTERNET" />\n'


def run(files):
    return ReviewEngine().review(ProjectFiles.from_mapping(files))


def found(files, prefix="manifest."):
    return sorted(
        (f.rule, f.file.rsplit("/", 1)[-1], f.key)
        for f in run(files).findings
        if f.rule.startswith(prefix)
    )


def kotlin(package: str, *lines: str) -> str:
    return f"package {package}\n\n" + "\n".join(lines) + "\n"


def with_manifest(extra: str = "", *, replace_activity: str | None = None, attrs: str = ""):
    """The good project with extra elements in <application>, optionally a changed MainActivity
    block, and extra attributes on <application>."""
    block = ACTIVITY_BLOCK if replace_activity is None else replace_activity
    files = broken({MANIFEST: (ACTIVITY_BLOCK, block + extra)})
    if attrs:
        files[MANIFEST] = files[MANIFEST].replace("<application", f"<application {attrs}", 1)
    return files


def with_sources(files, sources: dict[str, str]):
    out = dict(files)
    out.update({f"{MAIN}/{name}": text for name, text in sources.items()})
    return out


def edit_gradle(files, old, new):
    out = dict(files)
    assert old in out[APP_GRADLE], old
    out[APP_GRADLE] = out[APP_GRADLE].replace(old, new, 1)
    return out


def edit_manifest(files, old, new):
    out = dict(files)
    assert old in out[MANIFEST], old
    out[MANIFEST] = out[MANIFEST].replace(old, new, 1)
    return out


def test_the_known_good_project_has_no_manifest_findings():
    assert found(good_project()) == []


# --- declared classes that do not exist --------------------------------------------------------


def test_activity_declared_but_missing_is_reported():
    files = with_manifest(replace_activity=ACTIVITY_BLOCK.replace(".MainActivity", ".Ghost"))
    assert ("manifest.class_missing", "AndroidManifest.xml", f"{PACKAGE}.Ghost") in found(files)


def test_application_class_declared_but_missing_is_reported_then_fixed_by_creating_it():
    files = with_manifest(attrs='android:name=".TodoApp"')
    assert found(files) == [("manifest.class_missing", "AndroidManifest.xml", f"{PACKAGE}.TodoApp")]
    app = kotlin(PACKAGE, "import android.app.Application", "", "class TodoApp : Application()")
    assert found(with_sources(files, {"TodoApp.kt": app})) == []


def test_fully_qualified_library_components_are_not_ours_to_check():
    library = (
        '        <service android:name="com.google.firebase.messaging.FirebaseMessagingService"'
        ' android:exported="false" />\n'
    )
    assert found(with_manifest(library)) == []


def test_components_edited_out_at_merge_time_are_ignored():
    removed = '        <activity android:name=".Ghost" tools:node="remove" />\n'
    files = edit_manifest(with_manifest(removed), "<manifest ", f"<manifest {TOOLS} ")
    assert found(files) == []


def test_placeholder_names_are_not_resolved():
    placeholder = (
        '        <activity android:name="${applicationId}.Ghost" android:exported="false" />\n'
    )
    assert found(with_manifest(placeholder)) == []


def test_an_alias_must_point_at_a_real_class_or_declared_activity():
    alias = (
        '        <activity-alias android:name=".Alias" android:targetActivity=".MainActivity"'
        ' android:exported="true" />\n'
    )
    assert found(with_manifest(alias)) == []
    assert found(with_manifest(alias.replace(".MainActivity", ".Nope"))) == [
        ("manifest.class_missing", "AndroidManifest.xml", f"{PACKAGE}.Nope")
    ]


def test_an_alias_to_a_declared_but_missing_activity_reports_the_class_once():
    ghost = (
        '        <activity android:name=".Ghost" android:exported="false" />\n'
        '        <activity-alias android:name=".Alias" android:targetActivity=".Ghost"'
        ' android:exported="true" />\n'
    )
    findings = [f for f in run(with_manifest(ghost)).findings if f.rule == "manifest.class_missing"]
    assert [f.key for f in findings] == [f"{PACKAGE}.Ghost"]  # not twice: once for the alias too


def test_a_nested_class_declared_with_a_dollar_sign_is_found():
    files = with_manifest(
        '        <activity android:name=".Outer$Inner" android:exported="false" />\n'
    )
    outer = kotlin(
        PACKAGE,
        "import androidx.activity.ComponentActivity",
        "",
        "class Outer { class Inner : ComponentActivity() }",
    )
    assert found(with_sources(files, {"Outer.kt": outer})) == []


# --- classes started through an Intent but never declared --------------------------------------

SETTINGS = kotlin(
    PACKAGE,
    "import androidx.activity.ComponentActivity",
    "",
    "class SettingsActivity : ComponentActivity()",
)
OPENER = kotlin(
    PACKAGE,
    "import android.content.Context",
    "import android.content.Intent",
    "",
    "fun open(context: Context) {",
    "    context.startActivity(Intent(context, SettingsActivity::class.java))",
    "}",
)
DECLARE_SETTINGS = (
    '        <activity android:name=".SettingsActivity" android:exported="false" />\n'
)


def settings_project(*, declared: bool, opener: str = OPENER):
    files = with_sources(good_project(), {"SettingsActivity.kt": SETTINGS, "Opener.kt": opener})
    return (
        edit_manifest(files, ACTIVITY_BLOCK, ACTIVITY_BLOCK + DECLARE_SETTINGS)
        if declared
        else files
    )


def test_an_activity_started_through_an_intent_must_be_declared():
    assert found(settings_project(declared=False)) == [
        ("manifest.component_undeclared", "Opener.kt", f"{PACKAGE}.SettingsActivity")
    ]


def test_declaring_it_fixes_the_finding():
    assert found(settings_project(declared=True)) == []


def test_a_class_that_is_never_started_through_an_intent_is_not_reported():
    assert (
        found(settings_project(declared=False, opener=kotlin(PACKAGE, "fun noop() = Unit"))) == []
    )


def test_a_class_literal_that_is_not_an_intent_target_is_not_reported():
    reflection = kotlin(
        PACKAGE,
        "val name = SettingsActivity::class.java.simpleName",
        "val same = SettingsActivity::class == SettingsActivity::class",
    )
    assert found(settings_project(declared=False, opener=reflection)) == []


def test_services_and_receivers_follow_the_same_rule_and_inheritance_is_followed():
    sources = {
        "Sync.kt": kotlin(
            PACKAGE,
            "import android.app.Service",
            "import android.content.BroadcastReceiver",
            "import android.content.Context",
            "import android.content.Intent",
            "",
            "abstract class BaseService : Service()",
            "class SyncService : BaseService()",
            "class Boot : BroadcastReceiver()",
            "fun go(c: Context) {",
            "    c.startService(Intent(c, SyncService::class.java))",
            "    c.sendBroadcast(Intent(c, Boot::class.java))",
            "}",
        )
    }
    assert found(with_sources(good_project(), sources)) == [
        ("manifest.component_undeclared", "Sync.kt", f"{PACKAGE}.Boot"),
        ("manifest.component_undeclared", "Sync.kt", f"{PACKAGE}.SyncService"),
    ]


def test_abstract_classes_and_test_sources_are_ignored():
    files = with_sources(
        good_project(),
        {
            "SettingsActivity.kt": SETTINGS,
            "Base.kt": kotlin(
                PACKAGE,
                "import androidx.activity.ComponentActivity",
                "import android.content.Intent",
                "",
                "abstract class BaseActivity : ComponentActivity()",
                "val i = Intent(null, BaseActivity::class.java)",
            ),
        },
    )
    files["app/src/androidTest/java/com/example/todo/T.kt"] = kotlin(
        PACKAGE,
        "import android.content.Intent",
        "",
        "val j = Intent(null, SettingsActivity::class.java)",
    )
    assert found(files) == []


def test_placeholder_names_switch_the_undeclared_check_off():
    placeholder = (
        '        <activity android:name="${applicationId}.X" android:exported="false" />\n'
    )
    files = with_sources(
        with_manifest(placeholder), {"SettingsActivity.kt": SETTINGS, "Opener.kt": OPENER}
    )
    assert found(files) == []


# --- android:exported ---------------------------------------------------------------------------

FILTERED = """        <activity android:name=".Share">
            <intent-filter><action android:name="android.intent.action.SEND" /></intent-filter>
        </activity>
"""
SHARE = kotlin(
    PACKAGE, "import androidx.activity.ComponentActivity", "", "class Share : ComponentActivity()"
)


def share_project(block: str = FILTERED):
    return with_sources(with_manifest(block), {"Share.kt": SHARE})


def test_intent_filter_without_exported_fails_on_android_12_and_later():
    assert found(share_project()) == [
        ("manifest.exported_missing", "AndroidManifest.xml", "activity:.Share")
    ]


def test_exported_present_or_no_intent_filter_is_fine():
    exported = FILTERED.replace(
        'android:name=".Share"', 'android:name=".Share" android:exported="true"'
    )
    assert found(share_project(exported)) == []
    assert found(share_project('        <activity android:name=".Share" />\n')) == []


def test_exported_is_not_required_below_android_12():
    assert found(edit_gradle(share_project(), "targetSdk = 35", "targetSdk = 30")) == []


def test_exported_is_not_judged_when_the_target_sdk_is_unknown():
    assert found(edit_gradle(share_project(), "        targetSdk = 35\n", "")) == []


# --- duplicates ---------------------------------------------------------------------------------


def test_the_same_component_declared_twice_in_one_manifest_is_reported():
    twice = ACTIVITY_BLOCK.replace(
        '            android:theme="@style/Theme.Todo">', "            >", 1
    )
    assert found(with_manifest(twice)) == [
        ("manifest.duplicate_component", "AndroidManifest.xml", f"activity:{PACKAGE}.MainActivity")
    ]


# --- permissions --------------------------------------------------------------------------------


def without_internet(files=None):
    return edit_manifest(files or good_project(), INTERNET, "")


def test_network_code_without_the_internet_permission_is_reported():
    assert found(without_internet()) == [
        ("manifest.permission_missing", "Api.kt", "android.permission.INTERNET")
    ]


def test_a_dependency_that_brings_the_permission_silences_the_rule():
    firebase = '    implementation("com.google.firebase:firebase-messaging:24.0.0")\n'
    assert (
        found(
            edit_gradle(
                without_internet(), "    testImplementation", firebase + "    testImplementation"
            )
        )
        == []
    )


def test_an_unreadable_dependency_list_silences_the_rule():
    jar = '    implementation(files("libs/x.jar"))\n'
    assert (
        found(
            edit_gradle(
                without_internet(), "    testImplementation", jar + "    testImplementation"
            )
        )
        == []
    )


def test_network_imports_in_tests_do_not_need_the_permission():
    files = without_internet()
    files[f"{MAIN}/data/Api.kt"] = kotlin(f"{PACKAGE}.data", "interface Api")
    files["app/src/test/java/com/example/todo/NetTest.kt"] = kotlin(
        PACKAGE, "import okhttp3.OkHttpClient", "", "val client = OkHttpClient()"
    )
    assert found(files) == []


def test_camera_use_needs_the_camera_permission():
    camera = kotlin(
        PACKAGE,
        "import androidx.camera.core.CameraSelector",
        "",
        "val s = CameraSelector.DEFAULT_BACK_CAMERA",
    )
    files = with_sources(good_project(), {"Cam.kt": camera})
    assert found(files) == [("manifest.permission_missing", "Cam.kt", "android.permission.CAMERA")]
    declared = edit_manifest(
        files,
        INTERNET,
        INTERNET + '    <uses-permission android:name="android.permission.CAMERA" />\n',
    )
    assert found(declared) == []


def test_either_location_permission_is_enough():
    user = kotlin(
        PACKAGE,
        "import com.google.android.gms.location.LocationServices",
        "",
        "val l = LocationServices::class",
    )
    files = with_sources(good_project(), {"Loc.kt": user})
    assert found(files) == [
        ("manifest.permission_missing", "Loc.kt", "android.permission.ACCESS_FINE_LOCATION")
    ]
    for permission in ("ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION"):
        line = f'    <uses-permission android:name="android.permission.{permission}" />\n'
        assert found(edit_manifest(files, INTERNET, INTERNET + line)) == []


def test_a_permission_edited_out_at_merge_time_does_not_count_as_declared():
    removed = (
        '    <uses-permission android:name="android.permission.INTERNET" tools:node="remove" />\n'
    )
    files = edit_manifest(
        edit_manifest(good_project(), INTERNET, removed), "<manifest ", f"<manifest {TOOLS} "
    )
    assert [rule for rule, *_ in found(files)] == ["manifest.permission_missing"]


# --- launcher -----------------------------------------------------------------------------------


def no_entry_point():
    return with_manifest(replace_activity=ACTIVITY_BLOCK.replace("MAIN", "VIEW"))


def test_an_app_without_any_entry_point_gets_a_non_blocking_warning():
    findings = [f for f in run(no_entry_point()).findings if f.rule == "manifest.no_launcher"]
    assert len(findings) == 1 and not findings[0].blocking and findings[0].key == "app"


def test_a_library_module_needs_no_launcher():
    files = no_entry_point()
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":lib")'
    )
    files["lib/build.gradle.kts"] = 'plugins { id("com.android.library") }\n'
    files["lib/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application>'
        '<activity android:name=".A" android:exported="false" /></application></manifest>'
    )
    keys = [f.key for f in run(files).findings if f.rule == "manifest.no_launcher"]
    assert keys == ["app"]
