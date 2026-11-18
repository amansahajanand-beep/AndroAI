"""Change-aware rules: what a patch removed or altered compared with the 'before' project.

Placeholder module; populated in a later step. ``compare`` runs only when a 'before' state exists.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..models import Finding


def compare(before: ProjectAnalysis, after: ProjectAnalysis) -> Iterator[Finding]:
    return iter(())
