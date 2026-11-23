from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_storage import ObjectStorage

from ...db import get_db
from ...deps import AuthContext, get_owned_project, get_storage, require_permission
from ...errors import AppError
from ...models import BuildJob, BuildLog, BuildResult
from ...schemas import Page
from ...schemas_jobs import BuildCreateIn, BuildOut, BuildResultOut, LogChunkOut
from ...services import dispatch, scheduler
from ...services.notify import ResultNotifier, get_notifier

router = APIRouter(tags=["builds"])
run = require_permission("builds:run")


def owned_job(db: Session, ctx: AuthContext, model, job_id: str):
    job = db.scalars(select(model).where(model.id == job_id, model.tenant_id == ctx.tenant_id)).first()
    if job is None:
        raise AppError(404, "job_not_found", "Job not found")
    return job


@router.post("", response_model=BuildOut, status_code=201)
def create_build(body: BuildCreateIn, ctx: AuthContext = Depends(run), db: Session = Depends(get_db),
                 storage: ObjectStorage = Depends(get_storage)):
    """Queue a build of the project's current files. Release builds are unsigned."""
    project = get_owned_project(db, ctx, body.project_id)
    return scheduler.submit_build(db, storage, project, user_id=ctx.user_id, variant=body.variant,
                                  output_type=body.output_type, gradle_tasks=body.gradle_tasks,
                                  priority=body.priority, timeout_seconds=body.timeout_seconds)


@router.get("", response_model=Page[BuildOut])
def list_builds(project_id: str | None = None, state: str | None = Query(default=None, max_length=16),
                limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    q = select(BuildJob).where(BuildJob.tenant_id == ctx.tenant_id)
    if project_id:
        q = q.where(BuildJob.project_id == project_id)
    if state:
        q = q.where(BuildJob.state == state)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(BuildJob.created_at.desc(), BuildJob.id).limit(limit).offset(offset)))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=BuildOut)
def get_build(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    return owned_job(db, ctx, BuildJob, job_id)


@router.post("/{job_id}/cancel", response_model=BuildOut)
def cancel_build(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db),
                 storage: ObjectStorage = Depends(get_storage), notifier: ResultNotifier = Depends(get_notifier)):
    job = owned_job(db, ctx, BuildJob, job_id)
    dispatch.cancel(db, storage, notifier, job, actor_id=ctx.user_id)
    return job


@router.get("/{job_id}/logs", response_model=list[LogChunkOut])
def build_logs(job_id: str, after_seq: int = Query(-1, ge=-1), limit: int = Query(200, ge=1, le=1000),
               ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    """Poll with the last seen `seq` to tail a running build."""
    job = owned_job(db, ctx, BuildJob, job_id)
    return list(db.scalars(select(BuildLog).where(BuildLog.build_job_id == job.id, BuildLog.seq > after_seq)
                           .order_by(BuildLog.seq).limit(limit)))


@router.get("/{job_id}/result", response_model=BuildResultOut)
def build_result(job_id: str, ctx: AuthContext = Depends(run), db: Session = Depends(get_db)):
    job = owned_job(db, ctx, BuildJob, job_id)
    res = db.scalars(select(BuildResult).where(BuildResult.build_job_id == job.id)).first()
    if res is None:
        raise AppError(404, "result_not_ready", "The build has not finished")
    return res
