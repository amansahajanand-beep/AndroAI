"""Authentication-related facts read from sources, resources and build scripts.

Only what can be read with confidence is recorded: a literal, never a computed value. Nothing here
keeps or prints a secret: a finding carries the kind of secret, the identifier it was assigned to
and its length, never the value. Test source sets are never scanned.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .navigation import split_args
from .source import SourceFile

if TYPE_CHECKING:
    from .analysis import ProjectAnalysis

_PEM_HEADER = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_BASE64 = re.compile(r"[A-Za-z0-9+/=]+")

# Token formats with a distinctive prefix (the same shapes editing/redact.py masks). Google API keys
# ("AIza...") and JWTs are deliberately left out: Firebase and Maps keys are shipped inside apps by
# design, and example JWTs are common in samples. Reporting them would be noise.
_TOKEN_FORMATS = (
    ("an AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("a Stripe live secret key", re.compile(r"\bsk_live_[0-9A-Za-z]{20,}")),
    ("a Google OAuth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}")),
    ("an API secret key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_\-]{32,}")),
)

_SECRET_NAME = (
    r"[A-Za-z0-9_]{0,40}(?:(?:client|api|app|consumer)[_-]?secret|secret[_-]?key)[A-Za-z0-9_]{0,40}"
)
_NAMED_CODE = re.compile(
    rf"""(?<![\w.])(?P<name>{_SECRET_NAME})["']?\s*(?:[:=]|\bto\b)\s*"(?P<value>[^"\\$\n]{{16,}})\"""",
    re.IGNORECASE,
)
_NAMED_XML = re.compile(
    rf"""<string\s+name="(?P<name>{_SECRET_NAME})"[^>]*>(?P<value>[^<]{{16,}})</string>""",
    re.IGNORECASE,
)
_BUILD_CONFIG = re.compile(
    r"""buildConfigField\s*\(?\s*["']String["']\s*,\s*["'](?P<name>[A-Z0-9_]*SECRET[A-Z0-9_]*)["']\s*,"""
    r"""\s*["']\\"(?P<value>[^"'\\$]{16,})\\"["']"""
)
_PLACEHOLDER = re.compile(
    r"(?i)your|example|xxxx|changeme|change_me|placeholder|todo|replace|dummy|sample|test|fake"
    r"|[<>]|\{\{|\$\{|\*\*\*"
)
_SIGNING = re.compile(
    r"""\b(?P<field>storePassword|keyPassword)\b\s*(?:=\s*|\s+)(?P<q>["'])(?P<value>[^"'$\n]+)(?P=q)"""
    r"""[ \t]*(?:;|$)""",
    re.MULTILINE,
)
# The password of the debug keystore Android Studio creates; it is public by design.
_DEBUG_KEYSTORE_PASSWORD = "android"

_PUT_STRING = re.compile(r"putString\s*\(\s*(?=\")")
_EDITOR_CONTEXT = re.compile(r"\.edit\s*\(|\bedit\s*\{|\bedit\s*\(|\bEditor\b")
_SAFE_STORAGE = re.compile(
    r"EncryptedSharedPreferences|MasterKey|KeyStore|\bCipher\b|\bAead\b|\bTink\b|\bencrypt",
    re.IGNORECASE,
)
# Key names (lower-cased, letters only) of credentials: tokens that authenticate, and passwords.
_CREDENTIAL_KEYS = frozenset(
    """accesstoken refreshtoken idtoken authtoken sessiontoken bearertoken oauthtoken jwt
    password passwd""".split()
)

_REDIRECT_PARSE = re.compile(
    r'^\s*(?:android\.net\.)?Uri\s*\.\s*parse\s*\(\s*"([A-Za-z][A-Za-z0-9+.\-]*):[^"$\\]*"\s*\)\s*$'
)
_REDIRECT_TO_URI = re.compile(
    r'^\s*"([A-Za-z][A-Za-z0-9+.\-]*):[^"$\\]*"\s*\.\s*toUri\s*\(\s*\)\s*$'
)
_APPAUTH_REQUEST = re.compile(r"AuthorizationRequest\s*\.\s*Builder\s*\(")
_APPAUTH_SET_REDIRECT = re.compile(r"(?<![\w$])setRedirectUri\s*\(")


@dataclass(frozen=True)
class Located:
    path: str
    line: int
    column: int = 1


@dataclass(frozen=True)
class SecretUse:
    path: str
    line: int
    what: str  # "a GitHub token", or the identifier the literal is assigned to
    named: bool  # True when ``what`` is an identifier
    length: int


@dataclass(frozen=True)
class SigningPassword:
    path: str
    line: int
    field: str  # storePassword | keyPassword


@dataclass(frozen=True)
class PreferenceCredential:
    path: str
    line: int
    column: int
    key: str  # the preference key as written, e.g. "refresh_token"


@dataclass(frozen=True)
class RedirectUse:
    path: str
    line: int
    column: int
    scheme: str


@dataclass
class AuthFacts:
    private_keys: list[Located] = field(default_factory=list)
    secrets: list[SecretUse] = field(default_factory=list)
    signing: list[SigningPassword] = field(default_factory=list)
    credentials: list[PreferenceCredential] = field(default_factory=list)
    redirects: list[RedirectUse] = field(default_factory=list)

    @classmethod
    def build(cls, a: ProjectAnalysis) -> AuthFacts:
        facts = cls()
        for path, text in sorted(a.files.texts.items()):
            if a.is_test_source(path):
                continue
            _scan_text(facts, path, text)
        for path, source in sorted(a.sources.items()):
            if a.is_test_source(path):
                continue
            _scan_source(facts, path, source)
        return facts


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# -- text files: keys, tokens, secrets, signing passwords ----------------------------------------


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _looks_secret(value: str) -> bool:
    """A literal worth reporting under a secret-sounding name: no spaces, not a placeholder, a mix
    of letters and digits, and not too regular (the patterns that find it already require 16 or
    more characters). Identifiers such as ``client_secret_param`` (no digit) and phrases are not
    secrets."""
    if re.search(r"\s", value) or _PLACEHOLDER.search(value):
        return False
    if not (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
        return False
    return _entropy(value) >= 3.0


def _scan_text(facts: AuthFacts, path: str, text: str) -> None:
    if "PRIVATE KEY" in text:
        _scan_private_keys(facts, path, text)
    reported: set[int] = set()
    for what, pattern in _TOKEN_FORMATS:
        for match in pattern.finditer(text):
            line = _line(text, match.start())
            reported.add(line)  # a secret-named literal on the same line is the same finding
            facts.secrets.append(SecretUse(path, line, what, False, len(match.group())))
    patterns = []
    if path.endswith((".kt", ".java", ".kts", ".gradle")):
        patterns.append(_NAMED_CODE)
    if path.endswith(".xml"):
        patterns.append(_NAMED_XML)
    if path.endswith((".kts", ".gradle")):
        patterns.append(_BUILD_CONFIG)
    for pattern in patterns:
        for match in pattern.finditer(text):
            line = _line(text, match.start())
            if line in reported or not _looks_secret(match.group("value")):
                continue
            reported.add(line)
            facts.secrets.append(
                SecretUse(path, line, match.group("name"), True, len(match.group("value")))
            )
    if path.endswith((".kts", ".gradle")):
        for match in _SIGNING.finditer(text):
            if match.group("value") != _DEBUG_KEYSTORE_PASSWORD:
                facts.signing.append(
                    SigningPassword(path, _line(text, match.start()), match.group("field"))
                )


def _scan_private_keys(facts: AuthFacts, path: str, text: str) -> None:
    """A PEM private-key block with a real body (an ``-----END`` marker and at least 60 base64
    characters between the markers), so a regular expression or a message that only mentions the
    header is not a key."""
    for header in _PEM_HEADER.finditer(text):
        end = text.find("-----END", header.end())
        if end == -1:
            continue
        body = re.sub(r"""\\n|\\r|[\s"'+,]""", "", text[header.end() : end])
        if len(body) >= 60 and _BASE64.fullmatch(body):
            facts.private_keys.append(Located(path, _line(text, header.start())))


# -- sources: preference writes and OAuth redirect URIs -------------------------------------------


def _scan_source(facts: AuthFacts, path: str, source: SourceFile) -> None:
    if (
        "putString" in source.masked
        and "SharedPreferences" in source.masked
        and not _SAFE_STORAGE.search(source.masked)
    ):
        _scan_preferences(facts, path, source)
    if "net.openid.appauth" in source.text:
        _scan_redirects(facts, path, source)


def _scan_preferences(facts: AuthFacts, path: str, source: SourceFile) -> None:
    masked = source.masked
    for match in _PUT_STRING.finditer(masked):
        literal = source.lexed.string_starting_at(match.end())
        if literal is None or not literal.terminated:
            continue
        key = source.lexed.string_value(literal)
        if re.sub(r"[^a-z]", "", key.lower()) not in _CREDENTIAL_KEYS:
            continue
        # a SharedPreferences.Editor, not a Bundle or an Intent: the call is made on `edit()`,
        # inside an `edit { }` block, or on something typed as an Editor
        if not _EDITOR_CONTEXT.search(masked[max(0, match.start() - 400) : match.start()]):
            continue
        facts.credentials.append(
            PreferenceCredential(
                path, source.line(match.start()), source.column(match.start()), key
            )
        )


def _scheme_of(expression: str) -> str | None:
    for pattern in (_REDIRECT_PARSE, _REDIRECT_TO_URI):
        found = pattern.match(expression)
        if found:
            return found.group(1).lower()
    return None


def _scan_redirects(facts: AuthFacts, path: str, source: SourceFile) -> None:
    for pattern, position in ((_APPAUTH_REQUEST, 3), (_APPAUTH_SET_REDIRECT, 0)):
        for match in pattern.finditer(source.masked):
            spans = split_args(source.masked, match.end() - 1)
            if len(spans) <= position:
                continue
            start, end = spans[position]
            scheme = _scheme_of(source.text[start:end])
            if scheme:
                facts.redirects.append(
                    RedirectUse(
                        path, source.line(match.start()), source.column(match.start()), scheme
                    )
                )
