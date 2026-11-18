"""The patch engine: validate, apply atomically, roll back, recover.

Safety properties (each covered by tests):

* **All-or-nothing.** A patch is fully validated in memory first. Writes happen only if there
  are no blocking problems; if any write fails, every file already written is restored.
* **No silent overwrite of user edits.** Modify/delete need the checksum the author read;
  a mismatch is a ``conflict`` and blocks the whole patch. Rollback refuses to overwrite
  files that changed after the patch (it never discards later changes).
* **Crash recovery.** Pre-images and a manifest are persisted before the first write, so an
  interrupted apply can be undone with ``recover()``.
* **Isolation.** The engine is bound to one project id; patches for another project, paths
  outside the workspace, symlinks, ``.git`` and protected files are rejected.
* **Approval for destructive changes.** Deletions need explicit per-path approval.
"""

from __future__ import annotations

import contextlib
import difflib
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock, Timeout

from .checksum import sha256_hex
from .errors import (
    PatchApplyError,
    PatchRejected,
    PatchStateError,
    PathValidationError,
    ProtectedFileError,
    RollbackConflict,
    WorkspaceBusyError,
)
from .journal import Journal
from .models import (
    ApplyResult,
    ChangeRecord,
    CreateFile,
    DeleteFile,
    FileSnapshot,
    JournalEntry,
    JournalManifest,
    ModifyFile,
    PatchPreview,
    PatchSet,
    PlannedChange,
    Problem,
    ProblemCode,
    RecoveryReport,
    RollbackResult,
    Simulation,
    TextEdit,
    utcnow,
)
from .paths import normalize_relative_path
from .policy import DEFAULT_POLICY, ProtectionPolicy
from .redact import REDACTION_MARKER, count_redaction_markers, mask_secrets
from .workspace import Workspace

DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_FILES = 500


@dataclass(frozen=True)
class _Op:
    """One filesystem transition. ``None`` means 'file does not exist'."""

    path: str
    before: bytes | None
    after: bytes | None


@dataclass
class _Plan:
    problems: list[Problem] = field(default_factory=list)
    ops: list[_Op] = field(default_factory=list)
    planned: list[PlannedChange] = field(default_factory=list)  # parallel to ``ops``
    diffs: list[str] = field(default_factory=list)

    def problem(
        self, code: ProblemCode, path: str | None, message: str, *, blocking: bool = True
    ) -> None:
        self.problems.append(Problem(code=code, path=path, message=message, blocking=blocking))

    def to_preview(self) -> PatchPreview:
        return PatchPreview(problems=self.problems, planned=self.planned, diff="".join(self.diffs))


# --- text helpers ----------------------------------------------------------------------


