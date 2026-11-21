"""Adding AppSpec and ValidationProblem must not change anything that already existed."""

import hashlib
import json
from pathlib import Path

import androai_contracts as c
import pytest

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"

# SHA-256 of each existing schema file as it is on ``main`` (line endings normalised to LF), taken
# before AppSpec was added. A contracts change that touches one of these has to say so.
SCHEMA_SHA256 = {
    "AgentTask": "ba0696660b47b2998e0270ddf09c7c9de26f88b696fe796799b4bf2ed9c9dc94",
    "AgentTaskStatus": "89ba12b4cfee44faa01a056d8ed573094b3fcd62c3c4071320fe05ad26b6ed51",
    "BuildJob": "65307fc4ebc2e88c0ff74e412c66358c36fed31c3fa00edb879733987305ebd8",
    "BuildResult": "1e2fe2a5b18e0d317d7e43e2e6c6f7529096fb9e2dfef917c10f8194e438e7d7",
    "CodingResult": "fb267d019b2340850caed51fb0f7f4d216ea4e08433d535fbec10ad93b3a4e4f",
    "CodingTask": "5d1a7516ebf2419ef4af0b31ad76893c67cca5b84a9fa5de9a771687f5ca214e",
    "TestJob": "3567b83d6c80d6965b707d797cdb0ad3671430833e07c24abfee4d0c464806cc",
    "TestResult": "264613315fe847111e0ab01c2367efc186896364914d13b03e6c289f20995441",
}
# Field names and required fields of the existing models, as they are on ``main``.
EXISTING_FIELDS = {
    "AgentTask": (
        {
            "created_at",
            "id",
            "metadata",
            "project_id",
            "prompt",
            "schema_version",
            "user_id",
        },
        {"project_id", "user_id", "prompt"},
    ),
    "AgentTaskStatus": (
        {
            "error",
            "message",
            "progress",
            "schema_version",
            "state",
            "task_id",
            "updated_at",
        },
        {"task_id"},
    ),
    "BuildJob": (
        {
            "gradle_tasks",
            "id",
            "project_id",
            "schema_version",
            "source_key",
            "timeout_seconds",
            "variant",
        },
        {"project_id", "source_key"},
    ),
    "BuildResult": (
        {
            "artifact_key",
            "build_job_id",
            "duration_seconds",
            "error",
            "log_key",
            "schema_version",
            "state",
        },
        {"build_job_id", "state"},
    ),
    "CodingResult": (
        {"coding_task_id", "error", "files", "schema_version", "state", "summary"},
        {"coding_task_id", "state"},
    ),
    "CodingTask": (
        {
            "agent_task_id",
            "context_files",
            "id",
            "instructions",
            "project_id",
            "schema_version",
            "target",
        },
        {"agent_task_id", "project_id", "instructions", "target"},
    ),
    "TestJob": (
        {
            "build_job_id",
            "id",
            "kind",
            "project_id",
            "schema_version",
            "source_key",
            "timeout_seconds",
        },
        {"project_id", "source_key"},
    ),
    "TestResult": (
        {
            "error",
            "failed",
            "passed",
            "report_key",
            "schema_version",
            "skipped",
            "state",
            "test_job_id",
        },
        {"test_job_id", "state"},
    ),
}
PREVIOUS_EXPORTS = {
    "SCHEMA_VERSION",
    "AgentTask",
    "AgentTaskStatus",
    "AndroidTarget",
    "BuildJob",
    "BuildResult",
    "BuildVariant",
    "CodingResult",
    "CodingTask",
    "ContractModel",
    "ErrorInfo",
    "GeneratedFile",
    "Queues",
    "TaskState",
    "TestJob",
    "TestKind",
    "TestResult",
    "UiToolkit",
}


def normalised_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize("name", sorted(SCHEMA_SHA256))
def test_an_existing_schema_file_is_byte_identical_to_the_one_on_main(name):
    assert normalised_sha256(SCHEMAS / f"{name}.json") == SCHEMA_SHA256[name]


@pytest.mark.parametrize("name", sorted(SCHEMA_SHA256))
def test_an_existing_models_schema_is_still_what_its_class_generates(name):
    model = getattr(c, name)
    assert json.loads((SCHEMAS / f"{name}.json").read_text(encoding="utf-8")) == (
        model.model_json_schema()
    )


@pytest.mark.parametrize("name", sorted(EXISTING_FIELDS))
def test_an_existing_models_fields_and_required_fields_are_unchanged(name):
    fields, required = EXISTING_FIELDS[name]
    schema = getattr(c, name).model_json_schema()
    assert set(schema["properties"]) == fields
    assert set(schema.get("required", [])) == required
    assert schema["additionalProperties"] is False


def test_the_schema_version_is_not_bumped_by_an_additive_change():
    assert c.SCHEMA_VERSION == "0.1.0"
    assert c.AppSpec(
        app_name="A", screens=[{"id": "Home", "title": "Home"}]
    ).schema_version == ("0.1.0")
    assert (
        c.CodingTask.model_json_schema()["properties"]["schema_version"]["default"]
        == "0.1.0"
    )


def test_every_name_that_was_exported_before_still_is():
    assert PREVIOUS_EXPORTS <= set(c.__all__)
    assert {name for name in PREVIOUS_EXPORTS if not hasattr(c, name)} == set()
    assert {
        "AppSpec",
        "ScreenPlan",
        "UnsupportedCategory",
        "UnsupportedRequest",
        "ValidationProblem",
        "ProblemSeverity",
        "graph_problems",
    } <= set(c.__all__)


def test_existing_models_work_exactly_as_before():
    target = c.AndroidTarget(package_name="com.example.app")
    assert (target.language, target.ui, target.min_sdk, target.target_sdk) == (
        "kotlin",
        c.UiToolkit.COMPOSE,
        24,
        35,
    )
    task = c.CodingTask(
        agent_task_id="a", project_id="p", instructions="x", target=target
    )
    assert c.CodingTask.model_validate_json(task.model_dump_json()) == task
    assert (
        "app_spec" not in c.CodingTask.model_fields
    )  # wiring AppSpec in is a separate change


def test_the_new_models_follow_the_house_rules():
    for model in (c.AppSpec, c.ScreenPlan, c.UnsupportedRequest, c.ValidationProblem):
        assert issubclass(model, c.ContractModel)
        assert model.model_config["extra"] == "forbid"
        assert "schema_version" in model.model_fields


def test_the_export_script_writes_one_schema_per_listed_model_and_only_those():
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "export_contract_schemas.py"
    )
    text = script.read_text(encoding="utf-8")
    listed = {
        name
        for name in ("AppSpec", "ValidationProblem", *SCHEMA_SHA256)
        if f"c.{name}" in text
    }
    assert listed == {"AppSpec", "ValidationProblem", *SCHEMA_SHA256}
    on_disk = {p.stem for p in SCHEMAS.glob("*.json")}
    assert on_disk == listed  # no stale or missing schema file
