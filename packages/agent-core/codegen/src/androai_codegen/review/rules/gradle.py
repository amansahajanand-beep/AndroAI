"""Gradle build rules: dependencies on projects the build does not include."""

from __future__ import annotations

import difflib
from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..models import Finding, Severity, finding


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    yield from _unknown_projects(a)


def _unknown_projects(a: ProjectAnalysis) -> Iterator[Finding]:
    """``project(":x")`` / ``projects.x`` naming a project that ``settings`` does not include.

    Only when the build's project list is readable (see ``ProjectAnalysis.projects_known``).
    """
    if not a.projects_known:
        return
    by_style = {
        True: [k for k in a.project_dirs if k.startswith("projects.")],
        False: [k for k in a.project_dirs if k.startswith(":") and k != ":"],
    }
    for dep in a.project_dependencies:
        if dep.target is not None:
            continue
        close = difflib.get_close_matches(
            dep.reference, by_style[dep.reference.startswith("projects.")], n=3, cutoff=0.6
        )
        hint = f"Did you mean {', '.join(close)}? " if close else ""
        yield finding(
            Severity.ERROR,
            "gradle.unknown_project",
            "dependencies",
            dep.path,
            f"{dep.config} depends on {dep.reference}, but settings does not include that project.",
            line=dep.line,
            fix=hint + "Otherwise add the project to settings (include(...)).",
            key=dep.reference,
        )
