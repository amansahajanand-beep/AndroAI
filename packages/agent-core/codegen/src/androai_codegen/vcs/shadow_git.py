"""Shadow git repository: checkpoints and history without touching the project's own git.

The repository lives outside the workspace (``git --git-dir=<elsewhere> --work-tree=<workspace>``).
The project's own ``.git``, branch, index, hooks and config are never read or modified, and it
works the same whether or not the workspace is itself a git repository.

Hardening (each covered by tests):

* Inherited ``GIT_*`` environment variables are dropped and global/system config is disabled,
  so ambient settings cannot redirect or change behaviour.
* Hooks are disabled, and ``info/attributes`` overrides any ``.gitattributes`` in the (untrusted)
  workspace, so no line-ending/filter conversion alters stored bytes.
* Protected files (keys, ``.env``...), oversized files, symlinks and unsafe paths are never
  staged, so secrets are not copied into a second location or shown in diffs.
* Commit metadata is written by this class only; free text is single-line and sanitized, and
  only the final paragraph is parsed, so a description cannot forge an origin.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from androai_codegen.editing.errors import PathValidationError
from androai_codegen.editing.paths import normalize_relative_path
from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.redact import mask_secrets
from androai_codegen.editing.workspace import Workspace

from .errors import GitCommandError, GitNotAvailableError
from .models import (
    ORIGINS,
    ChangeStatus,
    ChangeSummary,
    CommitChanges,
    DiffResult,
    FileSummary,
    HistoryEntry,
    Origin,
    PathChange,
    SkippedPath,
    SnapshotInfo,
)

DEFAULT_MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_DIFF_BYTES = 1024 * 1024

_AI_IDENTITY = ("AndroAI Agent", "agent@androai.invalid")
_USER_IDENTITY = ("Workspace User", "workspace-user@androai.invalid")  # not a real person

_DEFAULT_EXCLUDES = (
    ".gradle/",
    "build/",
    ".idea/",
    ".cxx/",
    ".externalNativeBuild/",
    "captures/",
    "*.apk",
    "*.aab",
    "*.iml",
    ".DS_Store",
)

_COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")
_TRAILERS = {
    "AndroAI-Origin": "origin",
    "AndroAI-Run": "run_id",
    "AndroAI-Task": "task_id",
    "AndroAI-Patch": "patch_id",
}
_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "modified"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _oneline(text: str, limit: int = 200) -> str:
    return _CONTROL.sub(" ", text).strip()[:limit]


def _build_message(
    origin: str,
    description: str,
    run_id: str | None,
    task_id: str | None,
    patch_id: str | None,
) -> str:
    lines = [f"{origin}: {_oneline(description)}", "", f"AndroAI-Origin: {origin}"]
    if run_id:
        lines.append(f"AndroAI-Run: {_oneline(run_id, 128)}")
    if task_id:
        lines.append(f"AndroAI-Task: {_oneline(task_id, 128)}")
    if patch_id:
        lines.append(f"AndroAI-Patch: {_oneline(patch_id, 128)}")
    return "\n".join(lines) + "\n"


def _parse_message(body: str) -> tuple[str, dict[str, str]]:
    """Return (subject, metadata). Only the last paragraph is trusted for metadata."""
    paragraphs = body.strip("\n").split("\n\n")
    subject = paragraphs[0].splitlines()[0] if paragraphs and paragraphs[0] else ""
    meta: dict[str, str] = {}
    if len(paragraphs) > 1:
        for line in paragraphs[-1].splitlines():
            key, _, value = line.partition(": ")
            if key in _TRAILERS:
                meta[_TRAILERS[key]] = value
    if meta.get("origin") not in ORIGINS:
        meta["origin"] = "manual"  # unknown provenance is treated as the user's: safest
    return subject, meta


def _pairs(tokens: list[str]) -> list[PathChange]:
    items = [t for t in tokens if t != ""]
    return [
        PathChange(path=path, status=_STATUS.get(status[:1], "modified"))
        for status, path in zip(items[::2], items[1::2], strict=False)
    ]


def _parse_log(raw: bytes) -> list[tuple[str, datetime, str, dict[str, str], list[PathChange]]]:
    records = []
    for chunk in raw.decode("utf-8", errors="replace").split("\x1e"):
        if not chunk:
            continue
        commit, date, body, rest = chunk.split("\x1f", 3)
        subject, meta = _parse_message(body)
        changes = _pairs(rest.lstrip("\x00\n").split("\x00"))
        records.append((commit, datetime.fromisoformat(date), subject, meta, changes))
    return records


class ShadowGit:
    """Local :class:`~androai_codegen.vcs.protocol.VersionControl` backed by the git CLI."""

    def __init__(
        self,
        workspace: Workspace,
        git_dir: str | os.PathLike[str],
        *,
        protection: ProtectionPolicy = DEFAULT_POLICY,
        max_file_bytes: int = DEFAULT_MAX_TRACKED_FILE_BYTES,
        max_diff_bytes: int = DEFAULT_MAX_DIFF_BYTES,
        timeout: float = 60.0,
    ) -> None:
        git_path = Path(git_dir).resolve()
        if git_path.is_relative_to(workspace.root) or workspace.root.is_relative_to(git_path):
            raise ValueError("the shadow repository and the workspace must not contain each other")
        executable = shutil.which("git")
        if executable is None:
            raise GitNotAvailableError("the git executable was not found on PATH")
        self.workspace = workspace
        self.git_dir = git_path
        self.protection = protection
        self.max_file_bytes = max_file_bytes
        self.max_diff_bytes = max_diff_bytes
        self.timeout = timeout
        self._git_exe = executable
        self._empty_tree: str | None = None

    # -- running git --------------------------------------------------------------------

    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_ATTR_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            GIT_OPTIONAL_LOCKS="0",
            LC_ALL="C",
        )
        if extra:
            env.update(extra)
        return env

    def _git(
        self,
        *args: str,
        input: bytes | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        command = [
            self._git_exe,
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.workspace.root}",
            *args,
        ]
        try:
            proc = subprocess.run(
                command,
                input=input,
                capture_output=True,
                env=self._env(env),
                cwd=self.workspace.root,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(args, None, f"timed out after {self.timeout}s") from exc
        if check and proc.returncode != 0:
            raise GitCommandError(args, proc.returncode, proc.stderr.decode(errors="replace"))
        return proc

    @staticmethod
    def _rev(value: str) -> str:
        """Only full commit ids or HEAD may reach git: no option or ref-name injection."""
        if value != "HEAD" and not _COMMIT_ID.fullmatch(value):
            raise ValueError(f"not a commit id: {value!r}")
        return value

    # -- repository setup ---------------------------------------------------------------

    def init(self) -> None:
        if (self.git_dir / "HEAD").is_file():
            return
        self.git_dir.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("symbolic-ref", "HEAD", "refs/heads/main")
        no_hooks = self.git_dir / "no-hooks"
        no_hooks.mkdir(exist_ok=True)
        empty = self.git_dir / "empty"
        empty.write_bytes(b"")
        settings = {
            "core.autocrlf": "false",
            "core.safecrlf": "false",
            "core.filemode": "false",
            "core.symlinks": "false",
            "core.quotepath": "false",
            "core.longpaths": "true",
            "core.logallrefupdates": "false",
            "core.hookspath": no_hooks.as_posix(),
            "core.attributesfile": empty.as_posix(),
            "core.excludesfile": empty.as_posix(),
            "gc.auto": "0",
            "commit.gpgsign": "false",
        }
        for key, value in settings.items():
            self._git("config", key, value)
        info = self.git_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("\n".join(_DEFAULT_EXCLUDES) + "\n", encoding="utf-8")
        # Highest-precedence attributes: neutralise any .gitattributes inside the workspace.
        (info / "attributes").write_text("* -text -filter -ident\n", encoding="utf-8")

    def _empty_tree_id(self) -> str:
        if self._empty_tree is None:
            self._empty_tree = (
                self._git("hash-object", "-t", "tree", "-w", "--stdin", input=b"")
                .stdout.decode()
                .strip()
            )
        return self._empty_tree

    def _head_and_tree(self) -> tuple[str, str] | None:
        proc = self._git("log", "-1", "--format=%H%n%T", "HEAD", check=False)
        if proc.returncode != 0:
            return None
        commit, tree = proc.stdout.decode().split()
        return commit, tree

    def head(self) -> str | None:
        self.init()
        found = self._head_and_tree()
        return None if found is None else found[0]

    # -- staging ------------------------------------------------------------------------

    @staticmethod
    def _index_env(index_file: Path | None) -> dict[str, str] | None:
        return None if index_file is None else {"GIT_INDEX_FILE": str(index_file)}

    def _ls(self, *flags: str, index_file: Path | None = None) -> list[str]:
        raw = self._git("ls-files", "-z", *flags, env=self._index_env(index_file)).stdout
        found = []
        for token in raw.split(b"\0"):
            if not token or token.endswith(b"/"):  # nested repositories show up as 'dir/'
                continue
            with contextlib.suppress(UnicodeDecodeError):
                found.append(token.decode("utf-8"))
        return found

    def _classify(self, rel: str) -> str:
        """'ok', 'missing', or the reason the file must not be tracked."""
        try:
            if normalize_relative_path(rel) != rel:
                return "invalid_path"
        except PathValidationError:
            return "invalid_path"
        if self.protection.is_protected(rel):
            return "protected"
        try:
            kind = self.workspace.kind(rel)
        except PathValidationError:
            return "not_regular_file"  # symlink or junction
        if kind == "missing":
            return "missing"
        if kind != "file":
            return "not_regular_file"
        try:
            if self.workspace.resolve(rel).stat().st_size > self.max_file_bytes:
                return "too_large"
        except OSError:
            return "not_regular_file"
        return "ok"

    def _stage(self, index_file: Path | None, paths: Iterable[str] | None) -> list[SkippedPath]:
        """Bring the index in line with the workspace (all files, or only ``paths``)."""
        env = self._index_env(index_file)
        tracked = set(self._ls(index_file=index_file))
        if paths is None:
            others = self._ls("--others", "--exclude-standard", index_file=index_file)
            universe = list(dict.fromkeys([*sorted(tracked), *others]))
        else:
            universe = list(dict.fromkeys(paths))
        update: list[str] = []
        drop: list[str] = []
        skipped: list[SkippedPath] = []
        for rel in universe:
            state = self._classify(rel)
            if state == "ok":
                update.append(rel)
            elif state == "missing":
                if rel in tracked:
                    update.append(rel)  # --remove below turns this into a deletion
            else:
                skipped.append(SkippedPath(path=rel, reason=state))
                if rel in tracked:
                    drop.append(rel)
        if update:
            payload = b"".join(p.encode("utf-8") + b"\0" for p in update)
            self._git("update-index", "--add", "--remove", "-z", "--stdin", input=payload, env=env)
        if drop:
            payload = b"".join(p.encode("utf-8") + b"\0" for p in drop)
            self._git("update-index", "--force-remove", "-z", "--stdin", input=payload, env=env)
        return skipped

    def _worktree_tree(self) -> str:
        """Tree of the workspace as it is now, via a throw-away index (nothing is recorded)."""
        self.init()
        temp_index = self.git_dir / f"tmp-index-{uuid.uuid4().hex}"
        real_index = self.git_dir / "index"
        try:
            if real_index.is_file():
                # copy2, not copyfile: git decides whether a stat-identical file might still
                # have changed ("racily clean") by comparing file times with the index file's
                # own mtime. A copy with a fresh mtime defeats that and hides same-size edits
                # made within the same second as the last snapshot.
                shutil.copy2(real_index, temp_index)
            self._stage(temp_index, None)
            return self._git("write-tree", env=self._index_env(temp_index)).stdout.decode().strip()
        finally:
            for leftover in (temp_index, temp_index.with_name(temp_index.name + ".lock")):
                with contextlib.suppress(OSError):
                    leftover.unlink()

    # -- recording ----------------------------------------------------------------------

    def _name_status(self, base_tree: str, other: str) -> list[PathChange]:
        raw = self._git(
            "diff-tree", "-r", "--no-renames", "--name-status", "-z", base_tree, other
        ).stdout
        return _pairs(raw.decode("utf-8", errors="replace").split("\x00"))

    def snapshot(
        self,
        *,
        origin: Origin,
        description: str,
        run_id: str | None = None,
        task_id: str | None = None,
        patch_id: str | None = None,
        paths: Iterable[str] | None = None,
    ) -> SnapshotInfo | None:
        self.init()
        head = self._head_and_tree()
        skipped = self._stage(None, paths)
        tree = self._git("write-tree").stdout.decode().strip()
        if head is not None and tree == head[1]:
            return None
        name, email = _USER_IDENTITY if origin == "manual" else _AI_IDENTITY
        message = _build_message(origin, description, run_id, task_id, patch_id)
        args = ["commit-tree", tree, *(["-p", head[0]] if head else []), "-F", "-"]
        commit = (
            self._git(
                *args,
                input=message.encode("utf-8"),
                env={
                    "GIT_AUTHOR_NAME": name,
                    "GIT_AUTHOR_EMAIL": email,
                    "GIT_COMMITTER_NAME": name,
                    "GIT_COMMITTER_EMAIL": email,
                },
            )
            .stdout.decode()
            .strip()
        )
        # Compare-and-swap on the old value: a concurrent writer makes this fail loudly.
        self._git("update-ref", "HEAD", commit, head[0] if head else "0" * 40)
        changes = self._name_status(head[1] if head else self._empty_tree_id(), tree)
        return SnapshotInfo(
            commit=commit,
            origin=origin,
            message=message.splitlines()[0],
            run_id=run_id,
            task_id=task_id,
            patch_id=patch_id,
            created_at=datetime.now(UTC),
            changes=changes,
            skipped=skipped,
        )

    def pending_changes(self) -> list[PathChange]:
        head = self._head_and_tree()
        base = head[1] if head else self._empty_tree_id()
        return self._name_status(base, self._worktree_tree())

    # -- reading ------------------------------------------------------------------------

    def commits_between(self, base: str | None, head: str = "HEAD") -> list[CommitChanges]:
        self.init()
        if self._head_and_tree() is None:
            return []
        span = self._rev(head) if base is None else f"{self._rev(base)}..{self._rev(head)}"
        raw = self._git(
            "log",
            "--reverse",
            "--no-renames",
            "--name-status",
            "-z",
            "--format=%x1e%H%x1f%aI%x1f%B%x1f",
            span,
        ).stdout
        return [
            CommitChanges(
                commit=commit,
                origin=meta["origin"],  # type: ignore[arg-type]
                run_id=meta.get("run_id"),
                task_id=meta.get("task_id"),
                patch_id=meta.get("patch_id"),
                message=subject,
                created_at=created,
                changes=changes,
            )
            for commit, created, subject, meta, changes in _parse_log(raw)
        ]

    def read_blob(self, commit: str, path: str) -> bytes | None:
        rel = normalize_relative_path(path)
        listing = self._git("ls-tree", "-z", self._rev(commit), "--", rel).stdout
        if not listing:
            return None
        blob_id = listing.split(b"\t", 1)[0].split()[2].decode()
        return self._git("cat-file", "blob", blob_id).stdout

    def _target_tree(self, head: str | None) -> str:
        return self._worktree_tree() if head is None else self._rev(head)

    def _pathspec(self, paths: Iterable[str] | None) -> list[str]:
        if paths is None:
            return []
        return ["--", *[normalize_relative_path(p) for p in paths]]

    def diff(
        self,
        base: str,
        head: str | None = None,
        *,
        paths: Iterable[str] | None = None,
        mask: bool = True,
    ) -> DiffResult:
        target = self._target_tree(head)
        raw = self._git(
            "diff",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "-U3",
            self._rev(base),
            target,
            *self._pathspec(paths),
        ).stdout
        truncated = len(raw) > self.max_diff_bytes
        if truncated:
            raw = raw[: self.max_diff_bytes]
            raw = raw[: raw.rfind(b"\n") + 1] or raw
        text = raw.decode("utf-8", errors="replace")
        return DiffResult(text=mask_secrets(text) if mask else text, truncated=truncated)

    def summary(self, base: str, head: str | None = None) -> ChangeSummary:
        target = self._target_tree(head)
        base = self._rev(base)
        statuses = {c.path: c.status for c in self._name_status(base, target)}
        raw = self._git("diff", "--no-renames", "--numstat", "-z", base, target).stdout
        files: list[FileSummary] = []
        total_add = total_del = 0
        for record in raw.decode("utf-8", errors="replace").split("\x00"):
            if not record:
                continue
            added, deleted, path = record.split("\t", 2)
            binary = added == "-"
            add_n = None if binary else int(added)
            del_n = None if binary else int(deleted)
            total_add += add_n or 0
            total_del += del_n or 0
            files.append(
                FileSummary(
                    path=path,
                    status=statuses.get(path, "modified"),
                    additions=add_n,
                    deletions=del_n,
                )
            )
        return ChangeSummary(files=files, additions=total_add, deletions=total_del)

    def file_history(self, path: str, limit: int = 50) -> list[HistoryEntry]:
        rel = normalize_relative_path(path)
        self.init()
        if self._head_and_tree() is None:
            return []
        raw = self._git(
            "log",
            "--no-renames",
            "--name-status",
            "-z",
            f"--max-count={int(limit)}",
            "--format=%x1e%H%x1f%aI%x1f%B%x1f",
            "HEAD",
            "--",
            rel,
        ).stdout
        history = []
        for commit, created, subject, meta, changes in _parse_log(raw):
            status: ChangeStatus = next((c.status for c in changes if c.path == rel), "modified")
            history.append(
                HistoryEntry(
                    commit=commit,
                    origin=meta["origin"],  # type: ignore[arg-type]
                    status=status,
                    run_id=meta.get("run_id"),
                    task_id=meta.get("task_id"),
                    patch_id=meta.get("patch_id"),
                    message=subject,
                    created_at=created,
                )
            )
        return history
