"""Authentication rules (Phase 4b-2c).

Basis, checked against developer.android.com and the AppAuth-Android README: Credential Manager's
setup adds both ``credentials`` and ``credentials-play-services-auth`` (a request without the second
fails with a provider-configuration exception); AppAuth captures a custom-scheme redirect through the
``appAuthRedirectScheme`` manifest placeholder or its own redirect activity; the security tips say never
to commit keys and not to store passwords on the device, and the signing guide moves passwords out of
Gradle files. Internal storage is app-private and "sufficient for most applications", so the preferences
rule is an advisory for explicit credential keys only.

Every secret in these fixtures is synthetic. Each rule has twins that must stay quiet.
"""

# ruff: noqa: E501  (the fixtures embed Kotlin, Gradle and manifest XML, like tests/sample_project.py)
import json

from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine
from androai_codegen.review.analysis import ProjectAnalysis

MANIFEST = "app/src/main/AndroidManifest.xml"
APP = "app/build.gradle.kts"
PACKAGE = "com.example.todo"
SECRET = "k3J9xQ7mP2vL8nR4tY6w"  # synthetic: letters and digits, 20 characters, high entropy
PEM_BODY = (
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKjMzEfYyjiWA4R4/M2bS1GB4t7NXp98"
)


def review(files, before=None, config=None):
    report = ReviewEngine(config).review(
        ProjectFiles.from_mapping(files),
        before=ProjectFiles.from_mapping(before) if before is not None else None,
    )
    # a rule that crashes is turned into this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def found(files, prefix="auth."):
    return sorted((f.rule, f.key) for f in review(files).findings if f.rule.startswith(prefix))


def rules(files, prefix="auth."):
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


def with_dependency(coordinate, base=None, path=APP):
    return edit(
        base or good_project(),
        path,
        "dependencies {\n",
        f'dependencies {{\n    implementation("{coordinate}")\n',
    )


def with_core(base):
    """The project plus a library module ``core`` and the app depending on it."""
    files = dict(base)
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":core")'
    )
    files["core/build.gradle.kts"] = (
        'plugins {\n    id("com.android.library")\n}\n\nandroid {\n    namespace = "com.example.core"\n    compileSdk = 35\n}\n\n'
        "dependencies {\n}\n"
    )
    files["core/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n'
    )
    return edit(
        files, APP, "dependencies {\n", 'dependencies {\n    implementation(project(":core"))\n'
    )


def pem(kind="PRIVATE KEY", body=PEM_BODY):
    return f"-----BEGIN {kind}-----\\n{body}\\n-----END {kind}-----"


def test_the_known_good_project_has_no_auth_findings():
    assert found(good_project()) == []


# --- private keys ------------------------------------------------------------------------------------


def test_a_pem_private_key_in_source_is_an_error():
    files = with_code(f'const val KEY = "{pem()}"')
    assert found(files) == [("auth.private_key_in_source", "private-key#1")]
    item = next(f for f in review(files).findings if f.rule == "auth.private_key_in_source")
    assert item.blocking and item.severity.value == "error" and item.approval is None


def test_private_keys_are_found_in_resources_build_scripts_and_java():
    xml = good_project()
    xml["app/src/main/res/values/keys.xml"] = (
        f'<resources><string name="k">{pem()}</string></resources>\n'
    )
    assert rules(xml) == ["auth.private_key_in_source"]
    gradle = edit(
        good_project(),
        APP,
        "versionCode = 1\n",
        f'versionCode = 1\n        buildConfigField("String", "K", "\\"{pem()}\\"")\n',
    )
    assert "auth.private_key_in_source" in rules(gradle)
    java = good_project()
    java[f"{MAIN}/Keys.java"] = (
        f'package {PACKAGE};\n\nclass Keys {{\n    static final String K = "{pem("RSA PRIVATE KEY")}";\n}}\n'
    )
    assert rules(java) == ["auth.private_key_in_source"]


def test_a_multi_line_key_with_concatenated_literals_is_found():
    body = (
        '"-----BEGIN PRIVATE KEY-----\\n" +\n    "'
        + PEM_BODY[:40]
        + '\\n" +\n    "'
        + PEM_BODY[40:]
        + '\\n" +\n    "-----END PRIVATE KEY-----"'
    )
    assert rules(with_code(f"val key =\n    {body}")) == ["auth.private_key_in_source"]


def test_text_that_only_mentions_a_key_is_not_a_key():
    cases = (
        'val header = "-----BEGIN PRIVATE KEY-----"',
        'val regex = Regex("-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----")',
        f'val short = "{pem(body="MIIEvQIBADAN")}"',
        f'val cert = "{pem("CERTIFICATE")}"',
        f'val pub = "{pem("PUBLIC KEY")}"',
        "// -----BEGIN PRIVATE KEY----- never ends",
    )
    for body in cases:
        assert rules(with_code(body)) == [], body


def test_a_private_key_in_a_test_source_set_is_not_reported():
    files = with_code(
        f'const val KEY = "{pem()}"', path="app/src/test/java/com/example/todo/KeyTest.kt"
    )
    assert rules(files) == []


def test_two_keys_in_one_file_get_separate_keys():
    files = with_code(f'val a = "{pem()}"\nval b = "{pem()}"')
    assert [k for _, k in found(files)] == ["private-key#1", "private-key#2"]


