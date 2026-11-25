"""The modify job and its CLI, end to end on a small project with a fake model."""

import json
import zipfile

import pytest
from androai_codegen.ingest import OwnershipAttestation
from sample_project import good_project

from androai_agent import cli
from androai_agent.modify_job import ModifyJobRequest, run_modify_job

STRINGS = "app/src/main/res/values/strings.xml"
EMPTY_LIST = '    <string name="empty_list">Nothing to do</string>'
ATTEST = OwnershipAttestation(basis="own", statement="test", attested_by="tester")

EDIT = {
    "edits": [
        {
            "action": "modify",
            "path": STRINGS,
            "description": "add a string",
            "edits": [
                {
                    "old": EMPTY_LIST,
                    "new": EMPTY_LIST + '\n    <string name="done">Done</string>',
                }
            ],
        }
    ],
    "notes": "added",
}


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, system, user, output, *, max_output_tokens):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return output.model_validate(reply)


def make_zip(path, files, prefix=""):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            z.writestr(prefix + name, content)
    return path


@pytest.fixture
def todo_zip(tmp_path):
    return make_zip(tmp_path / "todo.zip", good_project(), "todo-main/")


def request(tmp_path, zip_path, prompt, **kw):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    kw.setdefault("mode", "single")  # these tests script the one-shot proposer
    return ModifyJobRequest(
        zip_path=zip_path, prompt=prompt, work_dir=work, attestation=ATTEST, **kw
    )


PROMPT = "Add a done label to the empty_list strings"


def test_full_job_completes_and_edits_the_workspace(tmp_path, todo_zip):
    client = FakeClient(EDIT)
    result = run_modify_job(request(tmp_path, todo_zip, PROMPT), client)
    assert result.status == "completed" and result.stage == "done", result
    assert result.detection and result.detection.supported
    assert [p for _, p in result.changes] == [STRINGS]
    assert 'name="done"' in (result.workspace / STRINGS).read_text()
    assert result.checkpoint_id and result.patch_id and "+" in result.diff
    assert result.review_summary and result.review_blocking is False
    assert "Add a done label" in client.prompts[0]
    # the uploaded archive is untouched
    assert "done" not in zipfile.ZipFile(todo_zip).read("todo-main/" + STRINGS).decode()


def test_unsupported_framework_never_reaches_the_model(tmp_path):
    flutter = make_zip(
        tmp_path / "f.zip",
        {
            "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",
            "android/settings.gradle": "",
        },
    )
    client = FakeClient()
    result = run_modify_job(request(tmp_path, flutter, PROMPT), client)
    assert (
        result.status == "unsupported"
        and result.stage == "detect"
        and not client.prompts
    )
    assert "Flutter" in result.problems[0]


def test_unmatched_request_asks_a_question_and_sends_nothing(tmp_path, todo_zip):
    client = FakeClient()
    result = run_modify_job(
        request(tmp_path, todo_zip, "frobnicate the zxqv widget"), client
    )
    assert (
        result.status == "needs_clarification"
        and result.questions
        and not client.prompts
    )
    assert result.workspace and not result.plan_files


def test_model_failure_leaves_the_project_untouched(tmp_path, todo_zip):
    result = run_modify_job(
        request(tmp_path, todo_zip, PROMPT), FakeClient(RuntimeError("down"))
    )
    assert result.status == "provider_failure" and not result.changes
    assert 'name="done"' not in (result.workspace / STRINGS).read_text()


def test_model_editing_outside_the_plan_is_rejected(tmp_path, todo_zip):
    bad = {
        "edits": [
            {
                "action": "create",
                "path": "evil/Backdoor.kt",
                "description": "x",
                "content": "x",
            }
        ]
    }
    result = run_modify_job(request(tmp_path, todo_zip, PROMPT), FakeClient(bad, bad))
    assert result.status == "rejected" and not result.changes


