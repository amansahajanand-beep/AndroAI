"""Target SDK resolution (Phase 4b follow-up).

The review used to read ``targetSdk`` only when it was written as a number, so the rules that depend on it
(PendingIntent mutability, Android 14 receiver flags, cleartext, ``manifest.exported_missing``) were silent on
most real projects. It now also reads exactly two indirections, deterministically and without evaluating
anything: a version-catalog entry used as ``libs.versions.<name>.get().toInt()`` and a ``const val`` of a whole
number in ``buildSrc`` / ``build-logic``. Everything else is unknown, and unknown means silent.
"""

# ruff: noqa: E501  (the fixtures embed Kotlin, Gradle and TOML, like tests/sample_project.py)
import pytest
from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine, ReviewTarget
from androai_codegen.review.analysis import ProjectAnalysis

APP = "app/build.gradle.kts"
CATALOG = "gradle/libs.versions.toml"
MANIFEST = "app/src/main/AndroidManifest.xml"
PACKAGE = "com.example.todo"


def edit(files, path, old, new):
    out = dict(files)
    assert out[path].count(old) == 1, f"{path}: {old!r} must match once"
    out[path] = out[path].replace(old, new)
    return out


def analysis(files, target=None):
    return ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig(), target)


def review(files, before=None, target=None):
    report = ReviewEngine().review(
        ProjectFiles.from_mapping(files),
        before=ProjectFiles.from_mapping(before) if before is not None else None,
        target=target,
    )
    # a rule that crashes is turned into this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def rules(files, prefixes=("security.", "manifest.exported_missing")):
    return sorted({f.rule for f in review(files).findings if f.rule.startswith(prefixes)})


def resolved(files):
    a = analysis(files)
    return a.target_sdk_of(a.gradle_scripts[APP])


# --- the ways a target SDK can be written ---------------------------------------------------------------


def direct(files, sdk):
    return edit(files, APP, "targetSdk = 35", f"targetSdk = {sdk}")


def catalog(files, sdk, key="targetSdk", accessor="targetSdk", conversion=".get().toInt()"):
    files = edit(files, CATALOG, "[versions]\n", f'[versions]\n{key} = "{sdk}"\n')
    return edit(files, APP, "targetSdk = 35", f"targetSdk = libs.versions.{accessor}{conversion}")


def buildsrc(
    files,
    sdk,
    declaration="object Versions {\n    const val TARGET_SDK = {sdk}\n}",
    reference="Versions.TARGET_SDK",
    path="buildSrc/src/main/kotlin/Versions.kt",
):
    files = dict(files)
    files[path] = declaration.replace("{sdk}", str(sdk)) + "\n"
    return edit(files, APP, "targetSdk = 35", f"targetSdk = {reference}")


MECHANISMS = {
    "direct number": direct,
    "catalog": catalog,
    "catalog, kebab-case key": lambda f, s: catalog(f, s, key="target-sdk", accessor="target.sdk"),
    "catalog, snake_case key": lambda f, s: catalog(f, s, key="target_sdk", accessor="target.sdk"),
    "catalog, toInteger()": lambda f, s: catalog(f, s, conversion=".get().toInteger()"),
    "catalog, Integer.parseInt": lambda f, s: edit(
        edit(f, CATALOG, "[versions]\n", f'[versions]\ntargetSdk = "{s}"\n'),
        APP,
        "targetSdk = 35",
        "targetSdk = Integer.parseInt(libs.versions.targetSdk.get())",
    ),
    "buildSrc const in an object": buildsrc,
    "buildSrc nested objects": lambda f, s: buildsrc(
        f,
        s,
        "object Config {\n    object Sdk {\n        const val TARGET = {sdk}\n    }\n}",
        "Config.Sdk.TARGET",
    ),
    "buildSrc val in an object": lambda f, s: buildsrc(
        f, s, "object Versions {\n    val targetSdk = {sdk}\n}", "Versions.targetSdk"
    ),
    "buildSrc top-level const": lambda f, s: buildsrc(
        f, s, "const val TARGET_SDK = {sdk}", "TARGET_SDK"
    ),
    "build-logic const": lambda f, s: buildsrc(
        f, s, path="build-logic/convention/src/main/kotlin/Versions.kt"
    ),
}


