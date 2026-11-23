"""Persistent job scheduler for build / test / emulator jobs.

State lives in PostgreSQL (`build_jobs`, `test_jobs`, `worker_registry`); there is no
in-memory queue, so API restarts lose nothing. Workers *pull*: they register, heartbeat and
claim jobs over the worker API, so they can sit behind NAT, in other clouds, or be CI
adapters. A claim takes a time-limited lease that heartbeats/log posts extend; a job whose
lease lapses is retried (bounded) or failed by `reap`.

Job states: queued -> starting -> running -> completed | failed | cancelled, plus `blocked`
(no registered worker can currently run it, e.g. no emulator-capable worker) which returns
to `queued` automatically when one appears.

Queues: "build" (BuildJob), "test" (TestJob, non-emulator), "emulator" (TestJob needing KVM).
AI tasks are scheduled by the orchestration worker's own Celery queue, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_android_tools import Environment, derive_requirements, detect, environment_supports, select_jdk
from androai_android_tools.detect import MAX_FILE_BYTES, is_relevant
from androai_contracts import BuildResult, ErrorInfo, TaskState, TestResult
from androai_storage import ObjectStorage, keys

from ..config import get_settings
from ..errors import AppError
from ..models import (BuildJob, BuildLog, BuildResult as BuildResultRow, BuildUsage, Project, ProjectFile,
                      ProjectFileSnapshot, TestJob, TestResult as TestResultRow, WorkerRegistry)
from . import projects as project_svc
from .audit import audit
from .notify import ResultNotifier

ACTIVE = ("starting", "running")
PENDING = ("queued", "blocked", "starting", "running")
TERMINAL = ("completed", "failed", "cancelled")
EMULATOR_KINDS = ("instrumented", "emulator")
_TASK_RE = re.compile(r"^[A-Za-z0-9:_.\-]{1,100}$")
_OUTCOMES = {"completed": TaskState.SUCCEEDED, "failed": TaskState.FAILED, "cancelled": TaskState.CANCELLED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def worker_kind_for_test(kind: str) -> str:
    return "emulator" if kind in EMULATOR_KINDS else "test"


def model_for(kind: str):
    """Path/URL job kind ('build' | 'test') -> table."""
    if kind == "build":
        return BuildJob
    if kind == "test":
        return TestJob
    raise AppError(404, "unknown_job_kind", "Unknown job kind")


# ------------------------------------------------------------------ workers

def worker_is_live(w: WorkerRegistry, now: datetime | None = None) -> bool:
    now = now or _now()
    return (w.last_heartbeat_at is not None and w.status != "offline"
            and w.last_heartbeat_at >= now - timedelta(seconds=get_settings().worker_heartbeat_timeout_seconds))


def _live_workers(db: Session, kind: str) -> list[WorkerRegistry]:
    rows = db.scalars(select(WorkerRegistry).where(WorkerRegistry.kind == kind, WorkerRegistry.draining.is_(False)))
    now = _now()
    return [w for w in rows if worker_is_live(w, now)]


def _can_run(job_kind: str, job, w: WorkerRegistry) -> bool:
    if job_kind == "emulator":
        return bool(w.capabilities.get("kvm")) and bool(w.capabilities.get("emulator"))
    req = (job.toolchain or {}).get("required")
    return environment_supports(req, Environment.from_dict(w.toolchain)) if req else True


def _job_queue(job) -> str:
    if isinstance(job, BuildJob):
        return "build"
    return worker_kind_for_test(job.kind)


def blocked_reason(db: Session, job) -> str | None:
    """None if some live worker could run this job now, else a human-readable reason."""
    queue = _job_queue(job)
    workers = _live_workers(db, queue)
    if not workers:
        return f"no live {queue} worker is registered"
    if not any(_can_run(queue, job, w) for w in workers):
        if queue == "emulator":
            return "no worker with KVM and an emulator is available; runtime testing cannot run"
        req = (job.toolchain or {}).get("required") or {}
        return f"no {queue} worker supports this project's toolchain (JDK {req.get('jdk')}, compileSdk {req.get('compile_sdk')})"
    return None


# ------------------------------------------------------------------ submission

def _check_limits(db: Session, tenant_id: str) -> None:
    s = get_settings()
    pending = sum(
        db.scalar(select(func.count()).select_from(m).where(m.tenant_id == tenant_id, m.state.in_(PENDING))) or 0
        for m in (BuildJob, TestJob)
    )
    if pending >= s.max_pending_jobs_per_user:
        raise AppError(429, "queue_limit", f"You already have {pending} pending jobs; wait for some to finish")
    depth = sum(db.scalar(select(func.count()).select_from(m).where(m.state == "queued")) or 0 for m in (BuildJob, TestJob))
    if depth >= s.max_queue_depth:
        raise AppError(503, "queue_full", "The build queue is full, try again shortly")


def analyze_snapshot(db: Session, storage: ObjectStorage, project: Project) -> dict:
    """Detect toolchain requirements from the project's current build files (small files only)."""
    rows = [r for r in db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id))
            if is_relevant(r.path) and r.size <= MAX_FILE_BYTES]
    files = {r.path: storage.get_bytes(keys.assert_key_in_tenant(r.storage_key, project.tenant_id)) for r in rows}
    detected = detect(files)
    req = derive_requirements(detected)
    return {"detected": detected.as_dict(), "required": req.as_dict()}