# --- hardcoded secrets ----------------------------------------------------------------------------------

SYNTHETIC_TOKENS = {
    "an AWS access key id": "AKIAABCDEFGHIJKLMNOP",
    "a GitHub token": "ghp_" + "a1B2c3" * 6,
    "a Slack token": "xoxb-1234567890-abcdefghijkl",
    "a Stripe live secret key": "sk_live_" + "a1B2c3" * 4,
    "a Google OAuth client secret": "GOCSPX-" + "a1B2c3" * 5,
    "an API secret key (sk-...)": "sk-" + "a1B2c3" * 7,
}


def test_tokens_with_a_distinctive_format_are_reported():
    for what, token in SYNTHETIC_TOKENS.items():
        files = with_code(f'val t = "{token}"')
        assert found(files) == [("auth.hardcoded_secret", f"token:{what}#1")], what


def test_google_api_keys_and_jwts_are_not_reported():
    aiza = "AIza" + "a1B2c3" * 6 + "x"
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
    assert rules(with_code(f'val k = "{aiza}"')) == []
    assert rules(with_code(f'val j = "{jwt}"')) == []
    assert rules(with_code('val s = "ghp_short"')) == []


def test_a_secret_named_literal_is_reported_in_kotlin_java_xml_and_gradle():
    kotlin = with_code(f'const val CLIENT_SECRET = "{SECRET}"')
    assert found(kotlin) == [("auth.hardcoded_secret", "client_secret#1")]
    mapped = with_code(f'val params = mapOf("clientSecret" to "{SECRET}")')
    assert rules(mapped) == ["auth.hardcoded_secret"]
    java = good_project()
    java[f"{MAIN}/Keys.java"] = (
        f'package {PACKAGE};\n\nclass Keys {{\n    private static final String API_SECRET = "{SECRET}";\n}}\n'
    )
    assert found(java) == [("auth.hardcoded_secret", "api_secret#1")]
    xml = good_project()
    xml["app/src/main/res/values/secrets.xml"] = (
        f'<resources><string name="client_secret">{SECRET}</string></resources>\n'
    )
    assert rules(xml) == ["auth.hardcoded_secret"]
    kts = edit(
        good_project(),
        APP,
        "versionCode = 1\n",
        f'versionCode = 1\n        buildConfigField("String", "CLIENT_SECRET", "\\"{SECRET}\\"")\n',
    )
    assert rules(kts) == ["auth.hardcoded_secret"]
    groovy = good_project()
    groovy["legacy/build.gradle"] = (
        f'android {{\n    defaultConfig {{\n        buildConfigField "String", "APP_SECRET", "\\"{SECRET}\\""\n    }}\n}}\n'
    )
    assert rules(groovy) == ["auth.hardcoded_secret"]


def test_literals_that_are_not_secrets_are_quiet():
    cases = (
        'const val CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE_1234"',
        'const val CLIENT_SECRET = "changeme-1234567890abc"',
        'const val PARAM_CLIENT_SECRET = "client_secret_param"',
        'const val CLIENT_SECRET = "short1"',
        "val clientSecret = BuildConfig.CLIENT_SECRET",
        'val clientSecret = System.getenv("CLIENT_SECRET")',
        f'val clientSecret = "$prefix-{SECRET}"',
        'val clientSecret = "abcdefghijklmnopqrstuvwxyz"',
        'val clientSecret = "aaaa1111aaaa1111aaaa"',
        f'val apiKey = "{SECRET}"',
        f'val title = "My secret recipes: {SECRET}"',
    )
    for body in cases:
        assert rules(with_code(body)) == [], body


def test_secrets_in_test_source_sets_are_not_reported():
    files = with_code(
        f'const val CLIENT_SECRET = "{SECRET}"',
        path="app/src/androidTest/java/com/example/todo/Fixture.kt",
    )
    assert rules(files) == []


def test_one_literal_is_reported_once_and_repeats_get_separate_keys():
    both = with_code(f'const val CLIENT_SECRET = "{SYNTHETIC_TOKENS["a Stripe live secret key"]}"')
    assert len(found(both)) == 1
    twice = with_code(
        f'const val CLIENT_SECRET = "{SECRET}"\nobject Other {{\n    const val CLIENT_SECRET = "{SECRET}x"\n}}'
    )
    assert [k for _, k in found(twice)] == ["client_secret#1", "client_secret#2"]


def test_no_finding_ever_repeats_a_secret():
    files = with_code(
        f'const val CLIENT_SECRET = "{SECRET}"\nval t = "{SYNTHETIC_TOKENS["a GitHub token"]}"\nval key = "{pem()}"'
    )
    dump = json.dumps([f.model_dump() for f in review(files).findings])
    for secret in (SECRET, SYNTHETIC_TOKENS["a GitHub token"], PEM_BODY[:30]):
        assert secret not in dump, secret
    assert len([f for f in review(files).findings if f.rule.startswith("auth.")]) == 3


# --- signing passwords ------------------------------------------------------------------------------------


def with_signing(body):
    return edit(
        good_project(), APP, "android {\n", "android {\n    signingConfigs {\n" + body + "    }\n"
    )


