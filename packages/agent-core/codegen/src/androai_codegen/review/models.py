"""Findings, report and configuration for static review."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Finding(_Model):
    """One review finding. Field names match the proposed contract's ``ReviewFinding``."""

    severity: Severity
    rule: str  # stable id, e.g. "import.missing"
    category: str  # syntax | imports | resources | manifest | navigation | dependencies | ...
    file: str
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    description: str
    suggested_fix: str | None = None
    blocking: bool
    key: str = ""  # stable discriminator (symbol, resource name...) used to match findings
    approval: str | None = None  # ApprovalKind value that would permit this change

    @property
    def fingerprint(self) -> tuple[str, str, str]:
        """Identity ignoring line numbers, so unrelated edits don't make old findings 'new'."""
        return (self.rule, self.file, self.key)


def finding(
    severity: Severity,
    rule: str,
    category: str,
    file: str,
    description: str,
    *,
    line: int | None = None,
    column: int | None = None,
    fix: str | None = None,
    blocking: bool | None = None,
    key: str = "",
    approval: str | None = None,
) -> Finding:
    return Finding(
        severity=severity,
        rule=rule,
        category=category,
        file=file,
        line=line,
        column=column,
        description=description,
        suggested_fix=fix,
        blocking=severity in (Severity.ERROR, Severity.CRITICAL) if blocking is None else blocking,
        key=key,
        approval=approval,
    )


STATIC_LIMITATIONS = (
    "Static review only: it does not compile or run the code and cannot prove it is correct.",
    "Symbol resolution is limited to the project's own declarations and a curated list of "
    "well-known Android libraries; a reference it cannot see may still be valid.",
)


class ReviewReport(_Model):
    scope: Literal["static"] = "static"  # review never proves runtime correctness
    findings: list[Finding] = Field(default_factory=list)
    files_reviewed: int = 0
    files_unparsed: list[str] = Field(default_factory=list)
    preexisting_suppressed: int = 0  # findings that were already there before the change
    omitted: int = 0  # findings dropped by the caps
    limitations: list[str] = Field(default_factory=lambda: list(STATIC_LIMITATIONS))

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def has_blocking(self) -> bool:
        return any(f.blocking for f in self.findings)

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)

    def summary(self) -> str:
        blocking = len(self.blocking_findings)
        parts = [
            f"Static review of {self.files_reviewed} files: {len(self.findings)} findings, "
            f"{blocking} blocking."
        ]
        if self.preexisting_suppressed:
            parts.append(f"{self.preexisting_suppressed} pre-existing findings not counted.")
        if self.omitted:
            parts.append(f"{self.omitted} further findings omitted.")
        parts.append("This is not a compile or run check.")
        return " ".join(parts)


@dataclass(frozen=True)
class ReviewTarget:
    """What the project is supposed to be (from the task), when known."""

    language: str | None = None  # "kotlin" | "java"
    ui: str | None = None  # "compose" | "xml"
    min_sdk: int | None = None
    target_sdk: int | None = None
    package_name: str | None = None


@dataclass(frozen=True)
class ReviewConfig:
    permitted_dependencies: tuple[str, ...] | None = None  # None: do not check the plan
    granted_approvals: frozenset[str] = frozenset()  # ApprovalKind values already granted
    default_target_sdk: int = 35
    disabled_rules: frozenset[str] = frozenset()
    max_findings: int = 200
    max_findings_per_rule: int = 40
    max_file_bytes: int = 1_000_000
    max_files: int = 20_000
    only_new: bool = True  # with a 'before' state, report only findings the change introduced
    notes: list[str] = field(default_factory=list, compare=False)
