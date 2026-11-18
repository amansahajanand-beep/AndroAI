from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base import ContractModel, ErrorInfo, TaskState, new_id


class UiToolkit(str, Enum):
    COMPOSE = "compose"
    XML = "xml"


class AndroidTarget(ContractModel):
    language: str = Field(default="kotlin", pattern="^(kotlin|java)$")
    ui: UiToolkit = UiToolkit.COMPOSE
    min_sdk: int = Field(default=24, ge=21)
    target_sdk: int = Field(default=35, ge=21)
    package_name: str


class GeneratedFile(ContractModel):
    path: str  # project-relative, forward slashes
    content: str


class CodingTask(ContractModel):
    """Orchestration -> ai-agent. Owners: Person 2 (producer), Person 3 (consumer)."""

    id: str = Field(default_factory=new_id)
    agent_task_id: str
    project_id: str
    instructions: str = Field(min_length=1)
    target: AndroidTarget
    context_files: list[str] = Field(default_factory=list)  # storage keys / paths


class CodingResult(ContractModel):
    """ai-agent -> orchestration. Owners: Person 3 (producer), Person 2 (consumer)."""

    coding_task_id: str
    state: TaskState
    files: list[GeneratedFile] = Field(default_factory=list)
    summary: str | None = None
    error: ErrorInfo | None = None
