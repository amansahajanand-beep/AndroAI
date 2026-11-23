from androai_contracts import AgentTask, GeneratedFile
from androai_orchestration_core.intelligence import ProjectScope
from androai_orchestration_core.persistence import RunStatus
from androai_orchestration_core.workflows import Limits

from harness import Env, MOD, build_fail, build_ok, coding_ok, llm_script, ok_tests

T = "tenant-1"
SCOPE = ProjectScope(tenant_id=T, project_id="p1")
AUTH = "app/src/main/java/com/example/shop/auth/AuthRepository.kt"


def task(prompt="add google login"):
    return AgentTask(project_id="p1", user_id="u1", prompt=prompt)


def test_modify_plan_is_grounded_in_the_project():
    env = Env()
    snap = env.svc.start(task(), T, workflow="modify")
    assert snap.status == RunStatus.WAITING_APPROVAL
    plan = env.store.latest_artifact(snap.run_id, "modification_plan")
    assert plan["affected_files"] == [AUTH]  # hallucinated file dropped
    assert plan["ungrounded_files"] == ["does/not/Exist.kt"]
    assert plan["requires_approval"] and "model referenced files that do not exist in the project" in plan["approval_reasons"]
    assert plan["project_analysis"]["authentication_exists"] is True
    assert any("LoginActivity" in r for r in plan["risks"])  # dependent file flagged
    assert env.store.latest_artifact(snap.run_id, "context_refs")
    # profile artifact holds facts only - no source text
    assert "class AuthRepository" not in str(env.store.latest_artifact(snap.run_id, "project_profile"))


def test_modify_end_to_end_and_scope_enforced():
    env = Env()
    snap = env.svc.start(task(), T, workflow="modify")
    snap = env.svc.respond(SCOPE, snap.run_id, {"approved": True})
    assert snap.status == RunStatus.WAITING_CODING
    ct = env.rec.coding[0]
    assert ct.target.package_name == "com.example.shop" and ct.target.min_sdk == 24
    assert AUTH in ct.context_files and "local.properties" not in ct.context_files
    assert "Preserve: email login" in ct.instructions
    # engine touching an unplanned file is rejected
    bad = env.svc.on_coding_result(coding_ok(ct, [GeneratedFile(path="app/src/main/java/com/example/shop/Other.kt", content="x")]))
    assert bad.status == RunStatus.FAILED and bad.error["code"] == "out_of_scope_change"


def test_modify_success_updates_index_and_validates():
    env = Env()
    snap = env.svc.start(task(), T, workflow="modify")
    env.svc.respond(SCOPE, snap.run_id, {"approved": True})
    new = "app/src/main/java/com/example/shop/auth/GoogleAuth.kt"
    env.svc.on_coding_result(coding_ok(env.rec.coding[0], [GeneratedFile(path=new, content="class GoogleAuth")]))
    idx = env.deps.indexes[SCOPE.key]
    assert new in idx.files and idx.symbols_named("GoogleAuth")
    env.svc.on_test_result(ok_tests(env.rec.tests[0]))
    assert env.svc.on_build_result(build_ok(env.rec.builds[0])).status == RunStatus.SUCCEEDED


def test_modify_refuses_to_guess_missing_package():
    env = Env(files={"app/src/main/java/A.kt": b"class A"})
    snap = env.svc.start(task(), T, workflow="modify")
    snap = env.svc.respond(SCOPE, snap.run_id, {"approved": True})
    assert snap.status == RunStatus.FAILED and "refusing to guess" in snap.error["message"]


def test_modify_empty_project_fails_fast():
    env = Env(files={})
    assert env.svc.start(task(), T, workflow="modify").error["code"] == "empty_project"


def test_destructive_plan_cannot_skip_approval():
    mod = {**MOD, "deleted_files": [AUTH]}
    env = Env(llm=llm_script({"ModificationPlan": mod}), limits=Limits(require_plan_approval=False))
    snap = env.svc.start(task(), T, workflow="modify")
    assert snap.status == RunStatus.WAITING_APPROVAL  # auto-approval is disabled but deletion still blocks
    assert "deletes files" in snap.pending["plan"]["approval_reasons"]


def test_repair_workflow_classifies_and_repairs():
    env = Env()
    failure = {"log": "e: app/src/main/java/com/example/shop/auth/AuthRepository.kt: (3, 1): Unresolved reference: Foo",
               "error_code": "compile_error", "retryable": False}
    snap = env.svc.start(task("fix the build"), T, workflow="repair", failure=failure, source_key="snap/p1/0")
    assert snap.status == RunStatus.WAITING_CODING
    cls = env.store.latest_artifact(snap.run_id, "classification")
    assert cls["category"] == "code"
    ct = env.rec.coding[0]
    assert '"task_type": "repair"' in ct.instructions and AUTH in ct.context_files
    env.svc.on_coding_result(coding_ok(ct, [GeneratedFile(path=AUTH, content="class AuthRepository")]))
    env.svc.on_test_result(ok_tests(env.rec.tests[0]))
    assert env.svc.on_build_result(build_ok(env.rec.builds[0])).status == RunStatus.SUCCEEDED


def test_repair_workflow_infra_failure_makes_no_llm_call():
    env = Env()
    failure = {"log": "java.net.UnknownHostException: repo.maven.apache.org", "error_code": None, "retryable": False}
    snap = env.svc.start(task("fix"), T, workflow="repair", failure=failure, source_key="snap/p1/0")
    assert snap.status == RunStatus.WAITING_VALIDATION and not env.provider.calls and not env.rec.coding


def test_repair_requires_inputs():
    import pytest
    with pytest.raises(ValueError):
        Env().svc.start(task(), T, workflow="repair")
