"""Licence detection for an imported project: recorded for people, never decisive.

This is a heuristic over well-known licence texts and ``SPDX-License-Identifier`` headers. It
cannot prove who owns the code or what a licence permits, and it is not legal advice: what makes an
import eligible for modification is the ownership or permission attestation the caller gives.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from androai_codegen.editing.workspace import Workspace

from .copying import FileRecord
from .models import LicenceClass, LicenceFile, LicenceInfo

_LICENCE_NAME = re.compile(r"^(?:licen[cs]e|copying|unlicense)(?:[._-].*)?$", re.IGNORECASE)
_SPDX_HEADER = re.compile(r"SPDX-License-Identifier:\s*([^\r\n*]+)")
_HEADER_SUFFIXES = (".kt", ".kts", ".java", ".xml", ".gradle")
_MAX_LICENCE_FILES = 20
_MAX_LICENCE_BYTES = 256 * 1024
_HEADER_PROBE_BYTES = 2048
_MAX_LICENCE_DEPTH = 2

_RANK = {
    LicenceClass.STRONG_COPYLEFT: 4,
    LicenceClass.WEAK_COPYLEFT: 3,
    LicenceClass.UNKNOWN: 2,
    LicenceClass.PERMISSIVE: 1,
    LicenceClass.NONE: 0,
}

_SPDX_CLASS = {
    "apache-2.0": LicenceClass.PERMISSIVE,
    "mit": LicenceClass.PERMISSIVE,
    "bsd-2-clause": LicenceClass.PERMISSIVE,
    "bsd-3-clause": LicenceClass.PERMISSIVE,
    "isc": LicenceClass.PERMISSIVE,
    "0bsd": LicenceClass.PERMISSIVE,
    "unlicense": LicenceClass.PERMISSIVE,
    "cc0-1.0": LicenceClass.PERMISSIVE,
    "mpl-2.0": LicenceClass.WEAK_COPYLEFT,
    "epl-1.0": LicenceClass.WEAK_COPYLEFT,
    "epl-2.0": LicenceClass.WEAK_COPYLEFT,
    "cddl-1.0": LicenceClass.WEAK_COPYLEFT,
    "lgpl-2.0": LicenceClass.WEAK_COPYLEFT,
    "lgpl-2.1": LicenceClass.WEAK_COPYLEFT,
    "lgpl-3.0": LicenceClass.WEAK_COPYLEFT,
    "gpl-2.0": LicenceClass.STRONG_COPYLEFT,
    "gpl-3.0": LicenceClass.STRONG_COPYLEFT,
    "agpl-3.0": LicenceClass.STRONG_COPYLEFT,
}
_SPDX_OPERATORS = {"or", "and", "with"}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def classify_text(text: str) -> tuple[str | None, LicenceClass]:
    """Recognise a well-known licence text. Returns ``(spdx id or None, class)``."""
    t = _squash(text)
    if "gnu affero general public license" in t:
        return "AGPL-3.0", LicenceClass.STRONG_COPYLEFT
    if "gnu lesser general public license" in t or "gnu library general public license" in t:
        if "version 3" in t:
            return "LGPL-3.0", LicenceClass.WEAK_COPYLEFT
        if "version 2.1" in t:
            return "LGPL-2.1", LicenceClass.WEAK_COPYLEFT
        return "LGPL-2.0", LicenceClass.WEAK_COPYLEFT
    if "gnu general public license" in t:
        if "version 3" in t:
            return "GPL-3.0", LicenceClass.STRONG_COPYLEFT
        if "version 2" in t:
            return "GPL-2.0", LicenceClass.STRONG_COPYLEFT
        return None, LicenceClass.STRONG_COPYLEFT
    if "mozilla public license" in t and "2.0" in t:
        return "MPL-2.0", LicenceClass.WEAK_COPYLEFT
    if "eclipse public license" in t:
        return ("EPL-2.0" if "2.0" in t else "EPL-1.0"), LicenceClass.WEAK_COPYLEFT
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0", LicenceClass.PERMISSIVE
    if "permission is hereby granted, free of charge" in t:
        return "MIT", LicenceClass.PERMISSIVE
    if "permission to use, copy, modify, and/or distribute this software" in t:
        return "ISC", LicenceClass.PERMISSIVE
    if "redistribution and use in source and binary forms" in t:
        if "neither the name" in t or "endorse or promote" in t:
            return "BSD-3-Clause", LicenceClass.PERMISSIVE
        return "BSD-2-Clause", LicenceClass.PERMISSIVE
    if "free and unencumbered software released into the public domain" in t:
        return "Unlicense", LicenceClass.PERMISSIVE
    if "cc0 1.0 universal" in t:
        return "CC0-1.0", LicenceClass.PERMISSIVE
    return None, LicenceClass.UNKNOWN


def classify_spdx_expression(expression: str) -> tuple[list[str], LicenceClass]:
    """The identifiers in an SPDX expression and the most restrictive class among them."""
    ids: list[str] = []
    worst = LicenceClass.NONE
    for token in re.findall(r"[A-Za-z0-9.+-]+", expression):
        if token.lower() in _SPDX_OPERATORS:
            continue
        ids.append(token)
        key = re.sub(r"(?:-only|-or-later|\+)$", "", token.lower())
        klass = _SPDX_CLASS.get(key, LicenceClass.UNKNOWN)
        if _RANK[klass] > _RANK[worst]:
            worst = klass
    return ids, worst


def detect_licence(workspace: Workspace, records: Mapping[str, FileRecord]) -> LicenceInfo:
    files: list[LicenceFile] = []
    spdx: set[str] = set()
    worst = LicenceClass.NONE

    def consider(klass: LicenceClass) -> None:
        nonlocal worst
        if _RANK[klass] > _RANK[worst]:
            worst = klass

    candidates = sorted(
        rel
        for rel in records
        if rel.count("/") < _MAX_LICENCE_DEPTH and _LICENCE_NAME.match(rel.rsplit("/", 1)[-1])
    )
    for rel in candidates[:_MAX_LICENCE_FILES]:
        if records[rel].size > _MAX_LICENCE_BYTES:
            files.append(LicenceFile(path=rel, spdx=None, classification=LicenceClass.UNKNOWN))
            consider(LicenceClass.UNKNOWN)
            continue
        text = workspace.read_bytes(rel).decode("utf-8", errors="replace")
        identifier, klass = classify_text(text)
        files.append(LicenceFile(path=rel, spdx=identifier, classification=klass))
        if identifier:
            spdx.add(identifier)
        consider(klass)

    headers = 0
    for rel in sorted(records):
        if not rel.endswith(_HEADER_SUFFIXES):
            continue
        with open(workspace.resolve(rel), "rb") as handle:
            head = handle.read(_HEADER_PROBE_BYTES).decode("utf-8", errors="replace")
        match = _SPDX_HEADER.search(head)
        if match:
            headers += 1
            ids, klass = classify_spdx_expression(match.group(1))
            spdx.update(ids)
            consider(klass)

    notes = ["Licence detection is a heuristic and not legal advice."]
    if worst is LicenceClass.NONE:
        notes.append(
            "No licence file or SPDX header was found: the code is all rights reserved by default, "
            "so only your ownership or permission makes this import eligible for modification."
        )
    elif worst is LicenceClass.STRONG_COPYLEFT:
        notes.append(
            "A strong copyleft licence was detected: check that your permission covers modifying "
            "and redistributing this code under its terms."
        )
    elif worst is LicenceClass.WEAK_COPYLEFT:
        notes.append(
            "A weak copyleft licence was detected: check its terms for the files it covers."
        )
    elif worst is LicenceClass.UNKNOWN:
        notes.append("A licence file or header was found that this check does not recognise.")

    return LicenceInfo(
        files=files,
        spdx_ids=sorted(spdx),
        classification=worst,
        source_headers=headers,
        notes=notes,
    )
