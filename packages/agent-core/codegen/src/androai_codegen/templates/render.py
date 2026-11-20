"""Placeholder substitution and the escapes a substituted value needs.

Templates are plain text with ``__NAME__`` placeholders (upper case, so ``__init__`` or a Kotlin
``__x`` never looks like one). Substitution is a **single pass**: a value that itself contains
``__FOO__`` is inserted as it is and never expanded again. An unknown placeholder is an error, not
an empty string, so a typo in a template fails loudly instead of producing a broken project.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import TemplateRenderError

PLACEHOLDER = re.compile(r"__([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)__")


@dataclass(frozen=True)
class TemplateFile:
    """One file of a template: a path and a content, both of which may hold placeholders."""

    path: str
    content: str
    description: str


@dataclass(frozen=True)
class RenderedFile:
    """A file after substitution: safe to hand to ``CreateFile``."""

    path: str
    content: str
    description: str


def placeholders(text: str) -> set[str]:
    """Every placeholder name used in ``text``."""
    return {match.group(1) for match in PLACEHOLDER.finditer(text)}


def substitute(text: str, values: Mapping[str, str], *, where: str) -> str:
    """Replace every placeholder of ``text`` in one pass (``where`` names the file in errors)."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return values[name]
        except KeyError:
            raise TemplateRenderError(
                f"{where}: unknown placeholder __{name}__ (known: {sorted(values)})"
            ) from None

    return PLACEHOLDER.sub(replace, text)


def android_string(value: str) -> str:
    """Escape ``value`` for the text of an Android ``<string>`` resource.

    ``&`` and ``<`` are XML metacharacters; an apostrophe must be escaped for AAPT. (Project names
    cannot contain ``<``, quotes, ``@``, ``?`` or backslashes; the escape still handles them, so it
    is correct on its own and not only because of the validator in front of it.)
    """
    out: list[str] = []
    for ch in value:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == "'":
            out.append("\\'")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        else:
            out.append(ch)
    text = "".join(out)
    if text[:1] in ("@", "?"):
        text = "\\" + text
    return text