@pytest.mark.parametrize("name", MECHANISMS)
def test_every_supported_way_of_writing_the_target_resolves_to_its_number_and_line(name):
    files = MECHANISMS[name](good_project(), 34)
    value = resolved(files)
    assert value is not None and value[0] == 34, name
    line = files[APP].split("\n")[value[1] - 1]
    assert "targetSdk" in line, (name, line)


def test_a_direct_number_is_read_exactly_as_before():
    a = analysis(good_project())
    script = a.gradle_scripts[APP]
    assert script.target_sdk is not None and a.target_sdk_of(script) == script.target_sdk
    groovy = edit(good_project(), APP, "targetSdk = 35", "targetSdkVersion 33")
    assert resolved(groovy)[0] == 33


# --- what is not resolved -------------------------------------------------------------------------------

UNRESOLVED = {
    "an alias the catalog does not have": lambda f: edit(
        f, APP, "targetSdk = 35", "targetSdk = libs.versions.nothing.get().toInt()"
    ),
    "a version that is not a whole number": lambda f: catalog(f, "34-rc01"),
    "a decimal version": lambda f: catalog(f, "34.1"),
    "a version table": lambda f: edit(
        edit(f, CATALOG, "[versions]\n", '[versions]\ntargetSdk = { require = "34" }\n'),
        APP,
        "targetSdk = 35",
        "targetSdk = libs.versions.targetSdk.get().toInt()",
    ),
    "arithmetic on a catalog version": lambda f: catalog(f, 34, conversion=".get().toInt() + 1"),
    "a catalog version used as a string": lambda f: catalog(f, 34, conversion=".get()"),
    "another conversion": lambda f: catalog(f, 34, conversion=".get().toLong().toInt()"),
    "rootProject.extra": lambda f: edit(
        f, APP, "targetSdk = 35", 'targetSdk = rootProject.extra["target"] as Int'
    ),
    "a Gradle property": lambda f: edit(
        f, APP, "targetSdk = 35", 'targetSdk = project.property("t").toString().toInt()'
    ),
    "a conditional": lambda f: edit(f, APP, "targetSdk = 35", "targetSdk = if (flag) 34 else 35"),
    "a constant that does not exist": lambda f: buildsrc(f, 34, reference="Versions.MISSING"),
    "a constant with arithmetic": lambda f: buildsrc(
        f, 34, "object Versions {\n    const val TARGET_SDK = 30 + 4\n}"
    ),
    "a string constant": lambda f: buildsrc(
        f, 34, 'object Versions {\n    const val TARGET_SDK = "34"\n}'
    ),
    "a plain val outside an object": lambda f: buildsrc(
        f, 34, "val TARGET_SDK = {sdk}", "TARGET_SDK"
    ),
    "a constant in a comment": lambda f: buildsrc(
        f, 34, "object Versions {\n    // const val TARGET_SDK = 34\n}"
    ),
    "a constant in a file outside buildSrc": lambda f: buildsrc(
        f, 34, path="app/src/main/kotlin/Versions.kt"
    ),
    "a constant of a method call": lambda f: buildsrc(
        f, 34, reference="Versions.TARGET_SDK.toInt()"
    ),
    "a convention plugin's value": lambda f: edit(f, APP, "        targetSdk = 35\n", ""),
}


@pytest.mark.parametrize("name", UNRESOLVED)
def test_anything_else_is_unknown(name):
    assert resolved(UNRESOLVED[name](good_project())) is None, name


