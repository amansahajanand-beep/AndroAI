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
    ]
    assert cli.main(args, client=FakeClient(EDIT)) == 0
    out = capsys.readouterr().out
    assert "status: completed" in out and "----- diff -----" in out
    assert (
        cli.main([*args[:-1], str(tmp_path / "w2"), "--json"], client=FakeClient(EDIT))
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
