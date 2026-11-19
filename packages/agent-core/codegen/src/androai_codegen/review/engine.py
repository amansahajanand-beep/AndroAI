"""The review engine: run the rules, compare with the 'before' state, apply policy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from androai_codegen.editing.engine import PatchEngine
from androai_codegen.editing.models import PatchSet, Simulation

from .analysis import ProjectAnalysis
from .models import (
    SEVERITY_RANK,
    Finding,
    ReviewConfig,
    ReviewReport,
    ReviewTarget,
    Severity,
    finding,
)
from .project import ProjectFiles
from .rules import RULE_MODULES

if TYPE_CHECKING:
    from .session import ReviewSession


class Baseline:
    """The analysis and findings of an unchanged project, reusable across several reviews.

    Reviewing a patch needs the project as it was (to tell what the patch introduced) and as it
    would become. The "was" side does not depend on the patch, so a caller reviewing many patches
    of one project state can build it once. Everything here is read-only after construction.
    """

    def __init__(
        self,
        engine: ReviewEngine,
        files: ProjectFiles,
        target: ReviewTarget | None = None,
    ) -> None:
        self.files = files
        self.config = engine.config
        self.target = target
        self.analysis = ProjectAnalysis(files, engine.config, target)
        self._engine = engine
        self._fingerprints: set[tuple[str, str, str]] | None = None

    @property
    def fingerprints(self) -> set[tuple[str, str, str]]:
        if self._fingerprints is None:
            self._fingerprints = {f.fingerprint for f in self._engine._run(self.analysis)[0]}
        return self._fingerprints

    def matches(
        self, before: ProjectFiles, config: ReviewConfig, target: ReviewTarget | None
    ) -> bool:
        """Safe to use for a review of ``before`` under ``config`` and ``target``."""
        return (
            self.config == config
            and self.target == target
            and (
                self.files is before
                or (
                    self.files.texts == before.texts
                    and self.files.other_paths == before.other_paths
                )
            )
        )


class ReviewEngine:
    def __init__(self, config: ReviewConfig | None = None) -> None:
        self.config = config or ReviewConfig()

    def baseline(self, before: ProjectFiles, *, target: ReviewTarget | None = None) -> Baseline:
        """Prepare ``before`` once, to pass to :meth:`review` for several patches."""
        return Baseline(self, before, target)

    def review(
        self,
        after: ProjectFiles,
        *,
        before: ProjectFiles | None = None,
        target: ReviewTarget | None = None,
        baseline: Baseline | None = None,
    ) -> ReviewReport:
        """Review ``after``. With ``before``, report only what the change introduced.

        Findings that already existed in ``before`` are counted in
        ``preexisting_suppressed`` but not reported: the change is not responsible for them.
        A ``baseline`` built for the same ``before``, config and target is reused instead of
        analysing ``before`` again; one that does not match is ignored, never trusted.
        """
        config = self.config
        analysis = ProjectAnalysis(after, config, target)
        findings, crashed = self._run(analysis)
        suppressed = 0
        if before is not None:
            if baseline is None or not baseline.matches(before, config, target):
                baseline = Baseline(self, before, target)
            if config.only_new:
                known = baseline.fingerprints
                fresh = [f for f in findings if f.fingerprint not in known]
                suppressed = len(findings) - len(fresh)
                findings = fresh
            findings.extend(self._compare(baseline.analysis, analysis))

        findings = [
            self._apply_approvals(f) for f in findings if f.rule not in config.disabled_rules
        ]
        findings, omitted = self._cap(self._sorted(findings))
        limitations = list(ReviewReport.model_fields["limitations"].default_factory())  # type: ignore[misc]
        limitations.extend(
            f"{name} could not be fully evaluated (internal error)." for name in crashed
        )
        return ReviewReport(
            findings=findings,
            files_reviewed=len(analysis.sources)
            + len(analysis.gradle_scripts)
            + len(analysis.xml_docs),
            files_unparsed=self._unparsed(analysis),
            preexisting_suppressed=suppressed,
            omitted=omitted,
            limitations=limitations,
        )

    # -- internals ----------------------------------------------------------------------

    def _run(self, analysis: ProjectAnalysis) -> tuple[list[Finding], list[str]]:
        findings: list[Finding] = []
        crashed: list[str] = []
        for module in RULE_MODULES:
            name = module.__name__.rsplit(".", 1)[-1]
            try:
                findings.extend(module.check(analysis))
            except Exception as exc:  # a rule bug must not hide every other finding
                crashed.append(f"Rule group '{name}'")
                findings.append(
                    finding(
                        Severity.WARNING,
                        "review.internal_error",
                        "review",
                        "<review>",
                        f"Rule group '{name}' failed with {type(exc).__name__}; its findings "
                        "are missing from this report.",
                        key=name,
                    )
                )
        return findings, crashed

    def _compare(self, before: ProjectAnalysis, after: ProjectAnalysis) -> Iterable[Finding]:
        from .rules import changes  # imported lazily: only needed when a 'before' state exists

        return changes.compare(before, after)

    def _apply_approvals(self, item: Finding) -> Finding:
        if item.approval and item.approval in self.config.granted_approvals:
            return item.model_copy(
                update={
                    "severity": Severity.INFO,
                    "blocking": False,
                    "description": item.description + " (approved)",
                }
            )
        return item

    @staticmethod
    def _sorted(findings: list[Finding]) -> list[Finding]:
        return sorted(
            findings,
            key=lambda f: (not f.blocking, -SEVERITY_RANK[f.severity], f.file, f.line or 0, f.rule),
        )

    def _cap(self, findings: list[Finding]) -> tuple[list[Finding], int]:
        per_rule: dict[str, int] = defaultdict(int)
        kept: list[Finding] = []
        omitted = 0
        for item in findings:
            per_rule[item.rule] += 1
            if (
                per_rule[item.rule] > self.config.max_findings_per_rule
                or len(kept) >= self.config.max_findings
            ):
                omitted += 1
            else:
                kept.append(item)
        return kept, omitted

    @staticmethod
    def _unparsed(analysis: ProjectAnalysis) -> list[str]:
        bad = [
            p
            for p, doc in analysis.xml_docs.items()
            if doc.error and p not in analysis.template_xml
        ]
        if analysis.catalog and analysis.catalog.error and analysis.catalog_path:
            bad.append(analysis.catalog_path)
        return sorted(bad)


class PatchReview:
    """A patch's preview together with the review of the project as it would become."""

    def __init__(self, simulation: Simulation, report: ReviewReport | None) -> None:
        self.simulation = simulation
        self.report = report

    @property
    def applicable(self) -> bool:
        """The patch passed validation and the review found nothing blocking."""
        return (
            self.report is not None and self.simulation.preview.ok and not self.report.has_blocking
        )


