"""Detect an Android project's toolchain requirements from its build files.

Pure functions over {path: bytes}; the caller decides which files to read (use
`RELEVANT_PATTERNS`). Detection is regex based and best-effort: anything not found is
`None` and reported in `Detected.notes`; we never guess a value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatch

RELEVANT_PATTERNS = (
    "gradle/wrapper/gradle-wrapper.properties",
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "gradle.properties", "gradle/libs.versions.toml",
    "*/build.gradle", "*/build.gradle.kts", "buildSrc/build.gradle*", "buildSrc/src/main/*/*.kt",
)
MAX_FILE_BYTES = 256 * 1024


def is_relevant(path: str) -> bool:
    return any(fnmatch(path, p) for p in RELEVANT_PATTERNS)


@dataclass
class Detected:
    gradle: str | None = None
    agp: str | None = None
    kotlin: str | None = None
    compile_sdk: int | None = None
    target_sdk: int | None = None
    min_sdk: int | None = None
    java_version: int | None = None  # source/target/toolchain level requested by the project
    has_wrapper: bool = False
    has_settings: bool = False
    plugins: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


_P = {
    "wrapper": re.compile(r"distributionUrl\s*=.*?gradle-(\d+(?:\.\d+){1,2})(?:-[A-Za-z0-9]+)*-(?:bin|all)\.zip"),
    "agp_classpath": re.compile(r"com\.android\.tools\.build:gradle:(\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9.]+)?)"),
    "agp_plugin": re.compile(r"""com\.android\.(?:application|library)['"]?\)?\s*version\s*\(?['"](\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9.]+)?)['"]"""),
    "agp_toml": re.compile(r"""^\s*(?:agp|androidGradlePlugin|android-gradle-plugin)\s*=\s*["'](\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9.]+)?)["']""", re.M),
    "kotlin_a": re.compile(r"""org\.jetbrains\.kotlin(?:\.android)?['"]?\)?\s*version\s*\(?['"](\d+\.\d+(?:\.\d+)?)['"]"""),
    "kotlin_b": re.compile(r"""kotlin(?:_version|Version)\s*=\s*['"](\d+\.\d+(?:\.\d+)?)['"]"""),
    "kotlin_c": re.compile(r"""kotlin-gradle-plugin:(\d+\.\d+(?:\.\d+)?)"""),
    "kotlin_toml": re.compile(r"""^\s*kotlin\s*=\s*["'](\d+\.\d+(?:\.\d+)?)["']""", re.M),
    "compile_sdk": re.compile(r"\bcompileSdk(?:Version)?\s*(?:=|\s)\s*(\d{2})\b"),
    "target_sdk": re.compile(r"\btargetSdk(?:Version)?\s*(?:=|\s)\s*(\d{2})\b"),
    "min_sdk": re.compile(r"\bminSdk(?:Version)?\s*(?:=|\s)\s*(\d{1,2})\b"),
    "java_a": re.compile(r"JavaVersion\.VERSION_(\d+)(?:_(\d+))?"),
    "java_b": re.compile(r"jvmToolchain\s*\(\s*(\d+)\s*\)"),
    "java_c": re.compile(r"""languageVersion\s*(?:=|\.set\()\s*JavaLanguageVersion\.of\(\s*(\d+)\s*\)"""),
}
_PLUGIN_MARKERS = {
    "kapt": "kotlin-kapt", "ksp": "com.google.devtools.ksp", "hilt": "dagger.hilt",
    "google-services": "com.google.gms.google-services", "firebase": "firebase-",
    "compose": "compose", "ndk": "externalNativeBuild", "navigation-safeargs": "androidx.navigation.safeargs",
}


def _ver_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("-")[0])[:3])


def _first(pattern, texts: list[str]) -> re.Match | None:
    for t in texts:
        m = pattern.search(t)
        if m:
            return m
    return None


def detect(files: Mapping[str, bytes]) -> Detected:
    d = Detected()
    texts: dict[str, str] = {
        p: b[:MAX_FILE_BYTES].decode("utf-8", errors="replace") for p, b in files.items() if is_relevant(p)
    }
    allt = list(texts.values())
    d.has_settings = any(p in texts for p in ("settings.gradle", "settings.gradle.kts"))
    wrapper = texts.get("gradle/wrapper/gradle-wrapper.properties")
    d.has_wrapper = wrapper is not None
    if wrapper and (m := _P["wrapper"].search(wrapper)):
        d.gradle = m.group(1)
    elif d.has_wrapper:
        d.notes.append("gradle-wrapper.properties present but distribution version not recognised")
    else:
        d.notes.append("no Gradle wrapper (gradle/wrapper/gradle-wrapper.properties)")

    for key in ("agp_classpath", "agp_plugin", "agp_toml"):
        if m := _first(_P[key], allt):
            d.agp = m.group(1)
            break
    else:
        d.notes.append("Android Gradle Plugin version not found")
    for key in ("kotlin_a", "kotlin_b", "kotlin_c", "kotlin_toml"):
        if m := _first(_P[key], allt):
            d.kotlin = m.group(1)
            break
    if m := _first(_P["compile_sdk"], allt):
        d.compile_sdk = int(m.group(1))
    else:
        d.notes.append("compileSdk not found")
    if m := _first(_P["target_sdk"], allt):
        d.target_sdk = int(m.group(1))
    if m := _first(_P["min_sdk"], allt):
        d.min_sdk = int(m.group(1))

    levels: list[int] = []
    for t in allt:
        for m in _P["java_a"].finditer(t):
            levels.append(1 if m.group(1) == "1" and m.group(2) else int(m.group(1)) if m.group(2) is None else int(m.group(2)))
        levels += [int(m.group(1)) for k in ("java_b", "java_c") for m in _P[k].finditer(t)]
    levels = [lv for lv in levels if lv >= 8]
    if levels:
        d.java_version = max(levels)

    blob = "\n".join(allt)
    d.plugins = sorted(name for name, marker in _PLUGIN_MARKERS.items() if marker in blob)
    return d
