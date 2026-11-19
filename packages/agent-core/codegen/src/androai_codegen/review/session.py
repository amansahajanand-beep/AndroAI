"""Reviewing many patches of one workspace without redoing the work that does not change.

``review_patch`` on its own is stateless: every call reads every project file, parses them and
analyses the unchanged project (to tell what the patch introduced) before analysing the patched
one. On a 700-file project that is about five seconds per patch, most of it repeated work.

A :class:`ReviewSession` keeps what cannot have changed and re-checks it cheaply:

* **File texts** are cached with size and modification time and re-read when either differs, or
  when the file was modified very recently (see :class:`~.project.FileCache`).
* **The "before" analysis** is reused as long as the project text is identical. Any change to
  any file, or any file created or deleted, rebuilds it.
* **Nothing about a patch is kept**: each review overlays its own patch on a copy, so one patch
  never influences the next.

A session is bound to one workspace, project id, config and target and refuses anything else.
It is not thread-safe. It never writes to the workspace.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from androai_codegen.editing.engine import PatchEngine
from androai_codegen.editing.models import PatchSet

from .engine import Baseline, PatchReview, ReviewEngine
from .models import ReviewConfig, ReviewTarget
from .project import FileCache, ProjectFiles


@dataclass
class SessionStats:
    reviews: int = 0  # patch reviews that got as far as a report
    files_read: int = 0  # text files read from disk (cache misses)
    baseline_builds: int = 0  # times the "before" analysis was (re)built


class ReviewSession:
    def __init__(
        self,
        patch_engine: PatchEngine,
        config: ReviewConfig | None = None,
        target: ReviewTarget | None = None,
    ) -> None:
        self.engine = patch_engine
        self.config = config or ReviewConfig()
        self.target = target
        self.stats = SessionStats()
        self._root = patch_engine.workspace.root
        self._cache = FileCache()
        self._files: ProjectFiles | None = None
        self._baseline: Baseline | None = None

    # -- state --------------------------------------------------------------------------

    def invalidate(self) -> None:
        """Forget everything; the next review reads and analyses the whole project again."""
        self._cache.clear()
        self._files = None
        self._baseline = None

    def project_files(self) -> ProjectFiles:
        """The project as it is on disk now (unchanged files come from the cache)."""
        reads = self._cache.reads
        fresh = ProjectFiles.from_workspace(
            self.engine.workspace,
            protection=self.engine.protection,
            config=self.config,
            cache=self._cache,
        )
        self.stats.files_read += self._cache.reads - reads
        previous = self._files
        if (
            previous is not None
            and previous.texts == fresh.texts
            and previous.other_paths == fresh.other_paths
        ):
            return previous  # identical: keep the object so the baseline stays valid
        self._files = fresh
        self._baseline = None
        return fresh

    def _baseline_for(self, before: ProjectFiles) -> Baseline:
        if self._baseline is None or self._baseline.files is not before:
            self._baseline = ReviewEngine(self.config).baseline(before, target=self.target)
            self.stats.baseline_builds += 1
        return self._baseline

    # -- reviewing ----------------------------------------------------------------------

    def check_compatible(
        self,
        patch_engine: PatchEngine,
        config: ReviewConfig | None = None,
        target: ReviewTarget | None = None,
    ) -> None:
        """Raise ``ValueError`` unless this session may be used for ``patch_engine``."""
        if patch_engine.workspace.root != self._root:
            raise ValueError("this review session belongs to another workspace")
        if patch_engine.project_id != self.engine.project_id:
            raise ValueError("this review session belongs to another project id")
        if config is not None and config != self.config:
            raise ValueError("a review session has its own config; create a new session instead")
        if target is not None and target != self.target:
            raise ValueError("a review session has its own target; create a new session instead")

    def review_patch(
        self, patch: PatchSet, *, approved_deletions: Iterable[str] = ()
    ) -> PatchReview:
        """Like :func:`~.engine.review_patch`: nothing is written, the answer is the same."""
        simulation = self.engine.simulate(patch, approved_deletions)
        if not simulation.preview.ok:
            return PatchReview(simulation, None)
        before = self.project_files()
        after = before.overlay(simulation.files)  # a copy: ``before`` is never modified
        report = ReviewEngine(self.config).review(
            after, before=before, target=self.target, baseline=self._baseline_for(before)
        )
        self.stats.reviews += 1
        return PatchReview(simulation, report)
