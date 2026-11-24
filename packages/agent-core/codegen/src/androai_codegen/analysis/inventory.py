"""A typed inventory of an analysed project (M2B, task M2.10).

The inventory is a **view** over an ``AnalysisReport``: it groups the report's facts into the
sections a reader of the project wants (identity, build, modules, components, screens, architecture,
data, tests...) and extracts nothing new. Every entry therefore points at the facts that support it
(``fact_ids``) and carries either evidence (path, line, excerpt) or the reason the fact has none (an
``inferred`` fact says what was assumed, an ``unknown`` one says why it could not be read). An entry
without a fact, or without evidence or a reason, cannot be built.

What is **not** here, on purpose: a rendering for a prompt or for an LLM. How the inventory is
summarised for planning belongs to the orchestration layer.

An ``unknown`` or ``inferred`` fact stays an entry with that status: the inventory never turns
"could not be read" into an empty section, and a missing entry is "not observed", never "absent".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .model import AnalysisReport, AttrValue, Evidence, Fact, FactStatus, Limitation

INVENTORY_VERSION = 1
MAX_ITEMS_PER_SECTION = 200
MAX_EVIDENCE_PER_ITEM = 3

# section -> (fact kinds, convention dimensions or None for "every dimension of those kinds")
_SECTIONS: dict[str, tuple[tuple[str, ...], frozenset[str] | None]] = {
    "identity": (("module",), None),
    "build": (
        ("gradle_plugin", "sdk_level", "version_catalog", "build_feature", "build_source"),
        None,
    ),
    "modules": (("module", "module_type", "module_dependency"), None),
    "languages_and_ui": (("convention",), frozenset({"language", "ui_toolkit"})),
    "components": (
        (
            "application",
            "activity",
            "activity_alias",
            "service",
            "receiver",
            "provider",
            "entry_point",
        ),
        None,
    ),
    "permissions": (("permission", "permission_defined", "uses_feature"), None),
    "screens_and_navigation": (
        (
            "fragment",
            "compose_screen",
            "compose_route",
            "nav_graph",
            "nav_nested_graph",
            "nav_destination",
            "deep_link",
            "layout",
            "binding",
            "app_flow",
            "flow_gap",
            "intent_launch",
            "navigation",
        ),
        None,
    ),
    "architecture": (
        (
            "convention",
            "viewmodel",
            "hilt_viewmodel",
            "di_module",
            "dagger_component",
            "koin_module",
        ),
        frozenset(
            {
                "architecture",
                "app_structure",
                "package_layout",
                "naming",
                "di",
                "state",
                "async",
                "formatting",
            }
        ),
    ),
    "data_and_network": (
        (
            "room_database",
            "room_entity",
            "room_dao",
            "room_migration",
            "retrofit_service",
            "http_endpoint",
            "base_url",
            "http_interceptor",
            "shared_preferences",
            "datastore",
            "sqlite_helper",
            "file_storage",
        ),
        None,
    ),
    "integrations": (("technology", "meta_data"), None),
    "tests": (("convention",), frozenset({"testing"})),
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InventoryItem(_Frozen):
    kind: str
    name: str = Field(min_length=1, max_length=400)
    status: FactStatus
    fact_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    attributes: dict[str, AttrValue] = Field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _explained(self) -> InventoryItem:
        if not self.evidence and not self.reason:
            raise ValueError("an inventory entry needs evidence or a reason")
        return self


class InventorySection(_Frozen):
    name: str
    kinds: tuple[str, ...]
    total: int = Field(ge=0)
    truncated: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    items: tuple[InventoryItem, ...] = ()


class ProtectionSummary(_Frozen):
    """What the analysis could not read, and (when it is known) what an import found."""

    files_not_read: dict[str, int] = Field(default_factory=dict)  # reason -> count
    secret_findings: int | None = None
    secret_kinds: dict[str, int] | None = None


class ProjectInventory(_Frozen):
    inventory_version: int = INVENTORY_VERSION
    analysis_version: str
    report_fingerprint: str  # of the report this was built from: not of the project input
    complete: bool
    identity: InventorySection
    build: InventorySection
    modules: InventorySection
    languages_and_ui: InventorySection
    components: InventorySection
    permissions: InventorySection
    screens_and_navigation: InventorySection
    architecture: InventorySection
    data_and_network: InventorySection
    integrations: InventorySection
    tests: InventorySection
    protection: ProtectionSummary
    limitations: tuple[Limitation, ...] = ()

    def sections(self) -> dict[str, InventorySection]:
        return {name: getattr(self, name) for name in _SECTIONS}

    def fact_ids(self) -> set[str]:
        return {
            i
            for section in self.sections().values()
            for item in section.items
            for i in item.fact_ids
        }


def _item(fact: Fact) -> InventoryItem:
    evidence = fact.evidence[:MAX_EVIDENCE_PER_ITEM]
    reason = fact.reason or fact.note  # what was assumed (inferred) or why it is unread (unknown)
    return InventoryItem(
        kind=fact.kind,
        name=fact.subject,
        status=fact.status,
        fact_ids=(fact.id,),
        attributes=dict(fact.attributes),
        evidence=evidence,
        reason=reason,
    )


def _belongs(section: str, fact: Fact) -> bool:
    kinds, dimensions = _SECTIONS[section]
    if fact.kind not in kinds:
        return False
    if fact.kind == "convention" and dimensions is not None:
        return fact.attributes.get("dimension") in dimensions
    if section == "identity":
        return "application_id" in fact.attributes or "namespace" in fact.attributes
    return True


def build_inventory(
    report: AnalysisReport,
    *,
    secret_findings: int | None = None,
    secret_kinds: Mapping[str, int] | None = None,
) -> ProjectInventory:
    """Group a report's facts into sections. Pure and deterministic: the same report gives the
    same inventory. ``secret_findings`` and ``secret_kinds`` come from an import record when there
    is one (counts only, never values)."""
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in report.facts:  # already sorted by id
        for section in _SECTIONS:
            if _belongs(section, fact):
                grouped[section].append(fact)
    sections: dict[str, InventorySection] = {}
    for name, (kinds, _dimensions) in _SECTIONS.items():
        facts = sorted(grouped.get(name, ()), key=lambda f: (f.kind, f.subject))
        shown = facts[:MAX_ITEMS_PER_SECTION]
        sections[name] = InventorySection(
            name=name,
            kinds=kinds,
            total=len(facts),
            truncated=len(facts) > len(shown),
            counts=dict(sorted(Counter(f.kind for f in facts).items())),
            by_status=dict(sorted(Counter(f.status for f in facts).items())),
            items=tuple(_item(f) for f in shown),
        )
    return ProjectInventory(
        analysis_version=report.analysis_version,
        report_fingerprint=report.fingerprint,
        complete=report.complete,
        protection=ProtectionSummary(
            files_not_read=dict(sorted(report.stats.files_not_read.items())),
            secret_findings=secret_findings,
            secret_kinds=dict(sorted(secret_kinds.items())) if secret_kinds is not None else None,
        ),
        limitations=report.limitations,
        **sections,
    )
