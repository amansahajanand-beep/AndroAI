from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base import ContractModel, ErrorInfo, TaskState, new_id


class BuildVariant(str, Enum):
    DEBUG = "debug"
    RELEASE = "release"


class BuildJob(ContractModel):
    """API/orchestration -> android-build worker. Owner: Person 4."""

    id: str = Field(default_factory=new_id)
    project_id: str
    source_key: str  # object-storage key of the project snapshot
    variant: BuildVariant = BuildVariant.DEBUG
    gradle_tasks: list[str] = Field(default_factory=lambda: ["assembleDebug"])
    timeout_seconds: int = Field(default=900, gt=0)


class BuildResult(ContractModel):
    build_job_id: str
    state: TaskState
    artifact_key: str | None = None  # e.g. the APK in object storage
    log_key: str | None = None
    duration_seconds: float | None = None
    error: ErrorInfo | None = None
