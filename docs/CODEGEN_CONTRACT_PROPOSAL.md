# Proposal: CodingTask / CodingResult contract v0.2

- **Status:** DRAFT for review. Nothing in `packages/contracts` has been changed.
- **Author:** Person 3 (code generation). **Date:** 2026-11-18
- **Reviewers needed:** Person 2 (produces `CodingTask`, consumes `CodingResult`) and Person 4 (maintains
  `packages/contracts`; owns storage, build/test workers, CI). Process per `docs/TEAM_WORKFLOW.md`: a contracts-only
  PR after both of you agree.

## 1. Decisions I need

| # | Question | Who | My recommendation |
|---|---|---|---|
| 1 | **Repair loop ownership.** Is one `CodingTask(repair)` = exactly one repair attempt, with the orchestrator owning the loop, the cumulative budget and the stop decision? | P2 | Yes. The coding service never loops by itself; it enforces per-task limits and reports `no_progress` / `budget_exhausted`. |
| 2 | **Plan shape.** Can the planner emit `ImplementationPlan` (summary, architecture, steps with paths, permitted dependencies)? | P2 | Use it as the minimum; tell me what else you need. You own the shape. |
| 3 | **Failure classification.** You turn `BuildResult` / `TestResult` into a `ClassifiedFailure` (category + stable `signature`). Who owns signature normalization (strip paths and line numbers)? | P2 | You, since you classify. I only compare signatures. |
| 4 | **Approval flow.** `needs_approval` result, you ask the user, you re-enqueue the same task with `approvals=[...]`. Stateless re-run OK? | P2 | Yes. |
| 5 | **Task granularity.** One `CodingTask` per approved plan, or per plan step? | P2 | Per plan: one checkpoint, one reviewable patch. |
| 6 | **Snapshots.** I materialize the workspace from `source_key` and upload `result_source_key`. This needs the object-storage client (`packages/storage`, empty today). Who builds it, and what is the snapshot format? | P4 | You own storage. I only need `download_snapshot(key, dir)` and `upload_snapshot(dir) -> key`. |
| 7 | **Agent state between tasks.** Repair spans several tasks (code, build, test, code again), so my checkpoints and journal must survive between them. OK to round-trip an opaque archive as `agent_state_key`? Retention? | P4 | Yes; I'll cap its size and prune old history. |
| 8 | **Diff and log objects.** OK to store `diff_key` objects in storage, with retention you choose? | P4 | Yes. |
| 9 | **Image and CI.** The ai-agent image needs `git`. CI does not install or test codegen. I'll fix the Dockerfile (mine). Can you add codegen to CI and the Makefile (yours)? | P4 | Yes; exact lines are in `docs/CODE_GENERATION_PROGRESS.md`. |
| 10 | **Versioning.** One `SCHEMA_VERSION` covers every model and consumers do not check it. Bump to `0.2.0`, and should consumers reject a mismatch? | P4 | Bump now; add the check later. |

## 2. Why change

The current `CodingTask` has 6 fields and `CodingResult` has 5. The Role 3 spec needs more in both directions.

| Needed | Today |
|---|---|
| Task kind: generate, modify, repair, rollback | Missing |
| Approved plan, constraints, validation requirements, budget | Only `instructions`, `target`, `context_files` |
| Repair inputs: classified failure, attempt history | Missing |
| Which snapshot to work on; where the result is | Missing (`BuildJob.source_key` already shows the convention) |
| Modified / created / deleted split with checksums, diff reference | One `files` list carrying **full file content** |
| Review findings, repair summary, approval requests, problems | Missing |

`CodingResult.files` with full content also conflicts with patch-based editing and with the rule that "services
exchange keys, not blobs".

**Cost of breaking now is close to zero.** Nothing produces or consumes these models yet: I searched the repo and
the only references are the contracts package, its tests, the schema export, and docs. After Person 2 and
Person 3 start building against them, every change costs a coordinated release.

## 3. Design

**A. Repair is one attempt per task.** The orchestrator owns the loop, because the build and test workers sit
between my steps.

```
Orchestration                       ai-agent                          android-build / android-test
CodingTask(repair, iteration=1) --> one patch -> CodingResult(completed, result_source_key=K1)
BuildJob(source_key=K1) ---------------------------------------------------------> BuildResult
classify failure
CodingTask(repair, iteration=2, previous_attempts=[...], agent_state_key=S1) --> CodingResult(...)
... stops when the build passes, or the outcome is no_progress / budget_exhausted /
    infrastructure_failure / provider_failure (never "fixed" by editing source)
```

