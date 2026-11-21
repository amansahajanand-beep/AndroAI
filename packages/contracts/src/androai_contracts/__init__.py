"""AndroAI shared contracts.

Every message exchanged between services (API, orchestration, ai-agent,
android-build, android-test) is defined here. Do not redefine these models in
a service; import them. Changes require review from the owners of both the
producer and the consumer (see docs/TEAM_WORKFLOW.md).
"""

from .agent import AgentTask, AgentTaskStatus
from .appspec import (
    AppSpec,
    ScreenPlan,
    UnsupportedCategory,
    UnsupportedRequest,
    graph_problems,
)
from .base import SCHEMA_VERSION, ContractModel, ErrorInfo, TaskState
from .build import BuildJob, BuildResult, BuildVariant
from .codegen import AndroidTarget, CodingResult, CodingTask, GeneratedFile, UiToolkit
from .queues import Queues
from .testing import TestJob, TestKind, TestResult
from .validation import ProblemSeverity, ValidationProblem

__all__ = [
    "SCHEMA_VERSION",
    "AgentTask",
    "AgentTaskStatus",
    "AndroidTarget",
    "AppSpec",
    "BuildJob",
    "BuildResult",
    "BuildVariant",
    "CodingResult",
    "CodingTask",
    "ContractModel",
    "ErrorInfo",
    "GeneratedFile",
    "ProblemSeverity",
    "Queues",
    "ScreenPlan",
    "TaskState",
    "TestJob",
    "TestKind",
    "TestResult",
    "UiToolkit",
    "UnsupportedCategory",
    "UnsupportedRequest",
    "ValidationProblem",
    "graph_problems",
]
