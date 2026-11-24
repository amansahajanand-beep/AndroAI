"""The input of an analysis, and whether an old analysis still matches the project (M2B, M2.10).

Two fingerprints exist and they are never the same thing:

``AnalysisReport.fingerprint``
    A hash of the analysis *output* (facts, relationships, limitations). It says what the report
    contains.

``Provenance.input_fingerprint``
    A hash of the project *input*: the files the analysis considered. It says what the report was
    made from, and it is what ``check_freshness`` compares.

The input is a manifest, one entry per file, so a stale result can say *which* files changed:

* a text file that was read: its path and the SHA-256 of the text as it was analysed;
* a file that exists but was not read (protected, binary, too large, over a cap): its path only.
  Such a file is never opened here either. Whether it changed cannot matter to the analysis,
  which did not use its content; that it appeared or disappeared can.

``check_freshness`` recomputes the manifest of the current project with the same selection rules and
the configuration recorded in the result, then compares. It reports ``fresh`` (nothing the analysis
used has changed), ``stale`` (with the files added, deleted or changed, bounded) or ``unknown`` (the
project cannot be read now, the result cannot be compared, or the analysis stopped at its file limit
so files beyond it are not tracked).

This is change detection, not proof. A result loaded from JSON can say what it claims to be made
from; nothing in it is signed, so a copy that was edited by hand cannot be told from a genuine one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from androai_codegen.editing.errors import CodegenError
from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.workspace import Workspace
from androai_codegen.review.project import ProjectFiles

from .analyser import ReadAudit, read_project
from .config import AnalysisConfig
from .model import ANALYSIS_VERSION

if TYPE_CHECKING:
    from .result import AnalysisResult

MAX_CHANGED_PATHS = 50
_BOM = "﻿"
_HEX = "0123456789abcdef"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputFile(_Frozen):
    """One file of the analysed project: its path, and the hash of its text when it was read."""

    path: str = Field(min_length=1, max_length=400)
    sha256: str | None = None  # ``None``: the file exists but its content was not used

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("an input path must be a relative, forward-slash project path")
        return value

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 64 or any(ch not in _HEX for ch in value)):
            raise ValueError("sha256 must be 64 lower-case hex digits")
        return value


def hash_text(text: str) -> str:
    """SHA-256 of a text as the analysis saw it (UTF-8, without a byte order mark)."""
    return hashlib.sha256(text.removeprefix(_BOM).encode("utf-8")).hexdigest()


def manifest_of(
    files: ProjectFiles, audit: ReadAudit | None = None
) -> tuple[tuple[InputFile, ...], bool]:
    """The input manifest of what was read, and whether the file limit cut the walk short."""
    entries: dict[str, str | None] = {path: hash_text(text) for path, text in files.texts.items()}
    for path in files.other_paths:
        entries[path] = None
    if audit is not None:
        for path in audit.not_read.get("protected", ()):
            entries[path] = None  # listed, never opened
    capped = bool(audit and audit.capped_files)
    return tuple(InputFile(path=p, sha256=entries[p]) for p in sorted(entries)), capped


def manifest_fingerprint(entries: tuple[InputFile, ...] | list[InputFile]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda e: e.path):
        digest.update(f"{entry.path}\0{entry.sha256 or '-'}\n".encode())
    return digest.hexdigest()


def config_record(config: AnalysisConfig) -> dict[str, int | float | None]:
    """The limits of one run as plain values, so a later check can repeat it exactly."""
    return dict(sorted(asdict(config).items()))


def config_digest(record: Mapping[str, int | float | None]) -> str:
    canonical = json.dumps(dict(record), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


# -- the check -----------------------------------------------------------------------------------


class Freshness(_Frozen):
    state: Literal["fresh", "stale", "unknown"]
    reason: str
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    changed_count: int = 0
    added_count: int = 0
    deleted_count: int = 0
    truncated: bool = False  # a list above was cut at ``MAX_CHANGED_PATHS``; the counts are exact
    files_checked: int = 0


def _cut(paths: list[str]) -> tuple[tuple[str, ...], bool]:
    return tuple(paths[:MAX_CHANGED_PATHS]), len(paths) > MAX_CHANGED_PATHS


def check_freshness(
    result: AnalysisResult,
    source: Workspace | Mapping[str, str | bytes | None],
    *,
    protection: ProtectionPolicy = DEFAULT_POLICY,
    config: AnalysisConfig | None = None,
) -> Freshness:
    """Does ``result`` still describe ``source``?

    ``source`` is the project now: a ``Workspace`` (read with the same rules as the analysis, and a
    protected file is never opened) or a mapping of path to text. ``config`` may be given to ask
    "would this configuration give the same analysis"; without it the result's own configuration is
    used, which is the question "has the project changed".
    """
    if result.analysis_version != ANALYSIS_VERSION:
        return Freshness(
            state="stale",
            reason=(
                f"incompatible analysis version: the result is {result.analysis_version}, this "
                f"code is {ANALYSIS_VERSION}"
            ),
        )
    provenance = result.provenance
    if manifest_fingerprint(provenance.input_files) != provenance.input_fingerprint:
        return Freshness(
            state="unknown", reason="the stored input manifest does not match its fingerprint"
        )
    try:
        recorded = AnalysisConfig(**provenance.config)  # type: ignore[arg-type]
    except TypeError:
        return Freshness(
            state="stale", reason="incompatible configuration: it has settings this code lacks"
        )
    if config is not None and config_digest(config_record(config)) != provenance.config_digest:
        return Freshness(
            state="stale",
            reason="the configuration differs from the one the result was made with",
        )
    try:
        if isinstance(source, Mapping):
            files, audit = ProjectFiles.from_mapping(source), None
        else:
            files, audit = read_project(source, protection=protection, config=recorded)
    except (OSError, ValueError, CodegenError) as exc:
        return Freshness(
            state="unknown", reason=f"the current project could not be read ({type(exc).__name__})"
        )
    current_entries, _ = manifest_of(files, audit)
    now = {e.path: e.sha256 for e in current_entries}
    before = {e.path: e.sha256 for e in provenance.input_files}
    changed = sorted(p for p in before.keys() & now.keys() if before[p] != now[p])
    added = sorted(now.keys() - before.keys())
    deleted = sorted(before.keys() - now.keys())
    if not (changed or added or deleted):
        if provenance.capped:
            return Freshness(
                state="unknown",
                reason=(
                    "nothing tracked has changed, but the analysis stopped at its file limit and "
                    "files beyond it are not tracked"
                ),
                files_checked=len(now),
            )
        return Freshness(
            state="fresh",
            reason="no file the analysis used has changed",
            files_checked=len(now),
        )
    (changed_shown, c_cut), (added_shown, a_cut), (deleted_shown, d_cut) = (
        _cut(changed),
        _cut(added),
        _cut(deleted),
    )
    parts = [
        f"{len(changed)} changed" if changed else "",
        f"{len(added)} added" if added else "",
        f"{len(deleted)} deleted" if deleted else "",
    ]
    return Freshness(
        state="stale",
        reason="files differ from the analysed input: " + ", ".join(p for p in parts if p),
        changed=changed_shown,
        added=added_shown,
        deleted=deleted_shown,
        changed_count=len(changed),
        added_count=len(added),
        deleted_count=len(deleted),
        truncated=c_cut or a_cut or d_cut,
        files_checked=len(now),
    )
