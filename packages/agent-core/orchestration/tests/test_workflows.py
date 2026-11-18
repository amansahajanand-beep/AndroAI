import pytest

from androai_contracts import AgentTask, CodingResult, ErrorInfo, GeneratedFile, TaskState
from androai_orchestration_core.intelligence import ProjectScope
from androai_orchestration_core.persistence import RunStatus
from androai_orchestration_core.workflows import Limits

from harness import (
    Env, REQ, build_fail, build_ok, coding_ok, llm_script, ok_tests,
)

T = "tenant-1"
SCOPE = ProjectScope(tenant_id=T, project_id="p1")


def task(prompt="build a shop app"):
    return AgentTask(project_id="p1", user_id="u1", prompt=prompt)


def approve(env, run_id):
    return env.svc.respond(SCOPE, run_id, {"approved": True})


def finish_coding(env, n=None):
    """Deliver results for every coding task submitted so far that is not done."""
    for t in env.rec.coding:
        env.svc.on_coding_result(coding_ok(t))


def drive_to_validation(env, run_id):
    snap = approve(env, run_id)
    while snap.status == RunStatus.WAITING_CODING:
        before = len(env.rec.coding)
        snap = env.svc.on_coding_result(coding_ok(env.rec.coding[-1])) or snap
        assert len(env.rec.coding) >= before
    return snap


def test_new_app_happy_path():
    env = Env()
    snap = env.svc.start(task(), T)
    assert snap.status == RunStatus.WAITING_APPROVAL
    assert snap.pending["type"] == "plan_approval" and snap.pending["plan"]["tasks"] == ["Scaffold", "Home screen"]

    snap = drive_to_validation(env, snap.run_id)
    assert snap.status == RunStatus.WAITING_VALIDATION
    assert len(env.rec.coding) == 2 and len(env.rec.builds) == 1 and len(env.rec.tests) == 1
    # task 2 is only dispatched after task 1's result
    assert env.rec.coding[0].id != env.rec.coding[1].id
    assert '"androai_task_envelope": 1' in env.rec.coding[0].instructions

    # test result first, then build: run must keep waiting until both are in
    assert env.svc.on_test_result(ok_tests(env.rec.tests[0])).status == RunStatus.WAITING_VALIDATION
    done = env.svc.on_build_result(build_ok(env.rec.builds[0]))
    assert done.status == RunStatus.SUCCEEDED
    assert done.result["files_modified"] and done.result["tokens"] > 0
    assert env.store.usage(snap.run_id)  # token usage persisted
    kinds = {s["node"] for s in env.store.steps(snap.run_id)}
    assert {"requirements", "architecture", "decompose", "approval", "validate", "evaluate"} <= kinds


def test_start_is_idempotent():
    env = Env()
    t = task()
    a = env.svc.start(t, T)
    b = env.svc.start(t, T)
    assert a.run_id == b.run_id and len(env.provider.calls) == 3  # no second planning pass


def test_duplicate_result_delivery_is_ignored():
    env = Env()
    snap = env.svc.start(task(), T)
    approve(env, snap.run_id)
    res = coding_ok(env.rec.coding[0])
    env.svc.on_coding_result(res)
    n = len(env.rec.coding)
    assert env.svc.on_coding_result(res) is None
    assert len(env.rec.coding) == n


def test_essential_clarification_then_assumptions():
    amb = {**REQ, "ambiguities": [{"question": "Which store?", "essential": True}]}
    env = Env(llm=llm_script({"RequirementSpec": amb}))
    snap = env.svc.start(task("make something"), T)
    assert snap.status == RunStatus.WAITING_CLARIFICATION and snap.pending["questions"] == ["Which store?"]
    snap = env.svc.respond(SCOPE, snap.run_id, {"answers": {"Which store?": "groceries"}})
    # second round: ambiguities are forced non-essential, so no second question
    assert snap.status == RunStatus.WAITING_APPROVAL


def test_plan_revision_and_cap():
    env = Env(limits=Limits(max_plan_revisions=1))
    snap = env.svc.start(task(), T)
    snap = env.svc.respond(SCOPE, snap.run_id, {"approved": False, "feedback": "add dark mode"})
    assert snap.status == RunStatus.WAITING_APPROVAL
    assert any("add dark mode" in m.content for _, r in env.provider.calls for m in r.messages)
    snap = env.svc.respond(SCOPE, snap.run_id, {"approved": False, "feedback": "again"})
    assert snap.status == RunStatus.FAILED and snap.error["code"] == "revision_limit"


def test_rejection_cancels():
    env = Env()
    snap = env.svc.start(task(), T)
    snap = env.svc.respond(SCOPE, snap.run_id, {"approved": False})
    assert snap.status == RunStatus.CANCELLED


def test_tenant_isolation():
    env = Env()
    snap = env.svc.start(task(), T)
    other = ProjectScope(tenant_id="evil", project_id="p1")
    assert env.svc.status(other, snap.run_id) is None
    with pytest.raises(LookupError):
        env.svc.respond(other, snap.run_id, {"approved": True})


def test_repair_loop_then_success():
    env = Env()
    snap = env.svc.start(task(), T)
    snap = drive_to_validation(env, snap.run_id)
    env.svc.on_test_result(ok_tests(env.rec.tests[0]))
    snap = env.svc.on_build_result(build_fail(env.rec.builds[0]))
    assert snap.status == RunStatus.WAITING_CODING  # repair task dispatched
    repair = env.rec.coding[-1]
    assert '"task_type": "repair"' in repair.instructions
    env.svc.on_coding_result(coding_ok(repair))
    assert len(env.rec.builds) == 2
    env.svc.on_test_result(ok_tests(env.rec.tests[1]))
    assert env.svc.on_build_result(build_ok(env.rec.builds[1])).status == RunStatus.SUCCEEDED


