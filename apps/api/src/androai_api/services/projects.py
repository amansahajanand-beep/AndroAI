"""Project files, uploads and snapshots. All bytes go to object storage; the database
holds metadata. Callers must obtain `project` via `deps.get_owned_project` (tenant-scoped)."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from androai_storage import (ArchiveError, ArchiveLimits, ObjectStorage, build_zip, iter_zip_files,
                             keys, normalize_member_path, validate_apk)

from ..config import get_settings
from ..errors import AppError
from ..models import (BuildJob, Project, ProjectActivity, ProjectArtifact, ProjectFile,
                      ProjectFileChange, ProjectFileSnapshot, ProjectUpload, TestJob)
from .audit import audit

ACTIVE_JOB_STATES = ("queued", "starting", "running", "blocked")
_TEXT_PROBE = 8192


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:_TEXT_PROBE]


def limits_from_settings() -> ArchiveLimits:
    s = get_settings()
    return ArchiveLimits(
        max_archive_bytes=s.upload_max_bytes,
        max_total_bytes=s.upload_max_uncompressed_bytes,
        max_files=s.upload_max_files,
    )


def log_activity(db: Session, project: Project, actor_id: str | None, action: str, **detail) -> None:
    db.add(ProjectActivity(tenant_id=project.tenant_id, project_id=project.id, actor_id=actor_id,
                           action=action, detail=detail))


# ---------------------------------------------------------------- upload intake

def spool_upload(fileobj: BinaryIO, max_bytes: int) -> tuple[tempfile.SpooledTemporaryFile, int, str]:
    """Copy an incoming stream to a temp file, enforcing the size cap *while reading*."""
    out = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    h, total = hashlib.sha256(), 0
    try:
        while chunk := fileobj.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise AppError(413, "upload_too_large", f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit")
            h.update(chunk)
            out.write(chunk)
    except BaseException:
        out.close()
        raise
    out.seek(0)
    return out, total, h.hexdigest()


@dataclass
class UploadOutcome:
    upload: ProjectUpload
    file_count: int
    snapshot: ProjectFileSnapshot | None
    artifact: ProjectArtifact | None = None


def _record_rejected(db: Session, project: Project, user_id: str, kind: str, filename: str,
                     size: int, sha: str, upload_key: str, upload_id: str, reason: str) -> None:
    db.add(ProjectUpload(id=upload_id, tenant_id=project.tenant_id, project_id=project.id, user_id=user_id,
                         kind=kind, filename=filename[:255], size=size, sha256=sha, storage_key=upload_key,
                         status="rejected", error=reason[:500]))
    log_activity(db, project, user_id, "upload.rejected", kind=kind, reason=reason[:200])
    db.commit()


def process_zip_upload(db: Session, storage: ObjectStorage, project: Project, *, user_id: str,
                       fileobj: BinaryIO, filename: str) -> UploadOutcome:
    s = get_settings()
    spooled, size, sha = spool_upload(fileobj, s.upload_max_bytes)
    import uuid
    upload_id = str(uuid.uuid4())
    ukey = keys.upload_key(project.tenant_id, project.id, upload_id, filename or "upload.zip")
    written: list[str] = []
    try:
        existing_keys = {f.storage_key for f in db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id))}
        files: dict[str, tuple[str, int, bool]] = {}  # path -> (sha, size, binary)
        try:
            for path, data in iter_zip_files(spooled, limits_from_settings()):
                fsha = _sha(data)
                bkey = keys.file_key(project.tenant_id, project.id, fsha)
                if bkey not in existing_keys and bkey not in written and not storage.exists(bkey):
                    storage.put_bytes(bkey, data)
                    written.append(bkey)
                files[path] = (fsha, len(data), _is_binary(data))
        except ArchiveError as e:
            for k in written:
                storage.delete(k)
            _record_rejected(db, project, user_id, "zip", filename, size, sha, ukey, upload_id, str(e))
            raise AppError(422, "invalid_archive", str(e)) from None
        spooled.seek(0)
        storage.put_file(ukey, spooled, "application/zip")

        _replace_files(db, project, files, user_id, source="upload",
                       blob_key=lambda fsha: keys.file_key(project.tenant_id, project.id, fsha))
        project.source_type = "zip"
        upload = ProjectUpload(id=upload_id, tenant_id=project.tenant_id, project_id=project.id,
                               user_id=user_id, kind="zip", filename=filename[:255] or "upload.zip",
                               size=size, sha256=sha, storage_key=ukey, status="processed",
                               file_count=len(files))
        db.add(upload)
        db.flush()
        snap = create_snapshot(db, storage, project, user_id=user_id, label=f"upload:{upload_id[:8]}")
        log_activity(db, project, user_id, "upload.zip", files=len(files), size=size)
        audit(db, "project.upload", actor_id=user_id, tenant_id=project.tenant_id,
              resource_type="project", resource_id=project.id, detail={"kind": "zip", "files": len(files)})
        db.commit()
        return UploadOutcome(upload, len(files), snap)
    except AppError:
        raise
    except BaseException:
        db.rollback()
        for k in written:
            storage.delete(k)
        storage.delete(ukey)
        raise
    finally:
        spooled.close()


def process_apk_upload(db: Session, storage: ObjectStorage, project: Project, *, user_id: str,
                       fileobj: BinaryIO, filename: str) -> UploadOutcome:
    """APKs are validated structurally and stored; never unpacked or executed on the control plane."""
    import uuid
    s = get_settings()
    spooled, size, sha = spool_upload(fileobj, s.upload_max_bytes)
    upload_id = str(uuid.uuid4())
    ukey = keys.upload_key(project.tenant_id, project.id, upload_id, filename or "app.apk")
    try:
        try:
            info = validate_apk(spooled, limits_from_settings())
        except ArchiveError as e:
            _record_rejected(db, project, user_id, "apk", filename, size, sha, ukey, upload_id, str(e))
            raise AppError(422, "invalid_apk", str(e)) from None
        spooled.seek(0)
        storage.put_file(ukey, spooled, "application/vnd.android.package-archive")
        art_id = str(uuid.uuid4())
        akey = keys.artifact_key(project.tenant_id, project.id, art_id, filename or "app.apk")
        spooled.seek(0)
        storage.put_file(akey, spooled, "application/vnd.android.package-archive")
        upload = ProjectUpload(id=upload_id, tenant_id=project.tenant_id, project_id=project.id,
                               user_id=user_id, kind="apk", filename=filename[:255] or "app.apk",
                               size=size, sha256=sha, storage_key=ukey, status="processed",
                               file_count=info.entry_count)
        art = ProjectArtifact(id=art_id, tenant_id=project.tenant_id, project_id=project.id, kind="apk",
                              name=keys.safe_name(filename or "app.apk"), storage_key=akey, size=size, sha256=sha)
        db.add_all([upload, art])
        if project.source_type == "empty":
            project.source_type = "apk"
        log_activity(db, project, user_id, "upload.apk", size=size)
        audit(db, "project.upload", actor_id=user_id, tenant_id=project.tenant_id,
              resource_type="project", resource_id=project.id, detail={"kind": "apk"})
        db.commit()
        return UploadOutcome(upload, 0, None, art)
    except AppError:
        raise
    except BaseException:
        db.rollback()
        storage.delete(ukey)
        raise
    finally:
        spooled.close()


# ---------------------------------------------------------------- file index

def _replace_files(db: Session, project: Project, files: dict[str, tuple[str, int, bool]],
                   actor_id: str, *, source: str, blob_key) -> None:
    """Make the project's file set equal to `files`, recording per-file changes."""
    current = {f.path: f for f in db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id))}
    for path, (fsha, fsize, binary) in files.items():
        row = current.get(path)
        if row is None:
            db.add(ProjectFile(tenant_id=project.tenant_id, project_id=project.id, path=path, size=fsize,
                               sha256=fsha, storage_key=blob_key(fsha), is_binary=binary))
            db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=path,
                                     change_type="create", source=source, actor_id=actor_id,
                                     after_sha256=fsha, after_key=blob_key(fsha)))
        elif row.sha256 != fsha:
            db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=path,
                                     change_type="update", source=source, actor_id=actor_id,
                                     before_sha256=row.sha256, after_sha256=fsha,
                                     before_key=row.storage_key, after_key=blob_key(fsha)))
            row.sha256, row.size, row.is_binary = fsha, fsize, binary
            row.storage_key, row.version = blob_key(fsha), row.version + 1
    for path, row in current.items():
        if path not in files:
            db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=path,
                                     change_type="delete", source=source, actor_id=actor_id,
                                     before_sha256=row.sha256, before_key=row.storage_key))
            db.delete(row)
    db.flush()


