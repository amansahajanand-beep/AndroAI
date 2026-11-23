"""Structured planning outputs. Every LLM output is validated against these."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Ambiguity(BaseModel):
    question: str
    essential: bool = False  # True only if a sensible assumption is impossible
    assumption: str | None = None  # what we will assume if not essential/unanswered


class ScreenSpec(BaseModel):
    name: str
    purpose: str
    roles: list[str] = Field(default_factory=list)
    navigates_to: list[str] = Field(default_factory=list)


class RequirementSpec(BaseModel):
    app_name: str
    summary: str
    features: list[str] = Field(default_factory=list)
    user_roles: list[str] = Field(default_factory=list)
    screens: list[ScreenSpec] = Field(default_factory=list)
    navigation: str | None = None
    backend_requirements: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    database: list[str] = Field(default_factory=list)
    authentication: list[str] = Field(default_factory=list)
    payments: list[str] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    platform_constraints: list[str] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @property
    def essential_questions(self) -> list[str]:
        return [a.question for a in self.ambiguities if a.essential]


class PlannedFile(BaseModel):
    path: str  # project-relative
    purpose: str
    action: str = Field(default="create", pattern="^(create|modify|delete)$")


class ArchitecturePlan(BaseModel):
    package_name: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    ui_toolkit: str = Field(default="compose", pattern="^(compose|xml)$")
    language: str = Field(default="kotlin", pattern="^(kotlin|java)$")
    pattern: str = "MVVM"
    modules: list[str] = Field(default_factory=lambda: ["app"])
    libraries: list[str] = Field(default_factory=list)
    rationale: str = ""
    structure: list[PlannedFile] = Field(default_factory=list)


class TaskType(str, Enum):
    SCAFFOLD = "scaffold"
    FEATURE = "feature"
    SCREEN = "screen"
    MODIFY = "modify"
    REPAIR = "repair"


class PlannedTask(BaseModel):
    """One unit of work for the coding engine."""

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")  # stable within a plan; drives idempotency
    title: str
    task_type: TaskType
    instructions: str
    files: list[PlannedFile] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)


class TaskGraph(BaseModel):
    tasks: list[PlannedTask]

    @model_validator(mode="after")
    def _valid_dag(self) -> "TaskGraph":
        keys = [t.key for t in self.tasks]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate task keys")
        known = set(keys)
        for t in self.tasks:
            bad = [d for d in t.depends_on if d not in known or d == t.key]
            if bad:
                raise ValueError(f"task {t.key} has invalid dependencies {bad}")
        self.topological_order()  # raises on cycles
        return self

    def topological_order(self) -> list[PlannedTask]:
        by_key = {t.key: t for t in self.tasks}
        indeg = {t.key: len(set(t.depends_on)) for t in self.tasks}
        ready = sorted(k for k, d in indeg.items() if d == 0)
        out: list[PlannedTask] = []
        while ready:
            k = ready.pop(0)
            out.append(by_key[k])
            for t in self.tasks:
                if k in t.depends_on:
                    indeg[t.key] -= 1
                    if indeg[t.key] == 0:
                        ready.append(t.key)
            ready.sort()
        if len(out) != len(self.tasks):
            raise ValueError("task graph contains a cycle")
        return out


class ModificationPlan(BaseModel):
    """Plan for changing an existing project (see spec section 5)."""

    task: str
    project_analysis: dict[str, bool | str | int | None] = Field(default_factory=dict)
    affected_files: list[str] = Field(default_factory=list)  # existing files to change
    new_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    affected_symbols: list[str] = Field(default_factory=list)
    preserve: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    affects_api_contract: bool = False
    affects_database_schema: bool = False
    affects_navigation: bool = False
    needs_permission_or_config_change: bool = False
    risks: list[str] = Field(default_factory=list)
    needs_clarification: list[str] = Field(default_factory=list)
    # Set by deterministic grounding, never trusted from the model:
    ungrounded_files: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    approval_reasons: list[str] = Field(default_factory=list)


class FailureCategory(str, Enum):
    CODE = "code"  # compile/test failure caused by the sources
    DEPENDENCY = "dependency"  # unresolved/incompatible dependency or version
    CONFIGURATION = "configuration"  # gradle/manifest/sdk configuration
    INFRASTRUCTURE = "infrastructure"  # worker/network/disk/timeouts: NOT a code failure
    UNKNOWN = "unknown"


class FailureClassification(BaseModel):
    category: FailureCategory
    summary: str
    files: list[str] = Field(default_factory=list)
    retryable_without_changes: bool = False
    source: str = "rules"  # rules | llm


class RepairPlan(BaseModel):
    root_cause: str
    files: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