def test_repair_attempts_are_bounded_and_never_succeed():
    env = Env(limits=Limits(max_repair_attempts=2))
    snap = env.svc.start(task(), T)
    snap = drive_to_validation(env, snap.run_id)
    for _ in range(10):
        if snap.status != RunStatus.WAITING_VALIDATION:
            break
        env.svc.on_test_result(ok_tests(env.rec.tests[-1]))
        snap = env.svc.on_build_result(build_fail(env.rec.builds[-1]))
        if snap.status == RunStatus.WAITING_CODING:
            snap = env.svc.on_coding_result(coding_ok(env.rec.coding[-1]))
    assert snap.status == RunStatus.FAILED and snap.error["code"] == "repair_exhausted"
    assert len(env.rec.builds) == 3  # initial + 2 repairs


def test_infrastructure_failure_is_not_blamed_on_code():
    env = Env(limits=Limits(max_infra_retries=1))
    snap = env.svc.start(task(), T)
    snap = drive_to_validation(env, snap.run_id)
    calls_before = len(env.provider.calls)
    env.svc.on_test_result(ok_tests(env.rec.tests[0]))
    snap = env.svc.on_build_result(build_fail(env.rec.builds[0], code="infra_worker_lost", retryable=True, msg="worker lost"))
    assert snap.status == RunStatus.WAITING_VALIDATION and len(env.rec.builds) == 2  # re-validated, no repair
    assert len(env.provider.calls) == calls_before  # no LLM repair call
    env.svc.on_test_result(ok_tests(env.rec.tests[1]))
    snap = env.svc.on_build_result(build_fail(env.rec.builds[1], code="infra_worker_lost", retryable=True, msg="worker lost"))
    assert snap.status == RunStatus.FAILED and snap.error["code"] == "infrastructure_failure"
    assert len(env.rec.coding) == 2  # never asked the coding engine to "fix" infra


def test_failing_tests_block_success():
    env = Env(limits=Limits(max_repair_attempts=0))
    snap = env.svc.start(task(), T)
    snap = drive_to_validation(env, snap.run_id)
    env.svc.on_test_result(ok_tests(env.rec.tests[0], failed=2))
    snap = env.svc.on_build_result(build_ok(env.rec.builds[0]))
    assert snap.status == RunStatus.FAILED


def test_coding_failure_retry_then_fail():
    env = Env()
    snap = env.svc.start(task(), T)
    approve(env, snap.run_id)
    first = env.rec.coding[0]
    bad = CodingResult(coding_task_id=first.id, state=TaskState.FAILED, error=ErrorInfo(code="x", message="rate", retryable=True))
    snap = env.svc.on_coding_result(bad)
    assert snap.status == RunStatus.WAITING_CODING and len(env.rec.coding) == 2  # one retry, new id
    bad2 = CodingResult(coding_task_id=env.rec.coding[1].id, state=TaskState.FAILED, error=ErrorInfo(code="x", message="boom", retryable=True))
    assert env.svc.on_coding_result(bad2).status == RunStatus.FAILED


def test_unsafe_coding_output_rejected():
    env = Env()
    snap = env.svc.start(task(), T)
    approve(env, snap.run_id)
    res = coding_ok(env.rec.coding[0], [GeneratedFile(path="../../etc/passwd", content="x")])
    snap = env.svc.on_coding_result(res)
    assert snap.status == RunStatus.FAILED and snap.error["code"] == "unsafe_output"
    assert env.workspace.snapshots == 0


def test_budget_exceeded_stops_run():
    env = Env(limits=Limits(budget={"max_llm_calls": 1}))
    snap = env.svc.start(task(), T)
    assert snap.status == RunStatus.FAILED and snap.error["code"] == "budget_exceeded"


def test_cancel_stops_progress():
    env = Env()
    snap = env.svc.start(task(), T)
    approve(env, snap.run_id)
    env.svc.cancel(SCOPE, snap.run_id)
    env.svc.on_coding_result(coding_ok(env.rec.coding[0]))
    assert env.store.get_run(SCOPE, snap.run_id).status == RunStatus.CANCELLED
    assert len(env.rec.coding) == 1 and env.workspace.snapshots == 0  # nothing advanced


def test_recovery_after_restart_mid_wait():
    env = Env()
    snap = env.svc.start(task(), T)
    approve(env, snap.run_id)
    svc2 = env.new_service()  # worker restarted: in-memory state gone, DB + checkpoints remain
    res = coding_ok(env.rec.coding[0])
    env.store.complete_job(res.coding_task_id, res.model_dump(mode="json"))  # result stored, wake lost
    assert svc2.recover() == [snap.run_id]
    assert len(env.rec.coding) == 2  # advanced to the next task from the checkpoint
    assert svc2.status(SCOPE, snap.run_id).status == RunStatus.WAITING_CODING


def test_recovery_of_crashed_running_run():
    env = Env()
    snap = env.svc.start(task(), T)
    env.store.set_status(snap.run_id, RunStatus.RUNNING)  # as if the worker died mid-node
    import datetime
    from sqlalchemy import update
    from androai_orchestration_core.persistence.store import AgentRun
    with env.store._sf() as s:
        s.execute(update(AgentRun).values(updated_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)))
        s.commit()
    assert env.new_service().recover(stale_seconds=60) == [snap.run_id]
    assert env.store.get_run(SCOPE, snap.run_id).status == RunStatus.WAITING_APPROVAL