def _prepare(db: Session, storage: ObjectStorage, project: Project, user_id: str, *, needs_toolchain: bool):
    _check_limits(db, project.tenant_id)
    snap = project_svc.create_snapshot(db, storage, project, user_id=user_id, label="job")
    toolchain: dict = {}
    if needs_toolchain:
        toolchain = analyze_snapshot(db, storage, project)
        problems = toolchain["required"]["problems"]
        if problems:
            raise AppError(422, "unsupported_project", "; ".join(problems))
    return snap, toolchain


def _validate_tasks(tasks: list[str]) -> list[str]:
    if not tasks or len(tasks) > 10 or not all(_TASK_RE.match(t) and not t.startswith("-") for t in tasks):
        raise AppError(422, "invalid_gradle_tasks", "Gradle tasks must be plain task names (no options)")
    return tasks


def submit_build(db: Session, storage: ObjectStorage, project: Project, *, user_id: str, variant: str,
                 output_type: str, gradle_tasks: list[str] | None, priority: int, timeout_seconds: int,
                 agent_run_id: str | None = None) -> BuildJob:
    """Variant `release` produces an UNSIGNED artifact: signing keys are never available to
    build workers; release signing is a separate, authorised operation (not implemented yet)."""
    cap = variant.capitalize()
    tasks = _validate_tasks(gradle_tasks if gradle_tasks is not None
                            else [f"bundle{cap}" if output_type == "aab" else f"assemble{cap}"])
    snap, toolchain = _prepare(db, storage, project, user_id, needs_toolchain=True)
    job = BuildJob(tenant_id=project.tenant_id, user_id=user_id, project_id=project.id, snapshot_id=snap.id,
                   variant=variant, output_type=output_type, gradle_tasks=tasks, toolchain=toolchain,
                   priority=priority, timeout_seconds=timeout_seconds, agent_run_id=agent_run_id,
                   max_attempts=2, queued_at=_now(), state="queued")
    _place(db, job)
    project_svc.log_activity(db, project, user_id, "build.submit", job_id=job.id, variant=variant)
    audit(db, "build.submit", actor_id=user_id, tenant_id=project.tenant_id, resource_type="build_job", resource_id=job.id)
    db.commit()
    return job


def submit_test(db: Session, storage: ObjectStorage, project: Project, *, user_id: str, kind: str, priority: int,
                timeout_seconds: int, build_job_id: str | None = None, emulator_profile: dict | None = None,
                agent_run_id: str | None = None) -> TestJob:
    if build_job_id:
        b = db.scalars(select(BuildJob).where(BuildJob.id == build_job_id, BuildJob.tenant_id == project.tenant_id,
                                              BuildJob.project_id == project.id)).first()
        if b is None:
            raise AppError(404, "build_not_found", "Build job not found")
    snap, toolchain = _prepare(db, storage, project, user_id, needs_toolchain=kind not in EMULATOR_KINDS)
    if kind in EMULATOR_KINDS and not build_job_id:
        raise AppError(422, "build_required", "Instrumented/emulator tests need a completed build_job_id with an APK")
    job = TestJob(tenant_id=project.tenant_id, user_id=user_id, project_id=project.id, snapshot_id=snap.id,
                  kind=kind, build_job_id=build_job_id, emulator_profile=emulator_profile, toolchain=toolchain,
                  priority=priority, timeout_seconds=timeout_seconds, agent_run_id=agent_run_id,
                  max_attempts=2, queued_at=_now(), state="queued")
    _place(db, job)
    project_svc.log_activity(db, project, user_id, "test.submit", job_id=job.id, kind=kind)
    audit(db, "test.submit", actor_id=user_id, tenant_id=project.tenant_id, resource_type="test_job", resource_id=job.id)
    db.commit()
    return job


def _place(db: Session, job) -> None:
    db.add(job)
    db.flush()
    reason = blocked_reason(db, job)
    if reason:
        job.state, job.blocked_reason = "blocked", reason
