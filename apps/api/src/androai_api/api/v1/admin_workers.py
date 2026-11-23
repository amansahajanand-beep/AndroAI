import secrets

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import AuthContext, require_permission
from ...errors import AppError
from ...models import BuildJob, TestJob, WorkerRegistry
from ...schemas_jobs import QueueStatsOut, WorkerCreatedOut, WorkerCreateIn, WorkerOut, WorkerPatchIn
from ...security import hash_token
from ...services import dispatch
from ...services.audit import audit
from ...services.scheduler import worker_is_live

router = APIRouter(tags=["admin"])
perm = require_permission("admin:workers")


def _out(db: Session, w: WorkerRegistry, cls=WorkerOut, **extra):
    base = WorkerOut.model_validate(w).model_dump()
    base.update(live=worker_is_live(w), active_jobs=dispatch.worker_active_jobs(db, w.id), **extra)
    return cls(**base)


def _new_token() -> str:
    return "wk_" + secrets.token_urlsafe(32)


@router.post("/workers", response_model=WorkerCreatedOut, status_code=201)
def create_worker(body: WorkerCreateIn, ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)):
    token = _new_token()
    w = WorkerRegistry(name=body.name, kind=body.kind, provider=body.provider, capacity=body.capacity,
                       token_hash=hash_token(token), status="offline")
    db.add(w)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "worker_exists", "A worker with this name already exists") from None
    audit(db, "worker.create", actor_id=ctx.user_id, resource_type="worker", resource_id=w.id, ip=ctx.ip,
          detail={"name": w.name, "kind": w.kind})
    db.commit()
    return _out(db, w, WorkerCreatedOut, token=token)


@router.get("/workers", response_model=list[WorkerOut])
def list_workers(ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)):
    return [_out(db, w) for w in db.scalars(select(WorkerRegistry).order_by(WorkerRegistry.name))]


def _get(db: Session, worker_id: str) -> WorkerRegistry:
    w = db.get(WorkerRegistry, worker_id)
    if w is None:
        raise AppError(404, "worker_not_found", "Worker not found")
    return w


@router.patch("/workers/{worker_id}", response_model=WorkerOut)
def patch_worker(worker_id: str, body: WorkerPatchIn, ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)):
    """`draining=true` stops new claims; running jobs finish (use before maintenance / scale-down)."""
    w = _get(db, worker_id)
    if body.capacity is not None:
        w.capacity = body.capacity
    if body.draining is not None:
        w.draining = body.draining
    audit(db, "worker.update", actor_id=ctx.user_id, resource_type="worker", resource_id=w.id, ip=ctx.ip,
          detail=body.model_dump(exclude_none=True))
    db.commit()
    return _out(db, w)


@router.post("/workers/{worker_id}/rotate-token", response_model=WorkerCreatedOut)
def rotate_token(worker_id: str, ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)):
    w = _get(db, worker_id)
    token = _new_token()
    w.token_hash = hash_token(token)
    audit(db, "worker.rotate_token", actor_id=ctx.user_id, resource_type="worker", resource_id=w.id, ip=ctx.ip)
    db.commit()
    return _out(db, w, WorkerCreatedOut, token=token)


@router.delete("/workers/{worker_id}", status_code=204)
def delete_worker(worker_id: str, ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)) -> Response:
    w = _get(db, worker_id)
    if dispatch.worker_active_jobs(db, w.id):
        raise AppError(409, "worker_busy", "Drain the worker and wait for its jobs to finish first")
    audit(db, "worker.delete", actor_id=ctx.user_id, resource_type="worker", resource_id=w.id, ip=ctx.ip,
          detail={"name": w.name})
    db.delete(w)
    db.commit()
    return Response(status_code=204)


@router.get("/queues", response_model=QueueStatsOut)
def queue_stats(ctx: AuthContext = Depends(perm), db: Session = Depends(get_db)):
    queues: dict[str, dict[str, int]] = {"build": {}, "test": {}, "emulator": {}}
    for state, n in db.execute(select(BuildJob.state, func.count()).group_by(BuildJob.state)):
        queues["build"][state] = n
    for kind, state, n in db.execute(select(TestJob.kind, TestJob.state, func.count()).group_by(TestJob.kind, TestJob.state)):
        q = "emulator" if kind in ("instrumented", "emulator") else "test"
        queues[q][state] = queues[q].get(state, 0) + n
    workers: dict[str, dict[str, int]] = {}
    for w in db.scalars(select(WorkerRegistry)):
        status = "live" if worker_is_live(w) else "offline"
        workers.setdefault(w.kind, {}).setdefault(status, 0)
        workers[w.kind][status] += 1
    return QueueStatsOut(queues=queues, workers=workers)
