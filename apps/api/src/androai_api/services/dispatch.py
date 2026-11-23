"""Runtime half of the scheduler: claiming, leases, heartbeats, logs, completion, cancellation
and housekeeping. Submission and placement live in `scheduler.py`; see its docstring for the
state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_android_tools import Environment, Requirements, select_jdk
from androai_contracts import BuildResult, ErrorInfo, TaskState, TestResult
from androai_storage import ObjectStorage, keys

from ..config import get_settings
from ..errors import AppError
from ..models import (BuildJob, BuildLog, BuildResult as BuildResultRow, BuildUsage, ProjectArtifact, TestJob,
                      TestResult as TestResultRow, WorkerHeartbeat, WorkerRegistry)
from .audit import audit
from .notify import ResultNotifier
from .scheduler import (ACTIVE, EMULATOR_KINDS, TERMINAL, _can_run, blocked_reason, model_for, worker_is_live,
                        worker_kind_for_test)

_STATE_MAP = {"completed": TaskState.SUCCEEDED, "failed": TaskState.FAILED, "cancelled": TaskState.CANCELLED}
RETRYABLE_CODES = ("worker_lost", "infrastructure")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _usage_kind(job) -> str:
    return "build" if isinstance(job, BuildJob) else worker_kind_for_test(job.kind)


# ------------------------------------------------------------------ claiming

def _tenant_active(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in (BuildJob, TestJob):
        for tenant, n in db.execute(select(m.tenant_id, func.count()).where(m.state.in_(ACTIVE)).group_by(m.tenant_id)):
            counts[tenant] = counts.get(tenant, 0) + n
    return counts


def worker_active_jobs(db: Session, worker_id: str) -> int:
    return sum(db.scalar(select(func.count()).select_from(m).where(m.worker_id == worker_id, m.state.in_(ACTIVE))) or 0
               for m in (BuildJob, TestJob))


def selected_jdk(job, worker: WorkerRegistry) -> int | None:
    r = (job.toolchain or {}).get("required") or {}
    req = Requirements(jdk=r.get("jdk"), max_jdk=r.get("max_jdk"), compile_sdk=r.get("compile_sdk"), agp=r.get("agp"),
                       gradle=r.get("gradle"), kotlin=r.get("kotlin"))
    return select_jdk(req, Environment.from_dict(worker.toolchain))[0]


def claim_next(db: Session, worker: WorkerRegistry):
    """Atomically lease the best eligible job to `worker`, or return None.

    Order: priority (lower first), then FIFO. Skips jobs this worker's toolchain cannot run and
    tenants already at their concurrent-job limit (fairness: one user cannot occupy every
    worker). `FOR UPDATE SKIP LOCKED` makes concurrent claims safe on PostgreSQL."""
    s, now = get_settings(), _now()
    if worker.draining or worker_active_jobs(db, worker.id) >= worker.capacity:
        return None
    model = BuildJob if worker.kind == "build" else TestJob
    stmt = select(model).where(model.state == "queued", (model.not_before.is_(None)) | (model.not_before <= now))
    if model is TestJob:
        emu = TestJob.kind.in_(EMULATOR_KINDS)
        stmt = stmt.where(emu if worker.kind == "emulator" else ~emu)
    stmt = stmt.order_by(model.priority, model.queued_at, model.id).limit(50).with_for_update(skip_locked=True)
    active = _tenant_active(db)
    for job in db.scalars(stmt):
        if active.get(job.tenant_id, 0) >= s.max_active_jobs_per_user or not _can_run(worker.kind, job, worker):
            continue
        if model is BuildJob:
            job.toolchain = {**job.toolchain, "jdk": selected_jdk(job, worker)}
        job.state, job.worker_id, job.attempts = "starting", worker.id, job.attempts + 1
        job.started_at, job.blocked_reason = now, None
        job.lease_expires_at = now + timedelta(seconds=s.job_lease_seconds)
        worker.status = "busy"
        db.commit()
        return job
    return None


def get_worker_job(db: Session, worker: WorkerRegistry, kind: str, job_id: str):
    job = db.get(model_for(kind), job_id)
    if job is None or job.worker_id != worker.id:
        raise AppError(404, "job_not_found", "Job not found for this worker")
    return job


def _extend(job) -> None:
    job.lease_expires_at = _now() + timedelta(seconds=get_settings().job_lease_seconds)


def mark_running(db: Session, job) -> None:
    if job.state not in ACTIVE:
        raise AppError(409, "bad_state", f"Job is {job.state}")
    job.state = "running"
    _extend(job)
    db.commit()


def heartbeat(db: Session, worker: WorkerRegistry, *, load: dict | None = None) -> dict:
    """Record liveness, extend leases of the worker's active jobs, return cancel requests."""
    worker.last_heartbeat_at = _now()
    mine = [j for m in (BuildJob, TestJob) for j in db.scalars(select(m).where(m.worker_id == worker.id, m.state.in_(ACTIVE)))]
    for j in mine:
        _extend(j)
    worker.status = "draining" if worker.draining else ("busy" if len(mine) >= worker.capacity else "idle")
    db.add(WorkerHeartbeat(worker_id=worker.id, active_jobs=len(mine), load=load or {}))
    db.commit()
    return {"cancel": [j.id for j in mine if j.cancel_requested], "active_jobs": len(mine)}


