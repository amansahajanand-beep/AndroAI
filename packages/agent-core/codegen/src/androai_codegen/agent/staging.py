"""A scratch copy of a project that an agent can read, search and edit, leaving the real one alone.

Reads fall through to the real workspace (secrets masked, protected files refused); every change
lands in memory. ``changes()`` is the net difference from the real project, which the executor turns
into a patch. Nothing here writes to disk.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from androai_codegen.editing import PatchEngine, mask_secrets, normalize_relative_path
from androai_codegen.editing.errors import CodegenError, NotTextFileError, PathValidationError

from . import packages

MAX_FILE_BYTES = 400_000  # larger text files are not read or searched
MAX_STAGED_BYTES = 30_000_000
MAX_TOUCHED = 3000
READ_LINES = 400
READ_CHARS = 24_000
SEARCH_HITS = 60
SEARCH_SCAN_LIMIT = 6000


class ToolError(Exception):
    """A tool call that cannot be done; the message goes back to the model."""


@dataclass(frozen=True)
class StagedChange:
    action: str  # "create" | "modify" | "delete"
    path: str
    content: str | None
    base_checksum: str | None  # of the real file, for modify and delete


class StagedFiles:
    def __init__(self, engine: PatchEngine) -> None:
        self.engine = engine
        self.ws = engine.workspace
        self._staged: dict[str, str | None] = {}  # None = deleted
        self._base: dict[str, str] = {}  # real checksum, recorded the first time a file is touched
        self._read: set[str] = set()
        self._binary: set[str] = set()
        self._staged_bytes = 0

    # -- paths and real files -----------------------------------------------------------------

    def _path(self, raw: object) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ToolError("a file path is required")
        try:
            path = normalize_relative_path(raw.strip().replace("\\", "/"))
        except PathValidationError as exc:
            raise ToolError(f"invalid path: {exc}") from None
        if self.engine.protection.is_protected(path):
            raise ToolError(f"{path} is protected and cannot be read or changed")
        return path

    def _real_exists(self, path: str) -> bool:
        return self.ws.kind(path) == "file"

    def _real_text(self, path: str) -> str:
        if path in self._binary:
            raise ToolError(f"{path} is not a text file")
        try:
            if len(self.ws.read_bytes(path)) > MAX_FILE_BYTES:
                raise ToolError(f"{path} is larger than {MAX_FILE_BYTES // 1000} KB")
            return self.ws.read_text(path)
        except NotTextFileError:
            self._binary.add(path)
            raise ToolError(f"{path} is not a text file") from None
        except CodegenError as exc:
            raise ToolError(f"cannot read {path}: {exc}") from None

    def exists(self, path: str) -> bool:
        if path in self._staged:
            return self._staged[path] is not None
        return self._real_exists(path)

    def _current(self, path: str) -> str:
        if path in self._staged:
            text = self._staged[path]
            if text is None:
                raise ToolError(f"{path} does not exist (it was deleted)")
            return text
        if not self._real_exists(path):
            raise ToolError(f"{path} does not exist")
        return self._real_text(path)

    def _touch(self, path: str) -> None:
        """Remember the real file's checksum before the first change, so conflicts are caught."""
        if path not in self._base and path not in self._staged and self._real_exists(path):
            checksum = self.ws.checksum(path)
            if checksum:
                self._base[path] = checksum
        if len(self._staged) >= MAX_TOUCHED and path not in self._staged:
            raise ToolError(f"too many files changed (limit {MAX_TOUCHED})")

    def _set(self, path: str, text: str | None) -> None:
        old = self._staged.get(path)
        self._staged_bytes += len(text or "") - len(old or "")
        if self._staged_bytes > MAX_STAGED_BYTES:
            raise ToolError("the staged changes are too large")
        self._staged[path] = text

    # -- reading ------------------------------------------------------------------------------

    def list_dir(self, prefix: str = "") -> str:
        prefix = prefix.strip().strip("/").replace("\\", "/")
        if prefix:
            prefix = self._path(prefix)
        base = prefix + "/" if prefix else ""
        dirs: dict[str, int] = {}
        files: list[str] = []
        for path in self._all_paths():
            if not path.startswith(base):
                continue
            rest = path[len(base) :]
            head, sep, _ = rest.partition("/")
            if sep:
                dirs[head] = dirs.get(head, 0) + 1
            else:
                files.append(head)
        if not dirs and not files:
            raise ToolError(f"no such folder or it is empty: {prefix or '.'}")
        lines = [f"{name}/  ({count} files)" for name, count in sorted(dirs.items())]
        lines += sorted(files)
        shown = lines[:200]
        more = f"\n... and {len(lines) - 200} more entries" if len(lines) > 200 else ""
        return f"{prefix or '.'}:\n" + "\n".join(shown) + more

    def _all_paths(self) -> list[str]:
        paths = {p for p in self.ws.iter_files() if p not in self._staged}
        paths |= {p for p, t in self._staged.items() if t is not None}
        return sorted(p for p in paths if not self.engine.protection.is_protected(p))

    def read(self, raw: object, start: object = None, end: object = None) -> str:
        path = self._path(raw)
        text = self._current(path)
        self._read.add(path)
        lines = text.split("\n")
        first = max(1, int(start)) if isinstance(start, int) else 1
        last = (
            min(len(lines), int(end))
            if isinstance(end, int)
            else min(len(lines), first + READ_LINES - 1)
        )
        if first > len(lines):
            raise ToolError(f"{path} has only {len(lines)} lines")
        chunk, used = [], 0
        for number in range(first, last + 1):
            row = f"{number:>5}| {lines[number - 1]}"
            used += len(row) + 1
            if used > READ_CHARS:
                last = number - 1
                break
            chunk.append(row)
        body = mask_secrets("\n".join(chunk))
        note = (
            f"\n(showing lines {first}-{last} of {len(lines)}; use start/end to see more)"
            if last < len(lines)
            else ""
        )
        return f"{path} ({len(lines)} lines)\n{body}{note}"

    def search(self, pattern: object, glob: object = None, regex: object = False) -> str:
        if not isinstance(pattern, str) or not pattern:
            raise ToolError("a search pattern is required")
        try:
            rx = re.compile(pattern if regex else re.escape(pattern), re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"bad regular expression: {exc}") from None
        hits: list[str] = []
        scanned = 0
        for path in self._all_paths():
            if (
                isinstance(glob, str)
                and glob
                and not fnmatch.fnmatch(path, glob)
                and not fnmatch.fnmatch(path.rsplit("/", 1)[-1], glob)
            ):
                continue
            scanned += 1
            if scanned > SEARCH_SCAN_LIMIT:
                hits.append("(stopped: too many files; narrow the search with a glob)")
                break
            try:
                text = self._current(path)
            except ToolError:
                continue
            for number, line in enumerate(text.split("\n"), 1):
                if rx.search(line):
                    hits.append(f"{path}:{number}: {mask_secrets(line.strip())[:180]}")
                    if len(hits) >= SEARCH_HITS:
                        break
            if len(hits) >= SEARCH_HITS:
                hits.append(f"(stopped after {SEARCH_HITS} matches; narrow the search)")
                break
        return "\n".join(hits) if hits else "no matches"

    # -- changing -----------------------------------------------------------------------------

    def edit(self, raw: object, old: object, new: object, replace_all: object = False) -> str:
        path = self._path(raw)
        if not isinstance(old, str) or not old:
            raise ToolError("'old' must be the exact text to replace")
        if not isinstance(new, str):
            raise ToolError("'new' must be text")
        text = self._current(path)
        count = text.count(old)
        if count == 0:
            raise ToolError(
                f"'old' was not found in {path}; read the file and copy the text exactly"
            )
        if count > 1 and not replace_all:
            raise ToolError(
                f"'old' appears {count} times in {path}; add surrounding text or set replace_all"
            )
        self._touch(path)
        self._set(path, text.replace(old, new) if replace_all else text.replace(old, new, 1))
        return f"edited {path} ({count if replace_all else 1} replacement)"

    def multi_edit(self, raw: object, edits: object) -> str:
        """Several exact replacements in one file, all or nothing."""
        path = self._path(raw)
        if not isinstance(edits, list) or not edits:
            raise ToolError("'edits' must be a non-empty list of {old, new}")
        if len(edits) > 60:
            raise ToolError("at most 60 edits per call")
        text = self._current(path)
        for index, item in enumerate(edits, 1):
            if not isinstance(item, dict):
                raise ToolError(f"edit {index} must be an object with 'old' and 'new'")
            old, new = item.get("old"), item.get("new")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ToolError(f"edit {index}: 'old' must be the exact text and 'new' text")
            count = text.count(old)
            if count == 0:
                raise ToolError(f"edit {index}: 'old' was not found in {path}; nothing was changed")
            if count > 1 and not item.get("replace_all"):
                raise ToolError(
                    f"edit {index}: 'old' appears {count} times; add surrounding text or set "
                    "replace_all; nothing was changed"
                )
            text = text.replace(old, new) if item.get("replace_all") else text.replace(old, new, 1)
        self._touch(path)
        self._set(path, text)
        return f"edited {path} ({len(edits)} replacements)"

    def write(self, raw: object, content: object) -> str:
        path = self._path(raw)
        if not isinstance(content, str):
            raise ToolError("'content' must be text")
        exists = self.exists(path)
        if exists and path not in self._read and path not in self._created_here():
            raise ToolError(
                f"{path} already exists; read it first, then use edit_file for small changes"
            )
        self._touch(path)
        self._set(path, content)
        return f"{'rewrote' if exists else 'created'} {path} ({len(content.splitlines())} lines)"

    def _created_here(self) -> set[str]:
        return {p for p, t in self._staged.items() if t is not None and p not in self._base}

    def delete(self, raw: object) -> str:
        path = self._path(raw)
        if not self.exists(path):
            raise ToolError(f"{path} does not exist")
        self._touch(path)
        self._set(path, None)
        return f"deleted {path}"

    def move(self, src_raw: object, dst_raw: object) -> str:
        src, dst = self._path(src_raw), self._path(dst_raw)
        text = self._current(src)
        if self.exists(dst):
            raise ToolError(f"{dst} already exists")
        self._touch(src)
        self._touch(dst)
        self._set(src, None)
        self._set(dst, text)
        return f"moved {src} -> {dst}"

    def rename_package(self, old: object, new: object) -> str:
        if not isinstance(old, str) or not isinstance(new, str):
            raise ToolError("'old' and 'new' must be package names")
        old, new = old.strip(), new.strip()
        for label, name in (("old", old), ("new", new)):
            problem = packages.validate_package(name)
            if problem:
                raise ToolError(f"{label} package: {problem}")
        if old == new:
            raise ToolError("the new package name is the same as the old one")
        if new.startswith(old + "."):
            raise ToolError("the new package cannot be inside the old one")
        rewritten = moved = 0
        for path in self._all_paths():
            if not packages.is_rewritable(path):
                continue
            try:
                text = self._current(path)
            except ToolError:
                continue
            new_text = packages.rename_text(text, old, new)
            target = packages.rename_path(path, old, new)
            if new_text == text and target == path:
                continue
            if target != path and self.exists(target):
                raise ToolError(f"cannot move {path}: {target} already exists")
            self._touch(path)
            if target != path:
                self._touch(target)
                self._set(path, None)
                moved += 1
            self._set(target, new_text)
            rewritten += new_text != text
        if not rewritten and not moved:
            raise ToolError(f"no file mentions the package {old}")
        firebase = self._register_firebase([old], new)
        left = [p for p in self._leftovers(old) if p not in firebase]
        note = f"; still mentioning {old} (not changed): {', '.join(left[:5])}" if left else ""
        extra = self._firebase_note(firebase, new)
        return f"renamed {old} -> {new}: {rewritten} files rewritten, {moved} moved{note}{extra}"

    def _leftovers(self, old: str) -> list[str]:
        """Text files that still mention the old package (e.g. a JSON service config)."""
        found = []
        for path in self._all_paths():
            try:
                text = self._current(path)
            except ToolError:
                continue
            if packages.mentions(text, old):
                found.append(path)
        return found

    def _register_firebase(self, old_ids: list[str], new: str) -> list[str]:
        """Give each google-services.json a client entry for ``new``
        so the renamed app still builds. Returns the files that were changed."""
        changed = []
        for path in self._all_paths():
            if path.rsplit("/", 1)[-1] != "google-services.json":
                continue
            try:
                text = self._current(path)
            except ToolError:
                continue
            updated = packages.add_firebase_client(text, new, old_ids)
            if updated is not None and updated != text:
                self._touch(path)
                self._set(path, updated)
                changed.append(path)
        return changed

    @staticmethod
    def _firebase_note(changed: list[str], new: str) -> str:
        if not changed:
            return ""
        return (
            f"; added a Firebase client entry for {new} to {', '.join(changed)} (a copy of the old "
            "one, so the app still builds: register the new package in the Firebase console and "
            "replace the file before relying on Firebase)"
        )

    def set_application_id(self, new: object) -> str:
        if not isinstance(new, str):
            raise ToolError("'application_id' must be text")
        problem = packages.validate_package(new.strip())
        if problem:
            raise ToolError(f"application id: {problem}")
        total = 0
        old_ids: list[str] = []
        for path in self._all_paths():
            name = path.rsplit("/", 1)[-1]
            if name not in ("build.gradle", "build.gradle.kts"):
                continue
            text = self._current(path)
            old_ids += packages.application_ids(text)
            replaced, count = packages.set_application_id(text, new.strip())
            if count and replaced != text:
                self._touch(path)
                self._set(path, replaced)
            total += count
        if not total:
            raise ToolError("no applicationId was found in any build.gradle(.kts) file")
        firebase = self._register_firebase(old_ids, new.strip())
        return (
            f"set applicationId to {new.strip()} in {total} place(s); "
            "source packages were not changed" + self._firebase_note(firebase, new.strip())
        )

    # -- a read-only view of the edited project, for checks.ProjectView ---------------------------

    def paths(self) -> list[str]:
        return self._all_paths()

    def text(self, path: str) -> str | None:
        """The file as it is now (unmasked), or None if it is binary, huge or missing."""
        try:
            return self._current(path)
        except ToolError:
            return None

    def changed(self) -> set[str]:
        return {c.path for c in self.changes()}

    # -- results ------------------------------------------------------------------------------

    def changes(self) -> list[StagedChange]:
        out: list[StagedChange] = []
        for path in sorted(self._staged):
            text = self._staged[path]
            real = self._real_exists(path)
            if text is None:
                if real:
                    out.append(StagedChange("delete", path, None, self._base.get(path)))
            elif not real:
                out.append(StagedChange("create", path, text, None))
            elif text != self._real_text(path):
                out.append(StagedChange("modify", path, text, self._base.get(path)))
        return out

    def summary(self) -> str:
        changes = self.changes()
        if not changes:
            return "no changes staged yet"
        shown = [f"{c.action} {c.path}" for c in changes[:25]]
        more = f" (+{len(changes) - 25} more)" if len(changes) > 25 else ""
        return f"{len(changes)} staged change(s): " + "; ".join(shown) + more
