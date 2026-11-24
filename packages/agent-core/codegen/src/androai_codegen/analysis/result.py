"""The analysis result: report, inventory, provenance, eligibility, and its JSON form (M2B, M2.10).

``AnalysisResult`` wraps what one analysis produced:

``report``       the facts, relationships and limitations (``AnalysisReport``), with its own
                 ``fingerprint`` (a hash of the *output*);
``inventory``    a typed view over the report (``ProjectInventory``), built from it, not
                 re-extracted;
``provenance``   what the report was made from: the manifest of input files and its
                 ``input_fingerprint`` (a hash of the *input*), the configuration, and the import
                 record it came from, if any;
``eligibility``  whether the project may be modified, as recorded by an import. An import with no
                 attestation, or no import at all, can still be analysed; the result then says it
                 is **not eligible** and why. Nothing here creates or upgrades an attestation.

Serialization is canonical (sorted keys, compact, ASCII, no timestamps, no host paths), so the same
analysis of the same project gives the same bytes on every platform. ``loads`` checks size and
nesting before parsing, then the schema and the types, then the internal consistency of the result
(the stored fingerprints match the stored content; the inventory points at facts that exist). It
cannot recompute the *input* fingerprint from JSON alone, and a result carries no signature: a copy
edited by hand together with its hashes cannot be told from a genuine one. ``check_freshness`` is
what compares a result with a project.

This module writes nothing. Where a result is stored is not decided here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.workspace import Workspace
from androai_codegen.ingest import ImportResult
from androai_codegen.ingest.models import IngestReport
from androai_codegen.review.project import ProjectFiles

from .analyser import ReadAudit, analyse_files, read_project
from .config import AnalysisConfig
from .freshness import (
    InputFile,
    config_digest,
    config_record,
    manifest_fingerprint,
    manifest_of,
)
from .inventory import ProjectInventory, build_inventory
from .model import ANALYSIS_VERSION, AnalysisReport
from .store import report_fingerprint

RESULT_VERSION = 1
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 64


class InvalidAnalysisResult(ValueError):
    """Serialized result data that is too large, too deep, malformed, of an unsupported version, or
    inconsistent with itself."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportProvenance(_Frozen):
    """The import this analysis came from. ``content_fingerprint`` is the import's own hash of the
    files it copied: a different thing from the analysis input fingerprint, which changes as soon as
    anyone edits the project, while this one stays what the import recorded."""

    import_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    basis: str = Field(max_length=40)  # the attestation basis the import recorded


class Provenance(_Frozen):
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_files: tuple[InputFile, ...] = ()
    capped: bool = False  # the file limit cut the walk short: files beyond it are not tracked
    config: dict[str, int | float | None]
    config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported: ImportProvenance | None = None


class Eligibility(_Frozen):
    eligible_for_modification: bool
    reason: str = Field(max_length=300)
    import_id: str | None = None


class AnalysisResult(_Frozen):
    schema_version: int = RESULT_VERSION
    analysis_version: str
    report: AnalysisReport
    inventory: ProjectInventory
    provenance: Provenance
    eligibility: Eligibility

    @model_validator(mode="after")
    def _consistent(self) -> AnalysisResult:
        report = self.report
        if self.schema_version != RESULT_VERSION:
            raise ValueError(f"unsupported result version {self.schema_version}")
        if self.analysis_version != report.analysis_version:
            raise ValueError("the result and its report name different analysis versions")
        if report.fingerprint != report_fingerprint(report):
            raise ValueError("the report does not match its own fingerprint")
        if self.inventory.report_fingerprint != report.fingerprint:
            raise ValueError("the inventory was not built from this report")
        known = {fact.id for fact in report.facts}
        if not self.inventory.fact_ids() <= known:
            raise ValueError("the inventory points at facts the report does not have")
        provenance = self.provenance
        if manifest_fingerprint(provenance.input_files) != provenance.input_fingerprint:
            raise ValueError("the input manifest does not match its fingerprint")
        if config_digest(provenance.config) != provenance.config_digest:
            raise ValueError("the configuration does not match its digest")
        if self.eligibility.eligible_for_modification and provenance.imported is None:
            raise ValueError("a result is eligible for modification only through an import record")
        return self


# -- building ------------------------------------------------------------------------------------


def eligibility_of(import_report: IngestReport | None) -> Eligibility:
    """What an import record says about modification. Never more than it says."""
    if import_report is None:
        return Eligibility(
            eligible_for_modification=False,
            reason="no import record was given, so no ownership attestation is recorded",
        )
    if import_report.eligible_for_modification:
        return Eligibility(
            eligible_for_modification=True,
            reason="the import recorded an ownership attestation "
            f"({import_report.attestation.basis})",
            import_id=import_report.import_id,
        )
    return Eligibility(
        eligible_for_modification=False,
        reason="the import is not marked eligible for modification",
        import_id=import_report.import_id,
    )