def test_a_literal_signing_password_in_a_build_script_is_reported():
    files = with_signing(
        '        create("release") {\n            storePassword = "s3cretPass9"\n            keyPassword = "s3cretPass9"\n        }\n'
    )
    assert found(files) == [
        ("auth.signing_password_in_build_script", "keyPassword#1"),
        ("auth.signing_password_in_build_script", "storePassword#1"),
    ]
    groovy = good_project()
    groovy["legacy/build.gradle"] = (
        "android {\n    signingConfigs {\n        release {\n            storePassword 's3cretPass9'\n        }\n    }\n}\n"
    )
    assert found(groovy) == [("auth.signing_password_in_build_script", "storePassword#1")]


def test_signing_passwords_that_are_not_literals_or_are_the_debug_default_are_quiet():
    cases = (
        '            storePassword = "android"\n            keyPassword = "android"\n',
        '            storePassword = System.getenv("STORE_PASSWORD")\n',
        '            storePassword = keystoreProperties["storePassword"] as String\n',
        '            storePassword = "$fromProperties"\n',
        '            storePassword = ""\n',
        '            storePassword project.getProperties().getOrDefault("releaseStorePassword", "password")\n',
    )
    for line in cases:
        assert rules(with_signing('        create("release") {\n' + line + "        }\n")) == [], (
            line
        )


# --- credentials in plain preferences ---------------------------------------------------------------------

PREFS_IMPORTS = "import android.content.Context\nimport android.content.SharedPreferences\nimport androidx.core.content.edit\n"


def prefs(call, imports=PREFS_IMPORTS):
    body = f"class Probe(private val prefs: SharedPreferences) {{\n    fun save(token: String, outState: android.os.Bundle) {{\n        {call}\n    }}\n}}"
    return with_code(body, imports)


def test_a_credential_written_to_shared_preferences_is_reported():
    for call in (
        'prefs.edit().putString("refresh_token", token).apply()',
        'prefs.edit { putString("access_token", token) }',
        'prefs.edit().putString("Access-Token", token).commit()',
        'prefs.edit().putString("authToken", token).apply()',
        'prefs.edit().putString("id_token", token).apply()',
        'prefs.edit().putString("jwt", token).apply()',
    ):
        assert rules(prefs(call)) == ["auth.credential_in_plain_preferences"], call


def test_a_password_in_preferences_cites_the_password_guidance():
    files = prefs('prefs.edit().putString("password", token).apply()')
    item = next(
        f for f in review(files).findings if f.rule == "auth.credential_in_plain_preferences"
    )
    assert "passwords" in item.description and "AccountManager" in item.description
    other = next(
        f
        for f in review(prefs('prefs.edit().putString("refresh_token", token).apply()')).findings
        if f.rule == "auth.credential_in_plain_preferences"
    )
    assert "Keystore" in other.description and "deprecated" in other.description
    assert not item.blocking and item.severity.value == "warning"


def test_the_java_editor_form_is_read():
    java = good_project()
    java[f"{MAIN}/Store.java"] = (
        f"package {PACKAGE};\n\nimport android.content.SharedPreferences;\n\nclass Store {{\n"
        '    void save(SharedPreferences prefs, String t) {\n        SharedPreferences.Editor editor = prefs.edit();\n        editor.putString("access_token", t);\n        editor.apply();\n    }\n}\n'
    )
    assert rules(java) == ["auth.credential_in_plain_preferences"]


def test_writes_that_are_not_credentials_in_preferences_are_quiet():
    cases = (
        'outState.putString("password", token)',  # a Bundle, not a preferences editor
        'prefs.edit().putString("fcm_token", token).apply()',
        'prefs.edit().putString("token", token).apply()',
        'prefs.edit().putString("display_name", token).apply()',
        "prefs.edit().putString(KEY_ACCESS_TOKEN, token).apply()",
        '// prefs.edit().putString("refresh_token", token).apply()',
        'val text = "prefs.edit().putString(\\"refresh_token\\", token)"',
    )
    for call in cases:
        assert rules(prefs(call)) == [], call


def test_storage_that_is_encrypted_or_keystore_backed_is_not_judged():
    for extra in (
        "import androidx.security.crypto.EncryptedSharedPreferences\n",
        "import java.security.KeyStore\n",
        "import javax.crypto.Cipher\n",
        "import com.google.crypto.tink.Aead\n",
    ):
        assert (
            rules(
                prefs(
                    'prefs.edit().putString("refresh_token", token).apply()', PREFS_IMPORTS + extra
                )
            )
            == []
        ), extra


def test_credential_writes_in_test_sources_or_without_preferences_are_not_judged():
    in_test = with_code(
        'class T(private val prefs: android.content.SharedPreferences) {\n    fun s() = prefs.edit().putString("refresh_token", "x").apply()\n}',
        PREFS_IMPORTS,
        path="app/src/test/java/com/example/todo/StoreTest.kt",
    )
    assert rules(in_test) == []
    no_prefs = with_code(
        'class P {\n    fun s(b: android.os.Bundle) = b.putString("refresh_token", "x")\n}'
    )
    assert rules(no_prefs) == []


def test_each_write_of_the_same_key_gets_its_own_key():
    files = prefs(
        'prefs.edit().putString("refresh_token", token).apply()\n        prefs.edit().putString("refresh_token", token).apply()'
    )
    assert [k for _, k in found(files)] == ["refresh_token#1", "refresh_token#2"]


# --- dependency coordinates ---------------------------------------------------------------------------------