def review_patch(
    patch_engine: PatchEngine,
    patch: PatchSet,
    *,
    approved_deletions: Iterable[str] = (),
    config: ReviewConfig | None = None,
    target: ReviewTarget | None = None,
    session: ReviewSession | None = None,
) -> PatchReview:
    """Review a patch *before* applying it: nothing is written.

    If the patch itself is invalid (conflict, protected file, ...) there is nothing meaningful
    to review, so ``report`` is ``None`` and the reasons are in ``simulation.preview``.

    Pass a :class:`~.session.ReviewSession` to review many patches of one workspace without
    reloading and re-analysing the unchanged project each time; the answer is the same. A session
    for another workspace, project id, config or target is refused with ``ValueError``.
    """
    if session is not None:
        session.check_compatible(patch_engine, config, target)
        return session.review_patch(patch, approved_deletions=approved_deletions)
    simulation = patch_engine.simulate(patch, approved_deletions)
    if not simulation.preview.ok:
        return PatchReview(simulation, None)
    config = config or ReviewConfig()
    before = ProjectFiles.from_workspace(
        patch_engine.workspace, protection=patch_engine.protection, config=config
    )
    after = before.overlay(simulation.files)
    return PatchReview(simulation, ReviewEngine(config).review(after, before=before, target=target))
