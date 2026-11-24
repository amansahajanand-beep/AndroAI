"""Importing an Android project into an isolated workspace.

``import_project`` is the one entry point. It never changes the source, never executes anything
from it, and either returns a finished, eligible project or raises :class:`IngestRejected` leaving
nothing behind (not even a staging directory, also on interruption).
"""

from __future__ import annotations

import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from androai_codegen.detect import MAX_MARKER_BYTES, ProjectKind, detect_from_files
from androai_codegen.editing.engine import PatchEngine
from androai_codegen.editing.workspace import Workspace

from . import local_source, zip_source
from .budget import ImportBudget
from .copying import FileRecord, materialize, sha256_file, tree_fingerprint
from .errors import IngestCode, IngestRejected, shown
from .layout import Staging, check_data_root, finalize, project_dir
from .licence import detect_licence
from .models import (
    ImportCounts,
    ImportRequest,
    IngestReport,
    LocalDirectorySource,
    SourceInfo,
    SymlinkPolicy,
    ZipSource,
)
from .plan import Plan, PlannedEntry, android_check, reroot
from .secrets import ImportProtection, protection_for, scan_workspace


@dataclass(frozen=True)
class ImportResult:
    project_dir: Path
    workspace: Workspace
    journal_dir: Path
    report: IngestReport
    report_path: Path
    protection: ImportProtection

    @property
    def eligible_for_modification(self) -> bool:
        return self.report.eligible_for_modification

    def open_engine(self) -> PatchEngine:
        """A patch engine bound to this project, with its secret-bearing files protected."""
        return PatchEngine(
            self.report.project_id,
            self.workspace,
            self.journal_dir,
            protection=self.protection,
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _label(request: ImportRequest) -> str:
    if request.label:
        return request.label
    name = "".join(ch for ch in request.source.path.name if ch.isprintable())
    return (name or "imported-project")[:120]


def _is_junction(path: Path) -> bool:
    check = getattr(path, "is_junction", None)
    return bool(check and check())


def _check_directory_source(path: Path, policy: SymlinkPolicy, data_root: Path) -> Path:
    if not path.exists():
        raise IngestRejected(
            IngestCode.SOURCE_NOT_FOUND, "the source does not exist", shown(path.name)
        )
    if (path.is_symlink() or _is_junction(path)) and policy is SymlinkPolicy.REJECT_ALL:
        raise IngestRejected(
            IngestCode.SOURCE_IS_LINK, "the source path is a link", shown(path.name)
        )
    if not path.is_dir():
        raise IngestRejected(
            IngestCode.SOURCE_NOT_DIRECTORY, "the source is not a directory", shown(path.name)
        )
    resolved = path.resolve(strict=True)
    if resolved == data_root or data_root in resolved.parents or resolved in data_root.parents:
        raise IngestRejected(
            IngestCode.SOURCE_OVERLAPS_DATA_ROOT,
            "the source and the data root contain each other",
            shown(path.name),
        )
    return resolved


def _check_zip_source(path: Path, policy: SymlinkPolicy) -> Path:
    if not path.exists():
        raise IngestRejected(
            IngestCode.SOURCE_NOT_FOUND, "the source does not exist", shown(path.name)
        )
    if path.is_symlink() and policy is SymlinkPolicy.REJECT_ALL:
        raise IngestRejected(
            IngestCode.SOURCE_IS_LINK, "the source path is a link", shown(path.name)
        )
    if not path.is_file():
        raise IngestRejected(
            IngestCode.SOURCE_NOT_FILE, "the source is not a file", shown(path.name)
        )
    return path.resolve(strict=True)


def _require_android(
    plan: Plan, request: ImportRequest, read: Callable[[PlannedEntry], str | None] | None = None
) -> None:
    if not request.require_android_project:
        return
    check = android_check(plan.file_paths())
    if check.detected:
        return
    by_rel = {entry.rel: entry for entry in plan.entries if entry.kind == "file"}

    def read_marker(rel: str) -> str | None:
        entry = by_rel.get(rel)
        return read(entry) if read is not None and entry is not None else None

    detection = detect_from_files(plan.file_paths(), read_marker)
    if detection.kind not in (ProjectKind.NATIVE_ANDROID, ProjectKind.UNKNOWN):
        raise IngestRejected(
            IngestCode.UNSUPPORTED_FRAMEWORK,
            f"detected {detection.reason}; only native Android projects can be imported "
            "for modification right now",
        )
    hint = (
        f" (the Android project looks like it is in '{detection.android_root}')"
        if detection.android_root
        else ""
    )
    raise IngestRejected(
        IngestCode.NOT_AN_ANDROID_PROJECT,
        "expected a Gradle build file at the project root and an AndroidManifest.xml "
        f"(found build files: {check.gradle_files_at_root or 'none'}, "
        f"manifests: {check.manifests}); "
        f"is this the project's root folder?{hint}",
    )


def _locate_subdir(
    plan: Plan, request: ImportRequest, read: Callable[[PlannedEntry], str | None]
) -> Plan:
    """Re-root onto the Android project's folder when the top level is not one."""
    if not (request.require_android_project and request.locate_android_subdir):
        return plan
    if android_check(plan.file_paths()).detected:
        return plan
    by_rel = {entry.rel: entry for entry in plan.entries if entry.kind == "file"}

    def read_marker(rel: str) -> str | None:
        entry = by_rel.get(rel)
        return read(entry) if entry is not None else None

    detection = detect_from_files(plan.file_paths(), read_marker)
    if detection.kind is not ProjectKind.NATIVE_ANDROID or not detection.android_root:
        return plan
    # detect_from_files strips a wrapper folder itself; the plan was already stripped, so the
    # Android root it reports is relative to the plan only when there was no extra wrapper.
    root = detection.android_root
    if not any(p.startswith(root + "/") for p in plan.file_paths()):
        return plan
    return reroot(plan, root)


def _entry_reader(opener) -> Callable[[PlannedEntry], str | None]:
    def read(entry: PlannedEntry) -> str | None:
        try:
            with opener(entry) as handle:
                return handle.read(MAX_MARKER_BYTES).decode("utf-8", errors="replace")
        except Exception:  # unreadable marker: less evidence, never a crash
            return None

    return read


def _import_directory(
    request: ImportRequest, source: Path, workspace: Workspace, budget: ImportBudget
) -> tuple[Plan, dict[str, FileRecord], SourceInfo]:
    limits, policy = request.limits, request.symlinks
    plan = local_source.plan_directory(source, limits, policy)
    reader = _entry_reader(local_source.open_entry)
    plan = _locate_subdir(plan, request, reader)
    _require_android(plan, request, reader)
    records = materialize(plan, local_source.open_entry, workspace, budget)
    if request.verify_source:
        after = local_source.plan_directory(source, limits, policy)
        if plan.project_subdir:
            after = reroot(after, plan.project_subdir)
        local_source.verify_source_unchanged(plan, after, records, rehash=True)
    info = SourceInfo(
        kind="local_directory",
        label=_label(request),
        fingerprint=tree_fingerprint(records),
        fingerprint_of="tree",
    )
    return plan, records, info


def _import_zip(
    request: ImportRequest, archive_path: Path, workspace: Workspace, budget: ImportBudget
) -> tuple[Plan, dict[str, FileRecord], SourceInfo]:
    limits = request.limits
    size = archive_path.stat().st_size
    if size == 0 or not zipfile.is_zipfile(archive_path):
        raise IngestRejected(IngestCode.NOT_A_ZIP, "the source is not a ZIP archive")
    claimed = zip_source.declared_entry_count(archive_path)
    if claimed is not None and claimed > 2 * limits.max_files and claimed != 0xFFFF:
        raise IngestRejected(IngestCode.TOO_MANY_FILES, f"the archive lists {claimed} entries")
    before = sha256_file(archive_path)
    budget.archive_size = size
    try:
        archive = zipfile.ZipFile(archive_path)
    except (zipfile.BadZipFile, OverflowError, ValueError) as exc:
        raise IngestRejected(IngestCode.MALFORMED_ARCHIVE, "the archive cannot be read") from exc
    with archive:
        try:
            plan = zip_source.plan_zip(
                archive, limits, request.symlinks, strip_single_root=request.strip_single_root
            )
        except zip_source.ARCHIVE_ERRORS as exc:
            raise IngestRejected(
                IngestCode.MALFORMED_ARCHIVE,
                f"the archive is damaged or unsupported ({type(exc).__name__})",
            ) from exc
        reader = _entry_reader(zip_source.open_entry(archive))
        plan = _locate_subdir(plan, request, reader)
        _require_android(plan, request, reader)
        records = materialize(
            plan,
            zip_source.open_entry(archive),
            workspace,
            budget,
            read_errors=zip_source.ARCHIVE_ERRORS,
        )
    if request.verify_source and sha256_file(archive_path) != before:
        raise IngestRejected(
            IngestCode.SOURCE_CHANGED, "the archive file changed while it was being imported"
        )
    info = SourceInfo(
        kind="zip", label=_label(request), fingerprint=before, fingerprint_of="archive"
    )
    return plan, records, info


def import_project(
    request: ImportRequest,
    *,
    clock: Callable[[], datetime] = _utcnow,
    monotonic: Callable[[], float] = time.monotonic,
) -> ImportResult:
    """Import a local directory or a ZIP archive into a new isolated project.

    Raises :class:`IngestRejected` if any rule is broken; nothing is left behind in that case.
    """
    data_root = check_data_root(request.data_root)
    final = project_dir(data_root, request.tenant_id, request.project_id)
    if final.exists():
        raise IngestRejected(
            IngestCode.PROJECT_EXISTS, "this project already exists", shown(request.project_id)
        )

    source = request.source
    if isinstance(source, LocalDirectorySource):
        source_path = _check_directory_source(source.path, request.symlinks, data_root)
    elif isinstance(source, ZipSource):
        source_path = _check_zip_source(source.path, request.symlinks)
    else:  # pragma: no cover - the discriminated union has no other member
        raise TypeError("unsupported source")

    import_id = request.import_id or uuid.uuid4().hex
    staging = Staging(data_root, import_id)
    staging.create()
    try:
        budget = ImportBudget(request.limits, monotonic=monotonic)
        workspace = Workspace(staging.workspace)
        if isinstance(source, LocalDirectorySource):
            plan, records, info = _import_directory(request, source_path, workspace, budget)
        else:
            plan, records, info = _import_zip(request, source_path, workspace, budget)

        secrets = scan_workspace(workspace, records, request.limits)
        licence = detect_licence(workspace, records)
        report = IngestReport(
            import_id=import_id,
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            created_at=clock(),
            source=info,
            attestation=request.attestation,
            eligible_for_modification=True,
            limits=request.limits,
            counts=ImportCounts(
                files=len(records),
                directories=plan.directories,
                bytes=sum(record.size for record in records.values()),
                skipped_entries=plan.skipped_total,
                symlinks_skipped=plan.symlinks_skipped_total,
                nested_archives=plan.nested_archives_total,
            ),
            android=android_check(records),
            stripped_root=plan.stripped_root,
            project_subdir=plan.project_subdir,
            skipped=plan.skipped,
            symlinks_skipped=plan.symlinks_skipped,
            nested_archives=plan.nested_archives,
            secrets=secrets,
            licence=licence,
            content_fingerprint=tree_fingerprint(records),
            warnings=plan.warnings,
        )
        staging.write_report(report)
        finalize(staging, final)
    except BaseException:
        staging.cleanup()
        raise

    return _open(final, report)


def _open(final: Path, report: IngestReport) -> ImportResult:
    return ImportResult(
        project_dir=final,
        workspace=Workspace(final / "workspace"),
        journal_dir=final / "journal",
        report=report,
        report_path=final / "imports" / report.import_id / "report.json",
        protection=protection_for(report.secrets.protected_paths),
    )


def reopen_import(project_directory: Path) -> ImportResult:
    """Open a project that was imported earlier, from its report.

    Refuses a project whose report does not record a valid ownership or permission attestation:
    only an eligible import may be modified.
    """
    root = Path(project_directory)
    reports = sorted((root / "imports").glob("*/report.json"))
    if not reports:
        raise IngestRejected(
            IngestCode.SOURCE_NOT_FOUND, "no import report found", shown(root.name)
        )
    # The newest report wins (by the time recorded in it, not by its directory name).
    report = max(
        (IngestReport.model_validate_json(path.read_text(encoding="utf-8")) for path in reports),
        key=lambda candidate: candidate.created_at,
    )
    if not report.eligible_for_modification:
        raise IngestRejected(
            IngestCode.ATTESTATION_REQUIRED,
            "this import is not eligible for modification without an ownership or "
            "permission attestation",
        )
    return _open(root, report)


def import_local_directory(path: Path | str, **options: object) -> ImportResult:
    """``import_project`` for a local directory; ``options`` are the other request fields."""
    return import_project(ImportRequest(source=LocalDirectorySource(path=Path(path)), **options))  # type: ignore[arg-type]


def import_zip(path: Path | str, **options: object) -> ImportResult:
    """``import_project`` for a ZIP archive. ``options`` are the other ``ImportRequest`` fields."""
    return import_project(ImportRequest(source=ZipSource(path=Path(path)), **options))  # type: ignore[arg-type]
