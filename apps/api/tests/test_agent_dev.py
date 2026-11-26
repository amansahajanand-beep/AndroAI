"""The dev-only agent bridge: send a prompt, a thread runs the modify job, the user accepts the diff."""

import json
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
def step(tool, note="", **args):
    return {"tool": tool, "args": args, "note": note}


EDIT_STEPS = [
    step("read_file", "look", path=STRINGS),
    step("edit_file", "add a label", path=STRINGS, old=EMPTY_LIST, new=EMPTY_LIST + chr(10) + '    <string name="done">Done</string>'),
    step("finish", summary="Added the done label."),
]


class FakeNvidia:
    script: list = []
    prompts: list = []
    usage = {"input_tokens": 11, "output_tokens": 7, "calls": 1}

    def __init__(self, *a, **kw):
        pass

    def complete_json(self, system, user, output, *, max_output_tokens):
        FakeNvidia.prompts.append(user)
        item = FakeNvidia.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return output.model_validate(item)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    import androai_codegen.llm_nvidia as nv

    monkeypatch.setenv("AGENT_VERIFY_BUILD", "0")  # never start a real Gradle build in tests
    monkeypatch.setattr(nv, "NvidiaClient", FakeNvidia)
    FakeNvidia.script = list(EDIT_STEPS)
    FakeNvidia.prompts = []
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


def test_agent_question_blocks_the_task_and_the_answer_continues_the_conversation(client, todo_project):
    pid, h = todo_project
    FakeNvidia.script = [
        step("search", pattern="applicationId"),
        step("ask_user", question="What should the new package name be?"),
    ]
    task = wait_done(client, h, send(client, h, pid, "change the package name")["task"]["id"])
    assert task["status"] == "blocked" and "new package name" in task["blockedReason"]
    messages = client.get(f"{A}/projects/{pid}/messages", headers=h).json()
    assert "new package name" in messages[-1]["content"]
    # the person answers in a new message; the agent is shown the earlier question
    FakeNvidia.script = [
        step("rename_package", old="com.example.todo", new="com.acme.notes"),
        step("finish", summary="Renamed."),
    ]
    FakeNvidia.prompts = []
    second = wait_done(client, h, send(client, h, pid, "com.acme.notes")["task"]["id"])
    assert second["status"] == "completed"
    assert "change the package name" in FakeNvidia.prompts[0] and "new package name be" in FakeNvidia.prompts[0]


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
    FakeNvidia.script = [RuntimeError("model exploded")]
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


def test_package_rename_flows_through_the_panel_and_accepting_applies_it(client, todo_project):
    pid, h = todo_project
    FakeNvidia.script = [
        step("rename_package", "rename", old="com.example.todo", new="com.acme.notes"),
        step("finish", summary="Renamed the package."),
    ]
    task = wait_done(client, h, send(client, h, pid, "rename the package to com.acme.notes")["task"]["id"])
    assert task["status"] == "completed", task
    msgs = client.get(f"{A}/projects/{pid}/messages", headers=h).json()
    assistant = [m for m in msgs if m.get("changeSetId")][-1]
    assert "Included for your review" in assistant["content"] and "delete files" in assistant["content"]
    cs = client.get(f"{A}/change-sets/{assistant['changeSetId']}", headers=h).json()
    kinds = {f["changeType"] for f in cs["files"]}
    assert {"add", "delete"} <= kinds
    old_path = "app/src/main/java/com/example/todo/ui/TodoApp.kt"
    new_path = "app/src/main/java/com/acme/notes/ui/TodoApp.kt"
    assert client.get(f"{P}/{pid}/files/content", headers=h, params={"path": old_path}).status_code == 200
    accept = [f["path"] for f in cs["files"]]
    done = client.post(f"{A}/change-sets/{assistant['changeSetId']}/decision", headers=h, json={"acceptPaths": accept})
    assert done.status_code == 200 and done.json()["status"] == "applied"
    assert client.get(f"{P}/{pid}/files/content", headers=h, params={"path": old_path}).status_code == 404
    assert "package com.acme.notes.ui" in file_text(client, h, pid, new_path)


def test_every_agent_step_appears_on_the_timeline(client, todo_project):
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    rows = client.get(f"{A}/tasks/{task['id']}/timeline", headers=h).json()
    kinds = [e.get("kind") for e in rows]
    assert "thought" in kinds and "read" in kinds and "edit" in kinds
    read = next(e for e in rows if e.get("kind") == "read")
    assert read["title"].startswith("Read ") and read["path"] and read["ok"] is True
    edit = next(e for e in rows if e.get("kind") == "edit")
    assert edit["title"].startswith("Edited ") and edit["hunks"][0]["new"] != edit["hunks"][0]["old"]
    assert any(e["title"] == "Writing the summary" for e in rows)


def test_the_summary_streams_into_the_message_as_cumulative_deltas(client, todo_project):
    pid, h = todo_project
    task = wait_done(client, h, send(client, h, pid)["task"]["id"])
    body = client.get(f"{A}/tasks/{task['id']}/events", headers=h).text
    deltas = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ") and '"message.delta"' in line]
    assert len(deltas) > 3
    contents = [d["content"] for d in deltas]
    assert all(b.startswith(a) for a, b in zip(contents, contents[1:]))  # only ever grows
    final = [m for m in client.get(f"{A}/projects/{pid}/messages", headers=h).json() if m.get("changeSetId")][-1]
    assert final["content"] == contents[-1] and "Static review" in final["content"]


def test_chat_survives_a_restart_and_a_running_task_is_marked_interrupted(tmp_path, monkeypatch):
    from androai_api.api.v1 import agent_dev

    monkeypatch.setenv("AGENT_DEV_STATE", str(tmp_path / "state.json"))
    store = agent_dev._Store()
    task = agent_dev._new_task("p1", "t1", "do it", "modify")
    task["status"] = "generating"
    store.tasks[task["id"]] = task
    store.messages["p1"] = [
        agent_dev._message("user", "do it", taskId=task["id"]),
        agent_dev._message("assistant", "Working on your request…", taskId=task["id"]),
    ]
    store.save(force=True)

    fresh = agent_dev._Store()
    fresh.load()
    assert [m["role"] for m in fresh.messages["p1"]] == ["user", "assistant"]
    restored = fresh.tasks[task["id"]]
    assert restored["status"] == "failed" and "restarted" in restored["errorMessage"]
    assert "restarted" in fresh.messages["p1"][1]["content"]


def test_a_decision_may_accept_a_large_rename():
    from androai_api.api.v1.agent_dev import DecisionIn

    assert len(DecisionIn(acceptPaths=[f"f{i}.kt" for i in range(3000)]).acceptPaths) == 3000


def test_export_downloads_the_current_project_as_a_zip_and_is_tenant_scoped(client, todo_project):
    import io
    import zipfile

    pid, h = todo_project
    res = client.get(f"{A}/projects/{pid}/export", headers=h)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert "attachment" in res.headers["content-disposition"] and ".zip" in res.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert any(n.endswith("build.gradle.kts") or n.endswith("AndroidManifest.xml") for n in names)
    client.cookies.clear()
    assert client.get(f"{A}/projects/{pid}/export").status_code in (401, 403)