def list_files(db: Session, project: Project) -> list[ProjectFile]:
    return list(db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id)
                           .order_by(ProjectFile.path)))


def _file_row(db: Session, project: Project, path: str) -> ProjectFile | None:
    return db.scalars(select(ProjectFile).where(ProjectFile.project_id == project.id,
                                                ProjectFile.path == path)).first()


def read_file(db: Session, storage: ObjectStorage, project: Project, path: str) -> tuple[ProjectFile, bytes]:
    row = _file_row(db, project, _clean_path(path))
    if row is None:
        raise AppError(404, "file_not_found", "File not found")
    if row.size > get_settings().editor_max_file_bytes:
        raise AppError(413, "file_too_large", "File is too large to open in the editor")
    return row, storage.get_bytes(keys.assert_key_in_tenant(row.storage_key, project.tenant_id))


def _clean_path(path: str) -> str:
    try:
        return normalize_member_path(path)
    except ArchiveError as e:
        raise AppError(422, "invalid_path", str(e)) from None


def write_file(db: Session, storage: ObjectStorage, project: Project, *, path: str, content: bytes,
               actor_id: str, base_sha256: str | None, source: str = "editor",
               editor_session_id: str | None = None, agent_run_id: str | None = None) -> ProjectFile:
    """Create/update one file. `base_sha256` gives optimistic concurrency: pass the hash you
    read (or None to require that the file does not exist yet)."""
    path = _clean_path(path)
    if len(content) > get_settings().editor_max_file_bytes:
        raise AppError(413, "file_too_large", "File exceeds the editor size limit")
    row = _file_row(db, project, path)
    if row is None and base_sha256 is not None:
        raise AppError(409, "conflict", "File no longer exists")
    if row is not None and base_sha256 != row.sha256:
        raise AppError(409, "conflict", "File changed since you loaded it", )
    fsha = _sha(content)
    bkey = keys.file_key(project.tenant_id, project.id, fsha)
    if not storage.exists(bkey):
        storage.put_bytes(bkey, content)
    change = ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=path, source=source,
                               actor_id=actor_id, editor_session_id=editor_session_id,
                               agent_run_id=agent_run_id, after_sha256=fsha, after_key=bkey,
                               change_type="create" if row is None else "update")
    if row is None:
        row = ProjectFile(tenant_id=project.tenant_id, project_id=project.id, path=path, size=len(content),
                          sha256=fsha, storage_key=bkey, is_binary=_is_binary(content))
        db.add(row)
    else:
        change.before_sha256, change.before_key = row.sha256, row.storage_key
        row.sha256, row.size, row.storage_key = fsha, len(content), bkey
        row.is_binary, row.version = _is_binary(content), row.version + 1
    db.add(change)
    project.updated_at = _now()
    log_activity(db, project, actor_id, "file.write", path=path, change=change.change_type)
    db.commit()
    return row


