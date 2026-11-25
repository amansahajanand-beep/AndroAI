"""DEV-ONLY bridge for the AI assistant panel: run the modify job in a thread, keep state in memory.

Enabled only when ``AGENT_DEV_BRIDGE=1`` (``scripts/dev/run_api_sqlite.py`` sets it). It exists so
the frontend's agent endpoints (``agent.*`` in ``packages/shared-types/src/endpoints.ts``) can be
exercised locally without Redis, Celery or database migrations. It is NOT the production design:
state is lost on restart, one process only, no real cancellation of a running model call. The real
path is the ``CodingTask`` contract + the ai-agent Celery worker.

JSON is camelCase to match the frontend's agent types (``packages/shared-types/src/types.ts``).
Nothing is written to a project until the user accepts a change set.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from androai_storage import ObjectStorage
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ...db import get_db
from ...db.session import get_session_factory
from ...deps import AuthContext, get_owned_project, get_storage, require_permission
from ...errors import AppError
from ...models import Project
from ...services import projects as svc

router = APIRouter(tags=["agent-dev"])
manage = require_permission("projects:manage")

MODIFY_INTENTS = ("modify", "fix", "refactor")
TERMINAL = ("completed", "failed", "blocked", "cancelled")
MAX_FILE_BYTES = 2_000_000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


class _Store:
    """Everything the panel shows, in memory, keyed by tenant so tenants never see each other."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.messages: dict[str, list[dict]] = {}  # project id -> messages
        self.tasks: dict[str, dict] = {}
        self.timeline: dict[str, list[dict]] = {}
        self.changesets: dict[str, dict] = {}
        self.events: dict[str, list[tuple[str, dict]]] = {}  # task id -> (event name, data)
        self.cancelled: set[str] = set()

    def emit(self, task_id: str, name: str, data: dict) -> None:
        with self.lock:
            self.events.setdefault(task_id, []).append((name, data))


STORE = _Store()


class SendIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    intent: Literal["generate", "modify", "fix", "refactor", "explain", "chat"] = "modify"
    context: dict[str, Any] = Field(default_factory=dict)


class DecisionIn(BaseModel):
    acceptPaths: list[str] = Field(default_factory=list, max_length=500)


def _message(role: str, content: str, **extra: Any) -> dict:
    return {"id": _id(), "role": role, "content": content, "createdAt": _now(), **extra}


def _new_task(project_id: str, tenant_id: str, prompt: str, intent: str) -> dict:
    return {
        "id": _id(),
        "projectId": project_id,
        "_tenant": tenant_id,
        "title": prompt.strip().splitlines()[0][:80],
        "description": prompt[:2000],
        "intent": intent,
        "status": "queued",
        "currentStep": "Queued",
        "filesAnalyzing": [],
        "filesModifying": [],
        "buildProgress": None,
        "repairIterations": 0,
        "maxRepairIterations": 0,
        "tokenUsage": {"inputTokens": 0, "outputTokens": 0},
        "recordedCostUsd": 0,
        "blockedReason": None,
        "errorMessage": None,
        "createdAt": _now(),
        "startedAt": None,
        "finishedAt": None,
    }


def _public(task: dict) -> dict:
    return {k: v for k, v in task.items() if not k.startswith("_")}


def _set_status(task_id: str, status: str, title: str, detail: str | None = None, **fields: Any) -> None:
    with STORE.lock:
        task = STORE.tasks[task_id]
        task.update(status=status, currentStep=title, **fields)
        if status in TERMINAL:
            task["finishedAt"] = _now()
        event = {"id": _id(), "taskId": task_id, "at": _now(), "status": status, "title": title}
        if detail:
            event["detail"] = detail[:500]
        STORE.timeline.setdefault(task_id, []).append(event)
        STORE.emit(task_id, "timeline.appended", {"type": "timeline.appended", "event": event})
        STORE.emit(task_id, "task.updated", {"type": "task.updated", "task": _public(task)})


def _task_for(ctx: AuthContext, task_id: str) -> dict:
    with STORE.lock:
        task = STORE.tasks.get(task_id)
        if task is None or task["_tenant"] != ctx.tenant_id:
            raise AppError(404, "not_found", "Task not found")
        return task


# ---------------------------------------------------------------------------- routes


@router.get("/projects/{project_id}/messages")
def list_messages(project_id: str, ctx: AuthContext = Depends(manage), db: Session = Depends(get_db)):
    get_owned_project(db, ctx, project_id)
    with STORE.lock:
        return list(STORE.messages.get(project_id, []))