def analysis(files):
    return ProjectAnalysis(ProjectFiles.from_mapping(files), ReviewConfig())


def test_dependency_coordinates_cover_the_module_and_the_modules_it_depends_on():
    files = with_core(good_project())
    files = edit(
        files,
        "core/build.gradle.kts",
        "dependencies {\n}",
        'dependencies {\n    implementation("net.openid:appauth:0.11.1")\n}',
    )
    a = analysis(files)
    assert "net.openid:appauth" in a.dependency_coordinates_for("core")
    assert "net.openid:appauth" in a.dependency_coordinates_for("app")  # app depends on core
    assert "androidx.room:room-runtime" in a.dependency_coordinates_for("app")
    assert "androidx.room:room-runtime" not in a.dependency_coordinates_for("core")


def test_dependency_coordinates_are_unknown_when_the_build_cannot_be_read():
    assert analysis(good_project()).dependency_coordinates_for("app") is not None
    assert analysis(good_project()).dependency_coordinates_for(None) is None
    unresolved = edit(
        good_project(),
        APP,
        "implementation(libs.androidx.core.ktx)",
        "implementation(libs.androidx.nonexistent)",
    )
    assert analysis(unresolved).dependency_coordinates_for("app") is None
    opaque = edit(
        good_project(),
        APP,
        "alias(libs.plugins.ksp)\n",
        'alias(libs.plugins.ksp)\n    id("company.convention")\n',
    )
    assert analysis(opaque).dependency_coordinates_for("app") is None
    partly_written = with_dependency("com.example:${name}:1.0")
    assert analysis(partly_written).dependency_coordinates_for("app") is None
    shared = edit(
        good_project(),
        "build.gradle.kts",
        "plugins {\n",
        'allprojects {\n    dependencies {\n        implementation("a:b:1")\n    }\n}\nplugins {\n',
    )
    assert analysis(shared).dependency_coordinates_for("app") is None


# --- Credential Manager without its provider --------------------------------------------------------------

CREDENTIALS = "androidx.credentials:credentials:1.5.0"
PROVIDER = "androidx.credentials:credentials-play-services-auth:1.5.0"
CM_IMPORTS = "import androidx.credentials.CredentialManager\nimport android.content.Context\n"
CM_CODE = "class Probe(context: Context) {\n    val manager = CredentialManager.create(context)\n}"


def credential_manager(*coordinates):
    files = with_code(CM_CODE, CM_IMPORTS)
    for coordinate in coordinates:
        files = with_dependency(coordinate, files)
    return files


def test_credential_manager_without_the_play_services_provider_is_reported():
    files = credential_manager(CREDENTIALS)
    assert found(files) == [
        ("auth.credential_manager_provider_missing", "credentials-play-services-auth")
    ]
    item = next(
        f for f in review(files).findings if f.rule == "auth.credential_manager_provider_missing"
    )
    assert item.file.endswith("Probe.kt") and "ProviderConfigurationException" in item.description
    assert not item.blocking


def test_credential_manager_with_its_provider_or_without_the_library_is_quiet():
    assert rules(credential_manager(CREDENTIALS, PROVIDER)) == []
    assert rules(credential_manager()) == []  # no androidx.credentials dependency at all
    assert rules(with_dependency(CREDENTIALS)) == []  # declared, never used


def test_credential_manager_provider_in_another_module_counts():
    files = with_core(credential_manager(CREDENTIALS))
    files = edit(
        files,
        "core/build.gradle.kts",
        "dependencies {\n}",
        f'dependencies {{\n    implementation("{PROVIDER}")\n}}',
    )
    assert rules(files) == []


def test_a_wildcard_import_counts_as_use_and_a_test_import_does_not():
    wildcard = with_dependency(
        CREDENTIALS, with_code("class Probe", "import androidx.credentials.*\n")
    )
    assert rules(wildcard) == ["auth.credential_manager_provider_missing"]
    in_test = with_dependency(
        CREDENTIALS,
        with_code(CM_CODE, CM_IMPORTS, path="app/src/test/java/com/example/todo/CmTest.kt"),
    )
    assert rules(in_test) == []


def test_credential_manager_is_not_judged_when_the_build_cannot_be_read():
    files = edit(
        credential_manager(CREDENTIALS),
        APP,
        "implementation(libs.androidx.core.ktx)",
        "implementation(libs.androidx.nonexistent)",
    )
    assert rules(files) == []


# --- AppAuth redirect configuration -----------------------------------------------------------------------

APPAUTH = "net.openid:appauth:0.11.1"
PLACEHOLDER_KTS = '        manifestPlaceholders["appAuthRedirectScheme"] = "com.example.todo"\n'
REDIRECT_ACTIVITY = (
    '        <activity android:name="net.openid.appauth.RedirectUriReceiverActivity" android:exported="true" tools:node="replace">\n'
    '            <intent-filter><action android:name="android.intent.action.VIEW" /><category android:name="android.intent.category.DEFAULT" />'
    '<category android:name="android.intent.category.BROWSABLE" /><data android:scheme="com.example.todo" /></intent-filter>\n'
    "        </activity>\n"
)


def with_placeholder(base, line=PLACEHOLDER_KTS):
    return edit(base, APP, "versionCode = 1\n", "versionCode = 1\n" + line)


