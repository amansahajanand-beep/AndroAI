"""Security rules (Phase 4b-2b).

Basis, checked against developer.android.com: PendingIntent mutability is mandatory from Android 12
and a mutable PendingIntent around an implicit Intent throws from Android 14 (unless
FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT); context-registered receivers must pass an export flag from
Android 14 for non-system broadcasts; providers are not exported by default and should protect what
they export; cleartext is blocked by default from Android 9 and ignored-attribute rules around the
network security config; dangerous permissions must be declared and requested.

Each rule has twins that must stay quiet: the compliant form, the form the analyzer cannot read, and
the situation where the premise (target SDK, manifest content) does not hold.
"""

# ruff: noqa: E501  (the fixtures embed manifest XML and Kotlin, like tests/sample_project.py)
from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine, ReviewTarget
from androai_codegen.review.catalog import DANGEROUS_PERMISSIONS, SPECIAL_ACCESS_PERMISSIONS

MANIFEST = "app/src/main/AndroidManifest.xml"
DEBUG_MANIFEST = "app/src/debug/AndroidManifest.xml"
TEST_MANIFEST = "app/src/androidTest/AndroidManifest.xml"
APP = "app/build.gradle.kts"
NSC = "app/src/main/res/xml/network_security_config.xml"
PACKAGE = "com.example.todo"
INTERNET = '    <uses-permission android:name="android.permission.INTERNET" />\n'


def review(files, before=None, config=None):
    engine = ReviewEngine(config)
    report = engine.review(
        ProjectFiles.from_mapping(files),
        before=ProjectFiles.from_mapping(before) if before is not None else None,
    )
    # a rule that crashes is turned into this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def found(files, prefix="security."):
    return sorted((f.rule, f.key) for f in review(files).findings if f.rule.startswith(prefix))


def rules(files, prefix="security."):
    return sorted({rule for rule, _ in found(files, prefix)})


def edit(files, path, old, new):
    out = dict(files)
    assert out[path].count(old) == 1, f"{path}: {old!r} must match once"
    out[path] = out[path].replace(old, new)
    return out


def kt(body, imports=""):
    return f"package {PACKAGE}\n\n{imports}\n{body}\n"


def with_code(body, imports="", *, name="Probe", base=None, path=None):
    out = dict(base or good_project())
    out[path or f"{MAIN}/{name}.kt"] = kt(body, imports)
    return out


def with_java(body, *, name="Probe", base=None):
    out = dict(base or good_project())
    out[f"{MAIN}/{name}.java"] = f"package {PACKAGE};\n\n{body}\n"
    return out


def with_xml(*elements, base=None):
    return edit(
        base or good_project(),
        MANIFEST,
        "    </application>",
        "".join(elements) + "    </application>",
    )


def with_permissions(*names, base=None, extra=""):
    lines = "".join(
        f'    <uses-permission android:name="android.permission.{n}"{extra} />\n' for n in names
    )
    return edit(base or good_project(), MANIFEST, INTERNET, INTERNET + lines)


def application_attr(attr, base=None):
    return edit(
        base or good_project(),
        MANIFEST,
        'android:allowBackup="true"',
        f'android:allowBackup="true"\n        {attr}',
    )


def target(files, sdk):
    """The project with targetSdk set to ``sdk``, or unreadable when ``sdk`` is ``None``."""
    new = 'targetSdk = rootProject.extra["target"] as Int' if sdk is None else f"targetSdk = {sdk}"
    return edit(files, APP, "targetSdk = 35", new)


def test_the_known_good_project_has_no_security_findings():
    assert found(good_project()) == []


def test_the_permission_tables_match_the_documented_protection_levels():
    """Pinned to the android.Manifest.permission reference ("Protection level: dangerous"; the
    appop / installer-granted special-access permissions). A typo in the catalog must fail here."""
    assert (
        frozenset(
            """ACCEPT_HANDOVER ACCESS_BACKGROUND_LOCATION ACCESS_COARSE_LOCATION ACCESS_FINE_LOCATION
        ACCESS_LOCAL_NETWORK ACCESS_MEDIA_LOCATION ACTIVITY_RECOGNITION ADD_VOICEMAIL
        ANSWER_PHONE_CALLS BLUETOOTH_ADVERTISE BLUETOOTH_CONNECT BLUETOOTH_SCAN BODY_SENSORS
        BODY_SENSORS_BACKGROUND CALL_PHONE CAMERA GET_ACCOUNTS NEARBY_WIFI_DEVICES POST_NOTIFICATIONS
        PROCESS_OUTGOING_CALLS RANGING READ_CALENDAR READ_CALL_LOG READ_CONTACTS
        READ_EXTERNAL_STORAGE READ_MEDIA_AUDIO READ_MEDIA_IMAGES READ_MEDIA_VIDEO
        READ_MEDIA_VISUAL_USER_SELECTED READ_PHONE_NUMBERS READ_PHONE_STATE READ_SMS RECEIVE_MMS
        RECEIVE_SMS RECEIVE_WAP_PUSH RECORD_AUDIO SEND_SMS USE_SIP UWB_RANGING WRITE_CALENDAR
        WRITE_CALL_LOG WRITE_CONTACTS WRITE_EXTERNAL_STORAGE""".split()
        )
        == DANGEROUS_PERMISSIONS
    )
    assert {
        "SYSTEM_ALERT_WINDOW",
        "MANAGE_EXTERNAL_STORAGE",
        "WRITE_SETTINGS",
        "REQUEST_INSTALL_PACKAGES",
        "PACKAGE_USAGE_STATS",
    } == SPECIAL_ACCESS_PERMISSIONS
    assert not DANGEROUS_PERMISSIONS & SPECIAL_ACCESS_PERMISSIONS


# --- exported providers -----------------------------------------------------------------------------

PROVIDER = '        <provider android:name=".Notes" android:authorities="com.example.todo.notes" android:exported="true"{attrs}>{children}</provider>\n'


def provider(attrs="", children=""):
    return PROVIDER.format(attrs=(" " + attrs) if attrs else "", children=children)


def test_an_exported_provider_without_a_permission_is_reported():
    files = with_xml(provider())
    assert found(files) == [("security.provider_exported_unprotected", "provider:.Notes")]
    finding = next(f for f in review(files).findings if f.rule.startswith("security."))
    assert not finding.blocking and finding.severity.value == "warning"


def test_a_provider_that_can_grant_uri_permissions_says_so():
    files = with_xml(provider('android:grantUriPermissions="true"'))
    message = next(
        f for f in review(files).findings if f.rule == "security.provider_exported_unprotected"
    )
    assert "grant URI permissions" in message.description
    plain = next(
        f
        for f in review(with_xml(provider())).findings
        if f.rule == "security.provider_exported_unprotected"
    )
    assert "grant URI permissions" not in plain.description


def test_a_provider_protected_by_any_permission_is_quiet():
    for attrs in (
        'android:permission="com.example.todo.READ"',
        'android:readPermission="com.example.todo.READ"',
        'android:writePermission="com.example.todo.WRITE"',
    ):
        assert rules(with_xml(provider(attrs))) == [], attrs
    paths = (
        '<path-permission android:pathPrefix="/private" android:permission="com.example.todo.P" />'
    )
    assert rules(with_xml(provider(children=paths))) == []


