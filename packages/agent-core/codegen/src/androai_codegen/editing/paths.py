"""Strict validation of project-relative paths.

Contract paths are project-relative with forward slashes. Everything else is rejected rather
than "fixed up", because a lenient parser is where path-traversal bugs live.
"""

from __future__ import annotations

import re

from .errors import PathValidationError

MAX_PATH_LENGTH = 1024
MAX_SEGMENT_LENGTH = 255

# Windows device names are reserved with or without an extension (``con.txt``).
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_GIT_SHORT_NAME = re.compile(r"git~[0-9]+", re.IGNORECASE)
# ':' also blocks drive letters and NTFS alternate data streams (``file.txt:stream``).
_FORBIDDEN_CHARS = frozenset('<>:"|?*') | frozenset(chr(c) for c in range(32))


def normalize_relative_path(raw: object) -> str:
    """Return the canonical form of ``raw`` or raise :class:`PathValidationError`.

    Canonical form: forward slashes, no ``.``/empty segments, no leading or trailing slash.
    ``..`` is rejected (never resolved), as are absolute paths, backslashes, control
    characters, Windows-reserved names and any ``.git`` component.
    """
    if not isinstance(raw, str):
        raise PathValidationError("path must be a string")
    if not raw.strip():
        raise PathValidationError("path is empty")
    if len(raw) > MAX_PATH_LENGTH:
        raise PathValidationError(f"path is longer than {MAX_PATH_LENGTH} characters")
    if "\\" in raw:
        raise PathValidationError("backslashes are not allowed; use forward slashes")
    if raw.startswith("/"):
        raise PathValidationError("absolute paths are not allowed")
    bad = sorted({c for c in raw if c in _FORBIDDEN_CHARS})
    if bad:
        raise PathValidationError(f"path contains forbidden characters: {bad!r}")
    if raw.endswith("/"):
        raise PathValidationError("path must name a file, not a directory")

    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise PathValidationError("path traversal ('..') is not allowed")
        if segment != segment.strip() or segment.endswith("."):
            # Windows silently strips trailing dots/spaces, which makes aliases of other names.
            raise PathValidationError(f"segment {segment!r} has leading/trailing space or dot")
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise PathValidationError("path segment is too long")
        if segment.lower() == ".git" or _GIT_SHORT_NAME.fullmatch(segment):
            # ``GIT~1`` is the NTFS 8.3 short name of ``.git``.
            raise PathValidationError("the .git directory is off limits")
        if segment.split(".", 1)[0].lower() in _RESERVED_NAMES:
            raise PathValidationError(f"segment {segment!r} is a reserved device name")
        parts.append(segment)

    if not parts:
        raise PathValidationError("path is empty after normalization")
    return "/".join(parts)