def test_appauth_without_a_redirect_scheme_is_reported():
    files = with_dependency(APPAUTH)
    assert found(files) == [("auth.appauth_redirect_not_configured", "app")]
    item = next(
        f for f in review(files).findings if f.rule == "auth.appauth_redirect_not_configured"
    )
    assert item.file == APP and not item.blocking


def test_appauth_with_a_placeholder_or_its_own_redirect_activity_is_quiet():
    base = with_dependency(APPAUTH)
    for line in (
        PLACEHOLDER_KTS,
        '        manifestPlaceholders += mapOf("appAuthRedirectScheme" to "com.example.todo")\n',
        "        manifestPlaceholders = [appAuthRedirectScheme: 'com.example.todo']\n",
        '        manifestPlaceholders["appAuthRedirectScheme"] = scheme\n',  # computed: still configured
    ):
        assert rules(with_placeholder(base, line)) == [], line
    with_activity = edit(
        base, MANIFEST, "    </application>", REDIRECT_ACTIVITY + "    </application>"
    )
    assert rules(with_activity) == []


def test_appauth_in_a_library_is_judged_at_the_application_that_ships_it():
    files = with_core(good_project())
    files = edit(
        files,
        "core/build.gradle.kts",
        "dependencies {\n}",
        f'dependencies {{\n    implementation("{APPAUTH}")\n}}',
    )
    assert found(files) == [("auth.appauth_redirect_not_configured", "app")]
    configured = with_placeholder(files)
    assert rules(configured) == []


def test_appauth_is_not_judged_without_the_dependency_or_when_the_build_cannot_be_read():
    assert rules(good_project()) == []
    unreadable = edit(
        with_dependency(APPAUTH),
        APP,
        "implementation(libs.androidx.core.ktx)",
        "implementation(libs.androidx.nonexistent)",
    )
    assert rules(unreadable) == []


# --- AppAuth redirect scheme ------------------------------------------------------------------------------

APPAUTH_IMPORTS = "import android.net.Uri\nimport net.openid.appauth.AuthorizationRequest\nimport net.openid.appauth.AuthorizationServiceConfiguration\nimport net.openid.appauth.ResponseTypeValues\n"


def redirect(uri_expression, imports=APPAUTH_IMPORTS, method="builder"):
    if method == "builder":
        call = f'AuthorizationRequest.Builder(config, "client-id", ResponseTypeValues.CODE, {uri_expression}).build()'
    else:
        call = f'AuthorizationRequest.Builder(config, "client-id", ResponseTypeValues.CODE, other).setRedirectUri({uri_expression}).build()'
    body = f"class Probe(private val config: AuthorizationServiceConfiguration, private val other: Uri) {{\n    fun request() = {call}\n}}"
    return with_code(body, imports)


def with_scheme_filter(files, scheme="com.example.todo"):
    element = (
        f'        <activity android:name=".Redirect" android:exported="true"><intent-filter><action android:name="android.intent.action.VIEW" />'
        f'<data android:scheme="{scheme}" /></intent-filter></activity>\n'
    )
    return edit(files, MANIFEST, "    </application>", element + "    </application>")


def test_a_redirect_uri_that_no_filter_receives_is_reported():
    files = redirect('Uri.parse("com.example.todo:/oauth2redirect")')
    assert found(files) == [("auth.appauth_redirect_scheme_unmatched", "com.example.todo#1")]
    assert rules(redirect('"com.example.todo:/cb".toUri()')) == [
        "auth.appauth_redirect_scheme_unmatched"
    ]
    assert rules(redirect('Uri.parse("com.example.todo:/cb")', method="setter")) == [
        "auth.appauth_redirect_scheme_unmatched"
    ]
    item = next(
        f for f in review(files).findings if f.rule == "auth.appauth_redirect_scheme_unmatched"
    )
    assert not item.blocking and item.line is not None


def test_a_redirect_uri_that_a_filter_or_the_placeholder_receives_is_quiet():
    uri = 'Uri.parse("com.example.todo:/oauth2redirect")'
    assert rules(with_scheme_filter(redirect(uri))) == []
    assert (
        rules(with_scheme_filter(redirect(uri.replace("com.example.todo", "COM.Example.Todo"))))
        == []
    )
    assert rules(with_placeholder(redirect(uri))) == []
    placeholder_in_manifest = edit(
        with_placeholder(redirect(uri)),
        MANIFEST,
        "    </application>",
        '        <activity android:name=".Redirect" android:exported="true"><intent-filter><data android:scheme="${appAuthRedirectScheme}" /></intent-filter></activity>\n    </application>',
    )
    assert rules(placeholder_in_manifest) == []


def test_a_redirect_that_cannot_be_compared_is_not_judged():
    cases = (
        "Uri.parse(REDIRECT)",
        'Uri.parse("com.example.todo:/cb$suffix")',
        'Uri.parse("$scheme:/cb")',
        "other",
        'Uri.Builder().scheme("com.example.todo").build()',
    )
    for expression in cases:
        assert rules(redirect(expression)) == [], expression
    other_placeholder = edit(
        redirect('Uri.parse("com.example.todo:/cb")'),
        MANIFEST,
        "    </application>",
        '        <activity android:name=".R" android:exported="true"><intent-filter><data android:scheme="${other}" /></intent-filter></activity>\n    </application>',
    )
    assert rules(other_placeholder) == []
    computed = with_placeholder(
        redirect('Uri.parse("com.example.todo:/cb")'),
        '        manifestPlaceholders["appAuthRedirectScheme"] = scheme\n',
    )
    assert rules(computed) == []


