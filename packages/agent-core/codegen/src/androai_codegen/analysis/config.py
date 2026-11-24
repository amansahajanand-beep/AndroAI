"""Limits for one analysis run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """Bounds that keep one analysis finite on hostile or enormous projects.

    ``deadline_seconds`` is the only setting that makes the result depend on the machine; it is
    off by default. When it is set and runs out, the report says so (``time_budget_exceeded``)
    and is marked incomplete.
    """

    max_files: int = 20_000
    max_file_bytes: int = 1_000_000
    max_total_bytes: int = 250_000_000
    max_facts: int = 60_000
    max_members_per_type: int = 300
    max_evidence_per_fact: int = 8
    max_types_per_file: int = 400
    deadline_seconds: float | None = None