@router.post("/projects/{project_id}/messages", status_code=201)
def send_message(
    project_id: str,
    body: SendIn,
    ctx: AuthContext = Depends(manage),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    factory: sessionmaker = Depends(get_session_factory),
):
    project = get_owned_project(db, ctx, project_id)
    user_msg = _message("user", body.prompt, intent=body.intent)
    with STORE.lock:
        STORE.messages.setdefault(project_id, []).append(user_msg)
        busy = [
            t for t in STORE.tasks.values()
            if t["projectId"] == project_id and t["status"] not in TERMINAL
        ]
    if body.intent not in MODIFY_INTENTS:
        reply = _message(
            "assistant",
            "In this build the assistant can modify an existing native Android project from a "
            "request (choose Modify, Fix or Refactor). Generating new projects, explaining code "
            "and chatting are not connected yet.",
        )
        with STORE.lock:
            STORE.messages[project_id].append(reply)
        return {"message": user_msg, "task": None}
    if busy:
        raise AppError(409, "task_running", "A task is already running for this project")

    task = _new_task(project_id, ctx.tenant_id, body.prompt, body.intent)
    user_msg["taskId"] = task["id"]
    with STORE.lock:
        STORE.tasks[task["id"]] = task
    threading.Thread(
        target=_run_job,
        args=(factory, storage, project.id, ctx.user_id, task["id"], body.prompt),
        name=f"agent-dev-{task['id'][:8]}",
        daemon=True,
    ).start()
    return {"message": user_msg, "task": _public(task)}


@router.get("/tasks")
def list_tasks(
    projectId: str | None = Query(None),
    status: str | None = Query(None),
    ctx: AuthContext = Depends(manage),
):
    with STORE.lock:
        tasks = [t for t in STORE.tasks.values() if t["_tenant"] == ctx.tenant_id]
    if projectId:
        tasks = [t for t in tasks if t["projectId"] == projectId]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return [_public(t) for t in sorted(tasks, key=lambda t: t["createdAt"], reverse=True)]


@router.get("/tasks/{task_id}")
def get_task(task_id: str, ctx: AuthContext = Depends(manage)):
    return _public(_task_for(ctx, task_id))


@router.get("/tasks/{task_id}/timeline")
def get_timeline(task_id: str, ctx: AuthContext = Depends(manage)):
    _task_for(ctx, task_id)
    with STORE.lock:
        return list(STORE.timeline.get(task_id, []))


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, ctx: AuthContext = Depends(manage)):
    task = _task_for(ctx, task_id)
    with STORE.lock:
        if task["status"] in TERMINAL:
            return _public(task)
        STORE.cancelled.add(task_id)
    _set_status(task_id, "cancelled", "Cancelled by you")
    return _public(task)


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, ctx: AuthContext = Depends(manage)):
    _task_for(ctx, task_id)

    def stream():
        sent = 0
        idle = 0.0
        while True:
            with STORE.lock:
                batch = STORE.events.get(task_id, [])[sent:]
                done = STORE.tasks[task_id]["status"] in TERMINAL
            for name, data in batch:
                yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
            sent += len(batch)
            if done and not batch:
                return
            if not batch:
                idle += 0.4
                if idle >= 15:
                    idle = 0.0
                    yield ": keep-alive\n\n"
            else:
                idle = 0.0
            time.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/change-sets/{change_set_id}")
def get_change_set(change_set_id: str, ctx: AuthContext = Depends(manage)):
    return _changeset_for(ctx, change_set_id)["public"]


