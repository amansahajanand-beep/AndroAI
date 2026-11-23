"""Identifiers derived from the display name of a project.

The display name may hold any script (``Notes Ä``, ``नमस्ते``); the things derived here end up in
Kotlin identifiers, Android style names and the Gradle root project name, which must stay plain
ASCII. A name with no ASCII letters or digits at all falls back to a fixed word instead of
producing an empty or invalid identifier.
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[A-Za-z0-9]+")
FALLBACK_IDENTIFIER = "App"


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def pascal_identifier(project_name: str) -> str:
    """``"my notes-app"`` -> ``"MyNotesApp"``: ASCII, starts with a letter (a Kotlin identifier)."""
    words = _WORD.findall(_ascii_fold(project_name))
    pascal = "".join(word[0].upper() + word[1:] for word in words)
    if not pascal:
        return FALLBACK_IDENTIFIER
    if pascal[0].isdigit():
        return FALLBACK_IDENTIFIER + pascal
    return pascal


def gradle_project_name(project_name: str, package_name: str) -> str:
    """The ``rootProject.name``: ASCII words joined by ``-``, else the last package segment."""
    words = _WORD.findall(_ascii_fold(project_name))
    if words:
        return "-".join(words)
    return package_name.rsplit(".", 1)[-1]
