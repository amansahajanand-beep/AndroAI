from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base import ContractModel

# ``path`` names a field of the document that was checked: snake_case names joined by dots, with a
# zero-based index in brackets for a list item, e.g. ``screens[2].navigates_to[0]``. An empty path
# means the document as a whole.
PROBLEM_PATH_PATTERN = (
    r"^$|^[a-z_][a-z0-9_]*(\[[0-9]+\])?(\.[a-z_][a-z0-9_]*(\[[0-9]+\])?)*$"
)
# ``code`` is a stable machine-readable name, lower case with dots or underscores, e.g.
# ``unknown_screen``. Codes may be added over time; consumers must tolerate codes they do not know.
PROBLEM_CODE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
MAX_PROBLEM_PATH_LENGTH = 200
MAX_PROBLEM_CODE_LENGTH = 64
MAX_PROBLEM_MESSAGE_LENGTH = 500


class ProblemSeverity(str, Enum):
    ERROR = "error"  # the document cannot be used until it is fixed
    WARNING = "warning"  # usable, but the user or the caller should know


class ValidationProblem(ContractModel):
    """One thing wrong with (or worth knowing about) a structured document.

    Producers: any validator of a contract document (the first one is ``AppSpec``). Consumers:
    whoever has to correct the document (the planner's retry loop) or show the reason (the UI).
    Ownership of the model is to be confirmed under ``docs/TEAM_WORKFLOW.md``.
    """

    path: str = Field(max_length=MAX_PROBLEM_PATH_LENGTH, pattern=PROBLEM_PATH_PATTERN)
    code: str = Field(
        min_length=1, max_length=MAX_PROBLEM_CODE_LENGTH, pattern=PROBLEM_CODE_PATTERN
    )
    message: str = Field(min_length=1, max_length=MAX_PROBLEM_MESSAGE_LENGTH)
    severity: ProblemSeverity = ProblemSeverity.ERROR
