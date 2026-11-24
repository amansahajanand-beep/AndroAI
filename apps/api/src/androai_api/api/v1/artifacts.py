"""Artifact access. Downloads use short-lived HMAC-signed URLs so a browser can fetch them
without custom headers; the signature binds artifact id + expiry and the key is derived
from the server secret, so URLs cannot be forged, extended or reused for another artifact."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from androai_storage import ObjectNotFound, ObjectStorage, keys

from ...config import get_settings
from ...db import get_db
from ...deps import AuthContext, get_storage, require_permission
from ...errors import AppError
from ...models import ProjectArtifact
from ...schemas import ArtifactOut, DownloadUrlOut
from ...services.audit import audit

router = APIRouter(tags=["artifacts"])
manage = require_permission("projects:manage")


def _key() -> bytes:
    return hashlib.sha256(b"artifact-url-v1:" + get_settings().jwt_secret.encode()).digest()


def sign(artifact_id: str, exp: int) -> str:
    return hmac.new(_key(), f"{artifact_id}.{exp}".encode(), hashlib.sha256).hexdigest()


def _owned(db: Session, ctx: AuthContext, artifact_id: str) -> ProjectArtifact:
    art = db.scalars(select(ProjectArtifact).where(ProjectArtifact.id == artifact_id,
                                                   ProjectArtifact.tenant_id == ctx.tenant_id)).first()
    if art is None:
        raise AppError(404, "artifact_not_found", "Artifact not found")
    return art


@router.get("", response_model=list[ArtifactOut])
def list_artifacts(build_id: str | None = Query(default=None, max_length=64),
                   project_id: str | None = Query(default=None, max_length=64),
                   ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    q = select(ProjectArtifact).where(ProjectArtifact.tenant_id == ctx.tenant_id)
    if build_id:
        q = q.where(ProjectArtifact.build_job_id == build_id)
    if project_id:
        q = q.where(ProjectArtifact.project_id == project_id)
    return list(db.scalars(q.order_by(ProjectArtifact.created_at.desc()).limit(200)))


@router.get("/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    return _owned(db, ctx, artifact_id)


@router.post("/{artifact_id}/download-url", response_model=DownloadUrlOut)
def download_url(artifact_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    art = _owned(db, ctx, artifact_id)
    ttl = get_settings().signed_url_ttl_seconds
    exp = int(time.time()) + ttl
    audit(db, "artifact.download_url", actor_id=ctx.user_id, tenant_id=ctx.tenant_id,
          resource_type="artifact", resource_id=art.id, ip=ctx.ip)
    db.commit()
    return DownloadUrlOut(url=f"/api/v1/artifacts/{art.id}/content?exp={exp}&sig={sign(art.id, exp)}",
                          expires_in=ttl)


@router.get("/{artifact_id}/content")
def content(artifact_id: str, exp: int = Query(), sig: str = Query(max_length=128),
            db: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    """Unauthenticated by design: authorisation is the signature issued above."""
    if exp < time.time() or not hmac.compare_digest(sig, sign(artifact_id, exp)):
        raise AppError(403, "invalid_signature", "Link is invalid or has expired")
    art = db.get(ProjectArtifact, artifact_id)
    if art is None or (art.expires_at and art.expires_at < datetime.now(timezone.utc)):
        raise AppError(404, "artifact_not_found", "Artifact not found")
    key = keys.assert_key_in_tenant(art.storage_key, art.tenant_id)
    direct = storage.presigned_get_url(key, 60, art.name)
    if direct:
        return RedirectResponse(direct, status_code=302, headers={"Cache-Control": "no-store"})
    try:
        fh = storage.open_read(key)
    except ObjectNotFound:
        raise AppError(404, "artifact_not_found", "Artifact file is missing") from None

    def stream():
        try:
            while chunk := fh.read(1024 * 1024):
                yield chunk
        finally:
            fh.close()

    safe = "".join(c for c in art.name if c.isalnum() or c in "._-") or "download"
    return StreamingResponse(stream(), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "Content-Length": str(art.size),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.delete("/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db),
                    storage: ObjectStorage = Depends(get_storage)) -> Response:
    art = _owned(db, ctx, artifact_id)
    key = keys.assert_key_in_tenant(art.storage_key, art.tenant_id)
    audit(db, "artifact.delete", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, resource_type="artifact",
          resource_id=art.id, ip=ctx.ip)
    db.delete(art)
    db.commit()
    storage.delete(key)
    return Response(status_code=204)
