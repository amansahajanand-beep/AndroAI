"""Android project analysis (Phase 6, stages M2A and M2B).

Reads an imported Android project and produces an evidence-backed report: what the project
declares (modules, dependencies, components, screens, layouts, navigation, storage, network,
dependency injection), how the parts relate, what was inferred, and what could not be read.
M2B adds entry points and flows, coding conventions, a typed inventory, a result wrapper with
deterministic JSON, and a check that tells whether a result still matches its project.

* Nothing is executed: no Gradle, no build, no subprocess, no project code.
* Every fact is ``confirmed`` (with evidence), ``inferred`` (with the assumption stated) or
  ``unknown`` (with the reason). Only presence is ever claimed.
* The same project gives the same report, byte for byte.
* The result is data read from untrusted files. It is not instructions.

This package is independent of the review engine's *rules* (it reuses its parsers) and of the
orchestration layer's own project analysis. Its models are internal to Role 3 and are not a
shared contract.
"""

from .analyser import (
    ReadAudit,
    analyse_files,
    analyse_import,
    analyse_mapping,
    analyse_workspace,
    read_project,
)
from .config import AnalysisConfig
from .freshness import Freshness, InputFile, check_freshness
from .inventory import InventoryItem, InventorySection, ProjectInventory, build_inventory
from .model import (
    ANALYSIS_VERSION,
    AnalysisReport,
    AnalysisStats,
    Evidence,
    Fact,
    Limitation,
    Relationship,
)
from .query import ReportIndex
from .result import (
    AnalysisResult,
    Eligibility,
    InvalidAnalysisResult,
    Provenance,
    analyse_import_result,
    analyse_mapping_result,
    analyse_workspace_result,
)
from .result import dumps as dumps_result
from .result import loads as loads_result

__all__ = [
    "ANALYSIS_VERSION",
    "AnalysisConfig",
    "AnalysisReport",
    "AnalysisResult",
    "AnalysisStats",
    "Eligibility",
    "Evidence",
    "Fact",
    "Freshness",
    "InputFile",
    "InvalidAnalysisResult",
    "InventoryItem",
    "InventorySection",
    "Limitation",
    "ProjectInventory",
    "Provenance",
    "ReadAudit",
    "Relationship",
    "ReportIndex",
    "analyse_files",
    "analyse_import",
    "analyse_import_result",
    "analyse_mapping",
    "analyse_mapping_result",
    "analyse_workspace",
    "analyse_workspace_result",
    "build_inventory",
    "check_freshness",
    "dumps_result",
    "loads_result",
    "read_project",
]