def test_a_constant_declared_twice_with_different_values_is_dropped():
    files = buildsrc(good_project(), 34)
    files["buildSrc/src/main/kotlin/Other.kt"] = (
        "object Versions {\n    const val TARGET_SDK = 33\n}\n"
    )
    assert resolved(files) is None
    same = buildsrc(good_project(), 34)
    same["buildSrc/src/main/kotlin/Other.kt"] = (
        "object Versions {\n    const val TARGET_SDK = 34\n}\n"
    )
    assert resolved(same)[0] == 34


def test_two_catalog_keys_with_the_same_accessor_are_dropped():
    files = edit(
        catalog(good_project(), 34, key="target-sdk", accessor="target.sdk"),
        CATALOG,
        "[versions]\n",
        '[versions]\ntarget_sdk = "34"\n',
    )
    assert resolved(files) is None


def test_the_catalog_is_not_used_when_it_is_ambiguous_broken_or_not_the_only_one():
    two = catalog(good_project(), 34)
    two["build-logic/gradle/libs.versions.toml"] = '[versions]\ntargetSdk = "30"\n'
    assert resolved(two) is None
    broken = catalog(good_project(), 34)
    broken[CATALOG] = broken[CATALOG] + "\n[versions\n"
    assert resolved(broken) is None
    custom = catalog(good_project(), 34)
    custom["settings.gradle.kts"] += (
        'dependencyResolutionManagement {\n    versionCatalogs {\n        create("other") { from(files("../other.toml")) }\n    }\n}\n'
    )
    assert resolved(custom) is None


def test_a_direct_number_still_wins_and_otherwise_the_first_resolvable_expression_is_used():
    files = edit(
        good_project(),
        APP,
        "        targetSdk = 35\n",
        '        targetSdk = rootProject.extra["t"] as Int\n        targetSdk = 33\n',
    )
    assert resolved(files)[0] == 33  # unchanged: the written number
    via_constant = buildsrc(good_project(), 31)
    via_constant = edit(
        via_constant,
        APP,
        "        targetSdk = Versions.TARGET_SDK\n",
        '        targetSdk = rootProject.extra["t"] as Int\n        targetSdk = Versions.TARGET_SDK\n',
    )
    assert resolved(via_constant)[0] == 31


def test_comments_in_the_script_do_not_declare_a_target():
    files = edit(
        good_project(),
        APP,
        "        targetSdk = 35\n",
        "        // targetSdk = libs.versions.targetSdk.get().toInt()\n",
    )
    files = edit(files, CATALOG, "[versions]\n", '[versions]\ntargetSdk = "34"\n')
    assert resolved(files) is None


# --- every affected rule, through every supported mechanism ----------------------------------------------

CONTEXT_IMPORTS = "import android.app.PendingIntent\nimport android.content.BroadcastReceiver\nimport android.content.Context\nimport android.content.Intent\nimport android.content.IntentFilter\nimport retrofit2.Retrofit\n"
PROBE = {
    "pending": (
        "class Probe {\n    fun make(context: Context) = PendingIntent.getActivity(context, 0, Intent(context, Probe::class.java), 0)\n}",
        "security.pending_intent_mutability",
        31,
    ),
    "implicit": (
        'class Probe {\n    fun make(context: Context) = PendingIntent.getBroadcast(context, 0, Intent("x"), PendingIntent.FLAG_MUTABLE)\n}',
        "security.pending_intent_mutable_implicit",
        34,
    ),
    "receiver": (
        'class Probe(private val context: Context, private val receiver: BroadcastReceiver) {\n    fun start() {\n        context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))\n    }\n}',
        "security.receiver_export_flag_missing",
        34,
    ),
    "url": (
        'val client = Retrofit.Builder().baseUrl("http://api.acme.io/").build()',
        "security.cleartext_url_blocked",
        28,
    ),
}


def with_probe(files, kind):
    files = dict(files)
    files[f"{MAIN}/Probe.kt"] = f"package {PACKAGE}\n\n{CONTEXT_IMPORTS}\n{PROBE[kind][0]}\n"
    return files


