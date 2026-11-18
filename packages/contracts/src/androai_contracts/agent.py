from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel, ErrorInfo, TaskState, new_id, utcnow


class AgentTask(ContractModel):
    """A user request handed to the orchestration worker. Owner: Person 2."""

    id: str = Field(default_factory=new_id)
    project_id: str
    user_id: str
    prompt: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentTaskStatus(ContractModel):
    """Progress report for an AgentTask. Owner: Person 2."""

    task_id: str
    state: TaskState = TaskState.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str | None = None
    error: ErrorInfo | None = None
    updated_at: datetime = Field(default_factory=utcnow)
