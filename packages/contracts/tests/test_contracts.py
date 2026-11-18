import pytest
from pydantic import ValidationError

from androai_contracts import (
    AgentTask,
    AgentTaskStatus,
    AndroidTarget,
    BuildJob,
    BuildResult,
    CodingResult,
    CodingTask,
    TaskState,
    TestJob,
    TestResult,
)


def test_round_trip_all_contracts():
    task = AgentTask(project_id="p", user_id="u", prompt="build a todo app")
    coding = CodingTask(
        agent_task_id=task.id,
        project_id="p",
        instructions="x",
        target=AndroidTarget(package_name="com.example.app"),
    )
    models = [
        task,
        AgentTaskStatus(task_id=task.id),
        coding,
        CodingResult(coding_task_id=coding.id, state=TaskState.SUCCEEDED),
        BuildJob(project_id="p", source_key="k"),
        BuildResult(build_job_id="b", state=TaskState.FAILED),
        TestJob(project_id="p", source_key="k"),
        TestResult(test_job_id="t", state=TaskState.QUEUED),
    ]
    for m in models:
        assert type(m).model_validate_json(m.model_dump_json()) == m


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        AgentTask(project_id="p", user_id="u", prompt="x", bogus=1)
