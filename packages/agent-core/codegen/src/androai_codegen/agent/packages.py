"""Package and application-id renaming, done by code (never by a model).

``rename_text`` rewrites every dotted occurrence of a package (``com.old.app``) and of its
sub-packages (``com.old.app.ui``) when it stands on its own: not glued to other identifier
characters and not the tail of a longer dotted name. ``rename_path`` moves a source file to the
folder that matches its new package. Both are pure functions so they can be tested exhaustively.
"""

from __future__ import annotations

import re

JAVA_KEYWORDS = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int interface "
    "long native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while true false null".split()
)
_SEGMENT = re.compile(r"^[a-z][a-z0-9_]*$")
# Files whose text is rewritten. Anything else (images, JSON service configs, ...) is left alone and
# reported if it still mentions the old name.
TEXT_SUFFIXES = (
    ".kt", ".kts", ".java", ".xml", ".gradle", ".pro", ".properties", ".txt", ".md", ".cfg",
    ".toml",
    ".yml", ".yaml",
)  # fmt: skip
SOURCE_ROOTS = ("java", "kotlin")


def validate_package(name: str) -> str | None:
    """None if ``name`` is a usable package name, else why not."""
    parts = name.split(".")
    if len(parts) < 2:
        return "a package name needs at least two parts, like com.example.app"
    for part in parts:
        if not _SEGMENT.match(part):
            return (
                f"'{part}' is not a valid package segment (lowercase letters, digits, underscores)"
            )
        if part in JAVA_KEYWORDS:
            return f"'{part}' is a reserved word and cannot be used in a package name"
    return None


def _pattern(old: str) -> re.Pattern[str]:
    # Not preceded by an identifier character or a dot; not followed by an identifier character.
    return re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(old) + r"(?![A-Za-z0-9_])")


def rename_text(text: str, old: str, new: str) -> str:
    return _pattern(old).sub(new, text)


def mentions(text: str, old: str) -> bool:
    return _pattern(old).search(text) is not None


def is_rewritable(path: str) -> bool:
    return path.lower().endswith(TEXT_SUFFIXES)


def rename_path(path: str, old: str, new: str) -> str:
    """The new location of a source file; unchanged if it is not in the old package's folder."""
    parts = path.split("/")
    old_parts, new_parts = old.split("."), new.split(".")
    for i, part in enumerate(parts[:-1]):
        if part in SOURCE_ROOTS and parts[i + 1 : i + 1 + len(old_parts)] == old_parts:
            start = i + 1
            return "/".join(parts[:start] + new_parts + parts[start + len(old_parts) :])
    return path


_APP_ID = re.compile(r"""(applicationId\s*(?:=\s*)?)(["'])([^"']+)\2""")


def set_application_id(text: str, new: str) -> tuple[str, int]:
    """Replace the value of every ``applicationId`` in a Gradle script; how many were changed."""
    count = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}{new}{match.group(2)}"

    return _APP_ID.sub(swap, text), count
