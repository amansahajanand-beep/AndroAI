from androai_android_tools import Environment, derive_requirements, detect, environment_supports, select_jdk

WRAPPER = b"distributionUrl=https\\://services.gradle.org/distributions/gradle-8.7-bin.zip\n"

KTS = {
    "gradle/wrapper/gradle-wrapper.properties": WRAPPER,
    "settings.gradle.kts": b'rootProject.name = "x"',
    "build.gradle.kts": b'plugins { id("com.android.application") version "8.5.0" apply false\n id("org.jetbrains.kotlin.android") version "1.9.22" apply false }',
    "app/build.gradle.kts": b"android { compileSdk = 34\n defaultConfig { minSdk = 24\n targetSdk = 34 }\n compileOptions { sourceCompatibility = JavaVersion.VERSION_17 } }\nplugins { id(\"com.google.devtools.ksp\") }",
}


def test_detects_kts_project():
    d = detect(KTS)
    assert (d.gradle, d.agp, d.kotlin, d.compile_sdk, d.min_sdk, d.target_sdk) == ("8.7", "8.5.0", "1.9.22", 34, 24, 34)
    assert d.java_version == 17 and d.has_wrapper and d.has_settings and "ksp" in d.plugins


def test_detects_modules():
    d = detect({"settings.gradle.kts": b'include(":app", ":core:data")\ninclude(":feature:home")', "build.gradle": b""})
    assert d.modules == [":app", ":core:data", ":feature:home"]
    assert detect({"settings.gradle": b"include ':app', ':lib'"}).modules == [":app", ":lib"]


def test_detects_groovy_and_toml():
    files = {
        "gradle/wrapper/gradle-wrapper.properties": b"distributionUrl=https://services.gradle.org/distributions/gradle-7.5-all.zip",
        "settings.gradle": b"include ':app'",
        "build.gradle": b"buildscript { dependencies { classpath 'com.android.tools.build:gradle:7.4.2'\n classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:1.8.10\" } }",
        "app/build.gradle": b"android { compileSdkVersion 33\n defaultConfig { minSdkVersion 21 } }",
    }
    d = detect(files)
    assert (d.gradle, d.agp, d.kotlin, d.compile_sdk, d.min_sdk) == ("7.5", "7.4.2", "1.8.10", 33, 21)
    t = detect({**files, "build.gradle": b"", "gradle/libs.versions.toml": b'[versions]\nagp = "8.2.1"\nkotlin = "1.9.0"\n'})
    assert t.agp == "8.2.1" and t.kotlin == "1.9.0"


def test_requirements_and_jdk_selection():
    req = derive_requirements(detect(KTS))
    assert req.problems == [] and req.jdk == 17 and req.max_jdk == 21
    assert select_jdk(req, Environment(jdks=[11, 17], platforms=[34, 35])) == (17, None)
    jdk, why = select_jdk(req, Environment(jdks=[11], platforms=[34]))
    assert jdk is None and "JDK 17" in why
    jdk, why = select_jdk(req, Environment(jdks=[17], platforms=[33]))
    assert jdk is None and "platform 34" in why
    assert environment_supports(req.as_dict(), Environment(jdks=[17], platforms=[34]))
    assert not environment_supports(req.as_dict(), Environment(jdks=[11], platforms=[34]))


def test_old_gradle_cannot_use_jdk17():
    files = dict(KTS)
    files["gradle/wrapper/gradle-wrapper.properties"] = b"distributionUrl=x/gradle-6.9-bin.zip"
    req = derive_requirements(detect(files))
    assert any("cannot run on JDK 17" in p for p in req.problems)
    assert any("expects Gradle" in w for w in req.warnings)


def test_missing_pieces_are_reported_not_guessed():
    d = detect({"build.gradle": b"// empty"})
    assert d.gradle is None and d.agp is None and d.compile_sdk is None
    req = derive_requirements(d)
    joined = " ".join(req.problems)
    assert "wrapper" in joined and "Android Gradle Plugin" in joined and "compileSdk" in joined and "settings" in joined


def test_unknown_newer_agp_is_flagged_unverified():
    files = dict(KTS)
    files["build.gradle.kts"] = b'plugins { id("com.android.application") version "9.5.0" }'
    req = derive_requirements(detect(files))
    assert req.unverified and req.jdk >= 17 and any("not in the verified" in w for w in req.warnings)
