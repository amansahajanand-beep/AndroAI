"""Schemas for builds, tests, workers and queues."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BuildCreateIn(BaseModel):
    project_id: str
    variant: Literal["debug", "release"] = "debug"
    output_type: Literal["apk", "aab"] = "apk"
    gradle_tasks: list[str] | None = Field(default=None, max_length=10, description="plain task names only, no options")
    priority: int = Field(default=100, ge=50, le=200, description="lower runs sooner")
    timeout_seconds: int = Field(default=900, ge=60, le=3600)


class TestCreateIn(BaseModel):
    __test__ = False
    project_id: str
    kind: Literal["static", "compile", "unit", "instrumented", "emulator"] = "unit"
    build_job_id: str | None = None
    emulator_profile: dict | None = Field(default=None, description="e.g. {api_level: 34, device: 'pixel_6'}")
    priority: int = Field(default=100, ge=50, le=200)
    timeout_seconds: int = Field(default=900, ge=60, le=3600)


class JobOut(_Out):
    id: str
    project_id: str
    state: str
    priority: int
    attempts: int
    max_attempts: int
    timeout_seconds: int
    cancel_requested: bool
    blocked_reason: str | None
    error_code: str | None
    error_message: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class BuildOut(JobOut):
    variant: str
    output_type: str
    gradle_tasks: list[str]
    toolchain: dict
    agent_run_id: str | None


class BuildResultOut(_Out):
    build_job_id: str
    state: str
    artifact_id: str | None
    duration_seconds: float | None
    errors: list[dict]


class LogChunkOut(_Out):
    seq: int
    stream: str
    content: str


class TestOut(JobOut):
    __test__ = False
    kind: str
    build_job_id: str | None
    emulator_profile: dict | None
    toolchain: dict
    agent_run_id: str | None


class TestResultOut(_Out):
    __test__ = False
    test_job_id: str
    state: str
    outcome: str
    not_run_reason: str | None
    passed: int
    failed: int
    skipped: int
    duration_seconds: float | None


# ---- workers (admin)
class WorkerCreateIn(BaseModel):
    name: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    kind: Literal["build", "test", "emulator"]
    provider: Literal["docker", "vps", "cloud_vm", "external_ci"] = "docker"
    capacity: int = Field(default=1, ge=1, le=8)


class WorkerPatchIn(BaseModel):
    capacity: int | None = Field(default=None, ge=1, le=8)
    draining: bool | None = None


class WorkerOut(_Out):
    id: str
    name: str
    kind: str
    provider: str
    status: str
    capacity: int
    draining: bool
    toolchain: dict
    capabilities: dict
    last_heartbeat_at: datetime | None
    created_at: datetime
    live: bool = False
    active_jobs: int = 0


class WorkerCreatedOut(WorkerOut):
    token: str = Field(description="shown once; store it in the worker's secret store")


# ---- worker protocol
class WorkerRegisterIn(BaseModel):
    toolchain: dict = Field(default_factory=dict, description="{id?, jdks:[int], platforms:[int], build_tools?:[str]}")
    capabilities: dict = Field(default_factory=dict, description="{kvm: bool, emulator: bool, ...} from worker preflight")
    version: str | None = Field(default=None, max_length=64)


class HeartbeatIn(BaseModel):
    load: dict = Field(default_factory=dict)


class LogIn(BaseModel):
    stream: Literal["stdout", "stderr"] = "stdout"
    content: str = Field(max_length=256 * 1024)


class CompleteIn(BaseModel):
    outcome: Literal["completed", "failed", "cancelled"]
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    retryable: bool = False
    errors: list[dict] = Field(default_factory=list, max_length=100)
    artifact_id: str | None = None
    test_outcome: Literal["passed", "failed", "not_run", "error"] | None = None
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    not_run_reason: str | None = Field(default=None, max_length=255)


class QueueStatsOut(BaseModel):
    queues: dict[str, dict[str, int]]
    workers: dict[str, dict[str, int]]
