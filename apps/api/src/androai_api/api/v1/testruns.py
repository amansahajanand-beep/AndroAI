from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_storage import ObjectStorage

from ...db import get_db
from ...deps import AuthContext, get_owned_project, get_storage, require_permission
from ...errors import AppError
from ...models import TestJob, TestReport, TestResult
from ...schemas import Page
from ...schemas_jobs import TestCreateIn, TestOut, TestResultOut
from ...services import dispatch, scheduler
from ...services.views import tests_out
from ...services.notify import ResultNotifier, get_notifier
from .builds import owned_job

router = APIRouter(tags=["tests"])
run = require_permission("builds:run")


@router.post("", response_model=TestOut, status_code=201)
def create_test(body: TestCreateIn, ctx: AuthContext = Depends(run), db: Session = Depends(get_db),
                storage: ObjectStorage = Depends(get_storage)):
    """Queue a test job. Emulator/instrumented jobs become `blocked` (with the reason) when no
    KVM-capable worker is registered; they are never reported as passed without running."""
    project = get_owned_project(db, ctx, body.project_id)
    job = scheduler.submit_test(db, storage, project, user_id=ctx.user_id, kind=body.kind,
                                priority=body.priority, timeout_seconds=body.timeout_seconds,
                                build_job_id=body.build_job_id, emulator_profile=body.emulator_profile)
    return tests_out(db, [job])[0]


@router.get("", response_model=Page[TestOut])
def list_tests(project_id: str | None = None, state: str | None = Query(default=None, max_length=16),
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    q = select(TestJob).where(TestJob.tenant_id == ctx.tenant_id)
    if project_id:
        q = q.where(TestJob.project_id == project_id)
    if state:
        q = q.where(TestJob.state == state)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = tests_out(db, list(db.scalars(q.order_by(TestJob.created_at.desc(), TestJob.id).limit(limit).offset(offset))))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=TestOut)
def get_test(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    return tests_out(db, [owned_job(db, ctx, TestJob, job_id)])[0]


@router.post("/{job_id}/cancel", response_model=TestOut)
def cancel_test(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db),
                storage: ObjectStorage = Depends(get_storage), notifier: ResultNotifier = Depends(get_notifier)):
    job = owned_job(db, ctx, TestJob, job_id)
    dispatch.cancel(db, storage, notifier, job, actor_id=ctx.user_id)
    return tests_out(db, [job])[0]


@router.get("/{job_id}/result", response_model=TestResultOut)
def test_result(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    job = owned_job(db, ctx, TestJob, job_id)
    res = db.scalars(select(TestResult).where(TestResult.test_job_id == job.id)).first()
    if res is None:
        raise AppError(404, "result_not_ready", "The test run has not finished")
    return res


@router.get("/{job_id}/reports")
def test_reports(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    job = owned_job(db, ctx, TestJob, job_id)
    return [{"id": r.id, "format": r.format, "size": r.size, "created_at": r.created_at}
            for r in db.scalars(select(TestReport).where(TestReport.test_job_id == job.id))]
