"""Security-relevant call sites read from Kotlin and Java sources.

Only what can be read with confidence is recorded. A flag expression that is a variable, an intent
built elsewhere, a filter held in a field: each is recorded as "unknown", and the rules stay silent
about it. Test sources are never scanned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .navigation import split_args
from .source import SourceFile

if TYPE_CHECKING:
    from .analysis import ProjectAnalysis

_PENDING = re.compile(
    r"(?<![\w$])PendingIntent\s*\.\s*"
    r"(getActivity|getActivities|getBroadcast|getService|getForegroundService)\s*\("
)
_REGISTER = re.compile(r"(?<![\w$])registerReceiver\s*\(")
_URL_CALL = re.compile(r"(?<![\w$])(?:baseUrl|url|URL)\s*\(")
_PERMISSION_REF = re.compile(r"\bManifest\s*\.\s*permission\s*\.\s*([A-Z][A-Z0-9_]*)\b")
_PERMISSION_STRING = re.compile(r"android\.permission\.([A-Z][A-Z0-9_]*)")
# Calls that ask for, or test, a run-time permission. A file containing one is a file that deals
# with permissions: the permission names in it are being requested or checked, not merely listed.
_PERMISSION_MACHINERY = re.compile(
    r"\b(?:requestPermissions|checkSelfPermission|shouldShowRequestPermissionRationale|"
    r"RequestPermission|RequestMultiplePermissions|rememberPermissionState|"
    r"rememberMultiplePermissionsState|EasyPermissions|NeedsPermission)\b"
)
_FLAG_TOKEN = re.compile(r"(?:PendingIntent\s*\.\s*)?(FLAG_[A-Z_]+)")
_PENDING_FLAGS = frozenset(
    """FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT FLAG_CANCEL_CURRENT FLAG_IMMUTABLE FLAG_MUTABLE
    FLAG_NO_CREATE FLAG_ONE_SHOT FLAG_UPDATE_CURRENT""".split()
)
_IMPLICIT_INTENT = re.compile(
    r'(?:new\s+)?Intent\s*\(\s*(?:"[^"$\\\n]*"|Intent\s*\.\s*ACTION_\w+)?\s*\)'
)
_FILTER_START = re.compile(r"(?:new\s+)?IntentFilter\s*\(")
_ACTION_CALL = re.compile(r"(?<![\w$])addAction\s*\(")
_LITERAL = re.compile(r'\s*"([^"$\\\n]*)"\s*')
_SYSTEM_CONSTANT = re.compile(r"\s*(?:android\s*\.\s*content\s*\.\s*)?Intent\s*\.\s*ACTION_\w+\s*")


@dataclass(frozen=True)
class PendingCall:
    path: str
    line: int
    column: int
    kind: str  # getActivity, getBroadcast ...
    flags: str  # the flags argument as written, whitespace collapsed
    mutability: str | None  # "immutable" | "mutable" | None (neither flag is present)
    flags_readable: bool  # every flag is a PendingIntent constant or 0
    allows_unsafe_implicit: bool  # FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT
    no_create: bool  # FLAG_NO_CREATE: a lookup, not a creation
    implicit_intent: bool  # the Intent is written inline with at most an action: Intent("a")


@dataclass(frozen=True)
class ReceiverCall:
    path: str
    line: int
    column: int
    has_flags: bool  # the call passes the trailing flags argument (RECEIVER_EXPORTED...)
    custom_actions: tuple[str, ...]  # actions of the inline filter that are not system actions
    filter_readable: bool  # inline filter whose actions are all literals or Intent.ACTION_*


@dataclass(frozen=True)
class UrlUse:
    path: str
    line: int
    column: int
    url: str
    host: str


@dataclass(frozen=True)
class PermissionRef:
    path: str
    line: int
    name: str  # without the "android.permission." prefix, e.g. CAMERA


@dataclass
class SecurityFacts:
    pending: list[PendingCall] = field(default_factory=list)
    receivers: list[ReceiverCall] = field(default_factory=list)
    urls: list[UrlUse] = field(default_factory=list)
    permission_refs: list[PermissionRef] = field(default_factory=list)  # every mention in code
    requested_refs: list[PermissionRef] = field(default_factory=list)  # mentions in a file that
    # requests or checks run-time permissions

    @classmethod
    def build(cls, a: ProjectAnalysis) -> SecurityFacts:
        facts = cls()
        for path, source in sorted(a.sources.items()):
            if a.is_test_source(path):
                continue
            _scan_file(facts, path, source)
        return facts


def _arguments(source: SourceFile, open_index: int) -> list[str]:
    return [source.text[start:end] for start, end in split_args(source.masked, open_index)]


def _scan_file(facts: SecurityFacts, path: str, source: SourceFile) -> None:
    masked = source.masked
    if "PendingIntent" in masked:
        _scan_pending(facts, path, source)
    if "registerReceiver" in masked and "LocalBroadcastManager" not in masked:
        # LocalBroadcastManager.registerReceiver has the same two-argument shape but is in-process,
        # and the export flag does not exist for it: a file that uses it is not judged.
        _scan_receivers(facts, path, source)
    if "url" in masked or "Url" in masked or "URL" in masked:
        _scan_urls(facts, path, source)
    if "permission" in masked or "Permission" in masked or "android.permission" in source.text:
        _scan_permissions(facts, path, source)


# -- PendingIntent ------------------------------------------------------------------------------


def _flag_names(expression: str) -> tuple[list[str], bool]:
    """(PendingIntent flag names in a flags expression, whether the whole expression was readable).

    Readable means a ``|`` / ``or`` list of ``PendingIntent.FLAG_*`` constants and the number 0.
    """
    text = expression.strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    names: list[str] = []
    readable = True
    for token in re.split(r"\||\bor\b", text):
        token = token.strip()
        match = _FLAG_TOKEN.fullmatch(token)
        if match and match.group(1) in _PENDING_FLAGS:
            names.append(match.group(1))
        elif token != "0":
            readable = False
    return names, readable


def _scan_pending(facts: SecurityFacts, path: str, source: SourceFile) -> None:
    for match in _PENDING.finditer(source.masked):
        spans = split_args(source.masked, match.end() - 1)
        if len(spans) < 4:
            continue  # not the four-argument form (named or computed arguments are not read)
        args = [source.text[start:end] for start, end in spans]
        # the flags are code, never a string: read them from the comment-blanked text, so a comment
        # between the constants (``/* flags = */ A or B``) does not make them unreadable
        flags = source.masked[spans[3][0] : spans[3][1]]
        names, readable = _flag_names(flags)
        mutability = (
            "immutable"
            if "FLAG_IMMUTABLE" in names
            else "mutable"
            if "FLAG_MUTABLE" in names
            else None
        )
        facts.pending.append(
            PendingCall(
                path,
                source.line(match.start()),
                source.column(match.start()),
                match.group(1),
                re.sub(r"\s+", " ", flags.strip()),
                mutability,
                readable,
                "FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT" in names,
                "FLAG_NO_CREATE" in names,
                _IMPLICIT_INTENT.fullmatch(args[2].strip()) is not None,
            )
        )


# -- registerReceiver ---------------------------------------------------------------------------


def _filter_actions(text: str, masked: str) -> tuple[list[str], bool]:
    """(literal action strings, readable) of an inline ``IntentFilter(...)`` expression.

    ``masked`` is the same expression with strings and comments blanked: it is what brackets are
    matched on, while the action names are read from ``text``.
    """
    start = _FILTER_START.search(masked)
    if start is None or masked[: start.start()].strip():
        return [], False  # a variable, a field, a function call: not an inline filter
    actions: list[str] = []
    readable = True
    calls = [start.end() - 1, *(m.end() - 1 for m in _ACTION_CALL.finditer(masked))]
    for open_index in calls:
        spans = split_args(masked, open_index)
        first = text[spans[0][0] : spans[0][1]] if spans else ""
        literal = _LITERAL.fullmatch(first)
        if literal:
            actions.append(literal.group(1))
        elif _SYSTEM_CONSTANT.fullmatch(first):
            actions.append("android.intent.action.SYSTEM")
        elif first.strip() or open_index != start.end() - 1:
            readable = False  # a constant of our own, a variable: custom or system, we cannot say
    return actions, readable


def _scan_receivers(facts: SecurityFacts, path: str, source: SourceFile) -> None:
    for match in _REGISTER.finditer(source.masked):
        spans = split_args(source.masked, match.end() - 1)
        if len(spans) not in (2, 3, 4, 5):
            continue  # not one of the four shapes of Context.registerReceiver: a wrapper of ours
        # (receiver, filter) / (+ flags) / (+ permission, handler) / (+ permission, handler, flags);
        # the androidx ContextCompat helper has the context first, so its filter is not read here.
        filter_start, filter_end = spans[1]
        actions, readable = _filter_actions(
            source.text[filter_start:filter_end], source.masked[filter_start:filter_end]
        )
        facts.receivers.append(
            ReceiverCall(
                path,
                source.line(match.start()),
                source.column(match.start()),
                len(spans) in (3, 5),
                tuple(a for a in actions if not a.startswith("android.")),
                readable,
            )
        )


# -- plain HTTP URLs ----------------------------------------------------------------------------


def _scan_urls(facts: SecurityFacts, path: str, source: SourceFile) -> None:
    for match in _URL_CALL.finditer(source.masked):
        args = _arguments(source, match.end() - 1)
        if len(args) != 1:
            continue
        literal = re.fullmatch(r'\s*"(http://(\[[^\]"]+\]|[^/":?#$\\\s]+)[^"$\\\s]*)"\s*', args[0])
        if literal:
            facts.urls.append(
                UrlUse(
                    path,
                    source.line(match.start()),
                    source.column(match.start()),
                    literal.group(1),
                    literal.group(2).lower(),
                )
            )


# -- permission names ---------------------------------------------------------------------------


def _scan_permissions(facts: SecurityFacts, path: str, source: SourceFile) -> None:
    found: list[PermissionRef] = [
        PermissionRef(path, source.line(m.start()), m.group(1))
        for m in _PERMISSION_REF.finditer(source.masked)
    ]
    if "android.permission." in source.text:
        for literal in source.lexed.strings:
            if not literal.terminated:
                continue
            value = source.lexed.string_value(literal)
            match = _PERMISSION_STRING.fullmatch(value)
            if match:
                found.append(PermissionRef(path, source.line(literal.start), match.group(1)))
    facts.permission_refs.extend(found)
    if _PERMISSION_MACHINERY.search(source.masked):
        facts.requested_refs.extend(found)
