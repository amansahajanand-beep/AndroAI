"""The analysis facade: read a project, run the extractors, return one deterministic report.

Nothing here executes project code. Gradle scripts, manifests, layouts and sources are *read as
text*; no build, no Gradle, no subprocess, no import of anything from the project. A file that
cannot be read (protected, too large, not text, over a cap) is recorded as a limitation with its
path; the report is then marked incomplete, and no fact is ever concluded from its absence.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from androai_codegen.editing.errors import CodegenError
from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.workspace import Workspace
from androai_codegen.ingest import ImportResult
from androai_codegen.review.analysis import ProjectAnalysis
from androai_codegen.review.models import ReviewConfig
from androai_codegen.review.project import ProjectFiles, is_text_path

from .build import extract_build
from .components import extract_components
from .config import AnalysisConfig
from .context import Run
from .data import extract_data
from .di import extract_di
from .graph import build_graph
from .layouts import extract_layouts
from .model import AnalysisReport, AnalysisStats
from .navigation import extract_navigation
from .screens import ComposeIndex, extract_compose
from .store import FactStore
from .symbols import extract_symbols, parse_sources

MAX_LIMITATIONS_PER_CODE = 100
_BOM = "﻿"

# Source files in a language the analysis does not read: suffix -> (language, whether the file
# could define the kind of thing the analysis looks for). A JVM language can hold Android
# components, entities and screens, so an unread file of one makes the report incomplete (nothing
# may be concluded from what is missing); native, cross-platform and tooling languages are only
# reported, because what they hold is outside what this analysis models anyway.
UNSUPPORTED_SOURCE: dict[str, tuple[str, bool]] = {
    ".groovy": ("Groovy", True),
    ".gvy": ("Groovy", True),
    ".scala": ("Scala", True),
    ".aidl": ("AIDL", False),
    ".c": ("C", False),
    ".cc": ("C++", False),
    ".cpp": ("C++", False),
    ".cxx": ("C++", False),
    ".h": ("C/C++", False),
    ".hh": ("C++", False),
    ".hpp": ("C++", False),
    ".hxx": ("C++", False),
    ".dart": ("Dart", False),
    ".swift": ("Swift", False),
    ".js": ("JavaScript", False),
    ".jsx": ("JavaScript", False),
    ".mjs": ("JavaScript", False),
    ".ts": ("TypeScript", False),
    ".tsx": ("TypeScript", False),
    ".py": ("Python", False),
    ".rs": ("Rust", False),
    ".go": ("Go", False),
}


@dataclass
class ReadAudit:
    """What reading the workspace did, and which files it could not read, by reason."""

    files_seen: int = 0
    bytes_read: int = 0
    not_read: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    capped_files: bool = False
    capped_bytes: bool = False


def read_project(
    workspace: Workspace,
    *,
    protection: ProtectionPolicy = DEFAULT_POLICY,
    config: AnalysisConfig | None = None,
) -> tuple[ProjectFiles, ReadAudit]:
    """Read the reviewable text of a workspace and record every file that was skipped.

    Protected files (keys, ``.env``, files the import found to hold secrets) are never opened.
    """
    config = config or AnalysisConfig()
    audit = ReadAudit()
    texts: dict[str, str] = {}
    others: set[str] = set()
    for count, rel in enumerate(workspace.iter_files()):
        if count >= config.max_files:
            audit.capped_files = True
            break
        audit.files_seen += 1
        if protection.is_protected(rel):
            audit.not_read["protected"].append(rel)
            continue
        if not is_text_path(rel):
            others.add(rel)
            continue
        try:
            size = os.stat(workspace.resolve(rel)).st_size
        except OSError:
            audit.not_read["unreadable"].append(rel)
            others.add(rel)
            continue
        if size > config.max_file_bytes:
            audit.not_read["too_large"].append(rel)
            others.add(rel)
            continue
        if audit.bytes_read + size > config.max_total_bytes:
            audit.capped_bytes = True
            audit.not_read["capped"].append(rel)
            others.add(rel)
            continue
        try:
            text = workspace.read_text(rel)
        except (OSError, CodegenError):
            audit.not_read["unreadable"].append(rel)
            others.add(rel)
            continue
        texts[rel] = text.removeprefix(_BOM)
        audit.bytes_read += size
    return ProjectFiles(texts, frozenset(others)), audit


def analyse_workspace(
    workspace: Workspace,
    *,
    protection: ProtectionPolicy = DEFAULT_POLICY,
    config: AnalysisConfig | None = None,
) -> AnalysisReport:
    """Analyse the project in ``workspace``."""
    config = config or AnalysisConfig()
    files, audit = read_project(workspace, protection=protection, config=config)
    return analyse_files(files, config=config, audit=audit)


def analyse_import(result: ImportResult, *, config: AnalysisConfig | None = None) -> AnalysisReport:
    """Analyse a project imported by :mod:`androai_codegen.ingest`, honouring its protection."""
    return analyse_workspace(result.workspace, protection=result.protection, config=config)


def analyse_mapping(
    files: Mapping[str, str | bytes | None], *, config: AnalysisConfig | None = None
) -> AnalysisReport:
    """Analyse an in-memory project (path -> text). ``bytes`` and ``None`` mean "a file exists
    here that is not text"."""
    return analyse_files(ProjectFiles.from_mapping(files), config=config)


