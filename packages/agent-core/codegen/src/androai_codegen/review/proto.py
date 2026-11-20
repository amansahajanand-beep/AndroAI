"""Protocol Buffer files, read statically for the Java/Kotlin classes protoc generates from them.

Only what review needs: which class names a ``.proto`` makes importable. Nothing is executed.
"""

from __future__ import annotations

import re

_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_JAVA_PACKAGE = re.compile(r'\boption\s+java_package\s*=\s*"([^"]+)"')
_OUTER_CLASS = re.compile(r'\boption\s+java_outer_classname\s*=\s*"([^"]+)"')
_MULTIPLE_FILES = re.compile(r"\boption\s+java_multiple_files\s*=\s*true\b")
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_DECLARATION = re.compile(r"\b(?:message|enum|service)\s+([A-Za-z_]\w*)")


def _camel(stem: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", stem) if part)


def _top_level_names(code: str) -> list[str]:
    """Names of messages, enums and services declared outside any braces."""
    names: list[str] = []
    depth = 0
    start = 0
    for brace in re.finditer(r"[{}]", code):
        if depth == 0:
            names.extend(m.group(1) for m in _DECLARATION.finditer(code, start, brace.start()))
        depth = max(0, depth + (1 if brace.group() == "{" else -1))
        start = brace.end()
    if depth == 0:
        names.extend(m.group(1) for m in _DECLARATION.finditer(code, start))
    return names


def generated_classes(path: str, text: str) -> frozenset[str]:
    """Fully qualified names of the classes protoc would generate for this ``.proto`` file.

    Nested messages are reached through their outer class, so only top-level names are listed;
    callers accept any import that starts with one of them.
    """
    code = _COMMENTS.sub(" ", text)
    java_package = _JAVA_PACKAGE.search(code) or _PACKAGE.search(code)
    prefix = f"{java_package.group(1)}." if java_package else ""
    stem = path.rsplit("/", 1)[-1].removesuffix(".proto")
    outer_option = _OUTER_CLASS.search(code)
    outer = outer_option.group(1) if outer_option else _camel(stem)
    names = _top_level_names(code)

    # The wrapper class exists in every mode (protoc adds "OuterClass" if the name is taken).
    found = {prefix + outer, prefix + outer + "OuterClass"}
    for name in names:
        found.add(f"{prefix}{name}Kt")  # protobuf-kotlin DSL
        found.add(f"{prefix}{name}Grpc")  # gRPC services
        found.add(f"{prefix}{name}" if _MULTIPLE_FILES.search(code) else f"{prefix}{outer}.{name}")
    return frozenset(found)