def test_a_provider_that_is_not_exported_or_is_edited_out_is_quiet():
    private = '        <provider android:name=".Notes" android:authorities="a.b" android:exported="false" />\n'
    unspecified = '        <provider android:name=".Notes" android:authorities="a.b" />\n'
    removed = '        <provider android:name=".Notes" android:authorities="a.b" android:exported="true" tools:node="remove" />\n'
    assert rules(with_xml(private)) == []
    assert rules(with_xml(unspecified)) == []
    assert rules(with_xml(removed)) == []


def test_a_manifest_in_a_test_source_set_is_not_judged():
    files = good_project()
    files[TEST_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        f"    <application>\n{provider()}    </application>\n</manifest>\n"
    )
    assert rules(files) == []
    shipping = good_project()
    shipping["app/src/debug/AndroidManifest.xml"] = files[TEST_MANIFEST]
    assert rules(shipping) == ["security.provider_exported_unprotected"]


# --- provider grants --------------------------------------------------------------------------------


def grant(attr):
    return f"<grant-uri-permission {attr} />"


def test_a_grant_for_every_path_is_reported():
    for attr in ('android:pathPrefix="/"', 'android:pathPattern=".*"', 'android:pathPattern="/.*"'):
        files = with_xml(provider('android:permission="p.P"', grant(attr)))
        assert found(files) == [("security.provider_grants_all", "provider:.Notes")], attr


def test_a_grant_for_a_narrow_path_is_quiet():
    for attr in (
        'android:pathPrefix="/shared"',
        'android:path="/"',
        'android:pathPattern="/shared/.*"',
    ):
        files = with_xml(provider('android:permission="p.P"', grant(attr)))
        assert rules(files) == [], attr


def test_a_file_provider_with_the_standard_declaration_is_quiet():
    standard = (
        '        <provider android:name="androidx.core.content.FileProvider" android:authorities="com.example.todo.files"'
        ' android:exported="false" android:grantUriPermissions="true">'
        '<meta-data android:name="android.support.FILE_PROVIDER_PATHS" android:resource="@xml/paths" /></provider>\n'
    )
    assert rules(with_xml(standard)) == []


# --- exported services and receivers ----------------------------------------------------------------


def component(tag, attrs="", actions=()):
    inner = "".join(
        f'<intent-filter><action android:name="{a}" /></intent-filter>' for a in actions
    )
    return f'        <{tag} android:name=".Worker" android:exported="true"{(" " + attrs) if attrs else ""}>{inner}</{tag}>\n'


def test_an_exported_service_without_a_permission_is_reported():
    assert found(with_xml(component("service"))) == [
        ("security.service_exported_unprotected", "service:.Worker")
    ]
    custom = component("service", actions=("com.example.todo.SYNC",))
    assert rules(with_xml(custom)) == ["security.service_exported_unprotected"]


def test_an_exported_receiver_without_a_permission_is_reported():
    custom = component("receiver", actions=("com.example.todo.REFRESH",))
    assert found(with_xml(custom)) == [
        ("security.receiver_exported_unprotected", "receiver:.Worker")
    ]
    assert rules(with_xml(component("receiver"))) == ["security.receiver_exported_unprotected"]


def test_a_protected_unexported_or_platform_contract_component_is_quiet():
    for tag in ("service", "receiver"):
        assert rules(with_xml(component(tag, 'android:permission="com.example.todo.USE"'))) == []
        private = f'        <{tag} android:name=".Worker" android:exported="false" />\n'
        assert rules(with_xml(private)) == []
    platform = component("service", actions=("androidx.media3.session.MediaSessionService",))
    assert rules(with_xml(platform)) == []
    boot = component("receiver", actions=("android.intent.action.BOOT_COMPLETED",))
    assert rules(with_xml(boot)) == []
    mixed = component(
        "receiver", actions=("com.example.todo.X", "android.intent.action.BOOT_COMPLETED")
    )
    assert rules(with_xml(mixed)) == []


def test_an_implicitly_exported_component_is_left_to_the_exported_rule():
    implicit = '        <service android:name=".Worker"><intent-filter><action android:name="com.example.todo.X" /></intent-filter></service>\n'
    files = with_xml(implicit)
    assert rules(files) == []
    assert "manifest.exported_missing" in rules(files, "manifest.")


# --- cleartext: manifest and network security config --------------------------------------------------


def test_uses_cleartext_traffic_true_is_reported():
    files = application_attr('android:usesCleartextTraffic="true"')
    assert found(files) == [("security.cleartext_enabled", "usesCleartextTraffic")]
    assert (
        "block it"
        in next(
            f for f in review(files).findings if f.rule == "security.cleartext_enabled"
        ).description
    )


def test_uses_cleartext_traffic_false_absent_or_placeholder_is_quiet():
    assert rules(application_attr('android:usesCleartextTraffic="false"')) == []
    assert rules(good_project()) == []
    assert rules(application_attr('android:usesCleartextTraffic="${cleartext}"')) == []


def test_cleartext_enabled_only_in_a_debug_manifest_is_not_reported():
    files = good_project()
    files[DEBUG_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <application android:usesCleartextTraffic="true" />\n</manifest>\n'
    )
    assert rules(files) == []


def test_the_default_note_is_left_out_when_the_target_sdk_is_not_known():
    files = target(application_attr('android:usesCleartextTraffic="true"'), None)
    message = next(f for f in review(files).findings if f.rule == "security.cleartext_enabled")
    assert "block it" not in message.description


def nsc(body):
    return f'<?xml version="1.0" encoding="utf-8"?>\n<network-security-config>\n{body}\n</network-security-config>\n'


def with_nsc(body, *, attr='android:networkSecurityConfig="@xml/network_security_config"'):
    files = application_attr(attr)
    files[NSC] = nsc(body)
    return files


def test_a_config_that_permits_cleartext_everywhere_is_reported():
    files = with_nsc('    <base-config cleartextTrafficPermitted="true" />')
    assert found(files) == [("security.cleartext_permitted", "base-config:all domains")]


def test_a_config_that_permits_cleartext_for_a_real_domain_is_reported():
    body = '    <domain-config cleartextTrafficPermitted="true"><domain includeSubdomains="true">feeds.acme.io</domain></domain-config>'
    assert found(with_nsc(body)) == [
        ("security.cleartext_permitted", "domain-config:feeds.acme.io")
    ]


def test_a_config_for_development_hosts_or_without_cleartext_is_quiet():
    local = '    <domain-config cleartextTrafficPermitted="true"><domain>10.0.2.2</domain><domain>localhost</domain></domain-config>'
    assert rules(with_nsc(local)) == []
    mixed_case = '    <domain-config cleartextTrafficPermitted="true"><domain>Printer.LOCAL</domain></domain-config>'
    assert rules(with_nsc(mixed_case)) == []
    one_real = '    <domain-config cleartextTrafficPermitted="true"><domain>localhost</domain><domain>feeds.acme.io</domain></domain-config>'
    assert rules(with_nsc(one_real)) == ["security.cleartext_permitted"]
    blocked = '    <domain-config cleartextTrafficPermitted="false"><domain>feeds.acme.io</domain></domain-config>'
    assert rules(with_nsc(blocked)) == []
    debug = '    <debug-overrides><trust-anchors><certificates src="user" /></trust-anchors></debug-overrides>'
    assert rules(with_nsc(debug)) == []
    base = '    <base-config cleartextTrafficPermitted="false" />'
    assert rules(with_nsc(base)) == []


