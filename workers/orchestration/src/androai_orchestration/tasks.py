"""Celery tasks (queue: orchestration). Payloads are contract models serialised to JSON.

All tasks are idempotent: redelivery of the same message never repeats work
(see OrchestrationService). `tenant_id` is NOT part of AgentTask; the API must pass the
authenticated tenant explicitly (contract gap, tracked in docs)."""

from __future__ import annotations

from androai_contracts import AgentTask, BuildResult, CodingResult, TestResult
from androai_orchestration_core.intelligence import ProjectScope

from .celery_app import app
from .runtime import get_service

# Coding/build/test results arrive on this queue's tasks (producers send by name).
_COMMON = dict(acks_late=True, autoretry_for=(TimeoutError,), retry_backoff=True, max_retries=5)


def _dump(snap) -> dict | None:
    return snap.model_dump(mode="json") if snap else None


@app.task(name="androai_orchestration.start_run", **_COMMON)
def start_run(agent_task: dict, tenant_id: str, workflow: str = "new_app",
              failure: dict | None = None, source_key: str | None = None) -> dict:
    return _dump(get_service().start(AgentTask.model_validate(agent_task), tenant_id, workflow, failure, source_key))


@app.task(name="androai_orchestration.respond", **_COMMON)
def respond(tenant_id: str, project_id: str, run_id: str, reply: dict) -> dict:
    return _dump(get_service().respond(ProjectScope(tenant_id=tenant_id, project_id=project_id), run_id, reply))


@app.task(name="androai_orchestration.cancel_run", **_COMMON)
def cancel_run(tenant_id: str, project_id: str, run_id: str) -> dict:
    return _dump(get_service().cancel(ProjectScope(tenant_id=tenant_id, project_id=project_id), run_id))


@app.task(name="androai_orchestration.handle_coding_result", **_COMMON)
def handle_coding_result(result: dict) -> dict | None:
    return _dump(get_service().on_coding_result(CodingResult.model_validate(result)))


@app.task(name="androai_orchestration.handle_build_result", **_COMMON)
def handle_build_result(result: dict) -> dict | None:
    return _dump(get_service().on_build_result(BuildResult.model_validate(result)))


@app.task(name="androai_orchestration.handle_test_result", **_COMMON)
def handle_test_result(result: dict) -> dict | None:
    return _dump(get_service().on_test_result(TestResult.model_validate(result)))


@app.task(name="androai_orchestration.recover_runs")
def recover_runs(stale_seconds: int = 300) -> list[str]:
    return get_service().recover(stale_seconds)