def move_path(db: Session, project: Project, *, src: str, dst: str, actor_id: str) -> int:
    """Rename a file or a whole directory (no content is rewritten). Atomic: all or nothing."""
    src, dst = _clean_path(src), _clean_path(dst)
    if dst == src or dst.startswith(src + "/"):
        raise AppError(422, "invalid_path", "Cannot move a path into itself")
    rows = [r for r in list_files(db, project) if r.path == src or r.path.startswith(src + "/")]
    if not rows:
        raise AppError(404, "file_not_found", "File not found")
    existing = {r.path for r in list_files(db, project)}
    targets = {r.path: dst + r.path[len(src):] for r in rows}
    clash = [t for t in targets.values() if t in existing]
    # a destination that is a file where we need a directory (or vice versa) is also a conflict
    parts = dst.split("/")
    if clash or any("/".join(parts[:i]) in existing for i in range(1, len(parts))):
        raise AppError(409, "exists", f"{dst} already exists")
    for r in rows:
        new = targets[r.path]
        db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=r.path, source="editor",
                                 change_type="delete", actor_id=actor_id, before_sha256=r.sha256, before_key=r.storage_key))
        db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=new, source="editor",
                                 change_type="create", actor_id=actor_id, after_sha256=r.sha256, after_key=r.storage_key))
        r.path = new
    project.updated_at = _now()
    log_activity(db, project, actor_id, "file.move", src=src, dst=dst, files=len(rows))
    db.commit()
    return len(rows)


def delete_path(db: Session, project: Project, *, path: str, actor_id: str) -> int:
    """Delete a file, or a directory and everything under it."""
    path = _clean_path(path)
    rows = [r for r in list_files(db, project) if r.path == path or r.path.startswith(path + "/")]
    if not rows:
        raise AppError(404, "file_not_found", "File not found")
    for r in rows:
        db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=r.path, source="editor",
                                 change_type="delete", actor_id=actor_id, before_sha256=r.sha256, before_key=r.storage_key))
        db.delete(r)
    project.updated_at = _now()
    log_activity(db, project, actor_id, "file.delete", path=path, files=len(rows))
    db.commit()
    return len(rows)


