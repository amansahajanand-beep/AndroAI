"""Compatibility rules and build-environment selection.

The AGP -> minimum JDK / Gradle table below is transcribed from the Android Gradle Plugin
release notes. It is a *starting point*: verify it against
https://developer.android.com/build/releases/gradle-plugin before pinning production
images, and extend it as new AGP versions ship (unknown newer AGP versions are treated
as needing JDK 17+ and are flagged `unverified`, never silently accepted as exact).

We never modify the project's toolchain: a project whose requirements no worker
environment can satisfy is rejected with the reason, not "fixed".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detect import Detected, _ver_key

# (AGP major, minor) -> (minimum JDK, minimum Gradle)
AGP_REQUIREMENTS: dict[tuple[int, int], tuple[int, str]] = {
    (4, 0): (8, "6.1.1"), (4, 1): (8, "6.5"), (4, 2): (8, "6.7.1"),
    (7, 0): (11, "7.0.2"), (7, 1): (11, "7.2"), (7, 2): (11, "7.3.3"), (7, 3): (11, "7.4"), (7, 4): (11, "7.5"),
    (8, 0): (17, "8.0"), (8, 1): (17, "8.0"), (8, 2): (17, "8.2"), (8, 3): (17, "8.4"), (8, 4): (17, "8.6"),
    (8, 5): (17, "8.7"), (8, 6): (17, "8.7"), (8, 7): (17, "8.9"), (8, 8): (17, "8.10.2"), (8, 9): (17, "8.11.1"),
    (8, 10): (17, "8.11.1"),
}
# Gradle versions that cannot run on newer JDKs: (first Gradle supporting, JDK)
GRADLE_JDK_SUPPORT = [("8.5", 21), ("7.3", 17)]  # newest first
SUPPORTED_JDKS = (8, 11, 17, 21)


@dataclass
class Requirements:
    jdk: int | None
    max_jdk: int | None
    compile_sdk: int | None
    agp: str | None
    gradle: str | None
    kotlin: str | None
    unverified: bool = False
    problems: list[str] = field(default_factory=list)  # reasons the project cannot be built
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _agp_min(agp: str) -> tuple[int, str | None, bool]:
    major, minor = _ver_key(agp)[:2] if len(_ver_key(agp)) >= 2 else (0, 0)
    if (major, minor) in AGP_REQUIREMENTS:
        jdk, gradle = AGP_REQUIREMENTS[(major, minor)]
        return jdk, gradle, False
    if (major, minor) > max(AGP_REQUIREMENTS):
        return 17, None, True
    return 8, None, True  # older than the table: assume nothing beyond JDK 8


def _max_jdk_for_gradle(gradle: str) -> int:
    for first, jdk in GRADLE_JDK_SUPPORT:
        if _ver_key(gradle) >= _ver_key(first):
            return jdk
    return 11


def derive_requirements(d: Detected) -> Requirements:
    r = Requirements(jdk=None, max_jdk=None, compile_sdk=d.compile_sdk, agp=d.agp, gradle=d.gradle, kotlin=d.kotlin)
    if not d.has_wrapper:
        r.problems.append("Project has no Gradle wrapper; add gradle/wrapper/gradle-wrapper.properties and gradlew")
    if not d.has_settings:
        r.problems.append("Project has no settings.gradle(.kts)")
    if d.agp is None:
        r.problems.append("Android Gradle Plugin version could not be determined")
    if d.compile_sdk is None:
        r.problems.append("compileSdk could not be determined")
    jdk_min = 8
    if d.agp:
        jdk_min, agp_gradle, r.unverified = _agp_min(d.agp)
        if r.unverified:
            r.warnings.append(f"AGP {d.agp} is not in the verified compatibility table")
        if agp_gradle and d.gradle and _ver_key(d.gradle) < _ver_key(agp_gradle):
            r.warnings.append(f"AGP {d.agp} expects Gradle >= {agp_gradle} but the wrapper uses {d.gradle}; the build may fail")
    if d.java_version:
        jdk_min = max(jdk_min, d.java_version)
    r.jdk = jdk_min
    if d.gradle:
        r.max_jdk = _max_jdk_for_gradle(d.gradle)
        if r.jdk > r.max_jdk:
            r.problems.append(f"Gradle {d.gradle} cannot run on JDK {r.jdk} which this project needs")
    return r


@dataclass
class Environment:
    """What a worker advertises (stored in worker_registry.toolchain)."""

    jdks: list[int]
    platforms: list[int]  # installed Android platform API levels
    id: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Environment":
        return Environment(jdks=[int(x) for x in d.get("jdks", [])], platforms=[int(x) for x in d.get("platforms", [])],
                           id=str(d.get("id", "")))


def select_jdk(req: Requirements, env: Environment) -> tuple[int | None, str | None]:
    """Lowest installed JDK satisfying the project; else (None, reason)."""
    if req.jdk is None:
        return None, "project requirements unknown"
    ok = [j for j in sorted(env.jdks) if j >= req.jdk and (req.max_jdk is None or j <= req.max_jdk)]
    if not ok:
        return None, f"needs JDK {req.jdk}" + (f"..{req.max_jdk}" if req.max_jdk else "+") + f", worker has {sorted(env.jdks)}"
    if req.compile_sdk is not None and req.compile_sdk not in env.platforms:
        return None, f"needs Android platform {req.compile_sdk}, worker has {sorted(env.platforms)}"
    return ok[0], None


def environment_supports(req_dict: dict, env: Environment) -> bool:
    req = Requirements(jdk=req_dict.get("jdk"), max_jdk=req_dict.get("max_jdk"), compile_sdk=req_dict.get("compile_sdk"),
                       agp=req_dict.get("agp"), gradle=req_dict.get("gradle"), kotlin=req_dict.get("kotlin"))
    return select_jdk(req, env)[0] is not None