def test_a_config_that_cannot_be_found_is_not_judged():
    files = application_attr('android:networkSecurityConfig="@xml/network_security_config"')
    assert rules(files) == []
    assert rules(application_attr('android:networkSecurityConfig="${config}"')) == []


def test_the_manifest_flag_is_ignored_when_a_config_exists_so_only_the_config_is_judged():
    files = with_nsc('    <base-config cleartextTrafficPermitted="true" />')
    files = edit(
        files,
        MANIFEST,
        'android:allowBackup="true"',
        'android:allowBackup="true" android:usesCleartextTraffic="true"',
    )
    assert rules(files) == ["security.cleartext_permitted"]


# --- cleartext: plain-HTTP URLs under the platform default ---------------------------------------------

RETROFIT = "import retrofit2.Retrofit\n"


def url_code(literal, call='Retrofit.Builder().baseUrl("{u}").build()'):
    return with_code(f"val client = {call.format(u=literal)}\n", RETROFIT)


def test_a_plain_http_url_is_reported_when_nothing_permits_cleartext():
    files = url_code("http://api.acme.io/v1/")
    assert found(files) == [("security.cleartext_url_blocked", "http://api.acme.io/v1/#1")]
    assert rules(url_code("http://api.acme.io:8080/v1/")) == ["security.cleartext_url_blocked"]


def test_url_and_java_url_calls_are_read_too():
    assert rules(
        url_code("http://api.acme.io/", 'okhttp3.Request.Builder().url("{u}").build()')
    ) == ["security.cleartext_url_blocked"]
    java = with_java(
        'class Probe {\n    void open() throws Exception {\n        new java.net.URL("http://api.acme.io/x").openConnection();\n    }\n}'
    )
    assert rules(java) == ["security.cleartext_url_blocked"]


def test_https_local_placeholder_and_templated_urls_are_quiet():
    for literal in (
        "https://api.acme.io/",
        "http://localhost:8080/",
        "http://10.0.2.2:3000/",
        "http://192.168.1.20/",
        "http://172.20.0.5/",
        "http://172.16.0.1/",
        "http://172.31.255.1/",
        "http://169.254.1.1/",
        "http://Printer.LOCAL/",
        "http://127.0.0.1/",
        "http://0.0.0.0:8080/",
        "http://[::1]:8080/",
        "http://api.example.com/",
        "http://printer.local/",
        "http://dev.acme.test/",
        "http://intranet/",
        "http://$host/",
        "http://${env}.acme.io/",
        "http://api.acme.io/$path",
    ):
        assert rules(url_code(literal)) == [], literal


def test_public_addresses_close_to_the_private_ranges_are_still_reported():
    for literal in (
        "http://8.8.8.8/",
        "http://172.32.0.5/",
        "http://172.15.0.5/",
        "http://192.169.1.1/",
    ):
        assert rules(url_code(literal)) == ["security.cleartext_url_blocked"], literal


def test_a_call_named_url_with_other_arguments_is_not_a_url_call():
    assert (
        rules(
            with_code('fun go() = url("http://api.acme.io/", 80)\nfun url(a: String, b: Int) {}\n')
        )
        == []
    )


def test_a_url_in_a_test_source_set_is_quiet():
    files = with_code(
        'val c = Retrofit.Builder().baseUrl("http://api.acme.io/").build()\n',
        RETROFIT,
        path="app/src/test/java/com/example/todo/ProbeTest.kt",
    )
    assert rules(files) == []


def test_a_url_is_not_judged_when_cleartext_is_permitted_somewhere_or_unreadable():
    assert rules(
        application_attr('android:usesCleartextTraffic="true"', url_code("http://api.acme.io/"))
    ) == ["security.cleartext_enabled"]
    permitted = with_nsc('    <base-config cleartextTrafficPermitted="true" />')
    permitted = with_code(
        'val c = Retrofit.Builder().baseUrl("http://api.acme.io/").build()\n',
        RETROFIT,
        base=permitted,
    )
    assert "security.cleartext_url_blocked" not in rules(permitted)
    local_only = with_nsc(
        '    <domain-config cleartextTrafficPermitted="true"><domain>localhost</domain></domain-config>'
    )
    local_only = with_code(
        'val c = Retrofit.Builder().baseUrl("http://api.acme.io/").build()\n',
        RETROFIT,
        base=local_only,
    )
    assert rules(local_only) == []
    missing = application_attr(
        'android:networkSecurityConfig="@xml/network_security_config"',
        url_code("http://api.acme.io/"),
    )
    assert rules(missing) == []
    placeholder = application_attr(
        'android:usesCleartextTraffic="${cleartext}"', url_code("http://api.acme.io/")
    )
    assert rules(placeholder) == []
    config_placeholder = application_attr(
        'android:networkSecurityConfig="${config}"', url_code("http://api.acme.io/")
    )
    assert rules(config_placeholder) == []


def test_a_url_is_not_judged_when_the_target_sdk_is_below_28_or_unknown():
    assert rules(target(url_code("http://api.acme.io/"), 27)) == []
    assert rules(target(url_code("http://api.acme.io/"), None)) == []
    assert rules(target(url_code("http://api.acme.io/"), 28)) == ["security.cleartext_url_blocked"]


def test_a_url_is_not_judged_when_a_manifest_could_not_be_parsed():
    files = url_code("http://api.acme.io/")
    files[DEBUG_MANIFEST] = "<manifest"
    assert rules(files) == []


def test_a_manifest_in_a_test_source_set_that_does_not_parse_does_not_silence_the_rule():
    files = url_code("http://api.acme.io/")
    files[TEST_MANIFEST] = "<manifest"
    assert rules(files) == ["security.cleartext_url_blocked"]


def test_each_plain_http_url_gets_its_own_key():
    body = 'val a = Retrofit.Builder().baseUrl("http://api.acme.io/").build()\nval b = Retrofit.Builder().baseUrl("http://api.acme.io/").build()\n'
    assert found(with_code(body, RETROFIT)) == [
        ("security.cleartext_url_blocked", "http://api.acme.io/#1"),
        ("security.cleartext_url_blocked", "http://api.acme.io/#2"),
    ]


# --- PendingIntent mutability --------------------------------------------------------------------------

PENDING_IMPORTS = "import android.app.PendingIntent\nimport android.content.Context\nimport android.content.Intent\n"


def pending(
    flags,
    *,
    intent="Intent(context, Probe::class.java)",
    kind="getActivity",
    imports=PENDING_IMPORTS,
):
    body = f"class Probe {{\n    fun make(context: Context, flags: Int, base: Intent): PendingIntent =\n        PendingIntent.{kind}(context, 0, {intent}, {flags})\n}}"
    return with_code(body, imports)


def test_a_pending_intent_without_mutability_is_an_error():
    for flags in (
        "0",
        "PendingIntent.FLAG_UPDATE_CURRENT",
        "PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_ONE_SHOT",
        "(PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_ONE_SHOT)",
        "PendingIntent.FLAG_CANCEL_CURRENT",
    ):
        files = pending(flags)
        assert [r for r, _ in found(files)] == ["security.pending_intent_mutability"], flags
    finding = next(
        f for f in review(pending("0")).findings if f.rule == "security.pending_intent_mutability"
    )
    assert finding.blocking and finding.severity.value == "error"
    assert finding.approval is None


