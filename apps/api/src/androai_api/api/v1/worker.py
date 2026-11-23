"""Worker protocol (pull model). Authenticated by a per-worker bearer token, never by a user token.

Build workers run untrusted code, so they get NO storage or database credentials: the API
hands them the source snapshot and receives logs/artifacts over this API, scoped to the one
job they currently hold.
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from androai_storage import ObjectStorage, keys

from ...config import get_settings
from ...db import get_db
from ...errors import AppError
from ...models import (BuildJob, ProjectArtifact, ProjectFileSnapshot, TestJob, TestReport, WorkerRegistry,
                       BuildResult)
from ...schemas_jobs import CompleteIn, HeartbeatIn, LogIn, WorkerRegisterIn
from ...security import hash_token
from ...services import dispatch
from ...services import projects as project_svc
from ...services.notify import ResultNotifier, get_notifier
from ...deps import get_storage

router = APIRouter(tags=["worker-protocol"])
_bearer = HTTPBearer(auto_error=False, description="Worker token (wk_...) issued by an admin")


def current_worker(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> WorkerRegistry:
    if creds is None or not creds.credentials.startswith("wk_"):
        raise AppError(401, "not_authenticated", "Worker token required")
    w = db.scalars(select(WorkerRegistry).where(WorkerRegistry.token_hash == hash_token(creds.credentials))).first()
    if w is None:
        raise AppError(401, "invalid_token", "Invalid worker token")
    return w


@router.post("/register")
def register(body: WorkerRegisterIn, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db)):
    """Worker self-reports what it can do (toolchain, KVM/emulator preflight result)."""
    w.toolchain = body.toolchain
    w.capabilities = {**body.capabilities, "version": body.version}
    w.status = "idle"
    from datetime import datetime, timezone
    w.last_heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    return {"worker_id": w.id, "kind": w.kind, "capacity": w.capacity,
            "heartbeat_interval_seconds": max(5, get_settings().worker_heartbeat_timeout_seconds // 3)}


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db)):
    return dispatch.heartbeat(db, w, load=body.load)


@router.post("/claim")
def claim(w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db)):
    job = dispatch.claim_next(db, w)
    if job is None:
        return {"job": None}
    is_build = isinstance(job, BuildJob)
    payload = {
        "id": job.id, "kind": "build" if is_build else "test", "project_id": job.project_id,
        "attempt": job.attempts, "timeout_seconds": job.timeout_seconds,
        "lease_seconds": get_settings().job_lease_seconds,
        "requirements": (job.toolchain or {}).get("required"), "jdk": (job.toolchain or {}).get("jdk"),
    }
    if is_build:
        payload.update(variant=job.variant, output_type=job.output_type, gradle_tasks=job.gradle_tasks)
    else:
        payload.update(test_kind=job.kind, build_job_id=job.build_job_id, emulator_profile=job.emulator_profile)
    return {"job": payload}


def _snapshot(db: Session, job) -> ProjectFileSnapshot:
    snap = db.get(ProjectFileSnapshot, job.snapshot_id)
    if snap is None or snap.tenant_id != job.tenant_id:
        raise AppError(404, "snapshot_not_found", "Source snapshot missing")
    return snap


def _stream(fh):
    try:
        while chunk := fh.read(1024 * 1024):
            yield chunk
    finally:
        fh.close()


@router.get("/jobs/{kind}/{job_id}/source")
def source(kind: str, job_id: str, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db),
           storage: ObjectStorage = Depends(get_storage)):
    """The immutable source ZIP for the job this worker holds. Treat it as hostile content."""
    job = dispatch.get_worker_job(db, w, kind, job_id)
    snap = _snapshot(db, job)
    fh = storage.open_read(keys.assert_key_in_tenant(snap.storage_key, job.tenant_id))
    return StreamingResponse(_stream(fh), media_type="application/zip", headers={"X-Content-SHA256": snap.sha256})


@router.get("/jobs/test/{job_id}/apk")
def test_apk(job_id: str, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db),
             storage: ObjectStorage = Depends(get_storage)):
    """The APK built by the linked build job (instrumented/emulator tests)."""
    job = dispatch.get_worker_job(db, w, "test", job_id)
    res = db.scalars(select(BuildResult).where(BuildResult.build_job_id == job.build_job_id)).first() if job.build_job_id else None
    art = db.get(ProjectArtifact, res.artifact_id) if res and res.artifact_id else None
    if art is None or art.tenant_id != job.tenant_id:
        raise AppError(404, "apk_not_found", "The linked build produced no artifact")
    fh = storage.open_read(keys.assert_key_in_tenant(art.storage_key, job.tenant_id))
    return StreamingResponse(_stream(fh), media_type="application/octet-stream")


@router.post("/jobs/{kind}/{job_id}/start")
def start(kind: str, job_id: str, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db)):
    job = dispatch.get_worker_job(db, w, kind, job_id)
    dispatch.mark_running(db, job)
    return {"state": job.state, "cancel": job.cancel_requested}


@router.post("/jobs/{kind}/{job_id}/logs")
def logs(kind: str, job_id: str, body: LogIn, w: WorkerRegistry = Depends(current_worker), db: Session = Depends(get_db)):
    job = dispatch.get_worker_job(db, w, kind, job_id)
    return {"cancel": dispatch.append_log(db, job, stream=body.stream, content=body.content)}


@router.post("/jobs/{kind}/{job_id}/files", status_code=201)
def upload_file(request: Request, kind: str, job_id: str, role: str = Form(pattern="^(artifact|report)$"),
                file: UploadFile = File(...), name: str = Form(default="", max_length=200),
                format: str = Form(default="", max_length=16), w: WorkerRegistry = Depends(current_worker),
                db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    """Worker uploads a build artifact (APK/AAB) or a test report for the job it holds."""
    import uuid
    job = dispatch.get_worker_job(db, w, kind, job_id)
    if job.state not in dispatch.ACTIVE:
        raise AppError(409, "bad_state", f"Job is {job.state}")
    cap = get_settings().artifact_max_bytes
    raw = request.headers.get("content-length")
    if raw is None or not raw.isdigit() or int(raw) > cap + 1024 * 1024:
        raise AppError(413, "upload_too_large", "Missing or oversized Content-Length")
    spooled, size, sha = project_svc.spool_upload(file.file, cap)
    try:
        fname = keys.safe_name(name or file.filename or "file")
        rid = str(uuid.uuid4())
        if role == "artifact":
            if not isinstance(job, BuildJob):
                raise AppError(422, "bad_role", "Only build jobs upload artifacts")
            key = keys.artifact_key(job.tenant_id, job.project_id, rid, fname)
            storage.put_file(key, spooled, "application/octet-stream")
            db.add(ProjectArtifact(id=rid, tenant_id=job.tenant_id, project_id=job.project_id, kind=job.output_type,
                                   name=fname, storage_key=key, size=size, sha256=sha, build_job_id=job.id))
        else:
            if not isinstance(job, TestJob):
                raise AppError(422, "bad_role", "Only test jobs upload reports")
            key = keys.report_key(job.tenant_id, job.project_id, job.id, fname)
            storage.put_file(key, spooled)
            db.add(TestReport(id=rid, test_job_id=job.id, format=format or "json", storage_key=key, size=size))
        db.commit()
    finally:
        spooled.close()
    return {"id": rid, "size": size, "sha256": sha}


@router.post("/jobs/{kind}/{job_id}/complete")
def complete(kind: str, job_id: str, body: CompleteIn, w: WorkerRegistry = Depends(current_worker),
             db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage),
             notifier: ResultNotifier = Depends(get_notifier)):
    job = dispatch.get_worker_job(db, w, kind, job_id)
    job = dispatch.complete(db, storage, notifier, w, job, dispatch.Completion(**body.model_dump()))
    return {"state": job.state}
