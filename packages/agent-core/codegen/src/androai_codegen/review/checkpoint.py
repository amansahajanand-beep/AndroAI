"""Review the workspace against a checkpoint: what did everything since then change or break?

``review_patch`` judges one patch before it is applied. This is the other direction, used after
several patches (or after manual edits): it takes the project as it is now, rebuilds the project as
it was at the checkpoint from the shadow-git history, and reports only what changed in between,
including the change-aware rules (removed components, renamed package, converted language...).

Nothing is written, in the workspace or in the history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .engine import ReviewEngine
from .models import ReviewConfig, ReviewReport, ReviewTarget
from .project import ProjectFiles, is_text_path

if TYPE_CHECKING:
    from androai_codegen.vcs.manager import CheckpointManager


def project_at_checkpoint(
    manager: CheckpointManager,
    checkpoint_id: str,
    after: ProjectFiles,
    *,
    config: ReviewConfig | None = None,
) -> ProjectFiles:
    """The project as it was at ``checkpoint_id``, given the project as it is now (``after``).

    Only the files that differ are read back from history; everything else is shared with
    ``after``. A file that did not exist at the checkpoint is absent; one that cannot be reviewed
    (binary, not UTF-8, too large) is present by name only.
    """
    config = config or ReviewConfig()
    checkpoint = manager.get_checkpoint(checkpoint_id)
    summary = manager.summary_since(checkpoint_id)
    restored: dict[str, str | None] = {}
    by_name_only: list[str] = []
    for item in summary.files:
        blob = manager.vcs.read_blob(checkpoint.commit, item.path)
        if blob is None:
            restored[item.path] = None  # did not exist then
        elif not is_text_path(item.path) or len(blob) > config.max_file_bytes:
            restored[item.path] = None
            by_name_only.append(item.path)
        else:
            try:
                restored[item.path] = blob.decode("utf-8")
            except UnicodeDecodeError:
                restored[item.path] = None
                by_name_only.append(item.path)
    return after.overlay(restored).with_paths(by_name_only)


def review_since_checkpoint(
    manager: CheckpointManager,
    checkpoint_id: str,
    *,
    config: ReviewConfig | None = None,
    target: ReviewTarget | None = None,
) -> ReviewReport:
    """Review the workspace as it is now, reporting only what changed since ``checkpoint_id``.

    Includes edits nobody recorded yet (manual changes). Findings that already existed at the
    checkpoint are counted in ``preexisting_suppressed``, not reported.
    """
    config = config or ReviewConfig()
    after = ProjectFiles.from_workspace(
        manager.engine.workspace, protection=manager.engine.protection, config=config
    )
    before = project_at_checkpoint(manager, checkpoint_id, after, config=config)
    return ReviewEngine(config).review(after, before=before, target=target)