def test_every_pending_intent_factory_is_checked():
    for kind in ("getActivity", "getBroadcast", "getService", "getForegroundService"):
        assert rules(pending("0", kind=kind)) == ["security.pending_intent_mutability"], kind
    activities = pending("0", intent="arrayOf(Intent())", kind="getActivities")
    assert rules(activities) == ["security.pending_intent_mutability"]


def test_a_pending_intent_that_states_its_mutability_is_quiet():
    for flags in (
        "PendingIntent.FLAG_IMMUTABLE",
        "PendingIntent.FLAG_MUTABLE",
        "PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE",
        "PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT",
        "(PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)",
    ):
        assert rules(pending(flags)) == [], flags


def test_flags_the_analyzer_cannot_read_are_not_judged():
    for flags in (
        "flags",
        "flags or PendingIntent.FLAG_UPDATE_CURRENT",
        "if (flags > 0) PendingIntent.FLAG_IMMUTABLE else 0",
        "Intent.FLAG_ACTIVITY_NEW_TASK",
        "PendingIntent.FLAG_UPDATE_CURRENT or 67108864",
        "PendingIntent.FLAG_MUTABLE_UNAUDITED",
        "flags = PendingIntent.FLAG_UPDATE_CURRENT",
    ):
        assert rules(pending(flags)) == [], flags


def test_comments_inside_the_flags_neither_hide_nor_add_a_flag():
    assert (
        rules(
            pending(
                "/* flags = */ PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE"
            )
        )
        == []
    )
    assert rules(pending("/* flags = */ PendingIntent.FLAG_UPDATE_CURRENT")) == [
        "security.pending_intent_mutability"
    ]
    lookup = "// Using NO_CREATE so it returns null if the PI is not there\n PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_MUTABLE"
    assert rules(pending(lookup)) == []
    noted = "// this one is not FLAG_IMMUTABLE\n PendingIntent.FLAG_UPDATE_CURRENT"
    assert rules(pending(noted)) == ["security.pending_intent_mutability"]


def test_a_call_with_fewer_than_four_arguments_is_not_a_pending_intent_creation():
    short = with_code(
        "class Probe {\n    fun make(context: Context, intent: Intent) = PendingIntent.getActivity(context, 0, intent)\n}",
        PENDING_IMPORTS,
    )
    assert rules(short) == []


def test_a_pending_intent_lookup_with_no_create_is_not_a_creation():
    assert rules(pending("PendingIntent.FLAG_NO_CREATE")) == []
    assert rules(pending("PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_UPDATE_CURRENT")) == []


def test_the_androidx_helper_and_commented_code_are_not_pending_intent_calls():
    helper = with_code(
        "class Probe {\n    fun make(context: Context) = PendingIntentCompat.getActivity(context, 0, Intent(), 0, false)\n}",
        "import androidx.core.app.PendingIntentCompat\nimport android.content.Context\nimport android.content.Intent\n",
    )
    assert rules(helper) == []
    commented = with_code(
        'class Probe {\n    // PendingIntent.getActivity(context, 0, intent, 0)\n    /* PendingIntent.getBroadcast(context, 0, intent, 0) */\n    val text = "PendingIntent.getService(c, 0, i, 0)"\n}'
    )
    assert rules(commented) == []


def test_pending_intent_mutability_follows_the_target_sdk():
    assert rules(target(pending("0"), 30)) == []
    assert rules(target(pending("0"), 31)) == ["security.pending_intent_mutability"]
    assert rules(target(pending("0"), None)) == []


def test_java_pending_intents_are_read():
    java = with_java(
        "import android.app.PendingIntent;\nimport android.content.Context;\nimport android.content.Intent;\n\nclass Probe {\n"
        "    PendingIntent make(Context c) {\n        return PendingIntent.getActivity(c, 0, new Intent(c, Probe.class), PendingIntent.FLAG_UPDATE_CURRENT);\n    }\n"
        "    PendingIntent safe(Context c) {\n        return PendingIntent.getActivity(c, 0, new Intent(c, Probe.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);\n    }\n}"
    )
    assert [r for r, _ in found(java)] == ["security.pending_intent_mutability"]


def with_core(base):
    """The project plus a library module ``core`` whose manifest declares nothing."""
    files = dict(base)
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":core")'
    )
    files["core/build.gradle.kts"] = (
        'plugins {\n    id("com.android.library")\n}\n\n'
        'android {\n    namespace = "com.example.core"\n    compileSdk = 35\n}\n'
    )
    files["core/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n'
    )
    return files


def test_a_library_module_is_judged_by_the_app_that_ships_it():
    files = with_core(good_project())
    files["core/src/main/java/com/example/core/Probe.kt"] = (
        "package com.example.core\n\nimport android.app.PendingIntent\nimport android.content.Context\nimport android.content.Intent\n\n"
        "fun make(context: Context): PendingIntent = PendingIntent.getActivity(context, 0, Intent(), 0)\n"
    )
    assert rules(files) == ["security.pending_intent_mutability"]
    assert rules(target(files, 30)) == []
    assert rules(target(files, None)) == []


def with_wear(base, wear_target):
    """The project plus a second application module ``wear`` with its own target SDK."""
    files = dict(base)
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":wear")'
    )
    files["wear/build.gradle.kts"] = (
        'plugins {\n    id("com.android.application")\n}\n\n'
        'android {\n    namespace = "com.example.wear"\n    compileSdk = 35\n\n'
        f"    defaultConfig {{\n        targetSdk = {wear_target}\n    }}\n}}\n"
    )
    files["wear/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n'
    )
    return files


def test_a_library_shared_by_several_apps_is_judged_by_the_lowest_target():
    code = (
        "import android.app.PendingIntent\nimport android.content.Context\nimport android.content.Intent\n\n"
        "fun make(context: Context): PendingIntent = PendingIntent.getActivity(context, 0, Intent(), 0)\n"
    )
    files = with_wear(with_core(good_project()), 30)  # app targets 35, wear targets 30
    files["core/src/main/java/com/example/core/Probe.kt"] = "package com.example.core\n\n" + code
    assert rules(files) == []  # the library also ships in the app that targets 30
    files["wear/src/main/java/com/example/wear/Probe.kt"] = "package com.example.wear\n\n" + code
    assert rules(files) == []  # wear's own code is judged by wear's own target
    files[f"{MAIN}/Probe.kt"] = f"package {PACKAGE}\n\n" + code
    assert [r for r, _ in found(files)] == ["security.pending_intent_mutability"]
    only_core = with_wear(with_core(good_project()), 33)
    only_core["core/src/main/java/com/example/core/Probe.kt"] = (
        "package com.example.core\n\n" + code
    )
    assert rules(only_core) == ["security.pending_intent_mutability"]


def test_the_target_given_by_the_caller_is_used_when_the_build_cannot_be_read():
    no_build = {
        MANIFEST: good_project()[MANIFEST],
        f"{MAIN}/Probe.kt": kt(
            "class Probe {\n    fun make(context: Context) = PendingIntent.getActivity(context, 0, Intent(), 0)\n}",
            PENDING_IMPORTS,
        ),
    }

    def reviewed(sdk):
        report = ReviewEngine().review(
            ProjectFiles.from_mapping(no_build), target=ReviewTarget(target_sdk=sdk)
        )
        assert not [f for f in report.findings if f.rule == "review.internal_error"]
        return sorted({f.rule for f in report.findings if f.rule.startswith("security.")})

    assert reviewed(33) == ["security.pending_intent_mutability"]
    assert reviewed(30) == []
    assert reviewed(None) == []


