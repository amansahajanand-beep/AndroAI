"""Android project analysis (Phase 6, stage M2A).

Reads an imported Android project and produces an evidence-backed report: what the project
declares (modules, dependencies, components, screens, layouts, navigation, storage, network,
dependency injection), how the parts relate, what was inferred, and what could not be read.

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

__all__ = [
    "ANALYSIS_VERSION",
    "AnalysisConfig",
    "AnalysisReport",
    "AnalysisStats",
    "Evidence",
    "Fact",
    "Limitation",
    "ReadAudit",
    "Relationship",
    "ReportIndex",
    "analyse_files",
    "analyse_import",
    "analyse_mapping",
    "analyse_workspace",
    "read_project",
]
