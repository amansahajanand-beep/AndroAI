"""Response assembly for the web app: batch-loads the related rows so list endpoints stay at a
constant number of queries instead of N+1."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (BuildJob, BuildResult, Project, ProjectFile, ProjectFileSnapshot, TestJob, TestResult)
from ..schemas import LastBuildOut, ProjectOut
from ..schemas_jobs import BuildOut, TestOut, TestResultOut

_PENDING = ("queued", "blocked", "starting", "running")


def projects_out(db: Session, projects: Sequence[Project]) -> list[ProjectOut]:
    ids = [p.id for p in projects]
    storage: dict[str, int] = {}
    last: dict[str, BuildJob] = {}
    active: dict[str, int] = {}
    if ids:
        storage = dict(db.execute(select(ProjectFile.project_id, func.sum(ProjectFile.size))
                                  .where(ProjectFile.project_id.in_(ids)).group_by(ProjectFile.project_id)).all())
        newest = (select(BuildJob.project_id.label("pid"), func.max(BuildJob.number).label("n"))
                  .where(BuildJob.project_id.in_(ids)).group_by(BuildJob.project_id).subquery())
        for job in db.scalars(select(BuildJob).join(newest, (BuildJob.project_id == newest.c.pid) & (BuildJob.number == newest.c.n))):
            last[job.project_id] = job
        for m in (BuildJob, TestJob):
            for pid, n in db.execute(select(m.project_id, func.count()).where(m.project_id.in_(ids), m.state.in_(_PENDING))
                                     .group_by(m.project_id)):
                active[pid] = active.get(pid, 0) + n
    out = []
    for p in projects:
        lb = last.get(p.id)
        out.append(ProjectOut(
            id=p.id, name=p.name, description=p.description, source_type=p.source_type, status=p.status,
            metadata=p.metadata_ or {}, current_snapshot_id=p.current_snapshot_id,
            storage_bytes=int(storage.get(p.id) or 0), active_jobs=active.get(p.id, 0),
            last_build=LastBuildOut(id=lb.id, number=lb.number, state=lb.state, finished_at=lb.finished_at) if lb else None,
            created_at=p.created_at, updated_at=p.updated_at))
    return out


def project_out(db: Session, p: Project) -> ProjectOut:
    return projects_out(db, [p])[0]


def builds_out(db: Session, jobs: Sequence[BuildJob]) -> list[BuildOut]:
    ids = [j.id for j in jobs]
    results = {r.build_job_id: r for r in db.scalars(select(BuildResult).where(BuildResult.build_job_id.in_(ids)))} if ids else {}
    snaps = {s.id: s.sha256 for s in db.scalars(select(ProjectFileSnapshot).where(
        ProjectFileSnapshot.id.in_({j.snapshot_id for j in jobs})))} if jobs else {}
    out = []
    for j in jobs:
        r = results.get(j.id)
        b = BuildOut.model_validate(j)
        b.commit_sha = (snaps.get(j.snapshot_id) or "")[:7]
        b.artifact_ids = [r.artifact_id] if r and r.artifact_id else []
        b.errors = list(r.errors) if r else []
        b.duration_seconds = r.duration_seconds if r else None
        out.append(b)
    return out


def tests_out(db: Session, jobs: Sequence[TestJob]) -> list[TestOut]:
    ids = [j.id for j in jobs]
    results = {r.test_job_id: r for r in db.scalars(select(TestResult).where(TestResult.test_job_id.in_(ids)))} if ids else {}
    out = []
    for j in jobs:
        t = TestOut.model_validate(j)
        r = results.get(j.id)
        t.result = TestResultOut.model_validate(r) if r else None
        out.append(t)
    return out
