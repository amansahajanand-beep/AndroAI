"""Rules for the names of imported entries, shared by the directory and the ZIP importer.

Names come from untrusted input. They are checked here, once, before any byte is written; the
strict canonical form is the one the patch engine already requires (``normalize_relative_path``),
so an imported project can always be opened by the engine.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from collections.abc import Callable, Sequence

from androai_codegen.editing.errors import PathValidationError
from androai_codegen.editing.paths import normalize_relative_path

from .errors import IngestCode, IngestRejected, shown
from .models import IngestLimits

# Never imported. ``.git`` is matched case-insensitively. A ``build`` directory is only excluded
# where it is a Gradle output directory (see ``excluded_reason``), because ``build`` can also be a
# source package. The workspace skips the same names when it lists a project.
# AI coding tools keep skills, caches and whole extra checkouts (``.claude/worktrees``) beside the
# code; they are not part of the app and would only crowd out and confuse the real files.
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".gradle",
        ".idea",
        "node_modules",
        ".cxx",
        ".externalNativeBuild",
        "__MACOSX",
        ".claude",
        ".cursor",
        ".windsurf",
    }
)
EXCLUDED_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})

# Kept as ordinary, inert files and reported; never opened or extracted.
NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".jar",
    ".aar",
    ".apk",
    ".aab",
    ".war",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
)

_DRIVE = re.compile(r"^[A-Za-z]:")


def is_nested_archive(rel: str) -> bool:
    return rel.lower().endswith(NESTED_ARCHIVE_SUFFIXES)


def split_name(raw: str, *, is_dir: bool = False) -> list[str]:
    """Split an untrusted entry name into segments, refusing anything unsafe first."""
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise IngestRejected(IngestCode.INVALID_PATH, "name has a control character", shown(raw))
    if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
        raise IngestRejected(IngestCode.ABSOLUTE_PATH, "absolute paths are not allowed", shown(raw))
    if "\\" in raw:
        raise IngestRejected(IngestCode.INVALID_PATH, "backslashes are not allowed", shown(raw))
    name = raw[:-1] if is_dir and raw.endswith("/") else raw
    parts = name.split("/")
    if ".." in parts:
        raise IngestRejected(IngestCode.PATH_TRAVERSAL, "'..' is not allowed", shown(raw))
    if any(part in ("", ".") for part in parts):
        raise IngestRejected(
            IngestCode.INVALID_PATH, "empty and '.' segments are not allowed", shown(raw)
        )
    return parts


def excluded_reason(
    parts: Sequence[str],
    *,
    is_dir: bool,
    build_is_output: Callable[[Sequence[str]], bool],
) -> str | None:
    """Why this entry is left out of an import, or ``None`` if it is part of the project.

    ``build_is_output(prefix)`` says whether the directory ``prefix`` is a Gradle project (a
    ``build`` directory beside a ``build.gradle[.kts]``, or at the project root, holds outputs).
    """
    last = len(parts) - 1
    for index, name in enumerate(parts):
        is_directory_here = index < last or is_dir
        if is_directory_here:
            if name.lower() == ".git":
                return ".git"
            if name in EXCLUDED_DIR_NAMES:
                return name
            if name == "build" and build_is_output(parts[:index]):
                return "build"
        elif name in EXCLUDED_FILE_NAMES:
            return name
    return None


def finalize_name(parts: Sequence[str], limits: IngestLimits) -> str:
    """The canonical project-relative path, or a refusal."""
    rel = "/".join(parts)
    try:
        canonical = normalize_relative_path(rel)
    except PathValidationError as exc:
        raise IngestRejected(IngestCode.INVALID_PATH, str(exc), shown(rel)) from exc
    if canonical != rel:
        raise IngestRejected(IngestCode.INVALID_PATH, "name is not in canonical form", shown(rel))
    if len(parts) > limits.max_depth:
        raise IngestRejected(
            IngestCode.TOO_DEEP, f"deeper than {limits.max_depth} segments", shown(rel)
        )
    if len(rel) > limits.max_path_length:
        raise IngestRejected(
            IngestCode.PATH_TOO_LONG, f"longer than {limits.max_path_length} characters", shown(rel)
        )
    return rel


def link_target_is_unsafe(link_rel: str, target: str) -> bool:
    """Whether a link stored at ``link_rel`` could lead out of the project (or cannot be judged)."""
    text = target.replace("\\", "/")
    if not text or "\x00" in text or text.startswith("/") or _DRIVE.match(text):
        return True
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(link_rel), text))
    return joined == ".." or joined.startswith("../") or posixpath.isabs(joined)


class NameRegistry:
    """Detects names that would collide on a case-insensitive or normalising file system.

    ``Foo.kt`` and ``foo.kt`` (or the same accented name composed two ways) become one file on
    Windows and macOS, so an archive that contains both is refused, as is a name used both as a
    file and as a directory.
    """

    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._dirs: dict[str, str] = {}

    @staticmethod
    def _key(rel: str) -> str:
        return unicodedata.normalize("NFC", rel).casefold()

    def _add_dir(self, rel: str) -> None:
        key = self._key(rel)
        if key in self._files:
            raise IngestRejected(
                IngestCode.PATH_CONFLICT, "name is used as both file and directory", shown(rel)
            )
        seen = self._dirs.setdefault(key, rel)
        if seen != rel:
            raise IngestRejected(
                IngestCode.NAME_COLLISION, f"collides with {shown(seen)}", shown(rel)
            )

    def _add_ancestors(self, rel: str) -> None:
        parts = rel.split("/")
        for end in range(1, len(parts)):
            self._add_dir("/".join(parts[:end]))

    def add_directory(self, rel: str) -> None:
        self._add_ancestors(rel)
        self._add_dir(rel)

    def add_file(self, rel: str) -> None:
        self._add_ancestors(rel)
        key = self._key(rel)
        if key in self._dirs:
            raise IngestRejected(
                IngestCode.PATH_CONFLICT, "name is used as both file and directory", shown(rel)
            )
        seen = self._files.get(key)
        if seen is not None:
            message = "duplicate entry" if seen == rel else f"collides with {shown(seen)}"
            raise IngestRejected(IngestCode.NAME_COLLISION, message, shown(rel))
        self._files[key] = rel