@pytest.mark.parametrize("kind", PROBE)
@pytest.mark.parametrize("name", MECHANISMS)
def test_each_call_site_rule_follows_the_target_through_every_mechanism(name, kind):
    _body, rule, threshold = PROBE[kind]
    below = with_probe(MECHANISMS[name](good_project(), threshold - 1), kind)
    at = with_probe(MECHANISMS[name](good_project(), threshold), kind)
    assert rule not in rules(below), (name, kind, "below the threshold")
    assert rule in rules(at), (name, kind, "at the threshold")


def declared_and_requested(files):
    files = edit(
        files,
        MANIFEST,
        '    <uses-permission android:name="android.permission.INTERNET" />\n',
        '    <uses-permission android:name="android.permission.INTERNET" />\n    <uses-permission android:name="android.permission.CAMERA" />\n    <uses-permission android:name="android.permission.RECORD_AUDIO" />\n',
    )
    files[f"{MAIN}/Asks.kt"] = (
        f"package {PACKAGE}\n\nimport android.Manifest\nimport android.app.Activity\nimport androidx.core.app.ActivityCompat\n\n"
        "class Asks(private val activity: Activity) {\n    fun ask() = ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.RECORD_AUDIO), 1)\n}\n"
    )
    return files


@pytest.mark.parametrize("name", MECHANISMS)
def test_permissions_declared_but_never_requested_are_judged_from_install_time_below_23(name):
    below = declared_and_requested(MECHANISMS[name](good_project(), 22))
    at = declared_and_requested(MECHANISMS[name](good_project(), 23))
    assert "security.permission_never_requested" not in rules(below), name
    assert "security.permission_never_requested" in rules(at), name


def unexported_filter(files):
    element = '        <service android:name=".Worker"><intent-filter><action android:name="com.example.todo.X" /></intent-filter></service>\n'
    return edit(files, MANIFEST, "    </application>", element + "    </application>")


@pytest.mark.parametrize("name", MECHANISMS)
def test_exported_is_required_from_android_12_through_every_mechanism(name):
    below = unexported_filter(MECHANISMS[name](good_project(), 30))
    at = unexported_filter(MECHANISMS[name](good_project(), 31))
    assert "manifest.exported_missing" not in rules(below), name
    assert "manifest.exported_missing" in rules(at), name


@pytest.mark.parametrize("name", MECHANISMS)
def test_the_cleartext_note_about_the_platform_default_appears_from_android_9(name):
    def note(sdk):
        files = edit(
            MECHANISMS[name](good_project(), sdk),
            MANIFEST,
            'android:allowBackup="true"',
            'android:allowBackup="true"\n        android:usesCleartextTraffic="true"',
        )
        item = next(f for f in review(files).findings if f.rule == "security.cleartext_enabled")
        return "block it" in item.description

    assert note(27) is False and note(28) is True, name


# --- projects that must not change ---------------------------------------------------------------------


def test_a_project_whose_target_cannot_be_resolved_behaves_exactly_as_before():
    base = edit(
        good_project(), APP, "targetSdk = 35", 'targetSdk = rootProject.extra["target"] as Int'
    )
    for kind, (_body, rule, _threshold) in PROBE.items():
        assert rule not in rules(with_probe(base, kind)), kind
    assert "manifest.exported_missing" not in rules(unexported_filter(base))
    assert "security.permission_never_requested" not in rules(declared_and_requested(base))


def test_an_unreadable_application_target_is_not_replaced_by_the_callers():
    """Unchanged: the caller's target is the last resort only when the build has no application module
    at all (see test_review_security). An application whose own target is written in a way we cannot
    read stays unjudged rather than being judged by a value the build may contradict."""
    base = edit(
        good_project(), APP, "targetSdk = 35", 'targetSdk = rootProject.extra["target"] as Int'
    )
    files = with_probe(base, "pending")
    for sdk in (30, 33, 35):
        report = review(files, target=ReviewTarget(target_sdk=sdk))
        assert "security.pending_intent_mutability" not in {f.rule for f in report.findings}