def test_a_file_that_does_not_use_appauth_is_not_scanned_for_redirects():
    no_import = redirect('Uri.parse("com.example.todo:/cb")', imports="import android.net.Uri\n")
    assert rules(no_import) == []


def test_redirects_in_test_sources_are_ignored_and_repeats_get_separate_keys():
    in_test = with_code(
        'class T(private val config: AuthorizationServiceConfiguration) {\n    fun r() = AuthorizationRequest.Builder(config, "c", ResponseTypeValues.CODE, Uri.parse("zz.test:/cb")).build()\n}',
        APPAUTH_IMPORTS,
        path="app/src/test/java/com/example/todo/RedirectTest.kt",
    )
    assert rules(in_test) == []
    twice = with_code(
        "class P(private val config: AuthorizationServiceConfiguration) {\n"
        '    fun a() = AuthorizationRequest.Builder(config, "c", ResponseTypeValues.CODE, Uri.parse("zz.test:/cb")).build()\n'
        '    fun b() = AuthorizationRequest.Builder(config, "c", ResponseTypeValues.CODE, Uri.parse("zz.test:/cb")).build()\n}',
        APPAUTH_IMPORTS,
    )
    assert [k for _, k in found(twice)] == ["zz.test#1", "zz.test#2"]


# --- change: an authentication dependency is removed while code still uses it ---------------------------------

FIREBASE_AUTH = "com.google.firebase:firebase-auth:23.0.0"
FIREBASE_CODE = "class SignIn {\n    val auth = FirebaseAuth.getInstance()\n}"
FIREBASE_IMPORT = "import com.google.firebase.auth.FirebaseAuth\n"


def signed_in_project():
    return with_dependency(FIREBASE_AUTH, with_code(FIREBASE_CODE, FIREBASE_IMPORT, name="SignIn"))


def removed(files, line=f'    implementation("{FIREBASE_AUTH}")\n'):
    return edit(files, APP, line, "")


def changes(before, after, config=None, rule="change.auth_dependency_removed_still_used"):
    return sorted(
        (f.rule, f.file.rsplit("/", 1)[-1], f.key, f.blocking, f.approval)
        for f in review(after, before=before, config=config).findings
        if f.rule == rule
    )


def test_removing_an_authentication_dependency_that_code_still_imports_is_an_error():
    before = signed_in_project()
    after = removed(before)
    assert changes(before, after) == [
        (
            "change.auth_dependency_removed_still_used",
            "SignIn.kt",
            "Firebase Authentication",
            True,
            None,
        )
    ]
    # the removal itself is the approval-gated finding; this is the separate fact that it broke code
    assert changes(before, after, rule="change.integration_removed")[0][4] == "remove_integration"


def test_granting_the_removal_does_not_clear_the_broken_code():
    before = signed_in_project()
    after = removed(before)
    granted = ReviewConfig(granted_approvals=frozenset({"remove_integration"}))
    assert changes(before, after, granted, rule="change.integration_removed")[0][3] is False
    assert changes(before, after, granted) == [
        (
            "change.auth_dependency_removed_still_used",
            "SignIn.kt",
            "Firebase Authentication",
            True,
            None,
        )
    ]


def test_a_wildcard_import_counts_as_a_remaining_use():
    wildcard = with_dependency(
        FIREBASE_AUTH,
        with_code("class SignIn", "import com.google.firebase.auth.*\n", name="SignIn"),
    )
    assert len(changes(wildcard, removed(wildcard))) == 1


def test_removals_that_leave_the_build_able_to_resolve_the_code_are_quiet():
    before = signed_in_project()
    assert changes(before, before) == []
    # the sign-in code goes with the dependency
    gone = removed(before)
    gone[f"{MAIN}/SignIn.kt"] = kt("class SignIn")
    assert changes(before, gone) == []
    # another dependency still provides the classes
    replaced = edit(
        before,
        APP,
        f'    implementation("{FIREBASE_AUTH}")\n',
        '    implementation("com.firebaseui:firebase-ui-auth:8.0.2")\n',
    )
    assert changes(before, replaced) == []
    # the artifact is still declared (here with a different version)
    versioned = edit(before, APP, FIREBASE_AUTH, "com.google.firebase:firebase-auth:22.0.0")
    assert changes(before, versioned) == []
    ktx = edit(before, APP, FIREBASE_AUTH, "com.google.firebase:firebase-auth-ktx:22.0.0")
    assert changes(before, ktx) == []


def test_a_dependency_that_another_module_still_declares_is_not_removed():
    before = with_core(signed_in_project())
    before = edit(
        before,
        "core/build.gradle.kts",
        "dependencies {\n}",
        f'dependencies {{\n    implementation("{FIREBASE_AUTH}")\n}}',
    )
    after = removed(before)
    assert changes(before, after) == []