def analyse_files(
    files: ProjectFiles,
    *,
    config: AnalysisConfig | None = None,
    audit: ReadAudit | None = None,
) -> AnalysisReport:
    config = config or AnalysisConfig()
    if any(text.startswith(_BOM) for text in files.texts.values()):
        files = ProjectFiles(
            {p: t.removeprefix(_BOM) for p, t in files.texts.items()}, files.other_paths
        )
    review_config = ReviewConfig(max_file_bytes=config.max_file_bytes, max_files=config.max_files)
    store = FactStore(config)
    run = Run(ProjectAnalysis(files, review_config), files, config, store)
    _read_limitations(store, audit)
    unsupported = _unsupported_sources(store, files)

    def guard(name: str, step: Callable[[], object]) -> object:
        if run.expired():
            return None
        try:
            return step()
        except Exception as exc:  # noqa: BLE001 - one broken extractor must not hide the rest
            # Tests assert this never happens for valid or fuzzed projects; if it does, the
            # report says which step failed and is marked incomplete.
            store.limit(
                "extractor_error",
                name,
                f"the {name} step failed ({type(exc).__name__}); its facts are missing",
            )
            return None

    guard("sources", lambda: parse_sources(run))
    guard("file-health", lambda: _file_limitations(run))
    guard("symbols", lambda: extract_symbols(run))
    guard("build", lambda: extract_build(run))
    guard("components", lambda: extract_components(run))
    guard("layouts", lambda: extract_layouts(run))
    compose = guard("compose", lambda: extract_compose(run))
    guard(
        "navigation",
        lambda: extract_navigation(
            run, compose if isinstance(compose, ComposeIndex) else ComposeIndex()
        ),
    )
    guard("data", lambda: extract_data(run))
    guard("di", lambda: extract_di(run))
    guard("graph", lambda: build_graph(run))
    not_read = {k: len(v) for k, v in audit.not_read.items()} if audit else {}
    if unsupported:
        not_read["unsupported_source"] = unsupported
    stats = AnalysisStats(
        files_seen=max(len(files.paths), audit.files_seen if audit else 0),
        files_read=len(files.texts),
        source_files=len(run.infos),
        bytes_read=sum(len(t.encode("utf-8")) for t in files.texts.values()),
        files_not_read=dict(sorted(not_read.items())),
    )
    return store.freeze(stats)


def _unsupported_sources(store: FactStore, files: ProjectFiles) -> int:
    """Record every source file in a language the analysis does not read; returns how many.

    Without this a Groovy, Scala, C++ or Dart file would be neither analysed nor mentioned, and a
    report built without it could still say ``complete``.
    """
    found: dict[bool, list[tuple[str, str]]] = {True: [], False: []}
    for path in sorted(files.other_paths):
        entry = UNSUPPORTED_SOURCE.get(os.path.splitext(path)[1].lower())
        if entry is not None:
            found[entry[1]].append((path, entry[0]))
    for affects, items in found.items():
        for path, language in items[:MAX_LIMITATIONS_PER_CODE]:
            store.limit(
                "unsupported_source",
                path,
                f"{language} source is not analysed; "
                + (
                    "components, types and facts defined in it are missing"
                    if affects
                    else "it is outside what this analysis models"
                ),
                affects_completeness=affects,
            )
    extra = {a: len(items) - MAX_LIMITATIONS_PER_CODE for a, items in found.items()}
    if any(n > 0 for n in extra.values()):
        store.limit(
            "unsupported_source",
            "project",
            f"{sum(max(n, 0) for n in extra.values())} more source files in languages the "
            "analysis does not read were not analysed",
            affects_completeness=extra[True] > 0,
        )
    return len(found[True]) + len(found[False])


def _read_limitations(store: FactStore, audit: ReadAudit | None) -> None:
    if audit is None:
        return
    codes = {
        "protected": ("protected_not_read", "the file is protected and was never opened"),
        "too_large": (
            "file_too_large",
            "the file is larger than the analysis limit and was skipped",
        ),
        "unreadable": ("binary_not_read", "the file is not valid UTF-8 text and was skipped"),
        "capped": ("file_count_cap", "the total-size limit was reached before this file"),
    }
    for reason, paths in sorted(audit.not_read.items()):
        code, message = codes[reason]
        for path in sorted(paths)[:MAX_LIMITATIONS_PER_CODE]:
            analysable = is_text_path(path)
            store.limit(code, path, message, affects_completeness=analysable)  # type: ignore[arg-type]
        if len(paths) > MAX_LIMITATIONS_PER_CODE:
            store.limit(
                code,  # type: ignore[arg-type]
                "project",
                f"{len(paths) - MAX_LIMITATIONS_PER_CODE} more files were skipped "
                "for the same reason",
            )
    if audit.capped_files:
        store.limit(
            "file_count_cap",
            "project",
            "the file-count limit was reached; later files were not read",
        )


def _file_limitations(run: Run) -> None:
    """Files that were read but are broken: they may hide facts, so the report is incomplete."""
    a, store = run.a, run.store
    for path, doc in sorted(a.xml_docs.items()):
        if doc.error is None or path in a.template_xml or path in a.refused_xml:
            continue
        if path.endswith("AndroidManifest.xml") or "/res/" in f"/{path}":
            store.limit(
                "malformed_source",
                path,
                f"the XML does not parse ({doc.error.message}); facts from it are missing",
            )
    for path, script in sorted(a.gradle_scripts.items()):
        if script.bracket_errors:
            store.limit(
                "malformed_build_file",
                path,
                "the build script has unbalanced brackets or an unterminated string; facts "
                "from it may be incomplete",
            )