**B. State moves by key.** `source_key` in, `result_source_key` out (usable directly as `BuildJob.source_key`),
and an opaque `agent_state_key` that carries my checkpoints and journal from one task to the next.

**C. Changes by reference.** The result lists each change with previous/new checksum and description, and points
to the diff by `diff_key`. No file contents travel in the message.

**D. Approvals are data.** A patch that needs a high-impact change is not applied; the result carries
`approval_requests`. After the user agrees, the same task is re-sent with matching `approvals`.

**E. `outcome` lets you branch; `state` stays the lifecycle.** The validator rejects contradictory combinations.

| outcome | state | meaning |
|---|---|---|
| `completed` | succeeded | changes applied, build/validate next |
| `needs_approval` | succeeded | finished correctly, nothing applied, a human must decide |
| `rejected` | failed | nothing applied: conflict with manual edits, protected file, invalid patch |
| `budget_exhausted`, `no_progress` | failed | stop looping |
| `infrastructure_failure`, `provider_failure` | failed | not a source problem; source untouched |
| `failed` | failed | unexpected internal error |
| `cancelled` | cancelled | |

## 4. What changes

**`CodingTask`** adds: `task_type` (required), `source_key`, `agent_state_key`, `implementation_plan`,
`constraints`, `validation_requirements`, `budget` (defaults: 5 iterations, 45 minutes), `repair`,
`rollback_checkpoint_id`, `rollback_skip_conflicts`, `approvals`. `target` becomes optional (detected from an
existing project). `context_files` becomes project-relative paths only. A validator requires the right fields
for each `task_type` (for example repair needs `source_key` and `repair`).

**`CodingResult`** adds: `outcome`, `changes`, `patch_id`, `checkpoint_id`, `diff_key`, `diff_summary`,
`result_source_key`, `agent_state_key`, `review` (None means no review ran; review is always static),
`repair`, `requires_approval`, `approval_requests`, `problems`, `warnings`, `usage` (tokens, cost, seconds, so
you can enforce the cumulative budget). It **removes** `files` and `GeneratedFile`. `error` stays.

**Not changed:** `AndroidTarget`, `UiToolkit`, `TaskState`, `ErrorInfo`, and every other contract.

**Mapping from the implementation that already exists (Phases 1 and 2):**

| Contract field | Comes from |
|---|---|
| `changes[]` | `editing.ChangeRecord` (1:1: path, type, checksums, description) |
| `patch_id`, `diff_key` | `editing.ApplyResult` (diff uploaded to storage) |
| `diff_summary` | `vcs.ChangeSummary` |
| `checkpoint_id` | `vcs.Checkpoint.id` |
| `approval_requests` | `editing.PatchPreview.requires_approval` (deletions today) |
| `problems[]` | `editing.Problem` (`conflict`, `protected_file`, `path_invalid`, ...) |
| `outcome=rejected` | `PatchRejected`, `RestoreConflict` |
| `error.retryable=true` | `WorkspaceBusyError` |

## 5. Compatibility and rollout

- **Breaking, deliberately:** an old-style `CodingTask` (no `task_type`) no longer validates. Safe today because
  nothing produces one.
- `GeneratedFile` is removed from `androai_contracts.__init__`.
- Bump `SCHEMA_VERSION` to `0.2.0`.
- Contract models forbid unknown fields, so a *future* rollout must deploy consumers before producers.
- `scripts/export_contract_schemas.py` needs no change: nested models land in `$defs`. `make schemas`
  regenerates `CodingTask.json` and `CodingResult.json`.
- **On approval, the contracts-only PR contains:** the models below in `codegen.py`, tests (round trips, one test
  per validator rule, old-message rejection), regenerated schemas, the version bump, and an update to the
  contract table in `docs/ARCHITECTURE.md`. Follow-ups: my adapter in `workers/ai-agent`, your producer in
  `workers/orchestration`.

## 6. Not in this proposal

- **Visual editor edits.** A component identifier needs input from the frontend owner; I'll propose it
  separately in Phase 8 as an additive task type and field.
