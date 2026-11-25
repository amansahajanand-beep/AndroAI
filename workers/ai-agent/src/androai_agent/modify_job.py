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
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from androai_codegen.agent.loop import AgentConfig, AgentEditProposer
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
    # "agent": a tool-using loop that explores the project and changes what it needs (the default).
    # "single": one model call over files chosen up front (small, specific edits only).
    mode: Literal["agent", "single"] = "agent"
    # Earlier chat turns (role, text), so an answer to a question has its context.
    history: tuple[tuple[str, str], ...] = ()
    max_agent_steps: int = Field(default=40, ge=1, le=200)


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
    # Deletions and other approval-gated changes included for the user's review of the diff.
    deferred_approvals: tuple[ApprovalRequest, ...] = ()
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
    progress: Callable[[str, str], None] | None = None,
) -> ModifyJobResult:
    """``progress(stage, text)`` is called as each step starts; it must not raise or block."""
    started = time.monotonic()

    def step(stage: str, text: str) -> None:
        if progress is not None:
            try:
                progress(stage, text)
            except Exception:  # noqa: BLE001, S110  (a broken listener must never break the job)
                pass

    step("detect", "Checking the project type")

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

    step("analyze", "Importing and analysing the project")
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
    step(
        "retrieve",
        f"Analysed {len(report.facts)} facts; choosing the files for your request",
    )
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

    agent_mode = request.mode == "agent"
    if not agent_mode and (bundle.confidence == "none" or not plan_files):
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
            affected_files=() if agent_mode else plan_files,
            conventions=bundle.conventions[:6],
        ),
        context_files=() if agent_mode else impact,
        approved_deletions=request.approved_deletions,
        approvals=request.approvals,
        # The agent decides which files to touch; the diff review in the UI is the approval.
        scope="any" if agent_mode else "plan",
        defer_approvals=agent_mode,
    )
    if agent_mode:
        step("generate", "Starting the assistant")
        # A package rename moves hundreds of files, far above the default patch size.
        engine = PatchEngine(
            request.project_id, imported.workspace, imported.journal_dir, max_files=3000
        )
        proposer = AgentEditProposer(
            client,
            engine,
            project_facts=_facts(detection, len(report.facts), bundle.conventions),
            hints=(*plan_files, *impact),
            conversation=request.history,
            config=AgentConfig(max_steps=request.max_agent_steps),
            progress=lambda text: step("agent", text),
        )
    else:
        step("generate", "Asking the model to propose the edits")
        engine = PatchEngine(
            request.project_id, imported.workspace, imported.journal_dir
        )
        proposer = LlmEditProposer(client)
    outcome = run_modification(
        CheckpointManager(engine),
        ReviewSession(engine),
        proposer,
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
        deferred_approvals=outcome.deferred_approvals,
        questions=(outcome.question,) if outcome.question else (),
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
    ModifyOutcome.NEEDS_CLARIFICATION: "needs_clarification",
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


def _facts(detection: Detection, fact_count: int, conventions: tuple[str, ...]) -> str:
    lines = [
        (
            f"- native Android project; languages: {', '.join(detection.languages) or 'unknown'}; "
            f"UI: {', '.join(detection.ui_toolkits) or 'unknown'}"
        ),
        f"- the static analysis found {fact_count} facts about it",
    ]
    lines += [f"- convention: {c}" for c in conventions[:6]]
    return "\n".join(lines)