def _imported(import_report: IngestReport | None) -> ImportProvenance | None:
    if import_report is None:
        return None
    return ImportProvenance(
        import_id=import_report.import_id,
        content_fingerprint=import_report.content_fingerprint,
        basis=import_report.attestation.basis,
    )


def _result(
    files: ProjectFiles,
    audit: ReadAudit | None,
    config: AnalysisConfig,
    import_report: IngestReport | None,
) -> AnalysisResult:
    report = analyse_files(files, config=config, audit=audit)
    entries, capped = manifest_of(files, audit)
    record = config_record(config)
    secrets = import_report.secrets if import_report is not None else None
    inventory = build_inventory(
        report,
        secret_findings=secrets.total_findings if secrets is not None else None,
        secret_kinds=secrets.by_kind if secrets is not None else None,
    )
    return AnalysisResult(
        analysis_version=ANALYSIS_VERSION,
        report=report,
        inventory=inventory,
        provenance=Provenance(
            input_fingerprint=manifest_fingerprint(entries),
            input_files=entries,
            capped=capped,
            config=record,
            config_digest=config_digest(record),
            imported=_imported(import_report),
        ),
        eligibility=eligibility_of(import_report),
    )


def analyse_workspace_result(
    workspace: Workspace,
    *,
    protection: ProtectionPolicy = DEFAULT_POLICY,
    config: AnalysisConfig | None = None,
    import_report: IngestReport | None = None,
) -> AnalysisResult:
    """Analyse the project in ``workspace``. Without an ``import_report`` the result is not
    eligible for modification (and says so)."""
    config = config or AnalysisConfig()
    files, audit = read_project(workspace, protection=protection, config=config)
    return _result(files, audit, config, import_report)


def analyse_import_result(
    result: ImportResult, *, config: AnalysisConfig | None = None
) -> AnalysisResult:
    """Analyse an imported project, honouring its protection, and record what the import says."""
    return analyse_workspace_result(
        result.workspace,
        protection=result.protection,
        config=config,
        import_report=result.report,
    )


def analyse_mapping_result(
    files: Mapping[str, str | bytes | None],
    *,
    config: AnalysisConfig | None = None,
    import_report: IngestReport | None = None,
) -> AnalysisResult:
    """Analyse an in-memory project (path -> text)."""
    return _result(
        ProjectFiles.from_mapping(files), None, config or AnalysisConfig(), import_report
    )


# -- JSON ----------------------------------------------------------------------------------------


def dumps(result: AnalysisResult) -> str:
    """The canonical JSON of a result: sorted keys, compact, ASCII, one trailing newline."""
    payload = result.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def _depth_of(text: str, limit: int) -> int:
    """The deepest ``[``/``{`` nesting of JSON text, scanned without recursion; stops past
    ``limit``."""
    depth = deepest = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > limit:
                    return deepest
        elif ch in "]}":
            depth -= 1
    return deepest


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise InvalidAnalysisResult("the JSON repeats a key")
    return dict(pairs)


def _refuse_constant(name: str) -> object:
    raise InvalidAnalysisResult(f"the JSON holds {name}, which is not a number a result can hold")


def loads(
    data: str | bytes,
    *,
    max_bytes: int = MAX_RESULT_BYTES,
    max_depth: int = MAX_JSON_DEPTH,
) -> AnalysisResult:
    """Read a result from JSON, or raise ``InvalidAnalysisResult``.

    Checked in this order: size, nesting depth, JSON syntax (no repeated keys, no ``NaN``), schema
    and exact types, then internal consistency. Nothing in the text is executed or followed.
    """
    size = len(data) if isinstance(data, bytes) else len(data.encode("utf-8", "surrogatepass"))
    if size > max_bytes:
        raise InvalidAnalysisResult(f"the result is {size} bytes; the limit is {max_bytes}")
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as exc:
        raise InvalidAnalysisResult("the result is not valid UTF-8") from exc
    if _depth_of(text, max_depth) > max_depth:
        raise InvalidAnalysisResult(f"the JSON is nested deeper than {max_depth} levels")
    try:
        json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_refuse_constant)
        return AnalysisResult.model_validate_json(text, strict=True)
    except InvalidAnalysisResult:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InvalidAnalysisResult("the result is not valid JSON") from exc
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ())) or "(root)"
        raise InvalidAnalysisResult(
            f"the result does not match the schema at {where}: {first.get('msg', 'invalid')}"
        ) from exc
