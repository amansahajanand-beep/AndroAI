"""Static code review for Android projects (Kotlin, Java, XML, manifest, Gradle).

Review is static: it never compiles or runs anything and does not claim the code works. Every
report says so (``ReviewReport.scope == "static"`` plus ``limitations``).
"""

from .engine import PatchReview, ReviewEngine, review_patch
from .models import (
    Finding,
    ReviewConfig,
    ReviewReport,
    ReviewTarget,
    Severity,
)
from .project import ProjectFiles

__all__ = [
    "Finding",
    "PatchReview",
    "ProjectFiles",
    "ReviewConfig",
    "ReviewEngine",
    "ReviewReport",
    "ReviewTarget",
    "Severity",
    "review_patch",
]
