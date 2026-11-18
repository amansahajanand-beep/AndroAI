"""Secret redaction applied to every prompt before it reaches a model, and to
file content before it is indexed/returned as context."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),  # OpenAI/Anthropic-style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),  # Slack
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
]
# key = "value" style assignments (Gradle/properties/Kotlin/env) for secret-looking names
_ASSIGN = re.compile(
    r"""(?ix)
    (\b[\w.\-]*(?:password|passwd|secret|token|api[_\-]?key|apikey|storepass|keypass|private[_\-]?key|client[_\-]?secret)[\w.\-]*
     \s*[:=]\s*)
    (["']?)([^\s"',;]{6,})(\2)
    """
)


def redact(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    return _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}{m.group(4)}", text)


# Files whose content must never be indexed or sent anywhere.
SENSITIVE_FILENAMES = {
    "local.properties",
    "keystore.properties",
    "google-services.json",
    "GoogleService-Info.plist",
    ".env",
    "secrets.properties",
    "gradle.properties.local",
}
SENSITIVE_SUFFIXES = (".jks", ".keystore", ".p12", ".pem", ".key", ".pfx")


def is_sensitive_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in SENSITIVE_FILENAMES or name.startswith(".env") or name.endswith(SENSITIVE_SUFFIXES)