def delete_file(db: Session, project: Project, *, path: str, actor_id: str, base_sha256: str | None) -> None:
    path = _clean_path(path)
    row = _file_row(db, project, path)
    if row is None:
        raise AppError(404, "file_not_found", "File not found")
    if base_sha256 is not None and base_sha256 != row.sha256:
        raise AppError(409, "conflict", "File changed since you loaded it")
    db.add(ProjectFileChange(tenant_id=project.tenant_id, project_id=project.id, path=path, source="editor",
                             change_type="delete", actor_id=actor_id, before_sha256=row.sha256,
                             before_key=row.storage_key))
    db.delete(row)
    project.updated_at = _now()
    log_activity(db, project, actor_id, "file.delete", path=path)
    db.commit()


def search_files(db: Session, storage: ObjectStorage, project: Project, query: str, *,
                 max_hits: int = 200, max_files: int = 2000) -> list[dict]:
    """Case-insensitive text search over the project's editable text files (bounded work)."""
    q = query.lower()
    if not q:
        return []
    limit = get_settings().editor_max_file_bytes
    hits: list[dict] = []
    rows = [r for r in list_files(db, project) if not r.is_binary and r.size <= limit][:max_files]
    for r in rows:
        try:
            text = storage.get_bytes(keys.assert_key_in_tenant(r.storage_key, project.tenant_id)).decode("utf-8", errors="replace")
        except Exception:  # a missing blob must not break the whole search
            continue
        for i, line in enumerate(text.split("\n"), 1):
            col = line.lower().find(q)
            if col != -1:
                hits.append({"path": r.path, "line": i, "column": col + 1, "preview": line.strip()[:160]})
                if len(hits) >= max_hits:
                    return hits
    return hits


# ---------------------------------------------------------------- snapshots

def create_snapshot(db: Session, storage: ObjectStorage, project: Project, *, user_id: str | None,
                    label: str | None = None) -> ProjectFileSnapshot:
    """Freeze the current file set into an immutable ZIP (the input of build/test jobs).
    Reuses the latest snapshot if the content is byte-identical."""
    rows = list_files(db, project)
    if not rows:
        raise AppError(409, "empty_project", "The project has no files")
    tenant, pid = project.tenant_id, project.id

    def loader(r: ProjectFile):
        return lambda: storage.get_bytes(keys.assert_key_in_tenant(r.storage_key, tenant))

    zf = build_zip([(r.path, loader(r)) for r in rows])
    try:
        data_sha, size = hashlib.sha256(), 0
        while chunk := zf.read(1024 * 1024):
            data_sha.update(chunk)
            size += len(chunk)
        digest = data_sha.hexdigest()
        latest = db.scalars(select(ProjectFileSnapshot).where(ProjectFileSnapshot.project_id == pid)
                            .order_by(ProjectFileSnapshot.version.desc())).first()
        if latest and latest.sha256 == digest:
            project.current_snapshot_id = latest.id
            return latest
        version = (latest.version if latest else 0) + 1
        zf.seek(0)
        key = keys.snapshot_key(tenant, pid, version)
        storage.put_file(key, zf, "application/zip")
    finally:
        zf.close()
    snap = ProjectFileSnapshot(tenant_id=tenant, project_id=pid, version=version, storage_key=key,
                               size=size, sha256=digest, file_count=len(rows), label=label, created_by=user_id)
    db.add(snap)
    db.flush()
    project.current_snapshot_id = snap.id
    return snap


# ---------------------------------------------------------------- deletion

def delete_project(db: Session, storage: ObjectStorage, project: Project, *, actor_id: str) -> None:
    active = 0
    for model in (BuildJob, TestJob):
        active += db.scalar(select(func.count()).select_from(model).where(
            model.project_id == project.id, model.state.in_(ACTIVE_JOB_STATES))) or 0
    if active:
        raise AppError(409, "project_busy", "Cancel running build/test jobs before deleting the project")
    prefix = keys.project_prefix(project.tenant_id, project.id)
    audit(db, "project.delete", actor_id=actor_id, tenant_id=project.tenant_id, resource_type="project",
          resource_id=project.id, detail={"name": project.name})
    db.delete(project)  # rows cascade; usage/audit rows keep their history
    db.commit()
    # Objects are removed after the DB commit; an interrupted purge leaves orphans that the
    # retention sweeper (tenant prefix with no project row) collects.
    storage.delete_prefix(prefix)