# --- mutable PendingIntent around an implicit Intent --------------------------------------------------


def test_a_mutable_pending_intent_with_an_implicit_intent_is_an_error_on_android_14():
    for intent in ('Intent("com.example.todo.ACTION")', "Intent()", "Intent(Intent.ACTION_VIEW)"):
        files = pending("PendingIntent.FLAG_MUTABLE", intent=intent, kind="getBroadcast")
        assert rules(files) == ["security.pending_intent_mutable_implicit"], intent
    mixed = pending(
        "PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT", intent='Intent("x")'
    )
    assert rules(mixed) == ["security.pending_intent_mutable_implicit"]


def test_an_explicit_immutable_or_opted_out_pending_intent_is_quiet():
    cases = (
        ("PendingIntent.FLAG_MUTABLE", "Intent(context, Probe::class.java)"),
        ("PendingIntent.FLAG_MUTABLE", 'Intent("x").setPackage(context.packageName)'),
        ("PendingIntent.FLAG_MUTABLE", 'Intent("x").apply { `package` = "a.b" }'),
        ("PendingIntent.FLAG_MUTABLE", "base"),
        ("PendingIntent.FLAG_MUTABLE", "Intent(base)"),
        ("PendingIntent.FLAG_IMMUTABLE", 'Intent("x")'),
        (
            "PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT",
            'Intent("x")',
        ),
        ("flags or PendingIntent.FLAG_MUTABLE", 'Intent("x")'),
    )
    for flags, intent in cases:
        assert rules(pending(flags, intent=intent)) == [], (flags, intent)


def test_the_implicit_intent_rule_applies_from_target_sdk_34():
    files = pending("PendingIntent.FLAG_MUTABLE", intent='Intent("x")')
    assert rules(target(files, 33)) == []
    assert rules(target(files, 34)) == ["security.pending_intent_mutable_implicit"]
    assert rules(target(files, None)) == []


def test_two_identical_pending_intents_get_separate_keys_so_a_new_one_is_not_hidden():
    call = "PendingIntent.getActivity(context, 0, Intent(context, Probe::class.java), 0)"
    one = with_code(f"class Probe {{\n    fun a(context: Context) = {call}\n}}", PENDING_IMPORTS)
    two = with_code(
        f"class Probe {{\n    fun a(context: Context) = {call}\n    fun b(context: Context) = {call}\n}}",
        PENDING_IMPORTS,
    )
    assert [k for _, k in found(two)] == ["getActivity(0)#1", "getActivity(0)#2"]
    only_new = ReviewConfig(only_new=True)
    report = review(two, before=one, config=only_new)
    assert [f.key for f in report.findings if f.rule.startswith("security.")] == [
        "getActivity(0)#2"
    ]


# --- registerReceiver export flags ---------------------------------------------------------------------

RECEIVER_IMPORTS = "import android.content.BroadcastReceiver\nimport android.content.Context\nimport android.content.Intent\nimport android.content.IntentFilter\n"


def register(call, imports=RECEIVER_IMPORTS):
    body = f"class Probe(private val context: Context, private val receiver: BroadcastReceiver, private val filter: IntentFilter) {{\n    fun start() {{\n        {call}\n    }}\n}}"
    return with_code(body, imports)


def test_registering_for_a_custom_action_without_an_export_flag_is_an_error_on_android_14():
    for call in (
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))',
        'requireContext().registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))',
        'registerReceiver(receiver, IntentFilter().apply { addAction("com.example.todo.REFRESH") })',
        'context.registerReceiver(receiver, IntentFilter(Intent.ACTION_SCREEN_ON).apply { addAction("com.example.todo.REFRESH") })',
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"), "com.example.todo.PERM", null)',
    ):
        files = register(call)
        assert [r for r, _ in found(files)] == ["security.receiver_export_flag_missing"], call
    finding = next(
        f
        for f in review(register(call)).findings
        if f.rule == "security.receiver_export_flag_missing"
    )
    assert finding.blocking and "com.example.todo.REFRESH" in finding.description


def test_a_receiver_registered_with_an_export_flag_is_quiet():
    for call in (
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"), Context.RECEIVER_NOT_EXPORTED)',
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"), Context.RECEIVER_EXPORTED)',
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"), "p.P", null, Context.RECEIVER_NOT_EXPORTED)',
        'ContextCompat.registerReceiver(context, receiver, IntentFilter("com.example.todo.REFRESH"), ContextCompat.RECEIVER_NOT_EXPORTED)',
    ):
        assert (
            rules(register(call, RECEIVER_IMPORTS + "import androidx.core.content.ContextCompat\n"))
            == []
        ), call


def test_registering_for_system_broadcasts_only_is_quiet():
    for call in (
        "context.registerReceiver(receiver, IntentFilter(Intent.ACTION_SCREEN_ON))",
        'context.registerReceiver(receiver, IntentFilter("android.intent.action.SCREEN_OFF"))',
        "context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))",
        "context.registerReceiver(receiver, IntentFilter().apply { addAction(Intent.ACTION_SCREEN_ON); addAction(Intent.ACTION_SCREEN_OFF) })",
    ):
        assert rules(register(call)) == [], call


def test_a_filter_the_analyzer_cannot_read_is_not_judged():
    for call in (
        "context.registerReceiver(receiver, filter)",
        "context.registerReceiver(receiver, buildFilter())",
        "context.registerReceiver(receiver, IntentFilter(ACTION_REFRESH))",
        'context.registerReceiver(receiver, IntentFilter("com.example.todo.A").apply { addAction(OTHER) })',
        'context.registerReceiver(receiver, createFilter().apply { addAction("com.example.todo.A") })',
    ):
        assert rules(register(call)) == [], call


def test_local_broadcasts_have_no_export_flag_and_are_not_judged():
    local = with_code(
        'class Probe(private val receiver: BroadcastReceiver, private val context: Context) {\n    fun start() {\n        LocalBroadcastManager.getInstance(context).registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))\n    }\n}',
        RECEIVER_IMPORTS + "import androidx.localbroadcastmanager.content.LocalBroadcastManager\n",
    )
    assert rules(local) == []


def test_the_receiver_flag_rule_applies_from_target_sdk_34():
    files = register('context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))')
    assert rules(target(files, 33)) == []
    assert rules(target(files, 34)) == ["security.receiver_export_flag_missing"]
    assert rules(target(files, None)) == []


def test_java_register_receiver_is_read():
    java = with_java(
        "import android.content.BroadcastReceiver;\nimport android.content.Context;\nimport android.content.IntentFilter;\n\nclass Probe {\n"
        '    void start(Context c, BroadcastReceiver r) {\n        c.registerReceiver(r, new IntentFilter("com.example.todo.REFRESH"));\n    }\n'
        '    void safe(Context c, BroadcastReceiver r) {\n        c.registerReceiver(r, new IntentFilter("com.example.todo.REFRESH"), Context.RECEIVER_NOT_EXPORTED);\n    }\n}'
    )
    assert [r for r, _ in found(java)] == ["security.receiver_export_flag_missing"]


