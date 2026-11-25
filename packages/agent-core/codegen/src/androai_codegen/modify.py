"""Applying an approved modification plan to an imported project (Phase 6).

``run_modification`` is the executor behind ``CodingTask(modify_project)``. It does not decide what
to change (orchestration plans that) and it does not talk to a model itself: an ``EditProposer``
supplied by the caller turns the plan and the current file contents into edits. Everything after
that is deterministic and safe:

    read files (secrets masked, protected files refused)
      -> proposer returns edits
      -> scope check (only files the plan names)
      -> patch validation and static review of the project as it would become, nothing written
      -> blocking problems go back to the proposer once more (``max_revisions``), then a refusal
      -> high-impact changes (deletions, package renames, ...) wait for an explicit approval
      -> checkpoint, apply as an AI change, report

The outcome mirrors ``docs/CODEGEN_CONTRACT_PROPOSAL.md``; one call is one attempt, and the caller
owns any repair loop. Nothing is built or run: the review is static and the result says so.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from androai_codegen.editing import (
    CreateFile,
    DeleteFile,
    ModifyFile,
    PatchSet,
    PathValidationError,
    ProtectedFileError,
    TextEdit,
    normalize_relative_path,
)
from androai_codegen.editing.errors import CodegenError
from androai_codegen.editing.models import ChangeRecord, Problem, ProblemCode
from androai_codegen.review import ReviewReport, ReviewSession
from androai_codegen.vcs import CheckpointManager


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- what the caller supplies ------------------------------------------------------------------


class ModificationPlan(_Model):
    """The approved plan, reduced to what the executor needs."""

    summary: str = Field(min_length=1, max_length=2000)
    affected_files: tuple[str, ...] = ()  # existing files that may be modified
    new_files: tuple[str, ...] = ()  # files that may be created
    deleted_files: tuple[str, ...] = ()  # files that may be deleted (each needs an approval)
    changes: tuple[str, ...] = ()  # the steps, in words
    preserve: tuple[str, ...] = ()  # what must keep working
    conventions: tuple[str, ...] = ()


class ModificationTask(_Model):
    project_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    user_request: str = Field(min_length=1, max_length=8000)
    plan: ModificationPlan
    context_files: tuple[str, ...] = ()  # read-only files shown to the proposer as well
    approved_deletions: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()  # ApprovalKind values the user granted


class ModifyConfig(_Model):
    max_revisions: int = Field(default=1, ge=0, le=3)  # extra proposals after blocking problems
    max_files: int = Field(default=40, ge=1, le=500)
    max_file_chars: int = Field(default=24_000, ge=1000)  # per file shown to the proposer
    checkpoint_label: str = "before AI modification"


class FileView(_Model):
    path: str
    content: str  # secrets masked
    checksum: str  # of the real file
    editable: bool


class ProposalRequest(_Model):
    user_request: str
    plan: ModificationPlan
    files: tuple[FileView, ...]
    feedback: tuple[str, ...] = ()  # problems found in the previous proposal
    attempt: int = 1


class ProposedEdit(_Model):
    action: Literal["modify", "create", "delete"]
    path: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=300)
    edits: tuple[TextEdit, ...] | None = None  # modify: exact replacements ...
    content: str | None = None  # ... or whole new content (also for create)


class ProposedEdits(_Model):
    edits: tuple[ProposedEdit, ...] = ()
    notes: str = ""


class EditProposer(Protocol):
    """Turns a plan and file contents into edits. Any exception means a provider failure."""

    def propose(self, request: ProposalRequest) -> ProposedEdits: ...


# --- what comes back ---------------------------------------------------------------------------


class ModifyOutcome(StrEnum):
    COMPLETED = "completed"  # changes applied; build and validation come next
    NEEDS_APPROVAL = "needs_approval"  # correct, nothing applied, a person must decide
    REJECTED = "rejected"  # nothing applied: out of scope, conflict, invalid, review blocked
    NO_PROGRESS = "no_progress"  # the proposer changed nothing
    PROVIDER_FAILURE = "provider_failure"  # the proposer failed; source untouched


class ApprovalRequest(_Model):
    kind: str  # an ApprovalKind value
    paths: tuple[str, ...] = ()
    reason: str


class ModifyResult(_Model):
    outcome: ModifyOutcome
    patch_id: str | None = None
    checkpoint_id: str | None = None
    changes: tuple[ChangeRecord, ...] = ()
    diff: str = ""
    review: ReviewReport | None = None  # always static; None means no review ran
    approval_requests: tuple[ApprovalRequest, ...] = ()
    problems: tuple[Problem, ...] = ()
    warnings: tuple[str, ...] = ()
    attempts: int = 0
    notes: str = ""


# --- the executor ------------------------------------------------------------------------------


def run_modification(
    manager: CheckpointManager,
    session: ReviewSession,
    proposer: EditProposer,
    task: ModificationTask,
    config: ModifyConfig | None = None,
) -> ModifyResult:
    cfg = config or ModifyConfig()
    engine = manager.engine
    warnings: list[str] = []

    try:
        scope = _Scope.build(task)
    except PathValidationError as exc:
        return _rejected(Problem(code=ProblemCode.PATH_INVALID, message=str(exc)))
    if len(scope.all) > cfg.max_files:
        return _rejected(
            Problem(
                code=ProblemCode.TOO_MANY_FILES,
                message=f"the plan names {len(scope.all)} files; the limit is {cfg.max_files}",
            )
        )

    views, checksums, cut = _read_views(engine, scope, cfg, warnings)
    feedback: tuple[str, ...] = ()
    last_review: ReviewReport | None = None
    last_problems: tuple[Problem, ...] = ()
    attempts = 0

    for attempt in range(1, cfg.max_revisions + 2):
        attempts = attempt
        try:
            proposal = proposer.propose(
                ProposalRequest(
                    user_request=task.user_request,
                    plan=task.plan,
                    files=views,
                    feedback=feedback,
                    attempt=attempt,
                )
            )
        except Exception as exc:  # the provider is outside our control; the source is untouched
            return ModifyResult(
                outcome=ModifyOutcome.PROVIDER_FAILURE,
                warnings=(*warnings, _provider_warning(exc)),
                attempts=attempts,
            )
        if not proposal.edits:
            return ModifyResult(
                outcome=ModifyOutcome.NO_PROGRESS,
                warnings=tuple(warnings),
                attempts=attempts,
                notes=proposal.notes[:500],
            )

        problems = scope.check(proposal.edits)
        patch: PatchSet | None = None
        if not problems:
            patch, problems = _build_patch(task, proposal, checksums, cut)
        if problems:
            if _fatal(problems) or attempt > cfg.max_revisions:
                return _refusal(problems, warnings, attempts, last_review)
            feedback = tuple(_describe(p) for p in problems)
            last_problems = tuple(problems)
            continue

        assert patch is not None
        approved = set(task.approved_deletions)
        review = session.review_patch(patch, approved_deletions=approved)
        last_review = review.report
        preview = review.simulation.preview
        if preview.requires_approval:
            return _needs_approval(patch, preview.problems, approved, warnings, attempts)
        if not preview.ok:
            if attempt > cfg.max_revisions or _fatal(preview.blocking_problems):
                return _refusal(preview.blocking_problems, warnings, attempts, last_review)
            feedback = tuple(_describe(p) for p in preview.blocking_problems)
            last_problems = tuple(preview.blocking_problems)
            continue
        report = review.report
        assert report is not None
        needs, blocking = _split_findings(report, task.approvals)
        if needs:
            return ModifyResult(
                outcome=ModifyOutcome.NEEDS_APPROVAL,
                review=report,
                approval_requests=tuple(needs),
                warnings=tuple(warnings),
                attempts=attempts,
            )
        if blocking:
            if attempt > cfg.max_revisions:
                return ModifyResult(
                    outcome=ModifyOutcome.REJECTED,
                    review=report,
                    warnings=(*warnings, "static review found blocking problems; nothing applied"),
                    attempts=attempts,
                )
            feedback = tuple(
                f"{f.file}: [{f.rule}] {f.description}"
                + (f" Fix: {f.suggested_fix}" if f.suggested_fix else "")
                for f in blocking
            )
            continue

        return _apply(
            manager, session, patch, approved, task, cfg, report, warnings, attempts, proposal.notes
        )

    return ModifyResult(  # pragma: no cover - the loop always returns
        outcome=ModifyOutcome.REJECTED,
        problems=last_problems,
        review=last_review,
        attempts=attempts,
    )


def _provider_warning(exc: Exception) -> str:
    """What to tell the user. Only a provider that vouches for its message (``safe_message``, never
    containing keys or response bodies) is quoted; anything else is reported by type only."""
    safe = getattr(exc, "safe_message", None)
    if isinstance(safe, str) and safe:
        return f"the edit proposer failed: {safe[:300]}"
    return f"the edit proposer failed: {type(exc).__name__}"


def _apply(
    manager: CheckpointManager,
    session: ReviewSession,
    patch: PatchSet,
    approved: set[str],
    task: ModificationTask,
    cfg: ModifyConfig,
    report: ReviewReport,
    warnings: list[str],
    attempts: int,
    notes: str,
) -> ModifyResult:
    checkpoint = manager.checkpoint(cfg.checkpoint_label, run_id=task.run_id, task_id=task.task_id)
    try:
        tracked = manager.apply(patch, approved)
    except CodegenError as exc:
        return ModifyResult(
            outcome=ModifyOutcome.REJECTED,
            checkpoint_id=checkpoint.id,
            review=report,
            problems=(Problem(code=ProblemCode.IO_ERROR, message=str(exc)[:300]),),
            warnings=tuple(warnings),
            attempts=attempts,
        )
    session.invalidate()
    return ModifyResult(
        outcome=ModifyOutcome.COMPLETED,
        patch_id=tracked.result.patch_id,
        checkpoint_id=checkpoint.id,
        changes=tuple(tracked.result.records),
        diff=tracked.result.diff,
        review=report,
        warnings=(*warnings, *tracked.warnings),
        attempts=attempts,
        notes=notes[:500],
    )


# --- scope and patch building ------------------------------------------------------------------


class _Scope:
    def __init__(self, modify: set[str], create: set[str], delete: set[str], context: set[str]):
        self.modify, self.create, self.delete, self.context = modify, create, delete, context

    @property
    def all(self) -> set[str]:
        return self.modify | self.create | self.delete | self.context

    @classmethod
    def build(cls, task: ModificationTask) -> _Scope:
        def norm(paths: Iterable[str]) -> set[str]:
            return {normalize_relative_path(p) for p in paths}

        return cls(
            norm(task.plan.affected_files),
            norm(task.plan.new_files),
            norm(task.plan.deleted_files),
            norm(task.context_files),
        )

    def check(self, edits: Iterable[ProposedEdit]) -> list[Problem]:
        problems: list[Problem] = []
        seen: set[str] = set()
        for edit in edits:
            try:
                path = normalize_relative_path(edit.path)
            except PathValidationError as exc:
                problems.append(
                    Problem(code=ProblemCode.PATH_INVALID, path=edit.path, message=str(exc))
                )
                continue
            if path in seen:
                problems.append(
                    Problem(
                        code=ProblemCode.DUPLICATE_PATH,
                        path=path,
                        message="edited twice; combine the edits",
                    )
                )
            seen.add(path)
            allowed = {"modify": self.modify, "create": self.create, "delete": self.delete}[
                edit.action
            ]
            if path not in allowed:
                problems.append(
                    Problem(
                        code=ProblemCode.CONFLICT,
                        path=path,
                        message=f"the approved plan does not allow to {edit.action} this file",
                    )
                )
        return problems


def _read_views(engine, scope: _Scope, cfg, warnings: list[str]):
    views: list[FileView] = []
    checksums: dict[str, str] = {}
    cut: set[str] = set()
    for path in sorted(scope.modify | scope.delete | scope.context):
        try:
            snap = engine.read_for_llm(path)
        except ProtectedFileError:
            warnings.append(f"{path} is protected and was not shown to the proposer")
            continue
        except (CodegenError, OSError):
            warnings.append(f"{path} could not be read and was not shown to the proposer")
            continue
        checksums[path] = snap.checksum
        content = snap.content
        if len(content) > cfg.max_file_chars:
            content = content[: cfg.max_file_chars]
            cut.add(path)
            warnings.append(f"{path} was cut to {cfg.max_file_chars} characters for the proposer")
        views.append(
            FileView(
                path=path,
                content=content,
                checksum=snap.checksum,
                editable=path in scope.modify or path in scope.delete,
            )
        )
    return tuple(views), checksums, cut


def _build_patch(task: ModificationTask, proposal: ProposedEdits, checksums, cut: set[str]):
    problems: list[Problem] = []
    changes: list[CreateFile | ModifyFile | DeleteFile] = []
    for edit in proposal.edits:
        path = normalize_relative_path(edit.path)
        if edit.action == "create":
            if edit.content is None:
                problems.append(
                    Problem(code=ProblemCode.NO_CHANGE, path=path, message="create needs content")
                )
                continue
            changes.append(
                CreateFile(path=path, content=edit.content, description=edit.description)
            )
            continue
        checksum = checksums.get(path)
        if checksum is None:
            problems.append(
                Problem(
                    code=ProblemCode.MISSING_FILE,
                    path=path,
                    message="the file was not available to edit",
                )
            )
            continue
        if edit.action == "delete":
            changes.append(
                DeleteFile(path=path, expected_checksum=checksum, description=edit.description)
            )
        elif path in cut and edit.content is not None:
            problems.append(
                Problem(
                    code=ProblemCode.NO_CHANGE,
                    path=path,
                    message="this file was shown cut short; use edits, not full content",
                )
            )
        elif (edit.edits is None) == (edit.content is None):
            problems.append(
                Problem(
                    code=ProblemCode.NO_CHANGE,
                    path=path,
                    message="give either edits or full content",
                )
            )
        else:
            changes.append(
                ModifyFile(
                    path=path,
                    expected_checksum=checksum,
                    content=edit.content,
                    edits=list(edit.edits) if edit.edits is not None else None,
                    description=edit.description,
                )
            )
    if problems:
        return None, problems
    patch = PatchSet(
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.task_id,
        description=task.plan.summary[:300],
        changes=changes,
    )
    return patch, []


# --- results -----------------------------------------------------------------------------------

_FATAL = {
    ProblemCode.PATH_INVALID,
    ProblemCode.PROTECTED_FILE,
    ProblemCode.CONFLICT,
    ProblemCode.TOO_MANY_FILES,
}


def _fatal(problems: Iterable[Problem]) -> bool:
    """Problems another proposal cannot fix: bad or protected paths, or a conflict with the
    user's own edits. (A file outside the plan is also a CONFLICT, but a proposer can fix that.)"""
    return any(
        p.code in (ProblemCode.PATH_INVALID, ProblemCode.PROTECTED_FILE, ProblemCode.TOO_MANY_FILES)
        or (p.code is ProblemCode.CONFLICT and "plan does not allow" not in p.message)
        for p in problems
    )