- Standalone code review as its own task type, streaming progress (`AgentTaskStatus` is Person 2's), and
  schema-version negotiation.

## 7. How this was checked, and what was not

Checked in a throwaway script, not committed, against the real `androai_contracts` base: 8 checks.

- Round trips for all four task types and five result outcomes.
- Every validator rule fires **for its intended reason** (each rejection asserts its message).
- An old-style task is rejected.
- JSON Schema exports (`CodingTask` 18 fields, `CodingResult` 20 fields, 14 nested definitions).
- A `CodingResult` was populated from a real Phase 1/2 run: a patch that needed deletion approval
  (`needs_approval`), then the approved patch (`completed`, 3 changes, diff summary), then a rollback task.

Not checked: nobody except me has reviewed this; no producer or consumer exists to integrate with; Celery
serialization (only Pydantic JSON round trips); the shape of `ImplementationPlan` against what the planner can
actually emit.

## Appendix: draft models

Replaces `packages/contracts/src/androai_contracts/codegen.py` (`AndroidTarget` and `UiToolkit` unchanged).

```python
"""Proposed replacement for packages/contracts/src/androai_contracts/codegen.py (DRAFT).

Conventions follow the existing contracts: ContractModel base (strict, versioned), ``str, Enum``
enums, ``*_key`` fields for object-storage references, ErrorInfo/TaskState reused unchanged.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from androai_contracts.base import ContractModel, ErrorInfo, TaskState, new_id

# AndroidTarget and UiToolkit are unchanged from the current codegen.py.
from androai_contracts.codegen import AndroidTarget, UiToolkit  # noqa: F401

# --------------------------------------------------------------------------- enums


class CodingTaskType(str, Enum):
    GENERATE_PROJECT = "generate_project"
    MODIFY_PROJECT = "modify_project"
    REPAIR = "repair"  # exactly one repair attempt; the orchestrator owns the loop
    ROLLBACK = "rollback"  # undo AI changes since a checkpoint, never manual ones


class ValidationKind(str, Enum):
    BUILD = "build"
    UNIT = "unit"
    INSTRUMENTED = "instrumented"
    LINT = "lint"


class ApprovalKind(str, Enum):
    """High-impact changes the engine will not make without an explicit grant."""

    DELETE_FILES = "delete_files"
    RENAME_PACKAGE = "rename_package"  # package name or application id
    CONVERT_LANGUAGE = "convert_language"  # e.g. Java -> Kotlin
    CONVERT_UI_TOOLKIT = "convert_ui_toolkit"  # e.g. XML -> Compose
    CHANGE_API_CONTRACT = "change_api_contract"
    CHANGE_DATABASE_OPERATIONS = "change_database_operations"
    REMOVE_INTEGRATION = "remove_integration"  # auth, payments, third-party SDKs
    OTHER_HIGH_IMPACT = "other_high_impact"


class FailureCategory(str, Enum):
    # Fixable by changing source code:
    KOTLIN_COMPILE = "kotlin_compile"
    JAVA_COMPILE = "java_compile"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    MISSING_IMPORT = "missing_import"
    GRADLE_SCRIPT = "gradle_script"
    MANIFEST = "manifest"
    RESOURCE = "resource"
    RUNTIME_EXCEPTION = "runtime_exception"
    NULL_POINTER = "null_pointer"
    NAVIGATION = "navigation"
    API_INTEGRATION = "api_integration"
    TEST_FAILURE = "test_failure"
    UI_SOURCE = "ui_source"
    # Never fixed by editing source; returned to the orchestrator untouched:
    INFRASTRUCTURE = "infrastructure"  # worker outage, missing SDK, network, resource exhaustion
    EXTERNAL_PROVIDER = "external_provider"
    AI_PROVIDER = "ai_provider"
    UNKNOWN = "unknown"


class ChangeType(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CodingOutcome(str, Enum):
    """What happened, for the orchestrator to branch on. Maps onto TaskState (see validator)."""

    COMPLETED = "completed"  # changes applied: build/validate next
    NEEDS_APPROVAL = "needs_approval"  # nothing applied; approval_requests explains
    REJECTED = "rejected"  # nothing applied: conflict with manual edits, invalid patch, ...
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_PROGRESS = "no_progress"  # repeated error or an attempt that changes nothing
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"  # not a source problem
    PROVIDER_FAILURE = "provider_failure"  # external or AI provider; not a source problem
    FAILED = "failed"  # unexpected internal error
    CANCELLED = "cancelled"


_OUTCOME_STATE = {
    CodingOutcome.COMPLETED: TaskState.SUCCEEDED,
    CodingOutcome.NEEDS_APPROVAL: TaskState.SUCCEEDED,  # finished correctly; a human must decide
    CodingOutcome.CANCELLED: TaskState.CANCELLED,
}

# --------------------------------------------------------------------------- task side


class PlanStep(ContractModel):
    id: str
    description: str = Field(min_length=1)
    paths: list[str] = Field(default_factory=list)  # project-relative files expected to change


class ImplementationPlan(ContractModel):
    """The approved plan from orchestration. Owner of the shape: Person 2."""

    summary: str = Field(min_length=1)
    architecture: str | None = Field(default=None, max_length=64)  # e.g. "mvvm"
    steps: list[PlanStep] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # Gradle coordinates the plan permits


class CodingConstraints(ContractModel):
    protected_paths: list[str] = Field(default_factory=list)  # in addition to built-in secrets
    notes: list[str] = Field(default_factory=list)  # free-text user constraints


class ApprovalGrant(ContractModel):
    kind: ApprovalKind
    paths: list[str] = Field(default_factory=list)  # required for delete_files


class CodingBudget(ContractModel):
    max_iterations: int = Field(default=5, ge=1, le=20)  # repair attempts across the whole loop
    max_seconds: int = Field(default=2700, gt=0)  # per task
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class ClassifiedFailure(ContractModel):
    """Produced by orchestration from BuildResult/TestResult. Classifier owner: Person 2."""

    category: FailureCategory
    message: str
    signature: str  # stable fingerprint of the normalized error, for repeated-error detection
    files: list[str] = Field(default_factory=list)
    log_key: str | None = None  # full error + stack trace (BuildResult.log_key)
    report_key: str | None = None  # TestResult.report_key
    excerpt: str | None = Field(default=None, max_length=8000)


class RepairAttempt(ContractModel):
    iteration: int = Field(ge=1)
    signature: str
    patch_id: str | None = None


class RepairContext(ContractModel):
    failure: ClassifiedFailure
    iteration: int = Field(ge=1)  # 1-based; the agent refuses if > budget.max_iterations
    previous_attempts: list[RepairAttempt] = Field(default_factory=list)


class CodingTask(ContractModel):
    """Orchestration -> ai-agent. Owners: Person 2 (producer), Person 3 (consumer)."""

    id: str = Field(default_factory=new_id)
    agent_task_id: str
    project_id: str
    instructions: str = Field(min_length=1)
    task_type: CodingTaskType
    target: AndroidTarget | None = None  # required to generate; detected from the project otherwise
    source_key: str | None = None  # project snapshot (same meaning as BuildJob.source_key)
    agent_state_key: str | None = None  # opaque: ai-agent's checkpoints/journal, round-tripped
    implementation_plan: ImplementationPlan | None = None
    context_files: list[str] = Field(default_factory=list)  # project-relative paths
    constraints: CodingConstraints = Field(default_factory=CodingConstraints)
    validation_requirements: list[ValidationKind] = Field(default_factory=list)
    budget: CodingBudget = Field(default_factory=CodingBudget)
    repair: RepairContext | None = None
    rollback_checkpoint_id: str | None = None
    rollback_skip_conflicts: bool = False
    approvals: list[ApprovalGrant] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fields_match_task_type(self) -> CodingTask:
        kind = self.task_type
        problems: list[str] = []
        if kind is CodingTaskType.GENERATE_PROJECT:
            if self.target is None:
                problems.append("generate_project requires 'target'")
            if self.implementation_plan is None:
                problems.append("generate_project requires 'implementation_plan'")
        if kind is CodingTaskType.MODIFY_PROJECT:
            if self.source_key is None:
                problems.append("modify_project requires 'source_key'")
            if self.implementation_plan is None:
                problems.append("modify_project requires 'implementation_plan'")
        if kind is CodingTaskType.REPAIR:
            if self.source_key is None:
                problems.append("repair requires 'source_key'")
            if self.repair is None:
                problems.append("repair requires 'repair'")
        if kind is CodingTaskType.ROLLBACK:
            for name in ("source_key", "agent_state_key", "rollback_checkpoint_id"):
                if getattr(self, name) is None:
                    problems.append(f"rollback requires '{name}'")
        if kind is not CodingTaskType.REPAIR and self.repair is not None:
            problems.append("'repair' is only valid for repair tasks")
        if kind is not CodingTaskType.ROLLBACK and self.rollback_checkpoint_id is not None:
            problems.append("'rollback_checkpoint_id' is only valid for rollback tasks")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# --------------------------------------------------------------------------- result side


class FileChange(ContractModel):
    path: str  # project-relative, forward slashes
    change_type: ChangeType
    previous_checksum: str | None = None  # sha256; None for create
    new_checksum: str | None = None  # sha256; None for delete
    description: str


class DiffSummary(ContractModel):
    files_changed: int = Field(ge=0)
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)


class ApprovalRequest(ContractModel):
    kind: ApprovalKind
    paths: list[str] = Field(default_factory=list)
    reason: str


class PatchProblem(ContractModel):
    """Why a patch was not applied. ``code`` is a documented vocabulary, not a closed enum."""

    code: str  # conflict | protected_file | path_invalid | approval_required | restore_conflict ...
    path: str | None = None
    message: str
    blocking: bool = True


class ReviewFinding(ContractModel):
    severity: Severity
    rule: str  # stable id, e.g. "unresolved_reference"
    file: str
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    description: str
    suggested_fix: str | None = None
    blocking: bool


class ReviewReport(ContractModel):
    scope: Literal["static"] = "static"  # static review never proves runtime correctness
    findings: list[ReviewFinding] = Field(default_factory=list)


class RepairSummary(ContractModel):
    iteration: int = Field(ge=1)
    root_cause: str
    plan: str


class Usage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    seconds: float = Field(default=0.0, ge=0)


class CodingResult(ContractModel):
    """ai-agent -> orchestration. Owners: Person 3 (producer), Person 2 (consumer)."""

    coding_task_id: str
    state: TaskState
    outcome: CodingOutcome
    summary: str | None = None
    changes: list[FileChange] = Field(default_factory=list)
    patch_id: str | None = None
    checkpoint_id: str | None = None  # taken before the task changed anything
    diff_key: str | None = None  # unified diff in object storage
    diff_summary: DiffSummary | None = None
    result_source_key: str | None = None  # snapshot after the changes: feed to BuildJob.source_key
    agent_state_key: str | None = None  # pass back in the next CodingTask for this project
    review: ReviewReport | None = None  # None = no review ran
    repair: RepairSummary | None = None
    requires_approval: bool = False
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    problems: list[PatchProblem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    error: ErrorInfo | None = None

    @property
    def created_files(self) -> list[str]:
        return [c.path for c in self.changes if c.change_type is ChangeType.CREATE]

    @property
    def modified_files(self) -> list[str]:
        return [c.path for c in self.changes if c.change_type is ChangeType.MODIFY]

    @property
    def deleted_files(self) -> list[str]:
        return [c.path for c in self.changes if c.change_type is ChangeType.DELETE]

    @model_validator(mode="after")
    def _consistent(self) -> CodingResult:
        problems: list[str] = []
        expected_state = _OUTCOME_STATE.get(self.outcome, TaskState.FAILED)
        if self.state is not expected_state:
            problems.append(f"outcome {self.outcome.value} requires state {expected_state.value}")
        if self.requires_approval != bool(self.approval_requests):
            problems.append("requires_approval must equal 'approval_requests is non-empty'")
        if self.outcome is CodingOutcome.NEEDS_APPROVAL:
            if not self.approval_requests:
                problems.append("needs_approval requires approval_requests")
            if self.changes:
                problems.append("needs_approval means nothing was applied, so no changes")
        if self.outcome is CodingOutcome.COMPLETED:
            if self.error is not None:
                problems.append("completed must not carry an error")
            if self.changes and self.result_source_key is None:
                problems.append("completed with changes requires result_source_key")
        if self.state is TaskState.FAILED and self.error is None:
            problems.append("a failed result requires 'error'")
        if self.outcome in (CodingOutcome.REJECTED, CodingOutcome.NEEDS_APPROVAL) and self.changes:
            problems.append(f"{self.outcome.value} means nothing was applied, so no changes")
        if problems:
            raise ValueError("; ".join(problems))
        return self
```