def append_log(db: Session, job, *, stream: str, content: str) -> bool:
    """Append a bounded log chunk. Returns cancel_requested so workers learn about cancellation here too."""
    if job.state not in ACTIVE:
        raise AppError(409, "bad_state", f"Job is {job.state}")
    if isinstance(job, BuildJob):
        cap = get_settings().max_log_bytes_per_job
        used, last = db.execute(select(func.coalesce(func.sum(func.length(BuildLog.content)), 0),
                                       func.coalesce(func.max(BuildLog.seq), -1)).where(BuildLog.build_job_id == job.id)).one()
        if used < cap:
            chunk = content[: cap - used]
            if len(chunk) < len(content):
                chunk += "\n[log truncated: size limit reached]\n"
            db.add(BuildLog(build_job_id=job.id, seq=last + 1, stream=stream if stream in ("stdout", "stderr") else "stdout",
                            content=chunk))
    _extend(job)
    db.commit()
    return job.cancel_requested


# ------------------------------------------------------------------ finishing

def _record_usage(db: Session, job) -> None:
    seconds = max(0.0, (_now() - (job.started_at or _now())).total_seconds())
    db.add(BuildUsage(tenant_id=job.tenant_id, user_id=job.user_id, project_id=job.project_id, job_kind=_usage_kind(job),
                      job_id=job.id, attempt=max(job.attempts, 1), runtime_seconds=seconds))


