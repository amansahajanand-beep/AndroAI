"""The one place where the toolchain of a generated project is pinned.

**These pins are PROVISIONAL.** Every value below was read from an official source on 2026-11-20
(see ``SOURCES``), but nobody has run a Gradle build of a project generated with them: there is no
JDK, Gradle or Android SDK in the environment this was written in. Until a real build passes they
are a documented, internally consistent *proposal*, not a tested pair. To change a version, change
it here (and in ``docs/COMPATIBILITY_MATRIX.md`` once the team approves); nothing else in the
package spells a version number.

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
    compile_sdk_min: int  # lowest compileSdk the pinned Compose version builds with
    compile_sdk_max: int  # highest API level the pinned AGP supports


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
    compile_sdk_max=37,
)

DEFAULT_MIN_SDK = 24
DEFAULT_TARGET_SDK = 36
DEFAULT_COMPILE_SDK = 37

PROVISIONAL = True

# Where each pin comes from (all read 2026-11-20).
SOURCES: dict[str, str] = {
    "agp": "Google Maven metadata: newest final is 9.5.1 (9.6.0-alpha04 is a pre-release); "
    "developer.android.com/build/releases/gradle-plugin documents AGP 9.5: Gradle min and default "
    "9.6.0, JDK 17, build tools 36.0.0, maximum API level 37",
    "gradle": "services.gradle.org/versions/all lists 9.6.0 as a final release; it is AGP 9.5's "
    "documented minimum and default, and inside Kotlin 2.4.21's documented Gradle range "
    "(7.6.3-9.7.0)",
    "gradle_sha256": "identical in downloads.gradle.org/distributions/gradle-9.6.0-bin.zip.sha256, "
    "gradle.org/release-checksums and the services.gradle.org listing",
    "kotlin": "Maven Central: newest final kotlin-gradle-plugin is 2.4.21 (kotlinlang.org/docs/"
    "releases.html, 2026-10-08). AGP 9 bundles KGP 2.2.10 and documents a buildscript classpath "
    "entry for a newer one. KNOWN GAP: Kotlin's own table lists AGP 8.5.2-9.3.1 for 2.4.21, "
    "below 9.5.1",
    "compose_bom": "Google Maven metadata: newest final is 2026.11.01",
    "activity_compose": "Google Maven metadata: newest final is 1.13.0",
    "navigation_compose": "Google Maven metadata: newest final is 2.10.2 (maintenance mode: only "
    "critical fixes; Navigation 3 is the stable successor and is not used here)",
    "min_sdk_floor": "navigation 2.10.0-rc01: minimum SDK moved to API 24; "
    "lifecycle 2.10.0: API 23",
    "compile_sdk": "developer.android.com/develop/ui/compose/compiler: Compose 1.12.0 and later "
    "require compileSdk 37 and AGP 9; AGP 9.5 supports at most API level 37",
}