def with_core(base):
    files = dict(base)
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":core")'
    )
    files["core/build.gradle.kts"] = (
        'plugins {\n    id("com.android.library")\n}\n\nandroid {\n    namespace = "com.example.core"\n    compileSdk = 35\n}\n'
    )
    files["core/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n'
    )
    files["core/src/main/java/com/example/core/Probe.kt"] = (
        "package com.example.core\n\nimport android.app.PendingIntent\nimport android.content.Context\nimport android.content.Intent\n\n"
        "fun make(context: Context): PendingIntent = PendingIntent.getActivity(context, 0, Intent(), 0)\n"
    )
    return files


def test_a_library_is_judged_by_the_target_its_application_resolves_to():
    assert "security.pending_intent_mutability" in rules(with_core(catalog(good_project(), 34)))
    assert "security.pending_intent_mutability" not in rules(with_core(catalog(good_project(), 30)))
    assert "security.pending_intent_mutability" not in rules(
        with_core(
            edit(good_project(), APP, "targetSdk = 35", 'targetSdk = rootProject.extra["t"] as Int')
        )
    )


def test_sdk_order_and_sdk_change_still_read_only_numbers_that_are_written_out():
    """Narrow on purpose: these two rules compare several SDK levels and were not part of the change."""
    higher_min = edit(catalog(good_project(), 34), APP, "minSdk = 24", "minSdk = 35")
    assert "gradle.sdk_order" not in {f.rule for f in review(higher_min).findings}
    control = edit(good_project(), APP, "minSdk = 24", "minSdk = 36")
    assert "gradle.sdk_order" in {f.rule for f in review(control).findings}
    before = catalog(good_project(), 35)
    after = edit(before, CATALOG, 'targetSdk = "35"', 'targetSdk = "33"')
    assert "change.sdk_changed" not in {f.rule for f in review(after, before=before).findings}


def test_the_known_good_project_and_a_resolved_one_stay_clean():
    for files in (good_project(), catalog(good_project(), 35), buildsrc(good_project(), 35)):
        assert rules(files) == []


def test_a_trailing_comment_or_space_does_not_hide_a_constant_or_a_catalog_reference():
    commented = edit(
        buildsrc(good_project(), 34),
        APP,
        "targetSdk = Versions.TARGET_SDK",
        "targetSdk = Versions.TARGET_SDK  // keep in sync",
    )
    assert resolved(commented)[0] == 34
    spaced = edit(
        catalog(good_project(), 34),
        APP,
        "targetSdk = libs.versions.targetSdk.get().toInt()",
        "targetSdk = libs.versions.targetSdk.get().toInt()   ",
    )
    assert resolved(spaced)[0] == 34
    block = edit(
        buildsrc(good_project(), 34),
        APP,
        "targetSdk = Versions.TARGET_SDK",
        "targetSdk = Versions.TARGET_SDK /* sdk */",
    )
    assert resolved(block)[0] == 34


def test_a_catalog_reference_without_a_catalog_is_unknown():
    files = catalog(good_project(), 34)
    del files[CATALOG]
    assert resolved(files) is None


def test_a_version_written_with_non_ascii_digits_is_not_a_number():
    assert resolved(catalog(good_project(), "\uff13\uff14")) is None


def test_a_library_that_resolves_its_own_target_is_judged_by_that_target():
    files = with_core(good_project())  # the application targets 35 directly
    files = edit(files, CATALOG, "[versions]\n", '[versions]\nlibTarget = "30"\n')
    files = edit(
        files,
        "core/build.gradle.kts",
        "    compileSdk = 35\n",
        "    compileSdk = 35\n    defaultConfig {\n        targetSdk = libs.versions.libTarget.get().toInt()\n    }\n",
    )
    assert "security.pending_intent_mutability" not in rules(
        files
    )  # judged by the library's own 30
    unresolved = edit(
        files,
        "core/build.gradle.kts",
        "libs.versions.libTarget.get().toInt()",
        "libs.versions.nothing.get().toInt()",
    )
    assert "security.pending_intent_mutability" in rules(
        unresolved
    )  # falls back to the application's 35
