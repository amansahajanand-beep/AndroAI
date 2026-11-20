"""Validation of the names a project is built from.

Rules come from the documentation, not from habit:

* application ID (developer.android.com/build/configure-app-module): at least two segments, each
  starting with a letter, all characters ``[a-zA-Z0-9_]``;
* package name (the ``namespace``, which is the Kotlin package of the sources and of ``R``): the
  same, restricted to lowercase because it becomes directory names, and never a Kotlin hard
  keyword (kotlinlang.org/docs/keyword-reference.html), a Java reserved word or literal (JLS 3.9) or
  a Windows device name (the path validator would reject the directory anyway).

Anything else is rejected, never "fixed up".
"""

from __future__ import annotations

import re
import unicodedata

MAX_PACKAGE_LENGTH = 100
MAX_PROJECT_NAME_LENGTH = 50
MAX_VERSION_NAME_LENGTH = 40

KOTLIN_HARD_KEYWORDS = frozenset(
    """as break class continue do else false for fun if in interface is null object package return
    super this throw true try typealias typeof val var when while""".split()
)
# JLS 17 section 3.9: 51 reserved keywords (``_`` included), plus the three literals.
JAVA_RESERVED_WORDS = frozenset(
    """abstract assert boolean break byte case catch char class const continue default do double
    else enum extends final finally float for goto if implements import instanceof int interface
    long native new package private protected public return short static strictfp super switch
    synchronized this throw throws transient try void volatile while _ true false null""".split()
)
RESERVED_SEGMENTS = KOTLIN_HARD_KEYWORDS | JAVA_RESERVED_WORDS
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

_PACKAGE_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")
_APP_ID_SEGMENT = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")
_VERSION_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")
# Besides letters and digits, a project name may use these. Everything that has a meaning in
# XML, Kotlin, Gradle, a path or an Android string resource (``< > " \ / $ @ ? % :`` ...) is out.
_NAME_PUNCTUATION = frozenset(" _-.'&,()!+")


def _segments(value: object, what: str, limit: int) -> list[str]:
    if not isinstance(value, str):
        raise ValueError(f"{what} must be a string")
    if not value:
        raise ValueError(f"{what} is empty")
    if len(value) > limit:
        raise ValueError(f"{what} is longer than {limit} characters")
    parts = value.split(".")
    if len(parts) < 2:
        raise ValueError(f"{what} needs at least two segments separated by dots (like com.example)")
    return parts


def validate_package_name(value: object) -> str:
    """The Kotlin package / ``namespace``: lowercase segments, no keywords, no device names."""
    parts = _segments(value, "package name", MAX_PACKAGE_LENGTH)
    for part in parts:
        if not part:
            raise ValueError(
                "package name has an empty segment (a leading, trailing or double dot)"
            )
        if not _PACKAGE_SEGMENT.fullmatch(part):
            raise ValueError(
                f"package segment {part!r} must start with a lowercase letter and contain only "
                "lowercase letters, digits and underscores"
            )
        if part in RESERVED_SEGMENTS:
            raise ValueError(f"package segment {part!r} is a Kotlin or Java reserved word")
        if part in _WINDOWS_DEVICES:
            raise ValueError(f"package segment {part!r} is a reserved device name on Windows")
    assert isinstance(value, str)
    return value


def validate_application_id(value: object) -> str:
    """The Android application ID, by the documented rules."""
    parts = _segments(value, "application ID", MAX_PACKAGE_LENGTH)
    for part in parts:
        if not _APP_ID_SEGMENT.fullmatch(part):
            raise ValueError(
                f"application ID segment {part!r} must start with a letter and contain only "
                "letters, digits and underscores"
            )
    assert isinstance(value, str)
    return value


def _name_char_allowed(ch: str) -> bool:
    # Letters, numbers and combining marks (Devanagari, Thai ... need them) of any script.
    return ch in _NAME_PUNCTUATION or unicodedata.category(ch)[0] in "LNM"


def validate_project_name(value: object) -> str:
    """A display name: letters, digits, single spaces and a few harmless symbols, NFC-normalised."""
    if not isinstance(value, str):
        raise ValueError("project name must be a string")
    value = unicodedata.normalize("NFC", value)
    if not value:
        raise ValueError("project name is empty")
    if value != value.strip():
        raise ValueError("project name must not start or end with a space")
    if len(value) > MAX_PROJECT_NAME_LENGTH:
        raise ValueError(f"project name is longer than {MAX_PROJECT_NAME_LENGTH} characters")
    bad = sorted({ch for ch in value if not _name_char_allowed(ch)})
    if bad:
        raise ValueError(f"project name contains characters that are not allowed: {bad!r}")
    if unicodedata.category(value[0])[0] not in "LN":
        raise ValueError("project name must start with a letter or digit")
    if "  " in value:
        # Android collapses runs of whitespace in a string resource, so the app would not be
        # shown under the name that was asked for.
        raise ValueError("project name must not contain consecutive spaces")
    return value


def validate_version_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("version name must be a string")
    if len(value) > MAX_VERSION_NAME_LENGTH or not _VERSION_NAME.fullmatch(value):
        raise ValueError(
            "version name must start with a letter or digit and contain only letters, digits "
            f"and . _ + - (at most {MAX_VERSION_NAME_LENGTH} characters)"
        )
    return value
