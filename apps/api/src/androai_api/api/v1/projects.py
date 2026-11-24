from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_storage import ObjectStorage

from ...config import get_settings
from ...db import get_db
from ...deps import AuthContext, get_owned_project, get_storage, require_permission
from ...errors import AppError
from ...models import (Project, ProjectActivity, ProjectArtifact, ProjectFileChange,
                       ProjectFileSnapshot, ProjectUpload)
from ...schemas import (ActivityOut, ActivityRecentOut, AnalysisOut, ArtifactOut, FileContentOut, FileMoveIn, FileOut, FilePutIn,
                        Page, ProjectCreateIn, ProjectOut, ProjectPatchIn, SearchHitOut, SnapshotCreateIn,
                        SnapshotOut, UploadOut, UploadResultOut)
from ...services import projects as svc
from ...services import scheduler
from ...services.views import project_out, projects_out
from ...services.audit import audit

router = APIRouter(tags=["projects"])
manage = require_permission("projects:manage")
_MULTIPART_OVERHEAD = 1024 * 1024


def _limit_body(request: Request) -> None:
    """Reject oversized uploads from the Content-Length header before the body is parsed
    (the reverse proxy enforces the same cap; this is defence in depth)."""
    raw = request.headers.get("content-length")
    if raw is None:
        raise AppError(411, "length_required", "Content-Length header is required for uploads")
    try:
        n = int(raw)
    except ValueError:
        raise AppError(400, "bad_request", "Invalid Content-Length") from None
    cap = get_settings().upload_max_bytes + _MULTIPART_OVERHEAD
    if n > cap:
        raise AppError(413, "upload_too_large", "Upload is too large")


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreateIn, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    meta = body.metadata.model_dump(exclude_none=True) if body.metadata else {}
    project = Project(tenant_id=ctx.tenant_id, owner_id=ctx.user_id, name=body.name, description=body.description,
                      metadata_=meta)
    db.add(project)
    db.flush()
    svc.log_activity(db, project, ctx.user_id, "project.create")
    audit(db, "project.create", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, resource_type="project",
          resource_id=project.id, ip=ctx.ip)
    db.commit()
    return project_out(db, project)


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    status: str = Query("active", pattern="^(active|archived)$"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
):
    q = select(Project).where(Project.tenant_id == ctx.tenant_id, Project.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = projects_out(db, list(db.scalars(q.order_by(Project.updated_at.desc(), Project.id).limit(limit).offset(offset))))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/activity/recent", response_model=list[ActivityRecentOut])
def recent_activity(limit: int = Query(15, ge=1, le=100), ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    """Newest activity across all of the caller's projects (dashboard feed)."""
    rows = db.execute(select(ProjectActivity, Project.name).join(Project, Project.id == ProjectActivity.project_id)
                      .where(ProjectActivity.tenant_id == ctx.tenant_id, Project.status != "deleted")
                      .order_by(ProjectActivity.created_at.desc()).limit(limit)).all()
    return [ActivityRecentOut(id=a.id, project_id=a.project_id, project_name=name, action=a.action, detail=a.detail,
                              created_at=a.created_at) for a, name in rows]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    return project_out(db, get_owned_project(db, ctx, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectPatchIn, ctx: AuthContext = Depends(manage),
                   db: Session = Depends(get_db)):
    p = get_owned_project(db, ctx, project_id)
    if body.metadata is not None:
        p.metadata_ = {**(p.metadata_ or {}), **body.metadata.model_dump(exclude_none=True)}
    for field in body.model_fields_set - {"metadata"}:
        value = getattr(body, field)
        if field == "name":
            value = (value or "").strip()
            if not value:
                raise AppError(422, "validation_error", "name must not be blank")
        if value is None and field != "description":
            continue
        setattr(p, field, value)
    svc.log_activity(db, p, ctx.user_id, "project.update", fields=sorted(body.model_fields_set))
    db.commit()
    return project_out(db, p)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
                   storage: ObjectStorage = Depends(get_storage)) -> Response:
    p = get_owned_project(db, ctx, project_id)
    svc.delete_project(db, storage, p, actor_id=ctx.user_id)
    return Response(status_code=204)


# ---- uploads
@router.post("/{project_id}/uploads", response_model=UploadResultOut, status_code=201,
             dependencies=[Depends(_limit_body)])
def upload(project_id: str, file: UploadFile = File(...), ctx: AuthContext = Depends(manage),
           db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    """ZIP = project source (replaces the file set, creates a snapshot). APK = stored as an
    artifact only; it is validated structurally and never unpacked or run on this server."""
    p = get_owned_project(db, ctx, project_id)
    name = (file.filename or "").strip()
    lower = name.lower()
    if lower.endswith(".zip"):
        out = svc.process_zip_upload(db, storage, p, user_id=ctx.user_id, fileobj=file.file, filename=name)
    elif lower.endswith(".apk"):
        out = svc.process_apk_upload(db, storage, p, user_id=ctx.user_id, fileobj=file.file, filename=name)
    else:
        raise AppError(415, "unsupported_media_type", "Only .zip (source) and .apk uploads are supported")
    return UploadResultOut(upload=UploadOut.model_validate(out.upload), file_count=out.file_count,
                           snapshot_id=out.snapshot.id if out.snapshot else None,
                           artifact_id=out.artifact.id if out.artifact else None)


@router.get("/{project_id}/uploads", response_model=list[UploadOut])
def list_uploads(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    p = get_owned_project(db, ctx, project_id)
    return list(db.scalars(select(ProjectUpload).where(ProjectUpload.project_id == p.id)
                           .order_by(ProjectUpload.created_at.desc()).limit(100)))


# ---- files (editor)
@router.get("/{project_id}/files", response_model=list[FileOut])
def list_files(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    return svc.list_files(db, get_owned_project(db, ctx, project_id))


@router.get("/{project_id}/files/content", response_model=FileContentOut)
def read_file(project_id: str, path: str = Query(min_length=1, max_length=1024),
              ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
              storage: ObjectStorage = Depends(get_storage)):
    p = get_owned_project(db, ctx, project_id)
    row, data = svc.read_file(db, storage, p, path)
    if row.is_binary:
        raise AppError(415, "binary_file", "Binary files cannot be opened in the text editor")
    return FileContentOut(path=row.path, size=row.size, sha256=row.sha256, is_binary=False,
                          version=row.version, updated_at=row.updated_at,
                          content=data.decode("utf-8", errors="replace"))


@router.put("/{project_id}/files/content", response_model=FileOut)
def write_file(project_id: str, body: FilePutIn, path: str = Query(min_length=1, max_length=1024),
               ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
               storage: ObjectStorage = Depends(get_storage)):
    p = get_owned_project(db, ctx, project_id)
    return svc.write_file(db, storage, p, path=path, content=body.content.encode(), actor_id=ctx.user_id,
                          base_sha256=body.base_sha256, editor_session_id=body.editor_session_id)


@router.delete("/{project_id}/files", status_code=204)
def delete_file(project_id: str, path: str = Query(min_length=1, max_length=1024),
                base_sha256: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
                recursive: bool = Query(default=False, description="also delete everything under `path`"),
                ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)) -> Response:
    p = get_owned_project(db, ctx, project_id)
    if recursive:
        svc.delete_path(db, p, path=path, actor_id=ctx.user_id)
    else:
        svc.delete_file(db, p, path=path, actor_id=ctx.user_id, base_sha256=base_sha256)
    return Response(status_code=204)


@router.post("/{project_id}/files/move", status_code=204)
def move_file(project_id: str, body: FileMoveIn, ctx: AuthContext = Depends(manage),
              db: Session = Depends(get_db)) -> Response:
    """Rename/move a file or directory (JSON `{"from": "a/b", "to": "c/b"}`)."""
    svc.move_path(db, get_owned_project(db, ctx, project_id), src=body.src, dst=body.dst, actor_id=ctx.user_id)
    return Response(status_code=204)


@router.get("/{project_id}/files/history")
def file_history(project_id: str, path: str | None = Query(default=None, max_length=1024),
                 limit: int = Query(50, ge=1, le=200), ctx: AuthContext = Depends(manage),
                 db: Session = Depends(get_db)):
    """Version history for the editor / visual UI editor (who changed what, from which source)."""
    p = get_owned_project(db, ctx, project_id)
    q = select(ProjectFileChange).where(ProjectFileChange.project_id == p.id)
    if path:
        q = q.where(ProjectFileChange.path == path)
    rows = db.scalars(q.order_by(ProjectFileChange.created_at.desc()).limit(limit))
    return [{"id": r.id, "path": r.path, "change_type": r.change_type, "source": r.source,
             "actor_id": r.actor_id, "before_sha256": r.before_sha256, "after_sha256": r.after_sha256,
             "agent_run_id": r.agent_run_id, "created_at": r.created_at} for r in rows]


@router.get("/{project_id}/files/search", response_model=list[SearchHitOut])
def search_files(project_id: str, q: str = Query(min_length=1, max_length=200), ctx: AuthContext = Depends(manage),
                 db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    return svc.search_files(db, storage, get_owned_project(db, ctx, project_id), q)


@router.get("/{project_id}/analysis", response_model=AnalysisOut)
def analysis(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
             storage: ObjectStorage = Depends(get_storage)):
    """Detected Gradle/AGP/Kotlin/SDK settings and whether the project can be built."""
    p = get_owned_project(db, ctx, project_id)
    files = svc.list_files(db, p)
    if not files:
        raise AppError(409, "empty_project", "The project has no files to analyse")
    info = scheduler.analyze_snapshot(db, storage, p)
    paths = {f.path for f in files}
    kts = any(x.endswith(".kts") for x in ("settings.gradle.kts", "build.gradle.kts") if x in paths)
    groovy = any(x in paths for x in ("settings.gradle", "build.gradle"))
    return AnalysisOut(detected=info["detected"], required=info["required"], file_count=len(files),
                       modules=info["detected"].get("modules", []),
                       build_system="gradle-kts" if kts else "gradle-groovy" if groovy else "unknown")


# ---- snapshots, activity, artifacts
@router.get("/{project_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    p = get_owned_project(db, ctx, project_id)
    return list(db.scalars(select(ProjectFileSnapshot).where(ProjectFileSnapshot.project_id == p.id)
                           .order_by(ProjectFileSnapshot.version.desc()).limit(100)))


@router.post("/{project_id}/snapshots", response_model=SnapshotOut, status_code=201)
def create_snapshot(project_id: str, body: SnapshotCreateIn, ctx: AuthContext = Depends(manage),
                    db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    p = get_owned_project(db, ctx, project_id)
    snap = svc.create_snapshot(db, storage, p, user_id=ctx.user_id, label=body.label)
    svc.log_activity(db, p, ctx.user_id, "snapshot.create", version=snap.version)
    db.commit()
    return snap


@router.get("/{project_id}/activity", response_model=list[ActivityOut])
def activity(project_id: str, limit: int = Query(50, ge=1, le=200), ctx: AuthContext = Depends(manage),
             db: Session = Depends(get_db)):
    p = get_owned_project(db, ctx, project_id)
    return list(db.scalars(select(ProjectActivity).where(ProjectActivity.project_id == p.id)
                           .order_by(ProjectActivity.created_at.desc()).limit(limit)))


@router.get("/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    p = get_owned_project(db, ctx, project_id)
    return list(db.scalars(select(ProjectArtifact).where(ProjectArtifact.project_id == p.id)
                           .order_by(ProjectArtifact.created_at.desc()).limit(200)))
