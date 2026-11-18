from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base import ContractModel, ErrorInfo, TaskState, new_id


class TestKind(str, Enum):
    __test__ = False  # not a pytest class

    UNIT = "unit"
    INSTRUMENTED = "instrumented"
    LINT = "lint"


class TestJob(ContractModel):
    """-> android-test worker. Owner: Person 4."""

    __test__ = False

    id: str = Field(default_factory=new_id)
    project_id: str
    source_key: str
    kind: TestKind = TestKind.UNIT
    build_job_id: str | None = None
    timeout_seconds: int = Field(default=900, gt=0)


class TestResult(ContractModel):
    __test__ = False

    test_job_id: str
    state: TaskState
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    report_key: str | None = None
    error: ErrorInfo | None = None
