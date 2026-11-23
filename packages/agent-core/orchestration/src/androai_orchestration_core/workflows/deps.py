"""Dependencies and limits injected into workflow graphs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from ..intelligence import ProjectIndex, ProjectScope
from ..persistence import RunStore
from ..ports import CodingEngine, LogReader, ProjectWorkspace, ValidationRunner
from ..providers import Budget, BudgetTracker, LLMRouter


class Limits(BaseModel):
    """Hard bounds that make runaway loops impossible."""

    max_steps: int = Field(default=150, gt=0)  # node executions per run
    max_plan_revisions: int = Field(default=3, ge=0)
    max_repair_attempts: int = Field(default=3, ge=0)
    max_infra_retries: int = Field(default=2, ge=0)
    max_coding_retries: int = Field(default=1, ge=0)  # per task, retryable failures only
    require_plan_approval: bool = True
    require_tests: bool = True  # TestResult must succeed for the run to succeed
    gradle_tasks: list[str] = Field(default_factory=lambda: ["assembleDebug"])
    retrieval_token_budget: int = Field(default=6000, gt=0)
    budget: Budget = Field(default_factory=Budget)


class WorkflowState(TypedDict, total=False):
    # identity
    run_id: str
    tenant_id: str
    project_id: str
    user_id: str
    agent_task_id: str
    workflow: str  # new_app | modify | repair
    request: str
    # understanding / planning (JSON dicts so checkpoints stay serialisable)
    requirements: dict
    clarified: bool
    answers: dict
    plan_feedback: str
    plan_revisions: int
    architecture: dict
    task_graph: dict
    modification_plan: dict
    plan_approved: bool
    # execution
    queue: list  # PlannedTask dicts
    cursor: int
    coding_attempt: int
    files_modified: list
    source_key: str
    # validation / repair
    val_round: int
    validation: dict
    failure: dict  # {log, error_code, retryable}
    classification: dict
    repair_attempts: int
    infra_retries: int
    # control
    step_count: int
    status: str  # running | failed | succeeded
    error: dict
    result: dict


@dataclass
class WorkflowDeps:
    store: RunStore
    router_factory: Callable[[str], LLMRouter]  # run_id -> router that persists usage for that run
    workspace: ProjectWorkspace
    coding: CodingEngine
    validation: ValidationRunner
    logs: LogReader | None = None
    limits: Limits = field(default_factory=Limits)
    indexes: dict[str, ProjectIndex] = field(default_factory=dict)  # per-process cache, scope-keyed

    def router(self, run_id: str) -> LLMRouter:
        return self.router_factory(run_id)

    def tracker(self, run_id: str) -> BudgetTracker:
        """Rebuilt from persisted usage so budgets survive restarts/resumes."""
        return BudgetTracker(self.limits.budget, records=self.store.usage(run_id))

    def index_for(self, scope: ProjectScope) -> ProjectIndex:
        """Cached index; rebuilt from the workspace if this process has none (recovery)."""
        idx = self.indexes.get(scope.key)
        if idx is None:
            idx = ProjectIndex.build(scope, self.workspace.load_files(scope))
            self.indexes[scope.key] = idx
        assert idx.scope == scope, "index scope mismatch"  # tenant isolation guard
        return idx


def scope_of(state: dict[str, Any]) -> ProjectScope:
    return ProjectScope(tenant_id=state["tenant_id"], project_id=state["project_id"])
