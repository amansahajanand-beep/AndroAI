"""Checkpoints, tracked patch application and manual-change-safe restore.

All AI writes should go through :class:`CheckpointManager`. Anything that changes the
workspace without going through it is, by definition, a manual change, and is recorded as such
the next time the manager runs. That is what lets ``restore`` leave manual work alone.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from androai_codegen.editing.checksum import sha256_hex
from androai_codegen.editing.engine import PatchEngine
from androai_codegen.editing.errors import WorkspaceBusyError
from androai_codegen.editing.fsio import atomic_write_bytes
from androai_codegen.editing.models import (
    ApplyResult,
    CreateFile,
    DeleteFile,
    FileChange,
    ModifyFile,
    PatchSet,
)

from .errors import CheckpointNotFoundError, RestoreConflict, TrackingError, VcsError
from .models import (
    ChangeSummary,
    Checkpoint,
    DiffResult,
    HistoryEntry,
    PathChange,
    RestoreConflictItem,
    RestoreResult,
    SnapshotInfo,
    TrackedApply,
)
from .protocol import VersionControl
from .shadow_git import ShadowGit

_CHECKPOINT_ID = re.compile(r"^[0-9a-f]{32}$")


class CheckpointManager:
    def __init__(
        self,
        engine: PatchEngine,
        *,
        vcs: VersionControl | None = None,
        git_dir: str | Path | None = None,
    ) -> None:
        self.engine = engine
        self.vcs: VersionControl = vcs or ShadowGit(
            engine.workspace,
            git_dir if git_dir is not None else engine.journal.root / "vcs",
            protection=engine.protection,
        )
        self._checkpoint_dir = engine.journal.root / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # -- locking ------------------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        # Order is always vcs lock -> engine lock (the engine takes its own inside apply).
        lock = FileLock(str(self.engine.journal.root / ".vcs.lock"), timeout=0)
        try:
            lock.acquire()
        except Timeout as exc:
            raise WorkspaceBusyError("another version-control operation is running") from exc
        try:
            yield
        finally:
            lock.release()

    # -- recording state ----------------------------------------------------------------

    def _ensure_baseline(self) -> SnapshotInfo | None:
        self.vcs.init()
        if self.vcs.head() is not None:
            return None
        return self.vcs.snapshot(origin="baseline", description="initial workspace state")

    def _sync_manual(self, run_id: str | None, task_id: str | None) -> SnapshotInfo | None:
        """Record changes nobody told us about as manual, so they are never mistaken for AI's."""
        return self.vcs.snapshot(
            origin="manual",
            description="changes made outside AndroAI",
            run_id=run_id,
            task_id=task_id,
        )

    def ensure_baseline(self) -> SnapshotInfo | None:
        """Record the initial workspace state. Idempotent; other operations call it too."""
        with self._lock():
            return self._ensure_baseline()

    def pending_changes(self) -> list[PathChange]:
        """Changes made since the last recorded state (i.e. manual edits)."""
        with self._lock():
            self._ensure_baseline()
            return self.vcs.pending_changes()

    # -- tracked apply ------------------------------------------------------------------

    def _record_ai_snapshot(
        self,
        origin: str,
        result: ApplyResult,
        run_id: str,
        task_id: str,
        description: str,
    ) -> tuple[SnapshotInfo | None, list[str]]:
        """Snapshot only the files the engine wrote, and only if they are still as written."""
        verified: list[str] = []
        warnings: list[str] = []
        for record in result.records:
            if self.engine.workspace.checksum(record.path) == record.new_checksum:
                verified.append(record.path)
            else:
                warnings.append(
                    f"{record.path} changed again right after the patch; "
                    "left unrecorded so it is treated as a manual change"
                )
        snapshot = self.vcs.snapshot(
            origin=origin,  # type: ignore[arg-type]
            description=description,
            run_id=run_id,
            task_id=task_id,
            patch_id=result.patch_id,
            paths=verified,
        )
        return snapshot, warnings

    def apply(self, patch: PatchSet, approved_deletions: Iterable[str] = ()) -> TrackedApply:
        """Apply ``patch`` via the engine, then record it as an AI change.

        Manual edits made before the patch are recorded first, as manual. Raises whatever the
        engine raises (nothing is recorded as AI in that case), or :class:`TrackingError` if the
        patch was applied but could not be recorded.
        """
        with self._lock():
            self._ensure_baseline()
            manual = self._sync_manual(patch.run_id, patch.task_id)
            result = self.engine.apply(patch, approved_deletions)
            try:
                snapshot, warnings = self._record_ai_snapshot(
                    "ai", result, patch.run_id, patch.task_id, patch.description
                )
            except VcsError as exc:
                raise TrackingError(
                    f"patch {result.patch_id} was applied but could not be recorded: {exc}",
                    result,
                ) from exc
            return TrackedApply(
                result=result, ai_snapshot=snapshot, manual_snapshot=manual, warnings=warnings
            )

    # -- checkpoints --------------------------------------------------------------------

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID.fullmatch(checkpoint_id):
            raise CheckpointNotFoundError(f"invalid checkpoint id: {checkpoint_id!r}")
        return self._checkpoint_dir / f"{checkpoint_id}.json"

    def checkpoint(
        self, label: str, *, run_id: str | None = None, task_id: str | None = None
    ) -> Checkpoint:
        """Mark the current state so it can be diffed against or restored later.

        Pending manual edits are recorded first, so the checkpoint reflects the true state and
        they are attributed to the user rather than to whatever the AI does next.
        """
        with self._lock():
            self._ensure_baseline()
            manual = self._sync_manual(run_id, task_id)
            commit = self.vcs.head()
            assert commit is not None
            checkpoint = Checkpoint(
                id=uuid.uuid4().hex,
                label=" ".join(label.split())[:200] or "checkpoint",
                commit=commit,
                run_id=run_id,
                task_id=task_id,
                created_at=datetime.now(UTC),
                manual_commit=manual.commit if manual else None,
            )
            atomic_write_bytes(
                self._checkpoint_path(checkpoint.id), checkpoint.model_dump_json().encode("utf-8")
            )
            return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        path = self._checkpoint_path(checkpoint_id)
        if not path.is_file():
            raise CheckpointNotFoundError(f"no such checkpoint: {checkpoint_id}")
        return Checkpoint.model_validate_json(path.read_bytes())

    def list_checkpoints(self) -> list[Checkpoint]:
        found = [
            Checkpoint.model_validate_json(p.read_bytes())
            for p in self._checkpoint_dir.glob("*.json")
        ]
        return sorted(found, key=lambda c: c.created_at)

    # -- reading history ----------------------------------------------------------------

    def diff_since(
        self, checkpoint_id: str, *, paths: Iterable[str] | None = None, mask: bool = True
    ) -> DiffResult:
        """Diff from a checkpoint to the workspace now (includes unrecorded manual edits)."""
        checkpoint = self.get_checkpoint(checkpoint_id)
        with self._lock():
            self._ensure_baseline()
            return self.vcs.diff(checkpoint.commit, None, paths=paths, mask=mask)

    def summary_since(self, checkpoint_id: str) -> ChangeSummary:
        checkpoint = self.get_checkpoint(checkpoint_id)
        with self._lock():
            self._ensure_baseline()
            return self.vcs.summary(checkpoint.commit, None)

    def file_history(self, path: str, limit: int = 50) -> list[HistoryEntry]:
        """Who changed this file and when (AI vs manual), newest first."""
        with self._lock():
            self._ensure_baseline()
            self._sync_manual(None, None)  # so very recent manual edits show up
            return self.vcs.file_history(path, limit)

    # -- restore ------------------------------------------------------------------------

    def restore(
        self,
        checkpoint_id: str,
        *,
        run_id: str,
        task_id: str,
        skip_conflicts: bool = False,
    ) -> RestoreResult:
        """Undo what the AI changed since ``checkpoint_id``, without touching manual work.

        Only files the AI changed since the checkpoint are restored, to their content at the
        checkpoint. Files changed only manually are left alone. If a file was changed by both,
        restoring it would lose the manual change, so by default nothing is touched and
        :class:`RestoreConflict` is raised; with ``skip_conflicts`` those files are kept as
        they are and the rest are restored.
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        with self._lock():
            self._ensure_baseline()
            self._sync_manual(run_id, task_id)

            ai_paths: set[str] = set()
            manual_paths: set[str] = set()
            for commit in self.vcs.commits_between(checkpoint.commit):
                bucket = ai_paths if commit.origin in ("ai", "rollback") else manual_paths
                bucket.update(change.path for change in commit.changes)

            conflicts = [
                RestoreConflictItem(path=p, reason="also changed manually after the checkpoint")
                for p in sorted(ai_paths & manual_paths)
            ]
            if conflicts and not skip_conflicts:
                raise RestoreConflict(conflicts)

            changes: list[FileChange] = []
            deletions: list[str] = []
            for path in sorted(ai_paths - manual_paths):
                desired = self.vcs.read_blob(checkpoint.commit, path)
                current = (
                    self.engine.workspace.read_bytes(path)
                    if self.engine.workspace.kind(path) == "file"
                    else None
                )
                if desired == current:
                    continue
                description = f"restore {path} to checkpoint {checkpoint.label!r}"
                try:
                    desired_text = None if desired is None else desired.decode("utf-8")
                    if current is not None:
                        current.decode("utf-8")
                except UnicodeDecodeError:
                    conflicts.append(
                        RestoreConflictItem(path=path, reason="not a text file; cannot restore")
                    )
                    continue
                if desired_text is not None and current is not None:
                    changes.append(
                        ModifyFile(
                            path=path,
                            expected_checksum=sha256_hex(current),
                            content=desired_text,
                            normalize_eol=False,
                            description=description,
                        )
                    )
                elif desired_text is not None:
                    changes.append(
                        CreateFile(path=path, content=desired_text, description=description)
                    )
                else:
                    assert current is not None
                    changes.append(
                        DeleteFile(
                            path=path,
                            expected_checksum=sha256_hex(current),
                            description=description,
                        )
                    )
                    # Safe to auto-approve: the file did not exist at the checkpoint, only the
                    # AI changed it since, and nobody edited it by hand (checked above).
                    deletions.append(path)

            if conflicts and not skip_conflicts:
                raise RestoreConflict(conflicts)
            if not changes:
                return RestoreResult(checkpoint_id=checkpoint.id, conflicts=conflicts)

            description = f"restore checkpoint {checkpoint.label!r}"
            result = self.engine.apply(
                PatchSet(
                    project_id=self.engine.project_id,
                    run_id=run_id,
                    task_id=task_id,
                    description=description,
                    changes=changes,
                ),
                approved_deletions=deletions,
            )
            try:
                snapshot, _warnings = self._record_ai_snapshot(
                    "rollback", result, run_id, task_id, description
                )
            except VcsError as exc:
                raise TrackingError(
                    f"restore patch {result.patch_id} was applied but could not be recorded: {exc}",
                    result,
                ) from exc
            return RestoreResult(
                checkpoint_id=checkpoint.id,
                patch_id=result.patch_id,
                restored=[record.path for record in result.records],
                conflicts=conflicts,
                snapshot=snapshot,
            )