def _describe(problem: Problem) -> str:
    return f"{problem.path or 'patch'}: [{problem.code.value}] {problem.message}"


def _rejected(*problems: Problem) -> ModifyResult:
    return ModifyResult(outcome=ModifyOutcome.REJECTED, problems=tuple(problems))


def _refusal(problems, warnings, attempts, review) -> ModifyResult:
    return ModifyResult(
        outcome=ModifyOutcome.REJECTED,
        problems=tuple(problems),
        review=review,
        warnings=tuple(warnings),
        attempts=attempts,
    )


def _needs_approval(
    patch: PatchSet, problems, approved: set[str], warnings, attempts
) -> ModifyResult:
    paths = tuple(
        sorted(
            p.path
            for p in problems
            if p.code is ProblemCode.APPROVAL_REQUIRED and p.path and p.path not in approved
        )
    )
    return ModifyResult(
        outcome=ModifyOutcome.NEEDS_APPROVAL,
        approval_requests=(
            ApprovalRequest(
                kind="delete_files", paths=paths, reason="the plan deletes these files"
            ),
        ),
        warnings=tuple(warnings),
        attempts=attempts,
    )


def _split_findings(report: ReviewReport, granted: Iterable[str]):
    """Blocking findings that need an approval the user has not given, and ones that do not."""
    granted_set = set(granted)
    needs: dict[str, list[str]] = {}
    blocking = []
    for finding in report.blocking_findings:
        if finding.approval and finding.approval not in granted_set:
            needs.setdefault(finding.approval, []).append(finding.file)
        elif not finding.approval:
            blocking.append(finding)
    requests = [
        ApprovalRequest(
            kind=kind, paths=tuple(sorted(set(paths))), reason="a reviewed change needs an approval"
        )
        for kind, paths in sorted(needs.items())
    ]
    return requests, blocking
