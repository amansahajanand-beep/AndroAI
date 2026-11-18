"""Interfaces to services owned by other people. The orchestration layer depends only on
these; concrete implementations are injected (Celery adapters below, or fakes in tests).

Integration dependencies (all documented in docs/AI_ORCHESTRATION_PROGRESS.md):
  * ProjectWorkspace - Person 4 (project storage / snapshots)
  * CodingEngine     - Person 3 (androai_agent)
  * ValidationRunner - Person 4 (android-build / android-test)
  * LogReader        - Person 4 (object storage)
"""

from __future__ import annotations

import json
import uuid
from typing import Protocol

from androai_contracts import (
    AndroidTarget, BuildJob, CodingResult, CodingTask, Queues, TestJob,
)

from .intelligence.models import ProjectScope

ENVELOPE_VERSION = 1
_NS = uuid.UUID("6f1c7a1e-5b0e-4d3a-9d5e-3c1d8a2b7e40")


def deterministic_id(run_id: str, kind: str, key: str) -> str:
    """Stable id so a retried dispatch refers to the same job (idempotency)."""
    return str(uuid.uuid5(_NS, f"{run_id}:{kind}:{key}"))


class ProjectWorkspace(Protocol):
    def load_files(self, scope: ProjectScope) -> dict[str, bytes]:
        """Current project files (project-relative POSIX path -> bytes)."""
        ...

    def apply_result(self, scope: ProjectScope, result: CodingResult) -> str:
        """Persist generated files into the project and return an object-storage
        `source_key` for a snapshot that build/test jobs can consume."""
        ...


class CodingEngine(Protocol):
    def submit(self, task: CodingTask) -> None:
        """Enqueue. At-least-once: the receiver must dedupe on `task.id`."""
        ...


class ValidationRunner(Protocol):
    def submit_build(self, job: BuildJob) -> None: ...

    def submit_test(self, job: TestJob) -> None: ...


class LogReader(Protocol):
    def read_tail(self, log_key: str, max_chars: int = 8000) -> str: ...


def build_coding_task(
    *, run_id: str, key: str, agent_task_id: str, project_id: str, task_type: str, user_request: str,
    implementation_plan: dict, relevant_files: list[str], context: dict, constraints: list[str],
    validation_requirements: list[str], target: AndroidTarget,
) -> CodingTask:
    """Map the orchestration view of a task onto the shared `CodingTask` contract.

    The contract currently only has `instructions` and `context_files`. Until the
    contract is extended (proposal in docs/AI_ORCHESTRATION_PROGRESS.md), the rich
    fields travel as a versioned JSON envelope in `instructions`."""
    envelope = {
        "androai_task_envelope": ENVELOPE_VERSION,
        "task_type": task_type,
        "user_request": user_request,
        "implementation_plan": implementation_plan,
        "context": context,
        "constraints": constraints,
        "validation_requirements": validation_requirements,
    }
    return CodingTask(
        id=deterministic_id(run_id, "coding", key),
        agent_task_id=agent_task_id,
        project_id=project_id,
        instructions=json.dumps(envelope, ensure_ascii=False),
        target=target,
        context_files=relevant_files,
    )


# ---- Celery adapters ------------------------------------------------------------------
# Task names are NOT yet agreed with their owners; they are constructor parameters so the
# defaults can change without code changes here.
class CeleryCodingEngine:
    def __init__(self, celery_app, task_name: str = "androai_agent.run_coding_task"):
        self._app, self._name = celery_app, task_name

    def submit(self, task: CodingTask) -> None:
        self._app.send_task(self._name, args=[task.model_dump(mode="json")], queue=Queues.AI_AGENT, task_id=task.id)


class CeleryValidationRunner:
    def __init__(self, celery_app, build_task: str = "androai_android_build.run_build",
                 test_task: str = "androai_android_test.run_tests"):
        self._app, self._build, self._test = celery_app, build_task, test_task

    def submit_build(self, job: BuildJob) -> None:
        self._app.send_task(self._build, args=[job.model_dump(mode="json")], queue=Queues.ANDROID_BUILD, task_id=job.id)

    def submit_test(self, job: TestJob) -> None:
        self._app.send_task(self._test, args=[job.model_dump(mode="json")], queue=Queues.ANDROID_TEST, task_id=job.id)
