"""The dev-only agent bridge: send a prompt, a thread runs the modify job, the user accepts the diff."""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _src in (
    ROOT / "packages/agent-core/codegen/src",
    ROOT / "packages/agent-core/codegen/tests",
    ROOT / "workers/ai-agent/src",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from androai_api.api.v1 import agent_dev
from androai_api.main import app
from sample_project import good_project

from .test_projects import make_zip, new_project, upload

if not any(getattr(r, "path", "").startswith("/api/v1/agent/") for r in app.routes):
    app.include_router(agent_dev.router, prefix="/api/v1/agent")

A = "/api/v1/agent"
P = "/api/v1/projects"
STRINGS = "app/src/main/res/values/strings.xml"
EMPTY_LIST = '    <string name="empty_list">Nothing to do</string>'
PROMPT = "Add a done label next to the empty_list string"
EDIT = {
    "edits": [
        {
            "action": "modify",
            "path": STRINGS,
            "description": "add a string",
            "edits": [{"old": EMPTY_LIST, "new": EMPTY_LIST + '\n    <string name="done">Done</string>'}],
        }
    ],
    "notes": "Added the done label.",
}


class FakeNvidia:
    reply: object = EDIT
    usage = {"input_tokens": 11, "output_tokens": 7, "calls": 1}

    def __init__(self, *a, **kw):
        pass

    def complete_json(self, system, user, output, *, max_output_tokens):
        if isinstance(self.reply, Exception):
            raise self.reply
        return output.model_validate(self.reply)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    import androai_codegen.llm_nvidia as nv

    monkeypatch.setattr(nv, "NvidiaClient", FakeNvidia)
    FakeNvidia.reply = EDIT
    with agent_dev.STORE.lock:
        agent_dev.STORE.__init__()
    yield


@pytest.fixture()
def todo_project(client, alice):
    _, h = alice
    pid = new_project(client, h, "Todo")
    files = {k: v for k, v in good_project().items()}
    assert upload(client, h, pid, make_zip(files)).status_code == 201
    return pid, h


def wait_done(client, h, task_id, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        t = client.get(f"{A}/tasks/{task_id}", headers=h).json()
        if t["status"] in agent_dev.TERMINAL:
            return t
        time.sleep(0.2)
    raise AssertionError(f"task still {t['status']} after {seconds}s")


def send(client, h, pid, prompt=PROMPT, intent="modify"):
    r = client.post(f"{A}/projects/{pid}/messages", headers=h, json={"prompt": prompt, "intent": intent, "context": {}})
    assert r.status_code == 201, r.text
    return r.json()


def file_text(client, h, pid, path):
    r = client.get(f"{P}/{pid}/files/content", headers=h, params={"path": path})
    assert r.status_code == 200, r.text
    return r.json()["content"]


def test_requires_login(client):
    assert client.get(f"{A}/projects/x/messages").status_code == 401
    assert client.get(f"{A}/tasks").status_code == 401


def test_modify_produces_a_pending_change_set_and_writes_nothing_yet(client, todo_project):
    pid, h = todo_project
    out = send(client, h, pid)
    assert out["task"]["status"] == "queued" and out["message"]["role"] == "user"
    task = wait_done(client, h, out["task"]["id"])
    assert task["status"] == "completed", task
    assert task["tokenUsage"] == {"inputTokens": 11, "outputTokens": 7} and STRINGS in task["filesModifying"]
    messages = client.get(f"{A}/projects/{pid}/messages", headers=h).json()
    assistant = [m for m in messages if m["role"] == "assistant"][-1]
    cs = client.get(f"{A}/change-sets/{assistant['changeSetId']}", headers=h).json()
    assert cs["status"] == "pending" and [f["path"] for f in cs["files"]] == [STRINGS]
    assert 'name="done"' in cs["files"][0]["proposedContent"] and 'name="done"' not in cs["files"][0]["originalContent"]
    assert 'name="done"' not in file_text(client, h, pid, STRINGS)  # nothing written before approval
    timeline = client.get(f"{A}/tasks/{task['id']}/timeline", headers=h).json()
    assert [e["status"] for e in timeline][0] == "analyzing" and timeline[-1]["status"] == "completed"


def test_accepting_writes_the_file_and_rejecting_does_not(client, todo_project):
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    cs_id = [m for m in client.get(f"{A}/projects/{pid}/messages", headers=h).json() if m.get("changeSetId")][-1]["changeSetId"]
    bad = client.post(f"{A}/change-sets/{cs_id}/decision", headers=h, json={"acceptPaths": ["not/in/set.kt"]})
    assert bad.status_code == 422
    done = client.post(f"{A}/change-sets/{cs_id}/decision", headers=h, json={"acceptPaths": [STRINGS]})
    assert done.status_code == 200 and done.json()["status"] == "applied"
    assert 'name="done"' in file_text(client, h, pid, STRINGS)
    again = client.post(f"{A}/change-sets/{cs_id}/decision", headers=h, json={"acceptPaths": []})
    assert again.status_code == 409 and task["status"] == "completed"


def test_rejecting_leaves_the_project_alone(client, todo_project):
    pid, h = todo_project
    wait_done(client, h, send(client, h, pid)["task"]["id"])
    cs_id = [m for m in client.get(f"{A}/projects/{pid}/messages", headers=h).json() if m.get("changeSetId")][-1]["changeSetId"]
    r = client.post(f"{A}/change-sets/{cs_id}/decision", headers=h, json={"acceptPaths": []})
    assert r.json()["status"] == "rejected" and 'name="done"' not in file_text(client, h, pid, STRINGS)


def test_accepting_after_the_file_changed_is_refused(client, todo_project):
    pid, h = todo_project
    wait_done(client, h, send(client, h, pid)["task"]["id"])
    cs_id = [m for m in client.get(f"{A}/projects/{pid}/messages", headers=h).json() if m.get("changeSetId")][-1]["changeSetId"]
    current = client.get(f"{P}/{pid}/files/content", headers=h, params={"path": STRINGS}).json()
    r = client.put(f"{P}/{pid}/files/content", headers=h, params={"path": STRINGS},
                   json={"content": current["content"] + "\n<!-- edited by hand -->\n", "base_sha256": current["sha256"]})
    assert r.status_code in (200, 201), r.text
    d = client.post(f"{A}/change-sets/{cs_id}/decision", headers=h, json={"acceptPaths": [STRINGS]})
    assert d.status_code == 409 and d.json()["error"]["code"] == "conflict"
    assert 'name="done"' not in file_text(client, h, pid, STRINGS)


def test_other_tenants_cannot_see_tasks_or_change_sets(client, todo_project, bob):
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    _, hb = bob
    assert client.get(f"{A}/tasks/{task['id']}", headers=hb).status_code == 404
    assert client.get(f"{A}/projects/{pid}/messages", headers=hb).status_code == 404
    assert client.get(f"{A}/tasks", headers=hb).json() == []


def test_unmatched_request_blocks_with_a_question(client, todo_project):
    pid, h = todo_project
    out = send(client, h, pid, "frobnicate the zxqv widget")
    task = wait_done(client, h, out["task"]["id"])
    assert task["status"] == "blocked" and "Which screen" in task["blockedReason"]


def test_chat_intent_gets_an_honest_reply_and_no_task(client, todo_project):
    pid, h = todo_project
    out = send(client, h, pid, "what does this app do?", intent="explain")
    assert out["task"] is None
    messages = client.get(f"{A}/projects/{pid}/messages", headers=h).json()
    assert messages[-1]["role"] == "assistant" and "not connected" in messages[-1]["content"]


def test_missing_model_key_fails_the_task_with_a_clear_message(client, todo_project, monkeypatch):
    import androai_codegen.llm_nvidia as nv

    def no_key(*a, **kw):
        raise nv.LlmError("NVIDIA_API_KEY is not set")

    monkeypatch.setattr(nv, "NvidiaClient", no_key)
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    assert task["status"] == "failed" and "NVIDIA_API_KEY" in task["errorMessage"]


def test_model_failure_fails_the_task_and_changes_nothing(client, todo_project):
    FakeNvidia.reply = RuntimeError("model exploded")
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    assert task["status"] == "failed" and "exploded" not in (task["errorMessage"] or "")
    assert 'name="done"' not in file_text(client, h, pid, STRINGS)


def test_only_one_running_task_per_project(client, todo_project):
    pid, h = todo_project
    first = send(client, h, pid)
    second = client.post(f"{A}/projects/{pid}/messages", headers=h, json={"prompt": PROMPT, "intent": "modify", "context": {}})
    assert second.status_code in (201, 409)
    wait_done(client, h, first["task"]["id"])


def test_event_stream_replays_and_ends_when_the_task_is_done(client, todo_project):
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    r = client.get(f"{A}/tasks/{task['id']}/events", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    for name in ("timeline.appended", "task.updated", "changeset.ready", "message.completed"):
        assert f"event: {name}" in r.text