def _dominant_eol(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _match_eol(snippet: str, eol: str) -> str:
    """Give ``snippet`` the file's line endings, unless it already mixes in carriage returns."""
    if eol == "\r\n" and "\r" not in snippet:
        return snippet.replace("\n", "\r\n")
    return snippet


def _apply_edits(text: str, edits: list[TextEdit]) -> tuple[str | None, ProblemCode | None, str]:
    """Apply edits in order; each later edit sees the result of the earlier ones."""
    eol = _dominant_eol(text)
    for index, edit in enumerate(edits, start=1):
        old = _match_eol(edit.old, eol)
        new = _match_eol(edit.new, eol)
        count = text.count(old)
        if count == 0:
            return None, ProblemCode.EDIT_NOT_FOUND, f"edit {index}: text to replace not found"
        if count > 1 and not edit.replace_all:
            return (
                None,
                ProblemCode.EDIT_AMBIGUOUS,
                f"edit {index}: text matches {count} places; add context or set replace_all",
            )
        text = text.replace(old, new) if edit.replace_all else text.replace(old, new, 1)
    return text, None, ""


def _diff_lines(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n\\ No newline at end of file\n"
    return lines


def _unified_diff(path: str, before: bytes | None, after: bytes | None) -> str:
    """Informational unified diff (for review and audit, not guaranteed ``git apply``-able)."""
    try:
        old = None if before is None else before.decode("utf-8")
        new = None if after is None else after.decode("utf-8")
    except UnicodeDecodeError:
        return f"Binary file {path} changed\n"
    return "".join(
        difflib.unified_diff(
            [] if old is None else _diff_lines(old),
            [] if new is None else _diff_lines(new),
            fromfile="/dev/null" if old is None else f"a/{path}",
            tofile="/dev/null" if new is None else f"b/{path}",
        )
    )


# --- engine ----------------------------------------------------------------------------


class PatchEngine:
    """Applies :class:`PatchSet` objects to one project's :class:`Workspace`."""

    def __init__(
        self,
        project_id: str,
        workspace: Workspace,
        journal_dir: str | Path,
        *,
        protection: ProtectionPolicy = DEFAULT_POLICY,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        journal_root = Path(journal_dir).resolve()
        if journal_root.is_relative_to(workspace.root) or workspace.root.is_relative_to(
            journal_root
        ):
            raise ValueError("journal directory and workspace must not contain each other")
        self.project_id = project_id
        self.workspace = workspace
        self.protection = protection
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.journal = Journal(journal_root, project_id)

    # -- reading ------------------------------------------------------------------------

    def snapshot(self, paths: list[str]) -> dict[str, str | None]:
        """Checksums to record when a task starts; pass them back as ``expected_checksum``."""
        return self.workspace.snapshot(paths)

    def read_file(self, path: str) -> FileSnapshot:
        """Raw read for the engine's own callers (not for LLM prompts; see ``read_for_llm``)."""
        rel = normalize_relative_path(path)
        data = self.workspace.read_bytes(rel)
        return FileSnapshot(
            path=rel, content=self.workspace.read_text(rel), checksum=sha256_hex(data)
        )

    def read_for_llm(self, path: str) -> FileSnapshot:
        """Read a file for use in an LLM prompt: protected files refused, secrets masked.

        ``checksum`` is still the checksum of the real file, so it can be used as
        ``expected_checksum`` later.
        """
        rel = normalize_relative_path(path)
        if self.protection.is_protected(rel):
            raise ProtectedFileError(f"{rel} is protected and cannot be shown to an LLM")
        snapshot = self.read_file(rel)
        return snapshot.model_copy(update={"content": mask_secrets(snapshot.content)})

    # -- planning -----------------------------------------------------------------------

    def preview(self, patch: PatchSet, approved_deletions: Iterable[str] = ()) -> PatchPreview:
        """Validate without writing anything. Safe to call at any time."""
        return self._plan(patch, approved_deletions).to_preview()

    def simulate(self, patch: PatchSet, approved_deletions: Iterable[str] = ()) -> Simulation:
        """Like :meth:`preview`, but also returns the resulting text of every changed file.

        Lets a reviewer inspect the project *as it would be after the patch* without writing
        anything. Deleted files map to ``None``.
        """
        plan = self._plan(patch, approved_deletions)
        files = {op.path: None if op.after is None else op.after.decode("utf-8") for op in plan.ops}
        return Simulation(preview=plan.to_preview(), files=files)

    def _plan(self, patch: PatchSet, approved_deletions: Iterable[str]) -> _Plan:
        plan = _Plan()
        if patch.project_id != self.project_id:
            plan.problem(
                ProblemCode.PROJECT_MISMATCH,
                None,
                f"patch is for project {patch.project_id!r}, engine is bound to "
                f"{self.project_id!r}",
            )
            return plan
        if len(patch.changes) > self.max_files:
            plan.problem(
                ProblemCode.TOO_MANY_FILES,
                None,
                f"patch changes {len(patch.changes)} files; the limit is {self.max_files}",
            )
            return plan

        approved: set[str] = set()
        for raw in approved_deletions:
            with contextlib.suppress(PathValidationError):
                approved.add(normalize_relative_path(raw))

        seen: set[str] = set()
        for change in patch.changes:
            try:
                rel = normalize_relative_path(change.path)
            except PathValidationError as exc:
                plan.problem(ProblemCode.PATH_INVALID, change.path, str(exc))
                continue
            if rel in seen:
                plan.problem(ProblemCode.DUPLICATE_PATH, rel, "path appears more than once")
                continue
            seen.add(rel)
            if self.protection.is_protected(rel):
                plan.problem(ProblemCode.PROTECTED_FILE, rel, "file is protected")
                continue
            try:
                kind = self.workspace.kind(rel)
                if kind in ("dir", "other"):
                    plan.problem(ProblemCode.PATH_INVALID, rel, "not a regular file")
                    continue
                before = self.workspace.read_bytes(rel) if kind == "file" else None
            except PathValidationError as exc:
                plan.problem(ProblemCode.PATH_INVALID, rel, str(exc))
                continue
            except OSError as exc:
                plan.problem(ProblemCode.IO_ERROR, rel, f"cannot read file: {exc}")
                continue

            if isinstance(change, CreateFile):
                self._plan_create(plan, change, rel, before)
            elif isinstance(change, ModifyFile):
                self._plan_modify(plan, change, rel, before)
            elif isinstance(change, DeleteFile):
                self._plan_delete(plan, change, rel, before, rel in approved)
        return plan

    def _accept(
        self,
        plan: _Plan,
        rel: str,
        change_type: str,
        before: bytes | None,
        after: bytes | None,
        description: str,
    ) -> None:
        if after is not None and len(after) > self.max_file_bytes:
            plan.problem(
                ProblemCode.TOO_LARGE,
                rel,
                f"result is {len(after)} bytes; the limit is {self.max_file_bytes}",
            )
            return
        plan.ops.append(_Op(rel, before, after))
        plan.planned.append(
            PlannedChange(
                path=rel,
                change_type=change_type,  # type: ignore[arg-type]
                previous_checksum=None if before is None else sha256_hex(before),
                new_checksum=None if after is None else sha256_hex(after),
                description=description,
            )
        )
        plan.diffs.append(_unified_diff(rel, before, after))

    def _plan_create(self, plan: _Plan, change: CreateFile, rel: str, before: bytes | None) -> None:
        if before is not None:
            plan.problem(
                ProblemCode.ALREADY_EXISTS,
                rel,
                "file already exists (created by someone else since the task started?)",
            )
            return
        if count_redaction_markers(change.content):
            plan.problem(
                ProblemCode.REDACTION_MARKER,
                rel,
                f"content contains {REDACTION_MARKER}; masked secrets must not be written",
            )
            return
        try:
            after = change.content.encode("utf-8")
        except UnicodeEncodeError:
            plan.problem(ProblemCode.NOT_TEXT, rel, "content is not valid text")
            return
        self._accept(plan, rel, "create", None, after, change.description)

    def _plan_modify(self, plan: _Plan, change: ModifyFile, rel: str, before: bytes | None) -> None:
        if before is None:
            plan.problem(ProblemCode.MISSING_FILE, rel, "file does not exist")
            return
        actual = sha256_hex(before)
        if actual != change.expected_checksum:
            plan.problem(
                ProblemCode.CONFLICT,
                rel,
                "file changed since it was read "
                f"(expected {change.expected_checksum[:12]}, found {actual[:12]}); "
                "resolve the conflict instead of overwriting",
            )
            return
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError:
            plan.problem(ProblemCode.NOT_TEXT, rel, "existing file is not UTF-8 text")
            return

        if change.edits:
            new_text, code, message = _apply_edits(text, change.edits)
            if new_text is None:
                assert code is not None
                plan.problem(code, rel, message)
                return
            supplied = "".join(edit.new for edit in change.edits)
        else:
            assert change.content is not None
            new_text = (
                _match_eol(change.content, _dominant_eol(text))
                if change.normalize_eol
                else change.content
            )
            supplied = change.content

        if count_redaction_markers(supplied) > count_redaction_markers(text):
            plan.problem(
                ProblemCode.REDACTION_MARKER,
                rel,
                f"change introduces {REDACTION_MARKER}; masked secrets must not be written",
            )
            return
        try:
            after = new_text.encode("utf-8")
        except UnicodeEncodeError:
            plan.problem(ProblemCode.NOT_TEXT, rel, "new content is not valid text")
            return
        if after == before:
            plan.problem(
                ProblemCode.NO_CHANGE, rel, "edit leaves the file unchanged", blocking=False
            )
            return
        self._accept(plan, rel, "modify", before, after, change.description)

    def _plan_delete(
        self,
        plan: _Plan,
        change: DeleteFile,
        rel: str,
        before: bytes | None,
        approved: bool,
    ) -> None:
        if before is None:
            plan.problem(ProblemCode.MISSING_FILE, rel, "file does not exist")
            return
        actual = sha256_hex(before)
        if actual != change.expected_checksum:
            plan.problem(
                ProblemCode.CONFLICT,
                rel,
                f"file changed since it was read (expected {change.expected_checksum[:12]}, "
                f"found {actual[:12]}); refusing to delete",
            )
            return
        if not approved:
            plan.problem(
                ProblemCode.APPROVAL_REQUIRED, rel, "deleting a file requires explicit approval"
            )
            return
        self._accept(plan, rel, "delete", before, None, change.description)

    # -- locking ------------------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock = FileLock(str(self.journal.root / ".lock"), timeout=0)
        try:
            lock.acquire()
        except Timeout as exc:
            raise WorkspaceBusyError(
                "another operation holds the workspace lock; retry later"
            ) from exc
        try:
            yield
        finally:
            lock.release()

    # -- executing ----------------------------------------------------------------------

    def _current(self, path: str) -> bytes | None:
        return self.workspace.read_bytes(path) if self.workspace.kind(path) == "file" else None

    def _execute(self, ops: list[_Op]) -> None:
        for op in ops:
            if op.after is None:
                self.workspace.delete(op.path)
            else:
                self.workspace.write_bytes(op.path, op.after)

    def _undo(self, ops: list[_Op]) -> list[str]:
        """Restore every op's ``before`` state. Returns paths that could not be restored."""
        failed: list[str] = []
        for op in reversed(ops):
            try:
                if self._current(op.path) == op.before:
                    continue
                if op.before is None:
                    self.workspace.delete(op.path)
                else:
                    self.workspace.write_bytes(op.path, op.before)
            except Exception:
                failed.append(op.path)
        return failed

    def _missing_dirs(self, ops: list[_Op]) -> list[str]:
        dirs: list[str] = []
        for op in ops:
            if op.before is None and op.after is not None:
                for directory in self.workspace.missing_dirs(op.path):
                    if directory not in dirs:
                        dirs.append(directory)
        return sorted(dirs, key=lambda d: d.count("/"))

    # -- public operations --------------------------------------------------------------

    def apply(self, patch: PatchSet, approved_deletions: Iterable[str] = ()) -> ApplyResult:
        """Validate and apply ``patch`` atomically.

        Raises :class:`PatchRejected` (nothing changed) for blocking problems, and
        :class:`PatchApplyError` if the filesystem failed mid-way (``rolled_back`` says
        whether the workspace was restored).
        """
        with self._lock():
            plan = self._plan(patch, approved_deletions)
            preview = plan.to_preview()
            if preview.blocking_problems or not plan.ops:
                raise PatchRejected(preview)

            patch_id = uuid.uuid4().hex
            entries = [
                JournalEntry(
                    **planned.model_dump(),
                    preimage=f"pre/{index}" if op.before is not None else None,
                )
                for index, (planned, op) in enumerate(zip(plan.planned, plan.ops, strict=True))
            ]
            manifest = JournalManifest(
                patch_id=patch_id,
                project_id=self.project_id,
                run_id=patch.run_id,
                task_id=patch.task_id,
                description=patch.description,
                status="applying",
                entries=entries,
                created_dirs=self._missing_dirs(plan.ops),
            )
            preimages = {i: op.before for i, op in enumerate(plan.ops) if op.before is not None}
            try:
                self.journal.begin(manifest, preimages, preview.diff)
            except OSError as exc:
                raise PatchApplyError(
                    f"could not write the journal; nothing was changed: {exc}",
                    rolled_back=True,
                ) from exc

            finished = utcnow()
            try:
                self._execute(plan.ops)
                self.journal.set_status(patch_id, "applied", finished)
            except BaseException as exc:
                failed = self._undo(plan.ops)
                self.workspace.remove_empty_dirs(manifest.created_dirs)
                with contextlib.suppress(Exception):
                    self.journal.set_status(
                        patch_id, "needs_attention" if failed else "rolled_back", utcnow()
                    )
                if isinstance(exc, Exception):
                    raise PatchApplyError(
                        f"apply failed: {exc}", rolled_back=not failed, failed_paths=failed
                    ) from exc
                raise

            records = [self._record(manifest, entry, finished) for entry in entries]
            return ApplyResult(
                patch_id=patch_id,
                records=records,
                diff=preview.diff,
                diff_reference=f"journal:{patch_id}/diff.patch",
            )

    def rollback(self, patch_id: str) -> RollbackResult:
        """Undo an applied patch, unless that would overwrite changes made after it.

        Raises :class:`RollbackConflict` (nothing changed) if any touched file no longer
        matches the state the patch left it in.
        """
        with self._lock():
            manifest = self.journal.load(patch_id)
            if manifest.status != "applied":
                raise PatchStateError(
                    f"patch {patch_id} is {manifest.status!r}; only applied patches roll back"
                )
            ops: list[_Op] = []
            conflicts: list[Problem] = []
            for entry in manifest.entries:
                if self.workspace.kind(entry.path) not in ("file", "missing"):
                    conflicts.append(
                        Problem(
                            code=ProblemCode.CONFLICT,
                            path=entry.path,
                            message="path is no longer a regular file",
                        )
                    )
                    continue
                current = self._current(entry.path)
                current_sum = None if current is None else sha256_hex(current)
                if current_sum == entry.previous_checksum:
                    continue  # already back at the original state
                if current_sum != entry.new_checksum:
                    conflicts.append(
                        Problem(
                            code=ProblemCode.CONFLICT,
                            path=entry.path,
                            message="changed after the patch was applied; "
                            "rolling back would discard that change",
                        )
                    )
                    continue
                original = (
                    None if entry.preimage is None else self.journal.read_preimage(patch_id, entry)
                )
                ops.append(_Op(entry.path, current, original))
            if conflicts:
                raise RollbackConflict(conflicts)

            try:
                self._execute(ops)
            except BaseException as exc:
                failed = self._undo(ops)
                if isinstance(exc, Exception):
                    raise PatchApplyError(
                        f"rollback failed: {exc}", rolled_back=not failed, failed_paths=failed
                    ) from exc
                raise
            self.workspace.remove_empty_dirs(manifest.created_dirs)
            self.journal.set_status(patch_id, "rolled_back", utcnow())
            return RollbackResult(patch_id=patch_id, restored_paths=[op.path for op in ops])

    def recover(self) -> RecoveryReport:
        """Undo patches left in ``applying`` state by a crash. Call at worker start-up.

        A patch is restored only if every file is either untouched or exactly in the state
        the patch would have written. Anything else is reported, never overwritten.
        """
        report = RecoveryReport()
        with self._lock():
            for manifest in self.journal.list_patches():
                if manifest.status != "applying":
                    continue
                ops: list[_Op] = []
                problems: list[Problem] = []
                for entry in manifest.entries:
                    current = self._current(entry.path)
                    current_sum = None if current is None else sha256_hex(current)
                    if current_sum == entry.previous_checksum:
                        continue
                    if current_sum == entry.new_checksum:
                        original = (
                            None
                            if entry.preimage is None
                            else self.journal.read_preimage(manifest.patch_id, entry)
                        )
                        ops.append(_Op(entry.path, current, original))
                    else:
                        problems.append(
                            Problem(
                                code=ProblemCode.CONFLICT,
                                path=entry.path,
                                message="neither original nor patched content; left untouched",
                            )
                        )
                if not problems:
                    try:
                        self._execute(ops)
                    except Exception as exc:
                        problems.append(
                            Problem(code=ProblemCode.IO_ERROR, message=f"recovery failed: {exc}")
                        )
                if problems:
                    self.journal.set_status(manifest.patch_id, "needs_attention", utcnow())
                    report.needs_attention[manifest.patch_id] = problems
                else:
                    self.workspace.remove_empty_dirs(manifest.created_dirs)
                    self.journal.set_status(manifest.patch_id, "rolled_back", utcnow())
                    report.recovered.append(manifest.patch_id)
        return report

    # -- history ------------------------------------------------------------------------

    @staticmethod
    def _record(manifest: JournalManifest, entry: JournalEntry, applied_at) -> ChangeRecord:
        return ChangeRecord(
            patch_id=manifest.patch_id,
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            task_id=manifest.task_id,
            path=entry.path,
            change_type=entry.change_type,
            previous_checksum=entry.previous_checksum,
            new_checksum=entry.new_checksum,
            description=entry.description,
            applied_at=applied_at,
        )

    def history(self, path: str) -> list[ChangeRecord]:
        """Applied (not rolled back) changes to ``path``, oldest first."""
        rel = normalize_relative_path(path)
        return [
            self._record(manifest, entry, manifest.finished_at or manifest.created_at)
            for manifest in self.journal.list_patches()
            if manifest.status == "applied"
            for entry in manifest.entries
            if entry.path == rel
        ]

    def list_patches(self) -> list[JournalManifest]:
        return self.journal.list_patches()
