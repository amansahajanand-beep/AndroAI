"""The state every extractor shares during one analysis run."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from functools import cached_property

from androai_codegen.review.analysis import ProjectAnalysis
from androai_codegen.review.gradle import GradleScript
from androai_codegen.review.project import ProjectFiles

from .config import AnalysisConfig
from .members import FileInfo, TypeInfo
from .model import Basis, Evidence
from .resolve import TypeResolver
from .store import FactStore
from .text import LineText, xml_evidence

BUILD_SOURCE = re.compile(r"(?:^|/)(?:buildSrc|build-logic)/")


def module_label(module: str | None) -> str:
    return module or "."


@dataclass
class Run:
    """One analysis in progress. Extractors read from it and add facts to ``store``."""

    analysis: ProjectAnalysis
    files: ProjectFiles
    config: AnalysisConfig
    store: FactStore
    infos: dict[str, FileInfo] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    stopped: bool = False

    @property
    def a(self) -> ProjectAnalysis:
        return self.analysis

    # -- budget ---------------------------------------------------------------------------

    def expired(self) -> bool:
        """True once the optional deadline has passed (and, once true, stays true)."""
        if self.stopped:
            return True
        deadline = self.config.deadline_seconds
        # ``>=``: a budget of zero is already spent, even where the clock has not yet ticked
        if deadline is not None and time.monotonic() - self.started >= deadline:
            self.stopped = True
            self.store.limit(
                "time_budget_exceeded",
                "project",
                "the time budget ran out; facts beyond this point were not collected",
            )
        return self.stopped

    # -- project structure ----------------------------------------------------------------

    @cached_property
    def types(self) -> dict[str, TypeInfo]:
        found: dict[str, TypeInfo] = {}
        for path in sorted(self.infos):
            for info in self.infos[path].types:
                found.setdefault(info.fqn, info)
        return found

    @cached_property
    def resolver(self) -> TypeResolver:
        return TypeResolver(set(self.types))

    def module_of(self, path: str) -> str:
        return self.a.module_of(path) or ""

    def is_test(self, path: str) -> bool:
        return self.a.is_test_source(path)

    def is_build_logic(self, path: str) -> bool:
        return bool(BUILD_SOURCE.search(path))

    def path_tags(self, path: str) -> tuple[str, ...]:
        tags: list[str] = []
        module = self.a.module_of(path)
        if module is not None:
            tags.append(f"module:{module_label(module)}")
        source_set = self.a.source_set(path)
        if source_set:
            tags.append(f"source_set:{source_set}")
        if path.endswith(".kt"):
            tags.append("lang:kotlin")
        elif path.endswith(".java"):
            tags.append("lang:java")
        if self.is_test(path):
            tags.append("scope:test")
        if self.is_build_logic(path):
            tags.append("scope:build_logic")
        return tuple(tags)

    def app_types(self) -> list[tuple[FileInfo, TypeInfo]]:
        """Every type of application code with the file it is declared in, in path order."""
        return [(info, decl) for info in self.app_sources() for decl in info.types]

    def app_sources(self) -> list[FileInfo]:
        """Parsed source files that are part of the app (not tests, not build logic)."""
        return [
            self.infos[p]
            for p in sorted(self.infos)
            if not self.is_test(p) and not self.is_build_logic(p)
        ]

    # -- evidence -------------------------------------------------------------------------

    def gradle_evidence(self, script: GradleScript, line: int | None) -> Evidence:
        texts: dict[str, LineText] = self.__dict__.setdefault("_line_texts", {})
        if script.path not in texts:  # one line index per script, not one per fact
            texts[script.path] = LineText(script.text, script.masked)
        excerpt = texts[script.path].excerpt_at_line(line) if line else ""
        return Evidence(path=script.path, line=line, excerpt=excerpt)

    def xml_evidence(self, path: str, line: int | None) -> Evidence:
        lines: dict[str, list[str]] = self.__dict__.setdefault("_xml_lines", {})
        if path not in lines:
            lines[path] = self.files.texts.get(path, "").split("\n")
        made: dict[tuple[str, int | None], Evidence] = self.__dict__.setdefault("_xml_made", {})
        key = (path, line)
        if key not in made:
            made[key] = xml_evidence(lines[path], path, line)
        return made[key]

    def path_evidence(self, path: str) -> Evidence:
        return Evidence(path=path)

    # -- convenience ----------------------------------------------------------------------

    def fact(self, kind: str, subject: str, *, basis: Basis, **kwargs) -> str:
        return self.store.fact(kind, subject, basis=basis, **kwargs)
