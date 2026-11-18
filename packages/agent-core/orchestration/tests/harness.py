"""Test doubles: scripted LLM, fake workspace, fake coding engine, fake validation."""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from androai_contracts import (
    BuildJob, BuildResult, CodingResult, CodingTask, ErrorInfo, GeneratedFile, TaskState, TestJob, TestResult,
)
from androai_orchestration_core.intelligence import ProjectScope
from androai_orchestration_core.persistence import RunStore
from androai_orchestration_core.providers import (
    FakeProvider, LLMRouter, ModelSpec, ProvidersConfig, RetryPolicy, TaskKind, TaskRoute,
)
from androai_orchestration_core.workflows import Limits, OrchestrationService, WorkflowDeps, make_checkpointer

from fixtures import FILES

REQ = {
    "app_name": "Shop", "summary": "A shopping app", "features": ["browse", "cart"], "user_roles": ["customer"],
    "screens": [{"name": "Home", "purpose": "list products"}], "assumptions": ["Android only"], "ambiguities": [],
}
ARCH = {"package_name": "com.example.shop", "ui_toolkit": "compose", "language": "kotlin"}
GRAPH = {"tasks": [
    {"key": "scaffold", "title": "Scaffold", "task_type": "scaffold", "instructions": "create project",
     "files": [{"path": "app/src/main/java/com/example/shop/MainActivity.kt", "purpose": "entry"}]},
    {"key": "home", "title": "Home screen", "task_type": "screen", "instructions": "home", "depends_on": ["scaffold"]},
]}
MOD = {"task": "Add Google login", "affected_files": ["app/src/main/java/com/example/shop/auth/AuthRepository.kt", "does/not/Exist.kt"],
       "new_files": ["app/src/main/java/com/example/shop/auth/GoogleAuth.kt"], "changes": ["add google auth"],
       "preserve": ["email login"], "validation": ["compile"]}
REPAIR = {"root_cause": "missing import", "files": ["app/src/main/java/com/example/shop/auth/AuthRepository.kt"],
          "changes": ["add import"], "validation": ["compile"]}


def llm_script(overrides: dict | None = None):
    """Chooses a JSON answer by which schema the router asked for (system message)."""
    data = {"RequirementSpec": REQ, "ArchitecturePlan": ARCH, "TaskGraph": GRAPH,
            "ModificationPlan": MOD, "RepairPlan": REPAIR, **(overrides or {})}

    def fn(request):
        sys = request.messages[0].content
        for name, payload in data.items():
            if f'"title": "{name}"' in sys:
                return json.dumps(payload() if callable(payload) else payload)
        raise AssertionError("unexpected schema: " + sys[:200])

    return fn


def providers_config() -> ProvidersConfig:
    m = ModelSpec(provider="fake", model="m1", input_price_per_mtok=1.0, output_price_per_mtok=2.0)
    route = TaskRoute(models=[m.key])
    return ProvidersConfig(models=[m], routes={k: route for k in TaskKind},
                           retry=RetryPolicy(max_attempts=2, base_delay_seconds=0, schema_repair_attempts=0))


class FakeWorkspace:
    def __init__(self, files=None):
        self.files = dict(files if files is not None else FILES)
        self.snapshots = 0

    def load_files(self, scope: ProjectScope):
        return dict(self.files)

    def apply_result(self, scope, result: CodingResult) -> str:
        for f in result.files:
            self.files[f.path] = f.content.encode()
        self.snapshots += 1
        return f"snap/{scope.project_id}/{self.snapshots}"


class Recorder:
    """Both CodingEngine and ValidationRunner; tests deliver results manually."""

    def __init__(self):
        self.coding: list[CodingTask] = []
        self.builds: list[BuildJob] = []
        self.tests: list[TestJob] = []

    def submit(self, task):
        self.coding.append(task)

    def submit_build(self, job):
        self.builds.append(job)

    def submit_test(self, job):
        self.tests.append(job)


def coding_ok(task: CodingTask, files=None) -> CodingResult:
    files = files if files is not None else [GeneratedFile(path="app/src/main/java/com/example/shop/Gen.kt", content="class Gen")]
    return CodingResult(coding_task_id=task.id, state=TaskState.SUCCEEDED, files=files, summary="ok")


def build_ok(job):
    return BuildResult(build_job_id=job.id, state=TaskState.SUCCEEDED, artifact_key="apk")


def build_fail(job, code="compile_error", retryable=False, msg="e: Foo.kt: Unresolved reference: x"):
    return BuildResult(build_job_id=job.id, state=TaskState.FAILED, log_key="log",
                       error=ErrorInfo(code=code, message=msg, retryable=retryable))


def ok_tests(job, failed=0):
    return TestResult(test_job_id=job.id, state=TaskState.SUCCEEDED if not failed else TaskState.FAILED, passed=3, failed=failed)


class Env:
    def __init__(self, llm=None, limits: Limits | None = None, files=None, provider: FakeProvider | None = None):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.store = RunStore(self.engine)
        self.store.create_all()
        self.provider = provider or FakeProvider("fake", [llm or llm_script()])
        self.cfg = providers_config()
        self.workspace = FakeWorkspace(files)
        self.rec = Recorder()
        self.checkpointer = make_checkpointer()
        self.deps = WorkflowDeps(
            store=self.store,
            router_factory=lambda run_id: LLMRouter(self.cfg, {"fake": self.provider},
                                                    usage_sink=lambda rec: self.store.record_usage(run_id, rec),
                                                    sleep=lambda s: None),
            workspace=self.workspace, coding=self.rec, validation=self.rec, limits=limits or Limits(),
        )
        self.svc = OrchestrationService(self.deps, self.checkpointer)

    def new_service(self) -> OrchestrationService:
        """Simulates a worker restart: fresh service + empty index cache, same DB/checkpoints."""
        self.deps.indexes.clear()
        return OrchestrationService(self.deps, self.checkpointer)
