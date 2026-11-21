"""Best-effort masking of secrets before text is shown to an LLM or written to logs.

This is a safety net, not a guarantee: unknown secret formats will not be caught. Protected
files (see ``policy``) are never shown to the LLM at all; masking covers secrets that sit in
otherwise ordinary files.
"""

from __future__ import annotations

import re
from typing import NamedTuple

REDACTION_MARKER = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL
)

_TOKEN_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),  # Google API key
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack tokens
    re.compile(r"\bsk-[A-Za-z0-9_\-]{32,}"),  # OpenAI/Anthropic style keys
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
)

_KEYWORDS = (
    r"(?:password|passwd|passphrase|secret|token|api[_\-]?key|access[_\-]?key"
    r"|private[_\-]?key|credential)"
)
# key = value / key: value, in .properties, Gradle, Kotlin, Java, JSON and YAML forms. The
# {0,64} bounds keep matching linear even on huge single-line blobs.
_KEY_VALUE = re.compile(
    r"(?<![\w.\-])"
    r"(?P<prefix>(?P<q1>[\"']?)[\w.\-]{0,64}" + _KEYWORDS + r"[\w.\-]{0,64}(?P=q1)\s*[:=]\s*)"
    r"(?P<q2>[\"']?)(?P<value>(?![\w.]*\()[^\s\"'`,;{}]+)(?P=q2)",
    re.IGNORECASE,
)


def mask_secrets(text: str) -> str:
    """Return ``text`` with likely secret values replaced by ``[REDACTED]``.

    Over-masking is accepted (e.g. ``token_url = "https://..."``). Calls such as
    ``password = System.getenv("PW")`` are left alone because they hold no literal.
    """
    text = _PRIVATE_KEY.sub(REDACTION_MARKER, text)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTION_MARKER, text)
    return _KEY_VALUE.sub(lambda m: f"{m['prefix']}{m['q2']}{REDACTION_MARKER}{m['q2']}", text)


def count_redaction_markers(text: str) -> int:
    return text.count(REDACTION_MARKER)


# One label per entry of ``_TOKEN_PATTERNS``, in the same order.
_TOKEN_KINDS = (
    "aws_access_key",
    "github_token",
    "google_api_key",
    "slack_token",
    "openai_style_key",
    "jwt",
)
if len(_TOKEN_KINDS) != len(_TOKEN_PATTERNS):  # pragma: no cover - a maintenance guard
    raise RuntimeError("_TOKEN_KINDS must label every entry of _TOKEN_PATTERNS")


class SecretMatch(NamedTuple):
    """Where a likely secret sits in a text. Never carries the secret itself."""

    kind: str
    start: int
    end: int
    length: int  # length of the secret value (for a private key, of the whole block)


def find_secrets(text: str) -> list[SecretMatch]:
    """Where :func:`mask_secrets` would mask, with the kind and length of each value.

    It uses the same patterns, so detection and masking cannot drift apart. Overlapping matches
    are reported once, under the first (most specific) kind: private key, then a known token
    format, then a credential assignment. A value that is already the redaction marker is not a
    finding.
    """
    found: list[SecretMatch] = []

    def add(kind: str, start: int, end: int, length: int) -> None:
        if all(end <= other.start or start >= other.end for other in found):
            found.append(SecretMatch(kind, start, end, length))

    for match in _PRIVATE_KEY.finditer(text):
        add("private_key", match.start(), match.end(), match.end() - match.start())
    for kind, pattern in zip(_TOKEN_KINDS, _TOKEN_PATTERNS, strict=True):
        for match in pattern.finditer(text):
            add(kind, match.start(), match.end(), match.end() - match.start())
    for match in _KEY_VALUE.finditer(text):
        if match["value"] != REDACTION_MARKER:
            add(
                "credential_assignment",
                match.start("value"),
                match.end("value"),
                len(match["value"]),
            )
    return sorted(found, key=lambda item: item.start)
