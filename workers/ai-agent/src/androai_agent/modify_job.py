"""One "modify an uploaded project from a prompt" job, runnable without Celery or the API.

``run_modify_job`` is what the Celery task will call once the contract and the API endpoint exist,
and what ``python -m androai_agent modify`` calls today:

    ZIP -> detect framework -> import (isolated workspace) -> analyse -> retrieve context
        -> plan (from the retrieved files) -> model proposes edits -> executor validates,
        reviews statically, asks for approvals, checkpoints and applies

It never builds or runs the project, and the uploaded files are only read. The project's code is
sent to whatever ``LlmClient`` is given, so callers must only use a client the user agreed to.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Literal

from androai_codegen.analysis import analyse_import
from androai_codegen.detect import Detection, detect_zip
from androai_codegen.editing import PatchEngine
from androai_codegen.ingest import IngestRejected, OwnershipAttestation, import_zip
from androai_codegen.modify import (
    ApprovalRequest,
    ModificationPlan,
    ModificationTask,
    ModifyConfig,
    ModifyOutcome,
    run_modification,
)
from androai_codegen.proposer import LlmClient, LlmEditProposer
from androai_codegen.retrieval import ContextBundle, RetrievalConfig, retrieve_context
from androai_codegen.review import ReviewSession
from androai_codegen.vcs import CheckpointManager
from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["detect", "import", "retrieve", "modify", "done"]
Status = Literal[
    "completed",  # edits applied to the workspace
    "needs_approval",  # a person must approve something; nothing applied
    "needs_clarification",  # the request matched nothing; nothing sent to the model
    "unsupported",  # not a native Android project
    "rejected",  # refused by import, scope, validation or static review; nothing applied
    "no_progress",  # the model changed nothing
    "provider_failure",  # the model call failed; nothing applied
]

_CLARIFY = (
    "I could not match your request to any screen, class or setting in this project. "
    "Which screen or feature should change, and what should it do?"
)
CODE_SUFFIXES = (".kt", ".java", ".xml", ".kts", ".gradle")
MAX_PLAN_FILES = 8


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModifyJobRequest(_Model):
    zip_path: Path
    prompt: str = Field(min_length=1, max_length=8000)
    work_dir: (
        Path  # an existing directory; the workspace and journal are created inside it
    )
    attestation: OwnershipAttestation
    tenant_id: str = "local"
    project_id: str = "project"
    approved_deletions: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()
    max_plan_files: int = Field(default=MAX_PLAN_FILES, ge=1, le=40)


class ModifyJobResult(_Model):
    status: Status
    stage: Stage
    detection: Detection | None = None
    confidence: str | None = None
    plan_files: tuple[str, ...] = ()
    impact_files: tuple[str, ...] = ()
    unmatched_terms: tuple[str, ...] = ()
    changes: tuple[tuple[str, str], ...] = ()  # (change type, path)
    diff: str = ""
    review_summary: str | None = (
        None  # a static review; it never proves the code compiles
    )
    review_blocking: bool | None = None
    approval_requests: tuple[ApprovalRequest, ...] = ()
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    questions: tuple[
        str, ...
    ] = ()  # what to ask the user when status is needs_clarification
    attempts: int = 0
    notes: str = ""
    workspace: Path | None = None  # the (modified) project, when an import happened
    checkpoint_id: str | None = None
    patch_id: str | None = None
    seconds: float = 0.0


def run_modify_job(
    request: ModifyJobRequest,
    client: LlmClient,
    *,
    retrieval: RetrievalConfig | None = None,
    modify: ModifyConfig | None = None,
) -> ModifyJobResult:
    started = time.monotonic()

    def finish(**values) -> ModifyJobResult:
        return ModifyJobResult(seconds=round(time.monotonic() - started, 1), **values)

    detection = detect_zip(request.zip_path)
    if not detection.supported:
        return finish(
            status="unsupported",
            stage="detect",
            detection=detection,
            problems=(detection.reason,),
        )

    try:
        imported = import_zip(
            request.zip_path,
            data_root=request.work_dir,
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            attestation=request.attestation,
            import_id=uuid.uuid4().hex,
        )
    except IngestRejected as exc:
        return finish(
            status="rejected",
            stage="import",
            detection=detection,
            problems=(f"{exc.code.value}: {exc.problem.message}",),
        )

    workspace = imported.workspace.root
    report = analyse_import(imported)
    bundle = retrieve_context(report, request.prompt, retrieval)
    plan_files = _with_strings(_plan_files(bundle, request.max_plan_files), workspace)
    impact = tuple(f.path for f in bundle.impact[:5])
    common = {
        "detection": detection,
        "confidence": bundle.confidence,
        "plan_files": plan_files,
        "impact_files": impact,
        "unmatched_terms": bundle.unmatched_terms,
        "workspace": workspace,
        "warnings": tuple(bundle.notes),
    }

    if bundle.confidence == "none" or not plan_files:
        return finish(
            status="needs_clarification",
            stage="retrieve",
            questions=(_CLARIFY,),
            **{**common, "plan_files": ()},
        )

    task = ModificationTask(
        project_id=request.project_id,
        run_id=imported.report.import_id,
        task_id=uuid.uuid4().hex,
        user_request=request.prompt,
        plan=ModificationPlan(
            summary=request.prompt[:2000],
            affected_files=plan_files,
            conventions=bundle.conventions[:6],
        ),
        context_files=impact,
        approved_deletions=request.approved_deletions,
        approvals=request.approvals,
    )
    engine = PatchEngine(request.project_id, imported.workspace, imported.journal_dir)
    outcome = run_modification(
        CheckpointManager(engine),
        ReviewSession(engine),
        LlmEditProposer(client),
        task,
        modify,
    )

    status = _STATUS[outcome.outcome]
    return finish(
        status=status,
        stage="done" if status == "completed" else "modify",
        changes=tuple(
            (str(getattr(c.change_type, "value", c.change_type)), c.path)
            for c in outcome.changes
        ),
        diff=outcome.diff,
        review_summary=outcome.review.summary() if outcome.review else None,
        review_blocking=outcome.review.has_blocking if outcome.review else None,
        approval_requests=outcome.approval_requests,
        problems=tuple(
            f"[{p.code.value}] {p.path or 'patch'}: {p.message}"
            for p in outcome.problems
        ),
        attempts=outcome.attempts,
        notes=outcome.notes,
        checkpoint_id=outcome.checkpoint_id,
        patch_id=outcome.patch_id,
        **{**common, "warnings": (*common["warnings"], *outcome.warnings)},
    )


_STATUS: dict[ModifyOutcome, Status] = {
    ModifyOutcome.COMPLETED: "completed",
    ModifyOutcome.NEEDS_APPROVAL: "needs_approval",
    ModifyOutcome.REJECTED: "rejected",
    ModifyOutcome.NO_PROGRESS: "no_progress",
    ModifyOutcome.PROVIDER_FAILURE: "provider_failure",
}


def _plan_files(bundle: ContextBundle, limit: int) -> tuple[str, ...]:
    """Files the model may edit: the best matches and their neighbours, code and resources only."""
    chosen: list[str] = []
    for f in bundle.files:
        if f.role in ("primary", "related", "build") and f.path.endswith(CODE_SUFFIXES):
            chosen.append(f.path)
    return tuple(chosen[:limit])


def _with_strings(plan_files: tuple[str, ...], workspace: Path) -> tuple[str, ...]:
    """Let the model add or reword user-visible text: include the module's strings.xml.

    Retrieval works on code facts, so a request about on-screen text finds the screen but not the
    resource file that holds its text; without it the model can only hard-code strings.
    """
    if not any(p.endswith((".kt", ".java")) for p in plan_files):
        return plan_files
    extra: list[str] = []
    for path in plan_files:
        module = path.split("/src/", 1)[0] if "/src/" in path else ""
        candidate = (
            f"{module}/src/main/res/values/strings.xml"
            if module
            else "src/main/res/values/strings.xml"
        )
        if (
            candidate not in plan_files
            and candidate not in extra
            and (workspace / candidate).is_file()
        ):
            extra.append(candidate)
    return (*plan_files, *extra)