def _archive_log(db: Session, storage: ObjectStorage | None, job) -> str | None:
    if storage is None or not isinstance(job, BuildJob):
        return None
    chunks = db.scalars(select(BuildLog.content).where(BuildLog.build_job_id == job.id).order_by(BuildLog.seq)).all()
    if not chunks:
        return None
    key = keys.log_key(job.tenant_id, job.project_id, job.id)
    storage.put_bytes(key, "".join(chunks).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")
    return key


@dataclass
class Completion:
    outcome: str  # completed | failed | cancelled
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False  # infrastructure failure: worth running again elsewhere
    errors: list | None = None  # extracted compiler/Gradle errors [{file,line,message}]
    artifact_id: str | None = None
    test_outcome: str | None = None  # passed | failed | not_run | error
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    not_run_reason: str | None = None


def _finish(db: Session, storage: ObjectStorage | None, job, state: str, c: Completion | None = None,
            artifact: ProjectArtifact | None = None) -> None:
    """Terminal transition: state, result row, usage row. Caller commits, then notifies."""
    c = c or Completion(outcome=state)
    job.state, job.finished_at, job.lease_expires_at = state, _now(), None
    job.error_code = c.error_code if state != "completed" else None
    job.error_message = ((c.error_message or "")[:2000] or None) if state != "completed" else None
    duration = (job.finished_at - job.started_at).total_seconds() if job.started_at else None
    if isinstance(job, BuildJob):
        db.add(BuildResultRow(build_job_id=job.id, state=state, artifact_id=artifact.id if artifact else None,
                              log_key=_archive_log(db, storage, job), duration_seconds=duration,
                              errors=(c.errors or [])[:100]))
    else:
        outcome = c.test_outcome or ("passed" if state == "completed" else "error")
        db.add(TestResultRow(test_job_id=job.id, state=state, outcome=outcome, not_run_reason=c.not_run_reason,
                             passed=c.passed, failed=c.failed, skipped=c.skipped, duration_seconds=duration))
    if job.started_at:
        _record_usage(db, job)
    if job.worker_id and (w := db.get(WorkerRegistry, job.worker_id)) and w.status == "busy":
        w.status = "idle"
    db.flush()


def notify_finished(db: Session, notifier: ResultNotifier, job) -> None:
    """Send the contract result to orchestration (after commit; best effort)."""
    err = None
    if job.state != "completed":
        code = job.error_code or "failed"
        if isinstance(job, TestJob):
            res = db.scalars(select(TestResultRow).where(TestResultRow.test_job_id == job.id)).first()
            if res and res.outcome == "not_run":
                code = "runtime_unavailable"
        err = ErrorInfo(code=code, message=job.error_message or code, retryable=code in RETRYABLE_CODES)
    if isinstance(job, BuildJob):
        res = db.scalars(select(BuildResultRow).where(BuildResultRow.build_job_id == job.id)).first()
        art = db.get(ProjectArtifact, res.artifact_id) if res and res.artifact_id else None
        notifier.build_finished(BuildResult(build_job_id=job.id, state=_STATE_MAP[job.state],
                                            artifact_key=art.storage_key if art else None,
                                            log_key=res.log_key if res else None,
                                            duration_seconds=res.duration_seconds if res else None, error=err))
    else:
        res = db.scalars(select(TestResultRow).where(TestResultRow.test_job_id == job.id)).first()
        notifier.test_finished(TestResult(test_job_id=job.id, state=_STATE_MAP[job.state],
                                          passed=res.passed if res else 0, failed=res.failed if res else 0,
                                          skipped=res.skipped if res else 0, error=err))


def _requeue(job, why: str) -> None:
    job.state, job.worker_id, job.lease_expires_at = "queued", None, None
    job.not_before = _now() + timedelta(seconds=get_settings().retry_backoff_seconds * job.attempts)
    job.blocked_reason = why[:255]
    job.queued_at = _now()


def _validate_test_completion(job: TestJob, c: Completion) -> None:
    if c.test_outcome not in ("passed", "failed", "not_run", "error"):
        raise AppError(422, "invalid_outcome", "test_outcome must be passed, failed, not_run or error")
    if c.test_outcome == "passed":
        if c.failed > 0:
            raise AppError(422, "invalid_outcome", "A run with failures cannot be 'passed'")
        if job.kind in ("unit", "instrumented", "emulator") and c.passed == 0:
            raise AppError(422, "invalid_outcome", "A test run that executed no tests cannot be 'passed'")
    if c.test_outcome == "not_run" and not c.not_run_reason:
        raise AppError(422, "invalid_outcome", "not_run requires not_run_reason")
    if (c.outcome == "completed") != (c.test_outcome == "passed"):
        raise AppError(422, "invalid_outcome", "outcome 'completed' is only valid with test_outcome 'passed'")


def complete(db: Session, storage: ObjectStorage, notifier: ResultNotifier, worker: WorkerRegistry, job, c: Completion):
    """A worker reports the end of a job. Infrastructure failures are retried (bounded);
    compile/test failures are final. Test runs that could not execute are recorded as `not_run`."""
    if job.state not in ACTIVE:
        raise AppError(409, "bad_state", f"Job is {job.state}")
    is_build = isinstance(job, BuildJob)
    if c.outcome not in _STATE_MAP:
        raise AppError(422, "invalid_outcome", "outcome must be completed, failed or cancelled")
    cancelled = job.cancel_requested and c.outcome != "completed"
    artifact = None
    if is_build and c.outcome == "completed" and not cancelled:
        artifact = db.scalars(select(ProjectArtifact).where(ProjectArtifact.id == c.artifact_id,
                                                            ProjectArtifact.build_job_id == job.id)).first() if c.artifact_id else None
        if artifact is None:
            raise AppError(422, "artifact_required", "A completed build must upload its artifact first")
    if not is_build and not cancelled:
        _validate_test_completion(job, c)
    if c.outcome == "failed" and c.retryable and not cancelled and job.attempts < job.max_attempts:
        _record_usage(db, job)  # retries cost too
        _requeue(job, f"retry after: {c.error_message or c.error_code or 'infrastructure failure'}")
        worker.status = "idle"
        db.commit()
        return job
    state = "cancelled" if cancelled else c.outcome
    _finish(db, storage, job, state, c, artifact)
    audit(db, f"job.{state}", tenant_id=job.tenant_id, resource_type=type(job).__name__, resource_id=job.id,
          detail={"worker": worker.name, "attempts": job.attempts})
    db.commit()
    notify_finished(db, notifier, job)
    return job


def cancel(db: Session, storage: ObjectStorage, notifier: ResultNotifier, job, *, actor_id: str) -> None:
    if job.state in TERMINAL:
        raise AppError(409, "already_finished", f"Job already {job.state}")
    finished = job.state in ("queued", "blocked")
    if finished:
        _finish(db, storage, job, "cancelled", Completion("cancelled", "cancelled", "Cancelled by user", test_outcome="error"))
    else:
        job.cancel_requested = True  # the worker sees it on its next heartbeat/log call and aborts
    audit(db, "job.cancel", actor_id=actor_id, tenant_id=job.tenant_id, resource_type=type(job).__name__, resource_id=job.id)
    db.commit()
    if finished:
        notify_finished(db, notifier, job)


# ------------------------------------------------------------------ housekeeping

def reap(db: Session, storage: ObjectStorage | None = None, notifier: ResultNotifier | None = None) -> dict:
    """Idempotent maintenance; run every ~15 s (CLI `sweep`, Celery beat, or cron).

    * workers silent past the heartbeat timeout -> offline
    * jobs past their timeout -> failed `timeout` (not retried)
    * jobs whose lease lapsed (worker died) -> retried with backoff, else failed `worker_lost`
    * cancel-requested jobs whose worker vanished -> cancelled
    * blocked jobs a live worker can now run -> queued; queued jobs nobody can run -> blocked
    * heartbeat rows older than 1 day pruned"""
    now = _now()
    stats = {"workers_offline": 0, "timed_out": 0, "requeued": 0, "lost": 0, "unblocked": 0, "blocked": 0}
    finished: list = []
    for w in db.scalars(select(WorkerRegistry).where(WorkerRegistry.status != "offline")):
        if not worker_is_live(w, now):
            w.status = "offline"
            stats["workers_offline"] += 1
    db.flush()
    for m in (BuildJob, TestJob):
        for job in db.scalars(select(m).where(m.state.in_(ACTIVE)).with_for_update(skip_locked=True)):
            ran = (now - job.started_at).total_seconds() if job.started_at else 0
            if ran > job.timeout_seconds:
                _finish(db, storage, job, "failed", Completion("failed", "timeout", f"Exceeded {job.timeout_seconds}s limit", test_outcome="error"))
                stats["timed_out"] += 1
                finished.append(job)
            elif job.lease_expires_at and job.lease_expires_at < now:
                if job.cancel_requested:
                    _finish(db, storage, job, "cancelled", Completion("cancelled", "cancelled", "Cancelled", test_outcome="error"))
                    finished.append(job)
                elif job.attempts < job.max_attempts:
                    _record_usage(db, job)
                    _requeue(job, "worker lost; retrying")
                    stats["requeued"] += 1
                else:
                    _finish(db, storage, job, "failed", Completion("failed", "worker_lost", "Worker stopped responding", test_outcome="error"))
                    stats["lost"] += 1
                    finished.append(job)
        for job in db.scalars(select(m).where(m.state.in_(("blocked", "queued")))):
            reason = blocked_reason(db, job)
            if job.state == "blocked" and reason is None:
                job.state, job.blocked_reason = "queued", None
                stats["unblocked"] += 1
            elif job.state == "blocked":
                job.blocked_reason = reason  # keep the explanation current
            elif job.state == "queued" and reason and job.not_before is None:
                job.state, job.blocked_reason = "blocked", reason
                stats["blocked"] += 1
    db.query(WorkerHeartbeat).filter(WorkerHeartbeat.created_at < now - timedelta(days=1)).delete()
    db.commit()
    if notifier:
        for job in finished:
            notify_finished(db, notifier, job)
    return stats
