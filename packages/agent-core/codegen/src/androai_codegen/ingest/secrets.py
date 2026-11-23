"""Secret detection for an imported project, and the protection policy that follows from it.

Detection never alters the imported files and never records a value: a finding is a path, a kind,
a line and a length. What happens to a file that holds a secret is decided by what the file is:

* A file whose *purpose* is to hold secrets is protected (never shown to an LLM, never modified):
  keystores and the like (the default policy), ``google-services.json``, any configuration file
  (``.properties``, ``.json``, ``.yml`` ...) that contains a likely secret, and any file that
  contains a private key.
* A source or resource file that merely contains a secret stays editable. Its secret is masked
  whenever the file is shown to an LLM (``PatchEngine.read_for_llm``), and a patch that writes the
  redaction marker is refused. Protecting these files would make ordinary manifests and
  ``strings.xml`` files, which often hold API keys, impossible to change.
"""

from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from androai_codegen.editing.policy import DEFAULT_POLICY, ProtectionPolicy
from androai_codegen.editing.redact import find_secrets
from androai_codegen.editing.workspace import Workspace

from .copying import FileRecord
from .models import MAX_LISTED_FINDINGS, MAX_LISTED_PATHS, IngestLimits, SecretFinding, SecretScan

CONFIG_SUFFIXES = (".properties", ".env", ".ini", ".cfg", ".conf", ".yml", ".yaml", ".json")
# In code, a credential-like name next to something that is not a quoted literal is a type or a
# reference (``val password: String``), not a secret. Such matches are not reported. (Masking is
# unaffected: ``mask_secrets`` still masks them whenever the file is shown to an LLM.)
CODE_SUFFIXES = (".kt", ".kts", ".java", ".gradle")
SENSITIVE_CONFIG_NAMES = frozenset({"google-services.json"})
_BINARY_PROBE = 8192


@dataclass(frozen=True)
class ImportProtection(ProtectionPolicy):
    """The default protection plus the files this project's import found to be secret-bearing."""

    extra_paths: frozenset[str] = frozenset()  # project-relative, lower case

    def is_protected(self, rel_path: str) -> bool:
        return rel_path.lower() in self.extra_paths or super().is_protected(rel_path)


def protection_for(paths: list[str] | tuple[str, ...]) -> ImportProtection:
    return ImportProtection(extra_paths=frozenset(path.lower() for path in paths))


def scan_workspace(
    workspace: Workspace, records: Mapping[str, FileRecord], limits: IngestLimits
) -> SecretScan:
    findings: list[SecretFinding] = []
    by_kind: Counter[str] = Counter()
    protected: set[str] = set()
    large: list[str] = []
    scanned = 0
    not_scanned = 0
    total = 0

    def record(path: str, kind: str, line: int | None = None, length: int | None = None) -> None:
        nonlocal total
        total += 1
        by_kind[kind] += 1
        if len(findings) < MAX_LISTED_FINDINGS:
            findings.append(SecretFinding(path=path, kind=kind, line=line, length=length))

    for rel in sorted(records):
        lower = rel.lower()
        name = lower.rsplit("/", 1)[-1]
        if DEFAULT_POLICY.is_protected(rel):
            record(rel, "protected_file")  # protected already; listed so the report shows it exists
        if name in SENSITIVE_CONFIG_NAMES:
            record(rel, "sensitive_config_file")
            protected.add(rel)

        if records[rel].size > limits.secret_scan_max_bytes:
            not_scanned += 1
            if len(large) < MAX_LISTED_PATHS:
                large.append(rel)
            continue
        data = workspace.read_bytes(rel)
        if b"\0" in data[:_BINARY_PROBE]:
            not_scanned += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            not_scanned += 1
            continue
        scanned += 1

        matches = find_secrets(text)
        if lower.endswith(CODE_SUFFIXES):
            matches = [
                m
                for m in matches
                if m.kind != "credential_assignment" or text[m.start - 1 : m.start] in ('"', "'")
            ]
        if not matches:
            continue
        newlines = [index for index, char in enumerate(text) if char == "\n"]
        for match in matches:
            line = bisect.bisect_right(newlines, match.start) + 1
            record(rel, match.kind, line, match.length)
        if lower.endswith(CONFIG_SUFFIXES) or any(m.kind == "private_key" for m in matches):
            protected.add(rel)

    return SecretScan(
        findings=findings,
        total_findings=total,
        by_kind=dict(sorted(by_kind.items())),
        files_scanned=scanned,
        files_not_scanned=not_scanned,
        not_scanned_large=large,
        protected_paths=sorted(protected),
    )