def test_not_a_zip_is_reported_not_raised(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    result = run_modify_job(request(tmp_path, junk, PROMPT), FakeClient())
    assert result.status == "unsupported"


def test_cli_requires_consent_before_sending_code(tmp_path, todo_zip, capsys):
    code = cli.main(["--zip", str(todo_zip), "--prompt", PROMPT])
    assert code == 2 and "--yes-send-code" in capsys.readouterr().err


def test_cli_prints_a_summary_and_json(tmp_path, todo_zip, capsys):
    args = [
        "--zip",
        str(todo_zip),
        "--prompt",
        PROMPT,
        "--work-dir",
        str(tmp_path / "w1"),
        "--mode",
        "single",
    ]
    assert cli.main(args, client=FakeClient(EDIT)) == 0
    out = capsys.readouterr().out
    assert "status: completed" in out and "----- diff -----" in out
    assert (
        cli.main(
            [*args[:5], str(tmp_path / "w2"), "--mode", "single", "--json"],
            client=FakeClient(EDIT),
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_cli_missing_zip(tmp_path, capsys):
    assert (
        cli.main(
            ["--zip", str(tmp_path / "no.zip"), "--prompt", "x"], client=FakeClient()
        )
        == 2
    )


def test_dotenv_only_fills_nvidia_keys(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "NVIDIA_API_KEY=abc # c\nJWT_SECRET=zzz\nNVIDIA_MODEL=m/x\n"
    )
    for name in ("NVIDIA_API_KEY", "NVIDIA_MODEL", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert cli.load_dotenv(tmp_path) == tmp_path / ".env"
    import os

    assert os.environ["NVIDIA_API_KEY"] == "abc" and os.environ["NVIDIA_MODEL"] == "m/x"
    assert "JWT_SECRET" not in os.environ
    monkeypatch.delenv("NVIDIA_API_KEY"), monkeypatch.delenv("NVIDIA_MODEL")


def test_ui_code_changes_also_get_the_modules_strings_file(tmp_path, todo_zip):
    result = run_modify_job(request(tmp_path, todo_zip, PROMPT), FakeClient(EDIT))
    assert STRINGS in result.plan_files
    java_only = tuple(p for p in result.plan_files if p.endswith(".xml"))
    assert java_only  # resources stay editable alongside the code


# ---- agent mode (the default) -------------------------------------------------------------------


def step(tool, note="", **args):
    return {"tool": tool, "args": args, "note": note}


def agent_request(tmp_path, zip_path, prompt, **kw):
    kw.setdefault("mode", "agent")
    return request(tmp_path, zip_path, prompt, **kw)


def test_agent_renames_the_package_and_edits_text_in_one_job(tmp_path, todo_zip):
    client = FakeClient(
        step("search", pattern="applicationId", glob="*.kts"),
        step("rename_package", old="com.example.todo", new="com.acme.notes"),
        step("edit_file", path=STRINGS, old="Nothing to do", new="All done"),
        step("finish", summary="Renamed the package and reworded one string."),
    )
    seen = []
    result = run_modify_job(
        agent_request(tmp_path, todo_zip, "rename the package to com.acme.notes"),
        client,
        progress=lambda stage, text: seen.append((stage, text)),
    )
    assert result.status == "completed", result
    paths = {p for _, p in result.changes}
    assert (
        "app/src/main/java/com/acme/notes/ui/TodoApp.kt" in paths and STRINGS in paths
    )
    assert result.diff and result.notes.startswith("Renamed the package")
    assert any(r.kind == "delete_files" for r in result.deferred_approvals)
    assert 'name="empty_list">All done' in (result.workspace / STRINGS).read_text()
    assert (
        result.workspace / "app/src/main/java/com/acme/notes/ui/TodoApp.kt"
    ).is_file()
    texts = [t for stage, t in seen if stage == "agent"]
    assert texts[0].startswith("Searching") and any(
        t.startswith("Renaming package") for t in texts
    )


def test_agent_asking_a_question_becomes_a_clarification(tmp_path, todo_zip):
    client = FakeClient(
        step("search", pattern="namespace"),
        step("ask_user", question="What should the new package name be?"),
    )
    result = run_modify_job(
        agent_request(tmp_path, todo_zip, "change the package name"), client
    )
    assert (
        result.status == "needs_clarification"
        and "new package name" in result.questions[0]
    )
    assert not result.changes


def test_agent_gets_the_earlier_conversation_so_an_answer_has_context(
    tmp_path, todo_zip
):
    client = FakeClient(step("finish", summary="nothing to do"))
    history = (
        ("user", "change the package name"),
        ("assistant", "What should the new name be?"),
    )
    run_modify_job(
        agent_request(tmp_path, todo_zip, "com.acme.notes", history=history), client
    )
    assert (
        "change the package name" in client.prompts[0]
        and "What should the new name" in client.prompts[0]
    )


def test_agent_does_not_give_up_on_a_vague_request_it_can_explore(tmp_path, todo_zip):
    client = FakeClient(
        step("list_dir", path=""), step("finish", summary="looked around, no change")
    )
    result = run_modify_job(
        agent_request(tmp_path, todo_zip, "frobnicate the zxqv widget"), client
    )
    assert (
        result.status == "no_progress" and client.prompts
    )  # unlike single mode, the model ran


def test_agent_failures_are_reported_not_raised(tmp_path, todo_zip):
    result = run_modify_job(
        agent_request(tmp_path, todo_zip, "x"), FakeClient(RuntimeError("down"))
    )
    assert result.status == "provider_failure" and not result.changes


def test_agent_never_touches_the_uploaded_zip_or_unaccepted_files(tmp_path, todo_zip):
    before = todo_zip.read_bytes()
    client = FakeClient(
        step("rename_package", old="com.example.todo", new="com.acme.notes"),
        step("finish", summary="x"),
    )
    run_modify_job(agent_request(tmp_path, todo_zip, "rename"), client)
    assert todo_zip.read_bytes() == before


def test_cli_defaults_to_agent_mode(tmp_path, todo_zip, capsys):
    client = FakeClient(
        step("edit_file", path=STRINGS, old="Nothing to do", new="Empty"),
        step("finish", summary="reworded"),
    )
    code = cli.main(
        [
            "--zip",
            str(todo_zip),
            "--prompt",
            "reword the empty text",
            "--work-dir",
            str(tmp_path / "w"),
        ],
        client=client,
    )
    assert code == 0 and "status: completed" in capsys.readouterr().out


def test_the_agent_is_given_a_map_of_the_usual_key_files(tmp_path, todo_zip):
    client = FakeClient(step("finish", summary="nothing"))
    run_modify_job(agent_request(tmp_path, todo_zip, "change the colors"), client)
    first = client.prompts[0]
    assert "key files" in first
    for expected in (
        "colors.xml",
        "themes.xml",
        "strings.xml",
        "Color.kt",
        "Theme.kt",
        "AndroidManifest.xml",
    ):
        assert expected in first, expected
    assert "ExampleUnitTest" not in first  # test sources are not key files