def test_a_registerreceiver_wrapper_with_other_arity_is_not_the_platform_call():
    wrapper = register(
        'registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"), 1, 2, 3, 4)'
    )
    assert rules(wrapper) == []
    single = register('registerReceiver(IntentFilter("com.example.todo.REFRESH"))')
    assert rules(single) == []


def test_two_identical_registrations_get_separate_keys_so_a_new_one_is_not_hidden():
    call = 'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))'
    one = register(call)
    two = register(call + "\n        " + call)
    assert [k for _, k in found(two)] == [
        "registerReceiver(com.example.todo.REFRESH)#1",
        "registerReceiver(com.example.todo.REFRESH)#2",
    ]
    report = review(two, before=one, config=ReviewConfig(only_new=True))
    assert [f.key for f in report.findings if f.rule.startswith("security.")] == [
        "registerReceiver(com.example.todo.REFRESH)#2"
    ]


def test_a_method_named_register_receiver_that_is_declared_not_called_is_quiet():
    declared = with_code(
        "abstract class Probe : android.content.Context() {\n    override fun registerReceiver(receiver: BroadcastReceiver?, filter: IntentFilter?): Intent? = null\n}",
        RECEIVER_IMPORTS,
    )
    assert rules(declared) == []


# --- permissions: declared and requested ---------------------------------------------------------------

PERMISSION_IMPORTS = "import android.Manifest\nimport android.app.Activity\nimport androidx.core.app.ActivityCompat\n"


def request(*names, call="ActivityCompat.requestPermissions(activity, arrayOf({refs}), 1)"):
    refs = ", ".join(f"Manifest.permission.{n}" for n in names)
    body = f"class Probe(private val activity: Activity) {{\n    fun ask() {{\n        {call.format(refs=refs)}\n    }}\n}}"
    return with_code(body, PERMISSION_IMPORTS)


def test_requesting_a_permission_the_manifest_does_not_declare_is_reported():
    files = request("CAMERA")
    assert found(files) == [("security.permission_not_declared", "CAMERA")]
    finding = next(
        f for f in review(files).findings if f.rule == "security.permission_not_declared"
    )
    assert not finding.blocking and "always denied" in finding.description


def test_a_declared_permission_or_a_normal_one_is_quiet():
    assert rules(with_permissions("CAMERA", base=request("CAMERA"))) == []
    assert rules(request("VIBRATE")) == []
    assert rules(request("INTERNET")) == []


def test_a_permission_checked_through_a_string_or_a_contract_is_read():
    check = with_code(
        'class Probe(private val activity: Activity) {\n    fun granted() = ActivityCompat.checkSelfPermission(activity, "android.permission.RECORD_AUDIO") == 0\n}',
        PERMISSION_IMPORTS,
    )
    assert found(check) == [("security.permission_not_declared", "RECORD_AUDIO")]
    contract = with_code(
        "class Probe(private val activity: androidx.activity.ComponentActivity) {\n    val launcher = activity.registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {}\n    fun ask() = launcher.launch(Manifest.permission.READ_CONTACTS)\n}",
        "import android.Manifest\n",
    )
    assert found(contract) == [("security.permission_not_declared", "READ_CONTACTS")]


def test_every_way_of_dealing_with_permissions_marks_a_file_as_requesting_them():
    for word in (
        "requestPermissions",
        "checkSelfPermission",
        "shouldShowRequestPermissionRationale",
        "RequestPermission",
        "RequestMultiplePermissions",
        "rememberPermissionState",
        "rememberMultiplePermissionsState",
        "EasyPermissions",
        "NeedsPermission",
    ):
        files = with_code(f"val {word} = Manifest.permission.CAMERA\n", "import android.Manifest\n")
        assert found(files) == [("security.permission_not_declared", "CAMERA")], word


def test_a_permission_that_is_removed_by_the_merger_counts_as_not_declared():
    removed = edit(
        request("CAMERA"),
        MANIFEST,
        INTERNET,
        INTERNET
        + '    <uses-permission android:name="android.permission.CAMERA" tools:node="remove" />\n',
    )
    assert rules(removed) == ["security.permission_not_declared"]


def test_a_permission_declared_in_any_shipping_manifest_counts():
    files = request("CAMERA")
    files[DEBUG_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <uses-permission android:name="android.permission.CAMERA" />\n</manifest>\n'
    )
    assert rules(files) == []


def test_a_permission_only_listed_in_code_that_does_not_request_anything_is_not_a_request():
    listing = with_code(
        'object Labels {\n    val names = mapOf(Manifest.permission.CAMERA to "Camera")\n}',
        "import android.Manifest\n",
    )
    assert rules(listing) == []


def test_permissions_are_not_judged_when_a_manifest_could_not_be_parsed():
    files = request("CAMERA")
    files[DEBUG_MANIFEST] = "<manifest"
    assert rules(files) == []


def test_each_undeclared_permission_is_reported_once():
    files = request("CAMERA", "RECORD_AUDIO")
    files[f"{MAIN}/Again.kt"] = kt(
        "class Again(private val activity: Activity) {\n    fun ask() = ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.CAMERA), 2)\n}",
        PERMISSION_IMPORTS,
    )
    assert found(files) == [
        ("security.permission_not_declared", "CAMERA"),
        ("security.permission_not_declared", "RECORD_AUDIO"),
    ]


# --- permissions: declared and never requested ---------------------------------------------------------


def declared_and_requested(declared, requested, **kwargs):
    return with_permissions(*declared, base=request(*requested), **kwargs)


def test_a_dangerous_permission_declared_but_never_requested_is_reported():
    files = declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",))
    assert found(files) == [("security.permission_never_requested", "CAMERA")]
    finding = next(
        f for f in review(files).findings if f.rule == "security.permission_never_requested"
    )
    assert not finding.blocking and finding.line is not None


def test_declared_and_requested_permissions_are_quiet():
    assert (
        rules(declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("CAMERA", "RECORD_AUDIO"))) == []
    )


def test_a_normal_permission_declared_but_not_requested_is_quiet():
    assert rules(declared_and_requested(("VIBRATE", "RECORD_AUDIO"), ("RECORD_AUDIO",))) == []


def test_a_permission_mentioned_anywhere_in_the_project_is_not_reported():
    listed = declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",))
    listed[f"{MAIN}/Labels.kt"] = kt(
        'object Labels {\n    val camera = "android.permission.CAMERA"\n}'
    )
    assert rules(listed) == []
    in_resource = declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",))
    in_resource["app/src/main/res/values/arrays.xml"] = (
        '<resources><string-array name="p"><item>android.permission.CAMERA</item></string-array></resources>\n'
    )
    assert rules(in_resource) == []
    in_comment_only = declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",))
    in_comment_only[f"{MAIN}/Notes.kt"] = kt(
        '// Manifest.permission.CAMERA\n/* "android.permission.CAMERA" */\nclass Notes'
    )
    assert rules(in_comment_only) == ["security.permission_never_requested"]


def test_a_project_with_no_permission_code_is_not_judged():
    assert rules(with_permissions("CAMERA")) == []


