"""OrchestrationService: the entry points used by the Celery tasks / API.

Every method is safe to call more than once (idempotent) and serialises per run
through a RunLock. Graph progress is checkpointed by LangGraph; run/step/plan/usage
metadata lives in RunStore."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from androai_contracts import AgentTask, BuildResult, CodingResult, TestResult

from ..intelligence import ProjectScope
from ..persistence import JobKind, LocalRunLock, RunLock, RunRecord, RunStatus, RunStore
from .deps import WorkflowDeps
from .graphs import GRAPH_BUILDERS

log = logging.getLogger(__name__)

HUMAN_WAITS = {RunStatus.WAITING_CLARIFICATION, RunStatus.WAITING_APPROVAL}
JOB_WAITS = {RunStatus.WAITING_CODING, RunStatus.WAITING_VALIDATION}


class RunSnapshot(BaseModel):
    run_id: str
    status: str
    workflow: str
    pending: dict | None = None  # what the run is waiting for (questions / plan to approve / job)
    result: dict | None = None
    error: dict | None = None


def make_checkpointer(database_url: str | None = None) -> BaseCheckpointSaver:
    """PostgreSQL checkpointer when a URL is given (requires the `postgres` extra);
    otherwise in-memory (tests/dev only: checkpoints are lost on restart)."""
    if database_url:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row

        conn = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


class OrchestrationService:
    def __init__(self, deps: WorkflowDeps, checkpointer: BaseCheckpointSaver, lock: RunLock | None = None):
        self.d = deps
        self.lock = lock or LocalRunLock()
        self.graphs = {name: build(deps, checkpointer) for name, build in GRAPH_BUILDERS.items()}

    # ---- helpers ---------------------------------------------------------------------
    def _cfg(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": self.d.limits.max_steps * 2 + 10}

    def _snapshot(self, run_id: str) -> RunSnapshot:
        r = self.d.store.run_by_id(run_id)
        assert r is not None
        graph = self.graphs[r.workflow]
        pending = None
        if r.status not in RunStatus.TERMINAL:
            st = graph.get_state(self._cfg(run_id))
            for t in st.tasks:
                if t.interrupts:
                    pending = t.interrupts[0].value
                    break
        return RunSnapshot(run_id=run_id, status=r.status, workflow=r.workflow, pending=pending,
                           result=r.result, error=r.error)

    def _advance(self, run: RunRecord, input_: Any) -> RunSnapshot:
        """Run the graph until it finishes or interrupts. Caller holds the lock."""
        graph = self.graphs[run.workflow]
        try:
            graph.invoke(input_, self._cfg(run.id))
        except Exception as exc:  # noqa: BLE001 - unexpected crash: record, don't loop
            log.exception("run %s crashed", run.id)
            self.d.store.set_status(run.id, RunStatus.FAILED,
                                    error={"code": "internal_error", "message": type(exc).__name__})
        return self._snapshot(run.id)

    # ---- entry points ----------------------------------------------------------------------
    def start(self, task: AgentTask, tenant_id: str, workflow: str = "new_app",
              failure: dict | None = None, source_key: str | None = None) -> RunSnapshot:
        """Start (or, on a duplicate delivery, return) the run for an AgentTask."""
        if workflow not in GRAPH_BUILDERS:
            raise ValueError(f"unknown workflow {workflow!r}")
        if workflow == "repair" and not (failure and source_key):
            raise ValueError("repair requires `failure` and `source_key`")
        scope = ProjectScope(tenant_id=tenant_id, project_id=task.project_id)
        run = self.d.store.create_run(scope, workflow, task.id)
        if not run.created:
            return self._snapshot(run.id)
        state: dict[str, Any] = {
            "run_id": run.id, "tenant_id": tenant_id, "project_id": task.project_id, "user_id": task.user_id,
            "agent_task_id": task.id, "workflow": workflow, "request": task.prompt, "step_count": 0,
        }
        if failure:
            state.update(failure=failure, source_key=source_key)
        with self.lock.hold(run.id):
            return self._advance(run, state)

    def respond(self, scope: ProjectScope, run_id: str, reply: dict) -> RunSnapshot:
        """Deliver a human answer (clarification answers or plan approval)."""
        run = self.d.store.get_run(scope, run_id)
        if run is None:
            raise LookupError("run not found")
        with self.lock.hold(run_id):
            run = self.d.store.get_run(scope, run_id)
            if run is None or run.status not in HUMAN_WAITS:
                raise ValueError("run is not waiting for user input")
            return self._advance(run, Command(resume=reply))

    def cancel(self, scope: ProjectScope, run_id: str) -> RunSnapshot:
        run = self.d.store.get_run(scope, run_id)
        if run is None:
            raise LookupError("run not found")
        self.d.store.set_status(run_id, RunStatus.CANCELLED, error={"code": "cancelled", "message": "cancelled by user"})
        return self._snapshot(run_id)

    def status(self, scope: ProjectScope, run_id: str) -> RunSnapshot | None:
        return self._snapshot(run_id) if self.d.store.get_run(scope, run_id) else None

    # ---- results from other services ------------------------------------------------------------
    def on_coding_result(self, result: CodingResult) -> RunSnapshot | None:
        return self._on_result(result.coding_task_id, result.model_dump(mode="json"))

    def on_build_result(self, result: BuildResult) -> RunSnapshot | None:
        return self._on_result(result.build_job_id, result.model_dump(mode="json"))

    def on_test_result(self, result: TestResult) -> RunSnapshot | None:
        return self._on_result(result.test_job_id, result.model_dump(mode="json"))

    def _on_result(self, external_id: str, payload: dict) -> RunSnapshot | None:
        """Store first (durable, idempotent), then wake the run if it is waiting."""
        job, first = self.d.store.complete_job(external_id, payload)
        if job is None:
            log.warning("result for unknown job %s ignored", external_id)
            return None
        if not first:
            return None  # duplicate delivery
        return self._wake(job.run_id)

    def _wake(self, run_id: str) -> RunSnapshot | None:
        with self.lock.hold(run_id):
            status = self.d.store.status_of(run_id)
            if status not in JOB_WAITS:
                return None  # not waiting yet: the await node will find the stored result
            run = self.d.store.run_by_id(run_id)
            return self._advance(run, Command(resume=True)) if run else None

    # ---- recovery ---------------------------------------------------------------------------------
    def recover(self, stale_seconds: int = 300) -> list[str]:
        """Resume runs interrupted by a crash and re-wake runs whose result was stored but
        never delivered. Call periodically (Celery beat) and on worker start."""
        touched: list[str] = []
        for run in self.d.store.stale_running(stale_seconds):
            with self.lock.hold(run.id):
                if self.d.store.status_of(run.id) == RunStatus.RUNNING:
                    log.info("recovering run %s from checkpoint", run.id)
                    self._advance(run, None)  # None = continue from the last checkpoint
                    touched.append(run.id)
        for run in self.d.store.runs_with_status(list(JOB_WAITS)):
            if self._has_done_pending_job(run):
                self._wake(run.id)
                touched.append(run.id)
        return touched

    def _has_done_pending_job(self, run: RunRecord) -> bool:
        """True if the run waits on a job whose result is already stored."""
        st = self.graphs[run.workflow].get_state(self._cfg(run.id)).values
        if not st:
            return False
        if run.status == RunStatus.WAITING_CODING:
            j = self.d.store.get_job(run.id, JobKind.CODING, f"{st['queue'][st['cursor']]['key']}#{st.get('coding_attempt', 0)}")
            return bool(j and j.state == "done")
        rnd = st.get("val_round", 0)
        kinds = [(JobKind.BUILD, "build")] + ([(JobKind.TEST, "test")] if self.d.limits.require_tests else [])
        return all((j := self.d.store.get_job(run.id, k, f"{n}#{rnd}")) and j.state == "done" for k, n in kinds)