def test_removal_is_not_judged_when_a_dependency_cannot_be_resolved_or_the_import_is_in_a_test():
    before = signed_in_project()
    unresolved = edit(
        removed(before),
        APP,
        "implementation(libs.androidx.core.ktx)",
        "implementation(libs.androidx.nonexistent)",
    )
    assert changes(before, unresolved) == []
    only_test = with_dependency(
        FIREBASE_AUTH,
        with_code(
            FIREBASE_CODE, FIREBASE_IMPORT, path="app/src/test/java/com/example/todo/SignInTest.kt"
        ),
    )
    assert changes(only_test, removed(only_test)) == []
    never_declared = with_code(FIREBASE_CODE, FIREBASE_IMPORT, name="SignIn")
    assert changes(never_declared, never_declared) == []


def test_other_recognised_integrations_are_covered():
    cases = (
        (
            "androidx.credentials:credentials:1.5.0",
            "import androidx.credentials.CredentialManager\n",
            "Credential Manager",
        ),
        (
            "net.openid:appauth:0.11.1",
            "import net.openid.appauth.AuthorizationService\n",
            "AppAuth",
        ),
        (
            "com.google.android.gms:play-services-auth:21.0.0",
            "import com.google.android.gms.auth.api.signin.GoogleSignIn\n",
            "Google Sign-In (Play services)",
        ),
        ("com.auth0.android:auth0:3.0.0", "import com.auth0.android.Auth0\n", "Auth0"),
        (
            "com.firebaseui:firebase-ui-auth:8.0.2",
            "import com.firebase.ui.auth.AuthUI\n",
            "FirebaseUI Auth",
        ),
        (
            "com.google.android.libraries.identity.googleid:googleid:1.1.1",
            "import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential\n",
            "Sign in with Google (googleid)",
        ),
    )
    for coordinate, import_line, name in cases:
        before = with_dependency(coordinate, with_code("class SignIn", import_line, name="SignIn"))
        after = edit(before, APP, f'    implementation("{coordinate}")\n', "")
        assert [key for _, _, key, _, _ in changes(before, after)] == [name], name


# --- edge cases found by reading each rule against its mutations -------------------------------------------


def test_a_header_without_an_end_marker_or_a_real_body_is_not_a_key():
    no_end = with_code(f'val k = "-----BEGIN PRIVATE KEY-----\n{PEM_BODY}"')
    assert rules(no_end) == []
    not_base64 = with_code(
        'val k = "-----BEGIN PRIVATE KEY-----\n' + "!" * 80 + '\n-----END PRIVATE KEY-----"'
    )
    assert rules(not_base64) == []


def test_secret_named_literals_that_are_short_or_phrases_are_quiet():
    assert rules(with_code('val clientSecret = "k3J9xQ7mP2vL"')) == []  # 12 characters
    assert rules(with_code('val clientSecret = "my client secret value 12345 abc"')) == []


def test_every_credential_key_is_recognised():
    for key in ("session_token", "bearer_token", "oauth_token", "passwd", "id_token"):
        assert rules(prefs(f'prefs.edit().putString("{key}", token).apply()')) == [
            "auth.credential_in_plain_preferences"
        ], key
    assert (
        "passwords"
        in next(
            f
            for f in review(prefs('prefs.edit().putString("passwd", token).apply()')).findings
            if f.rule.startswith("auth.")
        ).description
    )


def test_each_form_of_editor_context_is_recognised():
    typed = with_code(
        'class Probe {\n    fun save(editor: SharedPreferences.Editor, token: String) = editor.putString("refresh_token", token)\n}',
        PREFS_IMPORTS,
    )
    assert rules(typed) == ["auth.credential_in_plain_preferences"]
    bare = with_code(
        'class Probe(private val prefs: SharedPreferences) {\n    fun save(token: String) = with(prefs) {\n        edit(commit = true) { putString("refresh_token", token) }\n    }\n}',
        PREFS_IMPORTS,
    )
    assert rules(bare) == ["auth.credential_in_plain_preferences"]


def test_a_write_on_something_that_is_not_shared_preferences_is_quiet():
    store = with_code(
        'class Probe(private val store: Store) {\n    fun save(t: String) = store.edit().putString("refresh_token", t)\n}'
    )
    assert rules(store) == []


def test_an_edit_call_far_before_the_write_is_not_its_context():
    padding = "".join(f"    val v{i} = {i}\n" for i in range(60))
    body = (
        "class Probe(private val prefs: SharedPreferences) {\n"
        '    fun a() = prefs.edit().putString("display_name", "x").apply()\n'
        f"{padding}"
        '    fun b(outState: android.os.Bundle) { outState.putString("password", "x") }\n}'
    )
    assert rules(with_code(body, PREFS_IMPORTS)) == []


def test_each_kind_of_encrypted_storage_marker_silences_the_preferences_rule():
    for extra in (
        "import androidx.security.crypto.MasterKey\n",
        "import com.google.crypto.tink.integration.android.AndroidKeysetManager\n",
        "typealias Sealed = com.example.Aead\n",
    ):
        assert (
            rules(
                prefs(
                    'prefs.edit().putString("refresh_token", token).apply()', PREFS_IMPORTS + extra
                )
            )
            == []
        ), extra
    assert rules(prefs('prefs.edit().putString("refresh_token", encrypt(token)).apply()')) == []


def test_a_signing_password_repeated_in_two_configs_gets_separate_keys():
    files = with_signing(
        '        create("release") {\n            storePassword = "s3cretPass9"\n        }\n'
        '        create("staging") {\n            storePassword = "s3cretPass8"\n        }\n'
    )
    assert [k for _, k in found(files)] == ["storePassword#1", "storePassword#2"]