@router.post("/change-sets/{change_set_id}/decision")
def decide(
    change_set_id: str,
    body: DecisionIn,
    ctx: AuthContext = Depends(manage),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    entry = _changeset_for(ctx, change_set_id)
    change_set = entry["public"]
    project = get_owned_project(db, ctx, entry["project_id"])
    if change_set["status"] != "pending":
        raise AppError(409, "already_decided", "This change set was already decided")
    accept = set(body.acceptPaths)
    unknown = accept - {f["path"] for f in change_set["files"]}
    if unknown:
        raise AppError(422, "validation_error", "acceptPaths names files that are not in the change set")
    for f in change_set["files"]:  # check everything before writing anything
        if f["path"] in accept:
            _check_unchanged(db, storage, project, f)
    for f in change_set["files"]:
        if f["path"] not in accept:
            f["decision"] = "rejected"
            continue
        _apply_file(db, storage, project, ctx.user_id, entry["task_id"], f)
        f["decision"] = "accepted"
    db.commit()
    accepted = sum(1 for f in change_set["files"] if f["decision"] == "accepted")
    change_set["status"] = (
        "applied" if accepted == len(change_set["files"]) else "partially_applied" if accepted else "rejected"
    )
    return change_set


def _changeset_for(ctx: AuthContext, change_set_id: str) -> dict:
    with STORE.lock:
        entry = STORE.changesets.get(change_set_id)
    if entry is None or entry["tenant"] != ctx.tenant_id:
        raise AppError(404, "not_found", "Change set not found")
    return entry


def _current(db: Session, storage: ObjectStorage, project: Project, path: str) -> tuple[bytes | None, str | None]:
    try:
        row, data = svc.read_file(db, storage, project, path)
    except AppError as exc:
        if exc.status_code == 404:
            return None, None
        raise
    return data, row.sha256


def _check_unchanged(db: Session, storage: ObjectStorage, project: Project, f: dict) -> None:
    data, _ = _current(db, storage, project, f["path"])
    expected = f["originalContent"]
    now = None if data is None else data.decode("utf-8", errors="replace")
    if now != expected:
        raise AppError(409, "conflict", f"{f['path']} changed since the assistant proposed this; nothing was applied")


def _apply_file(db: Session, storage: ObjectStorage, project: Project, user_id: str, task_id: str, f: dict) -> None:
    _, sha = _current(db, storage, project, f["path"])
    if f["changeType"] == "delete":
        svc.delete_file(db, project, path=f["path"], actor_id=user_id, base_sha256=sha)
        return
    svc.write_file(
        db, storage, project, path=f["path"], content=(f["proposedContent"] or "").encode("utf-8"),
        actor_id=user_id, base_sha256=sha, source="agent", agent_run_id=task_id,
    )


# ---------------------------------------------------------------------------- the job


def _run_job(
    factory: sessionmaker, storage: ObjectStorage, project_id: str, user_id: str, task_id: str, prompt: str
) -> None:
    """Runs in a thread. Never raises: every failure becomes a failed task with a message."""
    work = Path(tempfile.mkdtemp(prefix="androai-agent-dev-"))
    try:
        _set_status(task_id, "analyzing", "Loading your project")
        with STORE.lock:
            STORE.tasks[task_id]["startedAt"] = _now()
        try:
            from androai_agent.modify_job import ModifyJobRequest, run_modify_job
            from androai_codegen.ingest import OwnershipAttestation
            from androai_codegen.llm_nvidia import LlmError, NvidiaClient
        except ImportError as exc:  # codegen / worker not on PYTHONPATH
            raise _JobError("The code-modification engine is not installed on this server.") from exc
        try:
            client = NvidiaClient()
        except LlmError as exc:
            raise _JobError(f"No model is configured: {exc}. Set NVIDIA_API_KEY in the repo's .env.") from exc

        zip_path = work / "project.zip"
        _zip_project(factory, storage, project_id, zip_path)

        def progress(stage: str, text: str) -> None:
            status = {
                "detect": "analyzing",
                "analyze": "analyzing",
                "retrieve": "planning",
                "generate": "generating",
                "agent": "generating",
            }
            if task_id not in STORE.cancelled:
                _set_status(task_id, status.get(stage, "analyzing"), text)

        with STORE.lock:
            earlier = list(STORE.messages.get(project_id, []))[:-1]  # the last one is this prompt
        history = tuple(
            (m["role"], str(m["content"])[:1500]) for m in earlier[-8:] if m["role"] in ("user", "assistant")
        )
        result = run_modify_job(
            ModifyJobRequest(
                zip_path=zip_path,
                prompt=prompt,
                work_dir=work,
                history=history,
                attestation=OwnershipAttestation(
                    basis="own", statement="Uploaded by the project owner (dev bridge).", attested_by=str(user_id)[:60]
                ),
            ),
            client,
            progress=progress,
        )
        usage = {"inputTokens": client.usage["input_tokens"], "outputTokens": client.usage["output_tokens"]}
        if task_id in STORE.cancelled:
            return
        _finish(factory, storage, project_id, task_id, result, usage)
    except _JobError as exc:
        _fail(project_id, task_id, str(exc))
    except Exception as exc:
        _fail(project_id, task_id, f"The task failed unexpectedly ({type(exc).__name__}).")
    finally:
        _cleanup_later(work)


class _JobError(Exception):
    pass


def _zip_project(factory: sessionmaker, storage: ObjectStorage, project_id: str, target: Path) -> None:
    with factory() as db, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        project = db.get(Project, project_id)
        if project is None:
            raise _JobError("The project no longer exists.")
        for row in svc.list_files(db, project):
            _, data = svc.read_file(db, storage, project, row.path)
            if len(data) <= MAX_FILE_BYTES:
                archive.writestr(row.path, data)


def _finish(factory: sessionmaker, storage: ObjectStorage, project_id: str, task_id: str, result, usage: dict) -> None:
    status = result.status
    with STORE.lock:
        STORE.tasks[task_id]["tokenUsage"] = usage
        STORE.tasks[task_id]["filesAnalyzing"] = list(result.plan_files)
    if status == "completed":
        files = _change_files(factory, storage, project_id, result)
        change_set_id = _id()
        summary = (result.notes or "Proposed changes").strip()[:300]
        with STORE.lock:
            task = STORE.tasks[task_id]
            tenant = task["_tenant"]
            public = {"id": change_set_id, "taskId": task_id, "summary": summary, "status": "pending", "files": files}
            STORE.changesets[change_set_id] = {
                "tenant": tenant, "project_id": project_id, "task_id": task_id, "public": public,
            }
            reply = _message(
                "assistant",
                f"I prepared {len(files)} change{'s' if len(files) != 1 else ''}. {summary}\n\n"
                f"{_heads_up(result)}"
                f"Static review: {result.review_summary or 'not run'}. This is not a compile check, "
                "so please review the diff and build the project before relying on it.",
                taskId=task_id,
                changeSetId=change_set_id,
                plan={"summary": summary, "steps": [{"id": _id(), "title": "Edit files", "detail": "", "files": [f["path"] for f in files]}]},
            )
            STORE.messages.setdefault(project_id, []).append(reply)
            STORE.tasks[task_id]["filesModifying"] = [f["path"] for f in files]
            STORE.emit(task_id, "changeset.ready", {"type": "changeset.ready", "changeSet": public})
            STORE.emit(task_id, "message.completed", {"type": "message.completed", "message": reply})
        _set_status(task_id, "completed", f"{len(files)} change(s) ready to review")
        return
    if status == "needs_clarification":
        question = " ".join(result.questions) or "Could you say more about what should change?"
        _reply(project_id, task_id, question)
        _set_status(task_id, "blocked", "Needs more detail", blockedReason=question)
        return
    detail = "; ".join([*result.problems[:3], *result.warnings[:2]]) or status.replace("_", " ")
    text = {
        "unsupported": "This project type isn't supported yet: " + detail,
        "needs_approval": "This change needs your approval before it can be applied: "
        + "; ".join(f"{r.kind} {', '.join(r.paths)}" for r in result.approval_requests),
        "no_progress": "The model didn't change anything. " + (result.notes or "Try describing the change more specifically."),
    }.get(status, f"I couldn't complete that ({status.replace('_', ' ')}): {detail}")
    _reply(project_id, task_id, text[:1500])
    if status == "needs_approval":
        _set_status(task_id, "blocked", "Needs approval", blockedReason=text[:300])
    else:
        _set_status(task_id, "failed", "Could not complete", errorMessage=text[:300])


def _change_files(factory: sessionmaker, storage: ObjectStorage, project_id: str, result) -> list[dict]:
    files: list[dict] = []
    with factory() as db:
        project = db.get(Project, project_id)
        for kind, path in result.changes:
            original = None
            if project is not None and kind != "create":
                data, _ = _current(db, storage, project, path)
                original = None if data is None else data.decode("utf-8", errors="replace")
            proposed = None
            if kind != "delete":
                proposed = (result.workspace / path).read_text(encoding="utf-8", errors="replace")
            files.append({
                "path": path,
                "changeType": {"create": "add", "delete": "delete"}.get(kind, "modify"),
                "originalContent": original,
                "proposedContent": proposed,
                "decision": "pending",
            })
    return files


def _reply(project_id: str, task_id: str, text: str) -> None:
    reply = _message("assistant", text, taskId=task_id)
    with STORE.lock:
        STORE.messages.setdefault(project_id, []).append(reply)
        STORE.emit(task_id, "message.completed", {"type": "message.completed", "message": reply})


def _fail(project_id: str, task_id: str, text: str) -> None:
    _reply(project_id, task_id, text)
    _set_status(task_id, "failed", "Failed", errorMessage=text[:300])


def _cleanup_later(work: Path) -> None:
    import shutil

    threading.Timer(300, shutil.rmtree, args=(work,), kwargs={"ignore_errors": True}).start()


def _heads_up(result) -> str:
    """Deletions and similar high-impact changes, named up front: accepting the diff approves them."""
    lines = []
    for request in getattr(result, "deferred_approvals", ()):
        shown = ", ".join(request.paths[:4]) + (" and more" if len(request.paths) > 4 else "")
        label = request.kind.replace("_", " ")
        lines.append(f"- {label}{': ' + shown if shown else ''}")
    if not lines:
        return ""
    header = "Included for your review (accepting the diff approves them):"
    return header + chr(10) + chr(10).join(lines) + chr(10) + chr(10)