def test_a_legacy_capped_removed_or_non_main_declaration_is_quiet():
    base = declared_and_requested(("RECORD_AUDIO",), ("RECORD_AUDIO",))
    assert rules(base) == []
    capped = with_permissions("CAMERA", base=base, extra=' android:maxSdkVersion="28"')
    assert rules(capped) == []
    uncapped = with_permissions("CAMERA", base=base)
    assert rules(uncapped) == ["security.permission_never_requested"]
    removed = edit(
        base,
        MANIFEST,
        INTERNET,
        INTERNET
        + '    <uses-permission android:name="android.permission.CAMERA" tools:node="remove" />\n',
    )
    assert rules(removed) == []
    debug = dict(base)
    debug[DEBUG_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <uses-permission android:name="android.permission.CAMERA" />\n</manifest>\n'
    )
    assert rules(debug) == []


def test_install_time_permissions_below_target_sdk_23_are_not_judged():
    files = declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",))
    assert rules(target(files, 22)) == []
    assert rules(target(files, 23)) == ["security.permission_never_requested"]
    assert rules(target(files, None)) == []


CORE_ASKS = (
    "package com.example.core\n\nimport android.Manifest\nimport android.app.Activity\n"
    "import androidx.core.app.ActivityCompat\n\n"
    "fun ask(activity: Activity) = ActivityCompat.requestPermissions(\n"
    "    activity, arrayOf(Manifest.permission.RECORD_AUDIO), 1\n)\n"
)
CORE_MANIFEST_WITH_CAMERA = (
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
    '    <uses-permission android:name="android.permission.CAMERA" />\n</manifest>\n'
)


def test_a_permission_declared_in_two_modules_is_reported_once():
    files = with_core(declared_and_requested(("CAMERA", "RECORD_AUDIO"), ("RECORD_AUDIO",)))
    files["core/src/main/AndroidManifest.xml"] = CORE_MANIFEST_WITH_CAMERA
    files["core/src/main/java/com/example/core/Asks.kt"] = CORE_ASKS  # both modules ask
    assert [k for _, k in found(files)] == ["CAMERA"]


def test_a_declared_permission_is_judged_only_in_a_module_whose_own_code_asks_for_permissions():
    """iosched's ``ar`` module declares CAMERA and has no permission code: ARCore's ArFragment asks."""
    files = with_core(declared_and_requested(("RECORD_AUDIO",), ("RECORD_AUDIO",)))
    files["core/src/main/AndroidManifest.xml"] = CORE_MANIFEST_WITH_CAMERA
    assert rules(files) == []  # the app asks for RECORD_AUDIO, but core's code asks for nothing
    files["core/src/main/java/com/example/core/Asks.kt"] = CORE_ASKS
    assert found(files) == [("security.permission_never_requested", "CAMERA")]
    finding = next(
        f for f in review(files).findings if f.rule == "security.permission_never_requested"
    )
    assert finding.file == "core/src/main/AndroidManifest.xml"


# --- suppressions the project already made --------------------------------------------------------------


def test_tools_ignore_on_a_component_silences_the_matching_rule_only():
    cases = (
        (
            "provider",
            provider(),
            "ExportedContentProvider",
            "security.provider_exported_unprotected",
        ),
        (
            "service",
            component("service"),
            "ExportedService",
            "security.service_exported_unprotected",
        ),
        (
            "receiver",
            component("receiver"),
            "ExportedReceiver",
            "security.receiver_exported_unprotected",
        ),
    )
    for tag, element, lint_id, rule in cases:
        assert rules(with_xml(element)) == [rule], tag
        for ids in (lint_id, f"Other, {lint_id}", "all"):
            silenced = with_xml(element.replace(f"<{tag} ", f'<{tag} tools:ignore="{ids}" ', 1))
            assert rules(silenced) == [], (tag, ids)
        other = with_xml(element.replace(f"<{tag} ", f'<{tag} tools:ignore="SomethingElse" ', 1))
        assert rules(other) == [rule], tag
        wrong_kind = "ExportedService" if tag != "service" else "ExportedReceiver"
        wrong = with_xml(element.replace(f"<{tag} ", f'<{tag} tools:ignore="{wrong_kind}" ', 1))
        assert rules(wrong) == [rule], tag


def test_tools_ignore_on_the_application_or_manifest_covers_its_components():
    element = component("receiver", actions=("com.example.todo.REFRESH",))
    on_application = edit(
        with_xml(element),
        MANIFEST,
        'android:allowBackup="true"',
        'android:allowBackup="true" tools:ignore="ExportedReceiver"',
    )
    assert rules(on_application) == []
    on_manifest = edit(
        with_xml(element), MANIFEST, "<manifest ", '<manifest tools:ignore="ExportedReceiver" '
    )
    assert rules(on_manifest) == []
    assert rules(with_xml(element)) == ["security.receiver_exported_unprotected"]


def test_tools_ignore_on_a_grant_or_a_base_config_is_honoured():
    narrow = provider(
        'android:permission="p.P" tools:ignore="GrantAllUris"', grant('android:pathPrefix="/"')
    )
    assert rules(with_xml(narrow)) == []
    base = '    <base-config cleartextTrafficPermitted="true" tools:ignore="InsecureBaseConfiguration" />'
    assert rules(with_nsc(base)) == []
    assert rules(with_nsc('    <base-config cleartextTrafficPermitted="true" />')) == [
        "security.cleartext_permitted"
    ]
    wrong = '    <base-config cleartextTrafficPermitted="true" tools:ignore="GrantAllUris" />'
    assert rules(with_nsc(wrong)) == ["security.cleartext_permitted"]
    on_root = nsc('    <base-config cleartextTrafficPermitted="true" />').replace(
        "<network-security-config>",
        '<network-security-config tools:ignore="InsecureBaseConfiguration">',
    )
    files = with_nsc("")
    files[NSC] = on_root
    assert rules(files) == []


def test_tools_ignore_on_a_domain_config_is_not_honoured():
    body = '    <domain-config cleartextTrafficPermitted="true" tools:ignore="InsecureBaseConfiguration"><domain>feeds.acme.io</domain></domain-config>'
    assert rules(with_nsc(body)) == ["security.cleartext_permitted"]


def lint_xml(*issues):
    return '<?xml version="1.0" encoding="UTF-8"?>\n<lint>\n' + "".join(issues) + "</lint>\n"


def test_lint_xml_can_switch_a_rule_off_for_the_project():
    element = component("service")
    base = with_xml(element)
    off = dict(base)
    off["lint.xml"] = lint_xml('    <issue id="ExportedService" severity="ignore" />\n')
    assert rules(off) == []
    for issue in (
        '    <issue id="ExportedService" severity="error" />\n',
        '    <issue id="ExportedReceiver" severity="ignore" />\n',
        '    <issue id="ExportedService" severity="ignore"><ignore path="app/src/main/AndroidManifest.xml" /></issue>\n',
    ):
        files = dict(base)
        files["lint.xml"] = lint_xml(issue)
        assert rules(files) == ["security.service_exported_unprotected"], issue
    broken = dict(base)
    broken["lint.xml"] = "<lint"
    assert rules(broken) == ["security.service_exported_unprotected"]


