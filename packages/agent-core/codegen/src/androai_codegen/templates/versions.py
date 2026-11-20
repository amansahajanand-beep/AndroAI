"""The one place where the toolchain of a generated project is pinned.

Every value below was read from an official source on 2026-11-20 (see ``SOURCES``) and then built:
``VERIFIED_BUILD`` records the Gradle tasks that passed for the project generated from the default
config. **Only that was verified.** Not built or run: signing (the release APK and AAB are
unsigned), an emulator or device, other package names or SDK levels, the Gradle wrapper (system
Gradle was used), or any test (the generated app has none yet: ``test`` passes with nothing to run).

The first build, with ``compileSdk = 37``, failed in ``checkDebugAarMetadata``: the pinned Compose
1.13.0 libraries declare ``minCompileSdk=37`` *and* ``minCompileMinorSdk=1``, i.e. they must be
compiled against API **37.1**, and an integer ``compileSdk = 37`` means API 37.0.
``compile_sdk_*_minor`` and the ``compileSdk`` block of the template exist for that reason.

A later check found that AGP 9.5.1 cannot create its Compose Preview tasks (``gradle tasks
--all`` failed) unless unit tests include Android resources and are enabled for every variant;
``testOptions`` and ``androidComponents`` in the template's ``app/build.gradle.kts`` fix that.

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