def test_an_unreadable_module_makes_the_credential_manager_check_silent_everywhere():
    files = with_core(credential_manager(CREDENTIALS))
    files = edit(
        files,
        "core/build.gradle.kts",
        'id("com.android.library")',
        'id("com.android.library")\n    id("company.convention")',
    )
    assert rules(files) == []


def test_an_appauth_redirect_activity_in_a_test_manifest_does_not_configure_the_app():
    files = with_dependency(APPAUTH)
    files["app/src/androidTest/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" xmlns:tools="http://schemas.android.com/tools">\n'
        f"    <application>\n{REDIRECT_ACTIVITY}    </application>\n</manifest>\n"
    )
    assert rules(files) == ["auth.appauth_redirect_not_configured"]


def test_appauth_placeholders_may_be_written_with_put():
    base = with_dependency(APPAUTH)
    assert (
        rules(
            with_placeholder(
                base,
                '        manifestPlaceholders.put("appAuthRedirectScheme", "com.example.todo")\n',
            )
        )
        == []
    )


def test_a_redirect_is_not_judged_without_a_manifest_or_with_a_short_call():
    uri = 'Uri.parse("com.example.todo:/oauth2redirect")'
    files = redirect(uri)
    del files[MANIFEST]
    assert rules(files) == []
    short = with_code(
        "class Probe(private val config: AuthorizationServiceConfiguration) {\n    fun request() = AuthorizationRequest.Builder(config)\n}",
        APPAUTH_IMPORTS,
    )
    assert rules(short) == []


def test_scheme_case_is_ignored_in_either_direction():
    lowercase_use = redirect('Uri.parse("com.example.todo:/cb")')
    assert rules(with_scheme_filter(lowercase_use, "COM.EXAMPLE.TODO")) == []


def test_two_files_importing_a_removed_library_give_one_finding_and_build_sources_do_not_count():
    before = signed_in_project()
    before[f"{MAIN}/Another.kt"] = kt(FIREBASE_CODE.replace("SignIn", "Another"), FIREBASE_IMPORT)
    assert len(changes(before, removed(before))) == 1
    only_build_source = with_dependency(FIREBASE_AUTH)
    only_build_source["buildSrc/src/main/kotlin/Conventions.kt"] = kt(
        FIREBASE_CODE, FIREBASE_IMPORT
    )
    assert changes(only_build_source, removed(only_build_source)) == []


def test_identifiers_made_only_of_digits_or_of_a_repeating_pattern_are_not_secrets():
    assert rules(with_code('val clientSecret = "4829175036481920"')) == []  # digits only
    assert rules(with_code('val clientSecret = "ab12ab12ab12ab12ab12"')) == []  # low entropy


def test_two_tokens_on_one_line_are_two_findings():
    github, slack = SYNTHETIC_TOKENS["a GitHub token"], SYNTHETIC_TOKENS["a Slack token"]
    files = with_code(f'val both = listOf("{github}", "{github[:-1]}x")\nval other = "{slack}"')
    assert [k for _, k in found(files)] == [
        "token:a GitHub token#1",
        "token:a GitHub token#2",
        "token:a Slack token#1",
    ]


def with_sibling(base):
    """The project plus a library ``other`` that the app does NOT depend on, with a convention
    plugin the review cannot read."""
    files = dict(base)
    files["settings.gradle.kts"] = files["settings.gradle.kts"].replace(
        'include(":app")', 'include(":app")\ninclude(":other")'
    )
    files["other/build.gradle.kts"] = (
        'plugins {\n    id("com.android.library")\n    id("company.convention")\n}\n\n'
        'android {\n    namespace = "com.example.other"\n    compileSdk = 35\n}\n'
    )
    files["other/src/main/AndroidManifest.xml"] = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n'
    )
    return files


def test_an_unreadable_module_the_app_does_not_depend_on_still_silences_the_credential_check():
    readable = credential_manager(CREDENTIALS)
    assert rules(readable) == ["auth.credential_manager_provider_missing"]
    assert rules(with_sibling(readable)) == []  # `other` might declare the provider


def test_a_placeholder_in_the_manifest_resolves_to_its_gradle_value():
    wrong = edit(
        with_placeholder(
            redirect('Uri.parse("com.example.todo:/cb")'),
            '        manifestPlaceholders["appAuthRedirectScheme"] = "com.other.app"\n',
        ),
        MANIFEST,
        "    </application>",
        '        <activity android:name=".Redirect" android:exported="true"><intent-filter><data android:scheme="${appAuthRedirectScheme}" /></intent-filter></activity>\n    </application>',
    )
    assert found(wrong) == [("auth.appauth_redirect_scheme_unmatched", "com.example.todo#1")]


def test_a_redirect_matches_a_placeholder_written_with_put():
    files = with_placeholder(
        redirect('Uri.parse("com.example.todo:/cb")'),
        '        manifestPlaceholders.put("appAuthRedirectScheme", "com.example.todo")\n',
    )
    assert rules(files) == []
    other = with_placeholder(
        redirect('Uri.parse("com.example.todo:/cb")'),
        '        manifestPlaceholders.put("appAuthRedirectScheme", "com.other.app")\n',
    )
    assert rules(other) == ["auth.appauth_redirect_scheme_unmatched"]