def test_a_gradle_lint_block_can_switch_a_rule_off_for_the_project():
    files = pending("0")
    assert rules(files) == ["security.pending_intent_mutability"]
    for block in (
        'android {\n    lint {\n        disable += "UnspecifiedImmutableFlag"\n    }\n}\n',
        'android {\n    lint {\n        disable += setOf(\n            "Other",\n            "UnspecifiedImmutableFlag",\n        )\n    }\n}\n',
        "android {\n    lintOptions {\n        disable 'UnspecifiedImmutableFlag'\n    }\n}\n",
    ):
        silenced = dict(files)
        silenced[APP] = files[APP] + "\n" + block
        assert rules(silenced) == [], block
    padding = "// " + "x" * 80 + "\n"
    for block in (
        'android {\n    lint {\n        fatal += "UnspecifiedImmutableFlag"\n    }\n}\n',
        'android {\n    lint {\n        disable += "Other"\n    }\n}\n',
        'android {\n    lint {\n        disable += "Other"\n'
        + padding * 8
        + '        fatal += "UnspecifiedImmutableFlag"\n    }\n}\n',
    ):
        kept = dict(files)
        kept[APP] = files[APP] + "\n" + block
        assert rules(kept) == ["security.pending_intent_mutability"], block


def test_a_lint_suppression_in_the_source_file_silences_its_rule():
    call = "PendingIntent.getActivity(context, 0, Intent(context, Probe::class.java), 0)"
    plain = f"class Probe {{\n    fun make(context: Context) = {call}\n}}"
    assert rules(with_code(plain, PENDING_IMPORTS)) == ["security.pending_intent_mutability"]
    for annotation in (
        '@SuppressLint("UnspecifiedImmutableFlag")',
        '@Suppress("UnspecifiedImmutableFlag")',
        '@Suppress("Other", "UnspecifiedImmutableFlag")',
        '@SuppressWarnings("UnspecifiedImmutableFlag")',
    ):
        body = f"class Probe {{\n    {annotation}\n    fun make(context: Context) = {call}\n}}"
        assert (
            rules(with_code(body, PENDING_IMPORTS + "import android.annotation.SuppressLint\n"))
            == []
        ), annotation
    file_level = with_code(plain, PENDING_IMPORTS)
    path = f"{MAIN}/Probe.kt"
    file_level[path] = '@file:Suppress("UnspecifiedImmutableFlag")\n' + file_level[path]
    assert rules(file_level) == []
    other = f'class Probe {{\n    @Suppress("MutableImplicitPendingIntent")\n    fun make(context: Context) = {call}\n}}'
    assert rules(with_code(other, PENDING_IMPORTS)) == ["security.pending_intent_mutability"]


def test_the_implicit_intent_and_receiver_flag_rules_have_their_own_ids():
    implicit = 'PendingIntent.getBroadcast(context, 0, Intent("x"), PendingIntent.FLAG_MUTABLE)'
    body = f'class Probe {{\n    @Suppress("MutableImplicitPendingIntent")\n    fun make(context: Context) = {implicit}\n}}'
    assert rules(with_code(body, PENDING_IMPORTS)) == []
    wrong = f'class Probe {{\n    @Suppress("UnspecifiedImmutableFlag")\n    fun make(context: Context) = {implicit}\n}}'
    assert rules(with_code(wrong, PENDING_IMPORTS)) == ["security.pending_intent_mutable_implicit"]
    call = 'context.registerReceiver(receiver, IntentFilter("com.example.todo.REFRESH"))'
    suppressed = RECEIVER_BODY.format(
        annotation='@SuppressLint("UnspecifiedRegisterReceiverFlag")', call=call
    )
    assert (
        rules(with_code(suppressed, RECEIVER_IMPORTS + "import android.annotation.SuppressLint\n"))
        == []
    )
    wrong_id = RECEIVER_BODY.format(
        annotation='@SuppressLint("UnspecifiedImmutableFlag")', call=call
    )
    assert rules(
        with_code(wrong_id, RECEIVER_IMPORTS + "import android.annotation.SuppressLint\n")
    ) == ["security.receiver_export_flag_missing"]


RECEIVER_BODY = "class Probe(private val context: Context, private val receiver: BroadcastReceiver) {{\n    {annotation}\n    fun start() {{\n        {call}\n    }}\n}}"


# --- change: a sensitive permission is added -----------------------------------------------------------


def added(before, after, config=None):
    return sorted(
        (f.rule, f.key, f.blocking, f.approval)
        for f in review(after, before=before, config=config).findings
        if f.rule == "change.sensitive_permission_added"
    )


def test_adding_a_dangerous_permission_needs_approval():
    after = with_permissions("CAMERA")
    assert added(good_project(), after) == [
        (
            "change.sensitive_permission_added",
            "android.permission.CAMERA",
            True,
            "other_high_impact",
        )
    ]


def test_a_granted_approval_makes_it_non_blocking():
    after = with_permissions("CAMERA")
    config = ReviewConfig(granted_approvals=frozenset({"other_high_impact"}))
    assert added(good_project(), after, config) == [
        (
            "change.sensitive_permission_added",
            "android.permission.CAMERA",
            False,
            "other_high_impact",
        )
    ]
    finding = next(
        f
        for f in review(after, before=good_project(), config=config).findings
        if f.rule == "change.sensitive_permission_added"
    )
    assert finding.description.endswith("(approved)")


def test_adding_a_special_access_permission_needs_approval_too():
    after = with_permissions("SYSTEM_ALERT_WINDOW", "REQUEST_INSTALL_PACKAGES")
    assert [key for _, key, _, _ in added(good_project(), after)] == [
        "android.permission.REQUEST_INSTALL_PACKAGES",
        "android.permission.SYSTEM_ALERT_WINDOW",
    ]


def test_the_message_says_how_each_kind_of_permission_is_granted():
    def message(permission):
        report = review(with_permissions(permission), before=good_project())
        return next(
            f for f in report.findings if f.rule == "change.sensitive_permission_added"
        ).description

    assert "grant at run time" in message("CAMERA")
    assert "switch on in system settings" in message("SYSTEM_ALERT_WINDOW")
    assert message("CAMERA").startswith("The change adds the permission CAMERA")


def test_adding_a_normal_permission_or_keeping_an_existing_one_is_quiet():
    assert added(good_project(), with_permissions("VIBRATE", "ACCESS_NETWORK_STATE")) == []
    before = with_permissions("CAMERA")
    assert added(before, before) == []
    assert added(before, with_permissions("CAMERA", "VIBRATE")) == []


def test_moving_a_sensitive_permission_between_manifests_is_not_adding_it():
    before = with_permissions("CAMERA")
    after = edit(
        before, MANIFEST, '    <uses-permission android:name="android.permission.CAMERA" />\n', ""
    )
    after[DEBUG_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n    <uses-permission android:name="android.permission.CAMERA" />\n</manifest>\n'
    )
    assert added(before, after) == []


def test_a_permission_edited_out_by_the_merger_or_in_test_sources_is_not_added():
    removed = edit(
        good_project(),
        MANIFEST,
        INTERNET,
        INTERNET
        + '    <uses-permission android:name="android.permission.CAMERA" tools:node="remove" />\n',
    )
    assert added(good_project(), removed) == []
    test_only = good_project()
    test_only[TEST_MANIFEST] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n    <uses-permission android:name="android.permission.CAMERA" />\n</manifest>\n'
    )
    assert added(good_project(), test_only) == []


def test_a_project_being_created_has_no_before_state_to_compare_with():
    before = {
        path: text
        for path, text in good_project().items()
        if not path.endswith("AndroidManifest.xml")
    }
    assert added(before, with_permissions("CAMERA")) == []


def test_a_review_without_a_before_state_reports_no_change_findings():
    assert [
        f for f in review(with_permissions("CAMERA")).findings if f.rule.startswith("change.")
    ] == []
