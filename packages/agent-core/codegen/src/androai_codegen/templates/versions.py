"""The one place where the toolchain of a generated project is pinned.

Every value below was read from an official source on 2026-11-20 (see ``SOURCES``) and then built:
``VERIFIED_BUILD`` records the Gradle tasks that passed for the project generated from the default
config and, separately (``spec_*``), for four projects generated from a ``ProjectSpec`` together
with their generated navigation tests (Phase 5.3). **Only that was verified.** Not built or run:
signing (the release APK and AAB are unsigned), an instrumented test or any run of these builds on
a device by the code that renders them, other package names or SDK levels than the samples', the
Gradle wrapper (system Gradle was used). The default project has no test (``test`` passes with
nothing to run); a project with a spec has the navigation tests.

The first build, with ``compileSdk = 37``, failed in ``checkDebugAarMetadata``: the pinned Compose
1.13.0 libraries declare ``minCompileSdk=37`` *and* ``minCompileMinorSdk=1``, i.e. they must be
compiled against API **37.1**, and an integer ``compileSdk = 37`` means API 37.0.
``compile_sdk_*_minor`` and the ``compileSdk`` block of the template exist for that reason.

A later check found that AGP 9.5.1 cannot create its Compose Preview tasks (``gradle tasks
--all`` failed) unless unit tests include Android resources and are enabled for every variant;
``testOptions`` and ``androidComponents`` in the template's ``app/build.gradle.kts`` fix that.

Phase 5.3 added test-only libraries and found two limits with real runs. Robolectric 4.18.1 needs
Java 21 to simulate API 36 (the app's target) and the build is JDK 17, so the generated test pins
API 35 (``robolectric_sdk``) and a project whose ``minSdk`` is higher gets no test. And the
``ComponentActivity`` a Compose test launches comes from ``ui-test-manifest``, which only the debug
variant can have, so the release unit-test task (which must stay registered for the Compose
Preview) is skipped. Neither changed a pin.

To change a version, change it here (and in ``docs/COMPATIBILITY_MATRIX.md`` once the team
approves), then rebuild and update ``VERIFIED_BUILD``: a test fails while the two disagree. Nothing
else in the package spells a version number.

The Android section of ``docs/COMPATIBILITY_MATRIX.md`` is deliberately incomplete ("pin one tested
pair") and still lists compileSdk / targetSdk 35. The current libraries do not build with that,
which is why ``compile_sdk`` and ``target_sdk`` differ from the matrix's defaults.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolchainPins:
    agp: str  # Android Gradle plugin
    gradle: str
    gradle_sha256: str  # of ``gradle-<version>-bin.zip``, written into the wrapper properties
    kotlin: str
    compose_bom: str
    activity_compose: str
    navigation_compose: str
    jdk: int  # source / target compatibility of the generated code
    # Test-only libraries of the generated navigation tests (Phase 5.3). The Compose test libraries
    # (ui-test-junit4, ui-test-manifest) are versioned by the Compose BOM, and navigation-testing
    # by ``navigation_compose``; neither is pinned separately.
    junit: str
    robolectric: str
    # The Android level Robolectric simulates. Robolectric 4.18.1 needs Java 21 for API 36, and the
    # generated project builds on JDK 17, so this is the highest level that runs there.
    robolectric_sdk: int
    min_sdk_floor: int  # lowest minSdk the pinned AndroidX libraries support
    # The compile SDK is an API level plus a minor level (API 37.1 = 37, minor 1). The range is
    # lexicographic: (compile_sdk_min, compile_sdk_min_minor) <= (compile_sdk, minor) <=
    # (compile_sdk_max, compile_sdk_max_minor).
    compile_sdk_min: int  # API level of the lowest compileSdk the pinned Compose builds with
    compile_sdk_min_minor: int  # its minor level: Compose 1.13.0 needs 37.1, not 37.0
    compile_sdk_max: int  # API level of the highest compileSdk validated with the pinned AGP
    compile_sdk_max_minor: int  # its minor level


TOOLCHAIN = ToolchainPins(
    agp="9.5.1",
    gradle="9.6.0",
    gradle_sha256="bbaeb2fef8710818cf0e261201dab964c572f92b942812df0c3620d62a529a01",
    kotlin="2.4.21",
    compose_bom="2026.11.01",
    activity_compose="1.13.0",
    navigation_compose="2.10.2",
    jdk=17,
    junit="4.13.2",
    robolectric="4.18.1",
    robolectric_sdk=35,
    min_sdk_floor=24,
    compile_sdk_min=37,
    compile_sdk_min_minor=1,
    compile_sdk_max=37,
    compile_sdk_max_minor=1,
)

DEFAULT_MIN_SDK = 24
DEFAULT_TARGET_SDK = 36
DEFAULT_COMPILE_SDK = 37
DEFAULT_COMPILE_SDK_MINOR = 1

# The build that passed (a generated project, default config). Keep in step with ``TOOLCHAIN``: a
# test compares them, so a bumped pin cannot silently keep claiming to be verified.
VERIFIED_BUILD: dict[str, str | int | tuple[str, ...]] = {
    "tasks": (
        "build",
        "assembleDebug",
        "assembleRelease",
        "bundleRelease",
        "lint",
        "test",
        "tasks --all",
        ":app:generateDebugComposePreviewRunfiles --compose-preview-manifest-file=<path>",
        ":app:generateReleaseComposePreviewRunfiles --compose-preview-manifest-file=<path>",
    ),
    "outputs": "debug APK, unsigned release APK, unsigned release AAB; lint 0 errors 4 warnings",
    "date": "2026-11-20",
    "environment": "Docker (Linux), eclipse-temurin 17.0.21, system Gradle 9.6.0, Android SDK "
    "platform 37.1 and build-tools 36.0.0, cmdline-tools 15859902",
    "agp": "9.5.1",
    "gradle": "9.6.0",
    "kotlin": "2.4.21",
    "compose_bom": "2026.11.01",
    "activity_compose": "1.13.0",
    "navigation_compose": "2.10.2",
    "jdk": 17,
    "min_sdk": DEFAULT_MIN_SDK,
    "target_sdk": DEFAULT_TARGET_SDK,
    "compile_sdk": f"{DEFAULT_COMPILE_SDK}.{DEFAULT_COMPILE_SDK_MINOR}",
    # Phase 5.3: projects rendered from a ProjectSpec, with the generated NavigationTest. Same
    # environment and pins as above; the test libraries below are the ones that resolved.
    "spec_projects": (
        "1 screen",
        "3 screens",
        "4 screens named after Kotlin keywords",
        "12 screens with another package, application ID, name and version",
    ),
    "spec_tasks": (
        "build",
        "tasks --all",
        "assembleRelease",
        "bundleRelease",
        "lint",
        ":app:lintRelease",
        ":app:testDebugUnitTest --rerun",
    ),
    "spec_tests": "generated NavigationTest passes on the debug unit-test task (2, 7, 8 and 40 "
    "tests); the release unit-test task is skipped by design; lint 0 errors 4 warnings",
    "junit": "4.13.2",
    "robolectric": "4.18.1",
    "robolectric_sdk": 35,
    "navigation_testing": "2.10.2",
    "compose_ui_test": "1.13.0",  # ui-test-junit4 and ui-test-manifest, managed by the BOM
}

# False since that build passed. It was True while the pins had only been read from documentation.
PROVISIONAL = False

# Where each pin comes from (all read 2026-11-20).
SOURCES: dict[str, str] = {
    "agp": "Google Maven metadata: newest final is 9.5.1 (9.6.0-alpha04 is a pre-release); "
    "developer.android.com/build/releases/gradle-plugin documents AGP 9.5: Gradle min and default "
    "9.6.0, JDK 17, build tools 36.0.0",
    "gradle": "services.gradle.org/versions/all lists 9.6.0 as a final release; it is AGP 9.5's "
    "documented minimum and default, and inside Kotlin 2.4.21's documented Gradle range "
    "(7.6.3-9.7.0)",
    "gradle_sha256": "identical in downloads.gradle.org/distributions/gradle-9.6.0-bin.zip.sha256, "
    "gradle.org/release-checksums and the services.gradle.org listing",
    "kotlin": "Maven Central: newest final kotlin-gradle-plugin is 2.4.21 (kotlinlang.org/docs/"
    "releases.html, 2026-10-08). AGP 9 bundles KGP 2.2.10 and documents a buildscript classpath "
    "entry for a newer one. KNOWN GAP: Kotlin's own table lists AGP 8.5.2-9.3.1 for 2.4.21, "
    "below 9.5.1 (a real build with AGP 9.5.1 and Kotlin 2.4.21 printed no compatibility warning)",
    "compose_bom": "Google Maven metadata: newest final is 2026.11.01",
    "activity_compose": "Google Maven metadata: newest final is 1.13.0",
    "navigation_compose": "Google Maven metadata: newest final is 2.10.2 (maintenance mode: only "
    "critical fixes; Navigation 3 is the stable successor and is not used here)",
    "junit": "Maven Central: 4.13.2 is the newest final JUnit 4 release (after 4.13.1)",
    "robolectric": "Maven Central: 4.18.1 is the newest final (after 4.18, 4.17 and 4.16.1), "
    "released 2026-11-18. A real run: with the app's target SDK 36 it fails ('Android SDK 36 "
    "requires Java 21 (have Java 17)'); API 35 runs on JDK 17, with a 207 MB instrumented Android "
    "jar downloaded on first use",
    "robolectric_sdk": "a real run on JDK 17: 36 fails as above, 35 passes; with minSdk 36 and "
    "sdk 35 every test fails in ShadowPackageParser",
    "navigation_testing": "Google Maven: newest final navigation-testing is 2.10.2, the version of "
    "navigation-compose (the catalog uses one version for both)",
    "compose_ui_test": "compose-bom-2026.11.01.pom (dl.google.com/android/maven2) lists "
    "ui-test-junit4 and ui-test-manifest at 1.13.0; Google Maven's newest final is 1.13.0 too",
    "min_sdk_floor": "navigation 2.10.0-rc01: minimum SDK moved to API 24; "
    "lifecycle 2.10.0: API 23",
    "compile_sdk": "aar-metadata.properties of the Compose 1.13.0 AARs from BOM 2026.11.01 "
    "(ui, foundation, foundation-layout, animation, ui-tooling, ui-tooling-data): "
    "minCompileSdk=37, minCompileMinorSdk=1, minAndroidGradlePluginVersion=9.1.0, confirmed by the "
    "AGP error of a real build on 2026-11-20 ('compile against version 37.1 or later'). "
    "material3 1.5.0 needs 37.0, activity-compose 1.13.0 needs 36. Compose 1.12.1 (BOM 2026.09.00) "
    "needs 37.0. Platforms 37.0, 37.1 and 37.2 exist in the SDK manager; 37.1 is the one "
    "validated here, so the maximum is 37.1 too",
}
