"""Run/step/artifact/usage/job persistence on SQLAlchemy.

The Engine is injected (PostgreSQL in deployment, SQLite in tests); this module
creates no connections of its own. Tables are namespaced `orch_*` and live on their
own MetaData; Person 4 registers them with Alembic (see docs/AI_ORCHESTRATION_PROGRESS.md).
`create_all` is for tests/dev only.

Every read/write is scoped by (tenant_id, project_id): a run id from another tenant
is indistinguishable from a missing one. Stores metadata, plans and tokens - never
project source code or secrets."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import (
    JSON, DateTime, Engine, Float, ForeignKey, Index, Integer, MetaData, String, Text,
    UniqueConstraint, select, update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..intelligence.models import ProjectScope
from ..providers.budget import UsageRecord

JsonType = JSON().with_variant(JSONB(), "postgresql")


class OrchBase(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s",
    })


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class RunStatus:
    RUNNING = "running"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CODING = "waiting_coding"
    WAITING_VALIDATION = "waiting_validation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TERMINAL = {SUCCEEDED, FAILED, CANCELLED}


class JobKind:
    CODING = "coding"
    BUILD = "build"
    TEST = "test"


class AgentRun(OrchBase):
    __tablename__ = "orch_agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[str] = mapped_column(String(64))
    agent_task_id: Mapped[str] = mapped_column(String(64))  # AgentTask.id; idempotency key for start
    workflow: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.RUNNING)
    error: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_task_id", name="uq_orch_runs_tenant_task"),
        Index("ix_orch_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_orch_runs_status", "status"),
    )


class AgentStep(OrchBase):
    __tablename__ = "orch_agent_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("orch_agent_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # ok | error | interrupted
    detail: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentArtifact(OrchBase):
    """Versioned plans/decisions: requirements, architecture, task_graph, modification_plan,
    repair_plan, context_refs, approval, classification."""

    __tablename__ = "orch_agent_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("orch_agent_runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict | list] = mapped_column(JsonType)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("run_id", "kind", "version", name="uq_orch_artifacts_run_kind_ver"),)


class AgentUsage(OrchBase):
    __tablename__ = "orch_agent_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("orch_agent_runs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    task_kind: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentJob(OrchBase):
    """Work handed to another service (coding/build/test) and its result."""

    __tablename__ = "orch_agent_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("orch_agent_runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(128))  # task key / attempt label within the run
    external_id: Mapped[str] = mapped_column(String(64), unique=True)  # CodingTask.id / BuildJob.id / TestJob.id
    state: Mapped[str] = mapped_column(String(16), default="pending")  # pending | submitted | done
    request: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("run_id", "kind", "key", name="uq_orch_jobs_run_kind_key"),)


class RunRecord(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    agent_task_id: str
    workflow: str
    status: str
    error: dict | None = None
    result: dict | None = None
    created: bool = False  # True when this call created the run

    @property
    def scope(self) -> ProjectScope:
        return ProjectScope(tenant_id=self.tenant_id, project_id=self.project_id)


class JobRecord(BaseModel):
    run_id: str
    kind: str
    key: str
    external_id: str
    state: str
    request: dict | None = None
    result: dict | None = None


def _run(r: AgentRun, created: bool = False) -> RunRecord:
    return RunRecord(id=r.id, tenant_id=r.tenant_id, project_id=r.project_id, agent_task_id=r.agent_task_id,
                     workflow=r.workflow, status=r.status, error=r.error, result=r.result, created=created)


def _job(j: AgentJob) -> JobRecord:
    return JobRecord(run_id=j.run_id, kind=j.kind, key=j.key, external_id=j.external_id, state=j.state,
                     request=j.request, result=j.result)


class RunStore:
    def __init__(self, engine: Engine):
        self._sf = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self) -> None:
        """Dev/test only. Deployments use Alembic."""
        OrchBase.metadata.create_all(self._sf.kw["bind"])

    # ---- runs --------------------------------------------------------------------
    def create_run(self, scope: ProjectScope, workflow: str, agent_task_id: str) -> RunRecord:
        """Idempotent on (tenant, agent_task_id): a retried delivery returns the existing run."""
        with self._sf() as s:
            existing = s.scalar(select(AgentRun).where(
                AgentRun.tenant_id == scope.tenant_id, AgentRun.agent_task_id == agent_task_id))
            if existing:
                if existing.project_id != scope.project_id:
                    raise PermissionError("agent_task_id already used for a different project")
                return _run(existing)
            run = AgentRun(id=str(uuid.uuid4()), tenant_id=scope.tenant_id, project_id=scope.project_id,
                           agent_task_id=agent_task_id, workflow=workflow)
            s.add(run)
            s.commit()
            return _run(run, created=True)

    def get_run(self, scope: ProjectScope, run_id: str) -> RunRecord | None:
        with self._sf() as s:
            r = s.get(AgentRun, run_id)
            if not r or r.tenant_id != scope.tenant_id or r.project_id != scope.project_id:
                return None
            return _run(r)

    def set_status(self, run_id: str, status: str, error: dict | None = None, result: dict | None = None) -> None:
        """Terminal states are final: they are never overwritten."""
        with self._sf() as s:
            r = s.get(AgentRun, run_id)
            if r is None or r.status in RunStatus.TERMINAL:
                return
            r.status = status
            if error is not None:
                r.error = error
            if result is not None:
                r.result = result
            r.updated_at = _now()
            s.commit()

    def stale_running(self, older_than_seconds: int) -> list[RunRecord]:
        """Runs stuck in `running` (worker died mid-node): candidates for recovery."""
        cutoff = _now() - timedelta(seconds=older_than_seconds)
        with self._sf() as s:
            rows = s.scalars(select(AgentRun).where(AgentRun.status == RunStatus.RUNNING)).all()
            return [_run(r) for r in rows if _aware(r.updated_at) < cutoff]

    def run_by_id(self, run_id: str) -> RunRecord | None:
        """Internal (service-to-service) lookup without a scope; never expose to user requests."""
        with self._sf() as s:
            r = s.get(AgentRun, run_id)
            return _run(r) if r else None

    def status_of(self, run_id: str) -> str | None:
        with self._sf() as s:
            r = s.get(AgentRun, run_id)
            return r.status if r else None

    def runs_with_status(self, statuses: list[str]) -> list[RunRecord]:
        with self._sf() as s:
            return [_run(r) for r in s.scalars(select(AgentRun).where(AgentRun.status.in_(statuses)))]

    def touch(self, run_id: str) -> None:
        with self._sf() as s:
            s.execute(update(AgentRun).where(AgentRun.id == run_id).values(updated_at=_now()))
            s.commit()

    # ---- steps / artifacts / usage ----------------------------------------------
    def add_step(self, run_id: str, node: str, status: str, detail: dict | None = None) -> None:
        with self._sf() as s:
            n = len(s.scalars(select(AgentStep.id).where(AgentStep.run_id == run_id)).all())
            s.add(AgentStep(run_id=run_id, seq=n + 1, node=node, status=status, detail=detail))
            s.commit()

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        with self._sf() as s:
            rows = s.scalars(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)).all()
            return [{"seq": r.seq, "node": r.node, "status": r.status, "detail": r.detail} for r in rows]

    def save_artifact(self, run_id: str, kind: str, data: dict | list) -> int:
        with self._sf() as s:
            last = s.scalars(select(AgentArtifact.version).where(
                AgentArtifact.run_id == run_id, AgentArtifact.kind == kind).order_by(AgentArtifact.version.desc())).first()
            v = (last or 0) + 1
            s.add(AgentArtifact(run_id=run_id, kind=kind, version=v, data=data))
            s.commit()
            return v

    def latest_artifact(self, run_id: str, kind: str) -> dict | list | None:
        with self._sf() as s:
            row = s.scalars(select(AgentArtifact).where(
                AgentArtifact.run_id == run_id, AgentArtifact.kind == kind).order_by(AgentArtifact.version.desc())).first()
            return row.data if row else None

    def record_usage(self, run_id: str, rec: UsageRecord) -> None:
        with self._sf() as s:
            s.add(AgentUsage(run_id=run_id, provider=rec.provider, model=rec.model, task_kind=rec.task_kind,
                             input_tokens=rec.input_tokens, output_tokens=rec.output_tokens, cost_usd=rec.cost_usd))
            s.commit()

    def usage(self, run_id: str) -> list[UsageRecord]:
        with self._sf() as s:
            rows = s.scalars(select(AgentUsage).where(AgentUsage.run_id == run_id).order_by(AgentUsage.id)).all()
            return [UsageRecord(provider=r.provider, model=r.model, task_kind=r.task_kind,
                                input_tokens=r.input_tokens, output_tokens=r.output_tokens, cost_usd=r.cost_usd) for r in rows]

    # ---- jobs ----------------------------------------------------------------------
    def register_job(self, run_id: str, kind: str, key: str, external_id: str, request: dict | None = None) -> tuple[JobRecord, bool]:
        """Idempotent on (run, kind, key). Returns (job, created)."""
        with self._sf() as s:
            j = s.scalar(select(AgentJob).where(AgentJob.run_id == run_id, AgentJob.kind == kind, AgentJob.key == key))
            if j:
                return _job(j), False
            j = AgentJob(run_id=run_id, kind=kind, key=key, external_id=external_id, request=request)
            s.add(j)
            s.commit()
            return _job(j), True

    def mark_submitted(self, external_id: str) -> None:
        """pending -> submitted. A job left `pending` after a crash is re-dispatched on
        recovery (at-least-once), so receivers must be idempotent on the job id."""
        with self._sf() as s:
            j = s.scalar(select(AgentJob).where(AgentJob.external_id == external_id))
            if j and j.state == "pending":
                j.state = "submitted"
                s.commit()

    def get_job(self, run_id: str, kind: str, key: str) -> JobRecord | None:
        with self._sf() as s:
            j = s.scalar(select(AgentJob).where(AgentJob.run_id == run_id, AgentJob.kind == kind, AgentJob.key == key))
            return _job(j) if j else None

    def job_by_external_id(self, external_id: str) -> JobRecord | None:
        with self._sf() as s:
            j = s.scalar(select(AgentJob).where(AgentJob.external_id == external_id))
            return _job(j) if j else None

    def complete_job(self, external_id: str, result: dict) -> tuple[JobRecord | None, bool]:
        """Store a result once. Returns (job, first_delivery); duplicates return first_delivery=False."""
        with self._sf() as s:
            j = s.scalar(select(AgentJob).where(AgentJob.external_id == external_id))
            if j is None:
                return None, False
            if j.state == "done":
                return _job(j), False
            j.state, j.result = "done", result
            s.commit()
            return _job(j), True
