"""Static code review for Android projects (Kotlin, Java, XML, manifest, Gradle).

Review is static: it never compiles or runs anything and does not claim the code works. Every
report says so (``ReviewReport.scope == "static"`` plus ``limitations``).
"""

from .checkpoint import project_at_checkpoint, review_since_checkpoint
from .engine import PatchReview, ReviewEngine, review_patch
from .models import (
    Finding,
    ReviewConfig,
    ReviewReport,
    ReviewTarget,
    Severity,
)
from .project import ProjectFiles
from .session import ReviewSession

__all__ = [
    "Finding",
    "PatchReview",
    "ProjectFiles",
    "ReviewConfig",
    "ReviewEngine",
    "ReviewReport",
    "ReviewSession",
    "ReviewTarget",
    "Severity",
    "project_at_checkpoint",
    "review_patch",
    "review_since_checkpoint",
]
