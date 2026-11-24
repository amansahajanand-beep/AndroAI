"""Build / test jobs, results, logs and the worker registry (the scheduler's state)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.types import CreatedMixin, IdType, JsonType, TimestampMixin, UTCDateTime, pk

JOB_STATES = "('queued','starting','running','completed','failed','cancelled','blocked')"


class _JobColumns(TimestampMixin):
    """Columns shared by build_jobs and test_jobs (the scheduler treats them uniformly)."""

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)  # lower = sooner
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(IdType)  # logical ref to worker_registry
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    not_before: Mapped[datetime | None] = mapped_column(UTCDateTime)
    blocked_reason: Mapped[str | None] = mapped_column(String(255))
    agent_run_id: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    # {'detected': ..., 'required': ..., 'jdk': selected at claim} for build/test jobs
    toolchain: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)


class BuildJob(Base, _JobColumns):
    __tablename__ = "build_jobs"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("project_file_snapshots.id"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # per-project sequence (build #14)
    variant: Mapped[str] = mapped_column(String(16), default="debug", nullable=False)
    output_type: Mapped[str] = mapped_column(String(8), default="apk", nullable=False)  # apk|aab
    gradle_tasks: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)

    __table_args__ = (
        CheckConstraint(f"state IN {JOB_STATES}", name="state"),
        CheckConstraint("output_type IN ('apk','aab')", name="output_type"),
        Index("ix_build_jobs_state_priority", "state", "priority", "queued_at"),
        Index("ix_build_jobs_tenant_id_state", "tenant_id", "state"),
        Index("ix_build_jobs_project_id", "project_id"),
        UniqueConstraint("project_id", "number", name="uq_build_jobs_project_id_number"),
    )


class BuildResult(Base, CreatedMixin):
    __tablename__ = "build_results"

    id: Mapped[str] = pk()
    build_job_id: Mapped[str] = mapped_column(ForeignKey("build_jobs.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("project_artifacts.id", ondelete="SET NULL"))
    log_key: Mapped[str | None] = mapped_column(String(1024))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    errors: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)  # extracted Gradle/compiler errors
    __table_args__ = (UniqueConstraint("build_job_id", name="uq_build_results_build_job_id"),)


class BuildLog(Base, CreatedMixin):
    """Streamed log chunks (bounded; the full log is archived to object storage)."""

    __tablename__ = "build_logs"

    id: Mapped[str] = pk()
    build_job_id: Mapped[str] = mapped_column(ForeignKey("build_jobs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stream: Mapped[str] = mapped_column(String(8), default="stdout", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("build_job_id", "seq", name="uq_build_logs_build_job_id_seq"),)


class TestJob(Base, _JobColumns):
    __test__ = False
    __tablename__ = "test_jobs"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("project_file_snapshots.id"), nullable=False
    )
    build_job_id: Mapped[str | None] = mapped_column(ForeignKey("build_jobs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), default="unit", nullable=False)
    emulator_profile: Mapped[dict | None] = mapped_column(JsonType)

    __table_args__ = (
        CheckConstraint(f"state IN {JOB_STATES}", name="state"),
        CheckConstraint("kind IN ('static','compile','unit','instrumented','emulator')", name="kind"),
        Index("ix_test_jobs_state_priority", "state", "priority", "queued_at"),
        Index("ix_test_jobs_tenant_id_state", "tenant_id", "state"),
        Index("ix_test_jobs_project_id", "project_id"),
    )


class TestResult(Base, CreatedMixin):
    __test__ = False
    __tablename__ = "test_results"

    id: Mapped[str] = pk()
    test_job_id: Mapped[str] = mapped_column(ForeignKey("test_jobs.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    # 'not_run' + reason is how an unavailable runtime is reported; never recorded as passed.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # passed|failed|not_run|error
    not_run_reason: Mapped[str | None] = mapped_column(String(255))
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("test_job_id", name="uq_test_results_test_job_id"),
        CheckConstraint("outcome IN ('passed','failed','not_run','error')", name="outcome"),
    )


class TestReport(Base, CreatedMixin):
    __test__ = False
    __tablename__ = "test_reports"

    id: Mapped[str] = pk()
    test_job_id: Mapped[str] = mapped_column(ForeignKey("test_jobs.id", ondelete="CASCADE"), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)  # junit_xml|html|json|logcat
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (Index("ix_test_reports_test_job_id", "test_job_id"),)


class WorkerRegistry(Base, CreatedMixin):
    __tablename__ = "worker_registry"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # build|test|emulator
    provider: Mapped[str] = mapped_column(String(24), nullable=False)  # docker|vps|cloud_vm|external_ci
    status: Mapped[str] = mapped_column(String(16), default="idle", nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # concurrent jobs
    toolchain: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)  # jdk/gradle/agp/sdk offered
    capabilities: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)  # e.g. kvm, emulator
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # worker credential, hash only
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    draining: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", name="uq_worker_registry_name"),
        UniqueConstraint("token_hash", name="uq_worker_registry_token_hash"),
        CheckConstraint("kind IN ('build','test','emulator')", name="kind"),
        CheckConstraint("status IN ('idle','busy','unhealthy','offline','draining')", name="status"),
        Index("ix_worker_registry_kind_status", "kind", "status"),
    )


class WorkerHeartbeat(Base, CreatedMixin):
    __tablename__ = "worker_heartbeats"

    id: Mapped[str] = pk()
    worker_id: Mapped[str] = mapped_column(ForeignKey("worker_registry.id", ondelete="CASCADE"), nullable=False)
    active_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    load: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)  # cpu/ram/disk
    __table_args__ = (Index("ix_worker_heartbeats_worker_id_created_at", "worker_id", "created_at"),)
