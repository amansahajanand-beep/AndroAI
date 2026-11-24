"""Text helpers shared by the extractors: bracket maps, argument splitting, masked excerpts.

Everything here works on the lexer-masked copy of a file (comments and string contents blanked,
same length and offsets as the original), so a bracket, comma or keyword inside a comment or a
string can never change what is found. Bracket matching is done once per file in a single pass:
no helper scans to the end of a file per call, so a file full of unclosed brackets cannot make the
analysis quadratic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlsplit

from androai_codegen.editing.redact import REDACTION_MARKER, find_secrets, mask_secrets
from androai_codegen.review.source import SourceFile

from .model import ATTR_ITEM_MAX, EXCERPT_MAX, Evidence

_BRACKET = re.compile(r"[()\[\]{}]")
_OPENERS = {")": "(", "]": "[", "}": "{"}
_WS = re.compile(r"\s+")
_XML_COMMENT = re.compile(r"<!--.*?-->")
MAX_LINE_FOR_EXCERPT = 600  # the excerpt is 80 characters; this is the masking window


def clip(text: str, limit: int) -> str:
    """Whitespace collapsed to single spaces, then cut to ``limit`` characters (ellipsis)."""
    text = _WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


_URL_USERINFO = re.compile(r"(?<=://)[^/\s@\"'<>]{1,200}@")
_SENSITIVE_QUERY = re.compile(
    r"([?&;][\w.\-]{0,40}(?:key|token|secret|pass(?:word|wd)?|pwd|auth|sig(?:nature)?"
    r"|credential|session)[\w.\-]{0,40}=)[^&\s\"'<>#]+",
    re.IGNORECASE,
)
# scheme://authority followed by the path (the part that stops at a query, fragment or quote)
_URL_PATH = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]{1,20}://[^/\s\"'<>?#]*)(/[^\s\"'<>?#]*)")
# A Telegram bot token: ``<bot id>:<35 characters>``, where Telegram wants it in the path
# (``/bot123456789:AA.../getMe``). It has no keyword to recognise it by, so it is matched by shape.
_TELEGRAM_TOKEN = re.compile(r"(?<![\w.])(?:bot)?\d{6,12}:[A-Za-z0-9_-]{30,}(?![\w-])")
# Slack incoming-webhook and trigger paths: ``/services/T.../B.../<secret>``
_SLACK_PATH = re.compile(r"((?:^|/)(?:services|triggers)/)T[A-Z0-9]{6,}(?:/[A-Za-z0-9]+){1,3}")
# Discord webhooks: ``/webhooks/<id>/<token>`` (optionally followed by ``/slack`` or ``/github``)
_DISCORD_PATH = re.compile(r"((?:^|/)webhooks/)\d{15,}/[A-Za-z0-9._-]{10,}")

MIN_OPAQUE_SEGMENT = 12
MAX_ROUTE_SEGMENT = 200
_SEGMENT_CHARS = re.compile(r"[A-Za-z0-9._~+=%-]+")
# ``%20`` and ``%2F`` are separators like ``-``: ``android%20studio`` is two words, not one token.
_SEGMENT_SPLIT = re.compile(r"[._~+=-]|%[0-9A-Fa-f]{2}|%")
# What a human-chosen word looks like: ``users``, ``oauth2``, ``getNotes``, ``ApiV2``, ``42``, an
# all-capitals word (``SNAPSHOT``, ``RC1``) or the ``15T10`` of a time stamp.
_ROUTE_WORD = re.compile(
    r"(?:[A-Z]?[a-z]+\d{0,2})(?:[A-Z][a-z]+\d{0,2})*|[A-Z]{2,}\d{0,2}|\d{1,15}|\d{1,8}[A-Z]\d{1,8}"
)
# A name=value pair introduced by ``?``, ``&``, ``;`` or ``#``: a query, a matrix parameter or a
# fragment. The name may carry brackets (``s[]``, ``filter[id]``). The value is masked when it
# looks generated (see ``_mask_value``), whatever the parameter is called: ``?s=<32 hex digits>``
# is as much a secret as ``?token=...``.
_PARAM_VALUE = re.compile(r"([?&;#][\w.\-%\[\]]{1,40}=)([^&\s\"'<>#;?]{12,})")
# A query that is only a token, no ``name=``: ``https://host/path?<32 hex digits>``. Only after a
# ``?`` (not ``?.`` or ``?:``, which are Kotlin), never when an ``=`` follows (that is a name).
_BARE_QUERY = re.compile(r"(\?)([A-Za-z0-9+_~%-][A-Za-z0-9+_~.%/-]{11,})(?![A-Za-z0-9+_~.%/=-])")
# A run of characters a generated token is made of, ``/`` included (standard base64 has it).
_OPAQUE_RUN = re.compile(r"[A-Za-z0-9+_~.%/-]{12,}")
# What cuts a run into the pieces that are judged one by one: ``/``, or the same character
# percent-encoded (a whole path in a query value is usually written ``%2Fusers%2Fab12cd34``).
_SLASH = re.compile(r"(/|%2[Ff])")
# Punctuation that can follow an unquoted value: ``fetch(url?s=<token>)``, ``a=<token>,``.
_VALUE_TAIL = ")]},.:!"


def _opaque_segment(segment: str) -> bool:
    """Whether a URL path segment (or a value) looks like a generated token, not a chosen name.

    A segment is a *name* when every word in it (split at ``- _ . ~ + = %`` and at percent
    escapes) is a plain word, a camelCase run, an all-capitals word or a short number. Anything
    else that is long enough (12+ characters) - hex, base64, a UUID, a mix of digits and capitals -
    is treated as a credential or an opaque id. Short secrets (under 12 characters) look exactly
    like short names and are not recognised, and neither is a secret made only of capital letters.
    """
    if len(segment) < MIN_OPAQUE_SEGMENT or not _SEGMENT_CHARS.fullmatch(segment):
        return False
    if len(segment) > MAX_ROUTE_SEGMENT:
        return True
    return not all(_ROUTE_WORD.fullmatch(word) for word in _SEGMENT_SPLIT.split(segment) if word)


def _mask_if_opaque(value: str) -> str:
    return REDACTION_MARKER if _opaque_segment(value) else value


def _unusual_chars(piece: str) -> int:
    """How many characters of ``piece`` are in words that are not plain words (0: it is a name)."""
    return sum(
        len(word)
        for word in _SEGMENT_SPLIT.split(piece)
        if word and not _ROUTE_WORD.fullmatch(word)
    )


def _could_be_cut_base64(piece: str) -> bool:
    """A short piece that a ``/`` may have cut out of standard base64: not a name, and with a
    capital letter (the alphabet is mixed-case). ``u1234``, ``v8a``, ``ab12cd34`` and ``arm64-v8a``
    are ordinary short ids and version names; a random base64 piece of 6+ characters has a capital
    letter 9 times in 10."""
    return _unusual_chars(piece) > 0 and any(char.isupper() for char in piece)


def _mask_run(run: str) -> str:
    """One run of token characters (``/`` included), judged without letting ``/`` hide anything.

    Each piece between the slashes is judged on its own, by the rule that judges a URL path
    segment: a piece of 12+ characters with a word that is not plain is masked
    (``build/<hex>/out`` keeps ``build`` and ``out``). A short piece that looks unusual (``u1234``,
    ``v8a``, ``ab12cd34``) is not evidence of anything by itself and stays, and so does a path
    with several short ids that plain words keep apart (``users/ab12cd34/posts/ef56gh78``).

    Standard base64 contains ``/``, which can cut one token into pieces too short to be judged. So
    pieces that could be such cut-off parts (``_could_be_cut_base64``) are judged together with
    their neighbours: a group of them next to a piece that was masked (``<24 chars>/K7MDENG``) is
    one token; so is a group with ``MIN_OPAQUE_SEGMENT`` characters of unusual words between plain
    words or the ends of the run. A plain word, or a short piece without a capital letter, ends a
    group.
    """
    if not _opaque_segment(run.replace("/", "-")):
        return run
    parts = _SLASH.split(run)  # piece, separator, piece, ...: ``%2F`` cuts like ``/`` does
    pieces, ends = parts[0::2], [*parts[1::2], ""]  # ends[i]: the separator after pieces[i]
    shown = [_mask_if_opaque(piece) for piece in pieces]
    result: list[str] = []
    start = 0
    while start < len(pieces):
        end = start
        while end < len(pieces) and (
            shown[end] != pieces[end] or _could_be_cut_base64(pieces[end])
        ):
            end += 1
        if end == start:  # a name (or a short id): kept as written
            result.append(pieces[start] + ends[start])
            start += 1
            continue
        kept = [pieces[i] for i in range(start, end) if shown[i] == pieces[i]]
        masked_next_to_them = len(kept) < end - start
        unusual = sum(_unusual_chars(piece) for piece in kept)
        if kept and (masked_next_to_them or unusual >= MIN_OPAQUE_SEGMENT):
            result.append(REDACTION_MARKER + ends[end - 1])  # the group is one token
        else:
            result.extend(shown[i] + ends[i] for i in range(start, end))
        start = end
    return "".join(result)


def _mask_value(value: str) -> str:
    """A query, matrix or fragment value: each generated-looking token in it is masked and any
    punctuation that follows it is kept (``<token>)`` -> ``[REDACTED])``)."""
    core = value.rstrip(_VALUE_TAIL)
    return mask_opaque_runs(core) + value[len(core) :]


def _redact_segment(segment: str) -> str:
    """One path segment, with its matrix parameters (``name;key=value;key=value``) judged apart:
    the name and each value are masked when they look generated, the keys stay."""
    name, *params = segment.split(";")
    pieces = [_mask_if_opaque(name)]
    for param in params:
        key, equals, value = param.partition("=")
        pieces.append(f"{key}={_mask_if_opaque(value)}" if equals else _mask_if_opaque(param))
    return ";".join(pieces)


def redact_path(path: str) -> str:
    """A URL path with its credentials hidden and its readable structure kept.

    ``/bot123456789:AAHdqTcvCH1vpMEUsiL4V2MV0GGzoPLxcFk/getMe`` becomes ``/bot[REDACTED]/getMe``;
    ``/services/T0123ABCD/B0123ABCD/<24 characters>`` becomes ``/services/[REDACTED]``;
    ``/page;jsid=<32 hex digits>`` becomes ``/page;jsid=[REDACTED]``; every other opaque segment
    (see ``_opaque_segment``) becomes ``[REDACTED]`` and ordinary names such as
    ``/v1/users/{id}/notes`` are untouched.
    """
    path = _SLACK_PATH.sub(lambda m: m.group(1) + REDACTION_MARKER, path)
    path = _DISCORD_PATH.sub(lambda m: m.group(1) + REDACTION_MARKER, path)
    path = _TELEGRAM_TOKEN.sub(lambda m: _telegram_mask(m.group()), path)
    return "/".join(_redact_segment(segment) for segment in path.split("/"))


def _telegram_mask(token: str) -> str:
    return ("bot" if token.startswith("bot") else "") + REDACTION_MARKER


def mask_urls(text: str) -> str:
    """Hide the credentials a URL can carry: ``user:password@``, opaque path segments (a Telegram
    bot token, a Slack or Discord webhook secret, a generated id), and query, matrix and fragment
    values that are secret-looking by name (``token``, ``key``...) or generated-looking by shape.

    ``mask_secrets`` does not know these shapes, and a base URL with a key in its query string or
    its path is one of the most common places a credential ends up in source code.
    """
    text = _URL_USERINFO.sub(REDACTION_MARKER + "@", text)
    text = _URL_PATH.sub(lambda m: m.group(1) + redact_path(m.group(2)), text)
    text = _TELEGRAM_TOKEN.sub(lambda m: _telegram_mask(m.group()), text)
    text = _PARAM_VALUE.sub(lambda m: m.group(1) + _mask_value(m.group(2)), text)
    text = _BARE_QUERY.sub(lambda m: m.group(1) + _mask_value(m.group(2)), text)
    return _SENSITIVE_QUERY.sub(lambda m: m.group(1) + REDACTION_MARKER, text)


def mask_opaque_runs(text: str) -> str:
    """Replace each generated-looking token inside free text (hex, base64, a UUID, digits mixed
    with capitals...) with ``[REDACTED]``; the words and separators around it are kept, so
    ``user:<32 hex digits>`` becomes ``user:[REDACTED]``. A run may contain ``/`` (or ``%2F``),
    but it is not judged as one token: each piece between slashes is judged on its own, and pieces
    that a slash may have cut out of standard base64 are judged together only when there is
    evidence (see ``_mask_run``), so ``lib/arm64-v8a/libnative.so`` stays readable."""
    return _OPAQUE_RUN.sub(lambda m: _mask_run(m.group()), text)


def redact_text(text: str) -> str:
    """Every masking this package applies to text that came from a project file."""
    return mask_secrets(mask_urls(text))


_STRING_LITERAL = re.compile(r"\"((?:[^\"\\\n]|\\.){0,2000})\"|'((?:[^'\\\n]|\\.){0,2000})'")
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9+/_=~.\-]+")
LONG_STRING = 40
OPAQUE_STRING = 16


def hide_opaque_strings(text: str) -> str:
    """Replace the contents of long or token-like string literals with ``…``.

    An excerpt exists to show the *shape* of a declaration. A string that is long (it may be prose
    meant for a reader that is not a compiler) or that is a single unbroken run of letters, digits
    and ``+/_=-.`` (it may be a secret that no pattern recognises) is not part of that shape, so it
    is not echoed. Short, ordinary strings (``"SELECT * FROM notes"``, ``"home/{id}"``) stay.
    """

    def hide(match: re.Match[str]) -> str:
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        quote = match.group(0)[0]
        opaque = len(inner) >= OPAQUE_STRING and _TOKEN_CHARS.fullmatch(inner) is not None
        if len(inner) > LONG_STRING or opaque:
            return f"{quote}…{quote}"
        # A short string that is not one unbroken token can still hold a generated one next to a
        # label (``"user:<32 hex digits>"``, ``"hook?s=<32 hex digits>"``): mask just that part.
        masked = mask_opaque_runs(inner)
        return match.group(0) if masked == inner else f"{quote}{masked}{quote}"

    return _STRING_LITERAL.sub(hide, text)


def redact_excerpt(text: str) -> str:
    """Masking for evidence excerpts: everything ``redact_text`` does, and opaque strings go."""
    return hide_opaque_strings(redact_text(text))


def safe(text: str, limit: int = ATTR_ITEM_MAX) -> str:
    """Free text taken from a project file, with likely secrets masked, then clipped.

    Masking happens **before** clipping so that a cut can never leave a fragment of a secret.
    """
    return clip(redact_text(text[: limit * 8]), limit)


def safe_value(text: str, limit: int = ATTR_ITEM_MAX) -> str:
    """``safe`` for a *value* a project file sets (the content of a manifest ``meta-data``, say):
    generated-looking tokens inside it are masked too (``mask_opaque_runs``), before clipping.

    Not used for names and identifiers, which stay as written."""
    return clip(mask_opaque_runs(redact_text(text[: limit * 8])), limit)


def scrub(text: str) -> str:
    """Replace a recognisable credential (token formats, private keys) wherever it appears.

    Used as the last line of defence on every string that enters a report. Unlike ``safe`` it
    leaves ``key: value`` text alone, so a coordinate such as ``androidx.credentials:credentials``
    is not damaged.
    """
    text = mask_urls(text)
    spans = [m for m in find_secrets(text) if m.kind != "credential_assignment"]
    if not spans:
        return text
    pieces: list[str] = []
    last = 0
    for match in spans:
        pieces.append(text[last : match.start])
        pieces.append(REDACTION_MARKER)
        last = match.end
    pieces.append(text[last:])
    return "".join(pieces)


_AUTHORITY = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://[^/]*)(.*)", re.DOTALL)


def redact_url(url: str, limit: int = ATTR_ITEM_MAX) -> str:
    """A URL without credentials: user info and the query string are dropped, opaque path
    segments are masked (``redact_path``), the rest is kept.

    Query strings are where API keys usually travel (``?api_key=...``) and Telegram, Slack and
    Discord put theirs in the path. A value that is not a plain URL (a template, a placeholder, a
    relative endpoint path) gets the same treatment and is then clipped like any other free text.
    """
    text = url.strip()
    if "://" not in text or any(ch in text for ch in "${} \t\n"):
        return safe(_mask_target(_strip_query(text)), limit)
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return safe(_mask_target(_strip_query(text)), limit)
    return safe(f"{parts.scheme}://{host}{port}{redact_path(parts.path)}", limit)


def _mask_target(text: str) -> str:
    """``redact_path`` for a value that may or may not start with ``scheme://authority`` (the
    authority is a host, not a path, and is left to the ordinary masking)."""
    found = _AUTHORITY.fullmatch(text)
    if found:
        return found.group(1) + redact_path(found.group(2))
    return redact_path(text)


def _strip_query(text: str) -> str:
    return re.sub(r"//[^/@\s]*@", "//", text.split("?", 1)[0].split("#", 1)[0])


def split_spans(masked: str, start: int, end: int) -> list[tuple[int, int]]:
    """Offsets of the comma-separated items in ``masked[start:end]``, ignoring commas inside
    ``()``, ``[]``, ``{}`` and generic ``<>``. Empty items are dropped."""
    spans: list[tuple[int, int]] = []
    depth = generic = 0
    item = start
    for i in range(start, end):
        ch = masked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "<":
            before = masked[i - 1] if i > start else " "
            if before.isalnum() or before in "_?.":
                generic += 1
        elif ch == ">":
            before = masked[i - 1] if i > start else " "
            if generic and before not in "-=":
                generic -= 1
        elif ch == "," and depth == 0 and generic == 0:
            if masked[item:i].strip():
                spans.append((item, i))
            item = i + 1
    if masked[item:end].strip():
        spans.append((item, end))
    return spans


def strip_generics(text: str) -> str:
    """``Map<String, List<Int>>`` -> ``Map``; text without generics is returned unchanged."""
    out: list[str] = []
    depth = 0
    for index, ch in enumerate(text):
        if ch == "<":
            depth += 1
        elif ch == ">" and depth and text[index - 1] not in "-=":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def type_name(text: str) -> str:
    """The simple, generic-free, nullability-free name of a written type: ``a.b.List<X>?`` ->
    ``List``. Function types and anything unreadable give ``""``."""
    cleaned = strip_generics(text).strip().rstrip("?").strip()
    if not re.fullmatch(r"[A-Za-z_][\w.]*", cleaned):
        return ""
    return cleaned.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class LineText:
    """Original and masked text of one file, for building excerpts of a given line."""

    text: str
    masked: str

    @cached_property
    def _cache(self) -> dict[int, str]:
        return {}  # line start -> excerpt: many facts come from the same line

    @cached_property
    def _starts(self) -> list[int]:
        return [0] + [m.end() for m in re.finditer(r"\n", self.text)]

    def line_start(self, line: int) -> int | None:
        """Offset of the first character of a 1-based line, or ``None`` if there is no such line."""
        starts = self._starts
        return starts[line - 1] if 1 <= line <= len(starts) else None

    def excerpt_at_offset(self, offset: int) -> str:
        offset = max(0, min(offset, len(self.text)))
        start = self.text.rfind("\n", 0, offset) + 1
        end = self.text.find("\n", offset)
        end = len(self.text) if end < 0 else end
        return self._excerpt(start, end)

    def excerpt_at_line(self, line: int) -> str:
        starts = self._starts
        if not 1 <= line <= len(starts):
            return ""
        start = starts[line - 1]
        end = starts[line] - 1 if line < len(starts) else len(self.text)
        return self._excerpt(start, end)

    def _excerpt(self, start: int, end: int) -> str:
        cached = self._cache.get(start)
        if cached is not None:
            return cached
        excerpt = self._build_excerpt(start, end)
        self._cache[start] = excerpt
        return excerpt

    def _build_excerpt(self, start: int, end: int) -> str:
        end = min(end, start + MAX_LINE_FOR_EXCERPT)
        original = self.text[start:end]
        code = self.masked[start:end]
        if code.strip():  # keep the code part of the line: leading and trailing comments go
            left = len(code) - len(code.lstrip())
            right = len(code.rstrip())
            original = original[left:right]
        return clip(redact_excerpt(original), EXCERPT_MAX)


class SrcView:
    """A Kotlin or Java file with a precomputed bracket map."""

    def __init__(self, source: SourceFile) -> None:
        self.source = source
        self.path = source.path
        self.text = source.text
        self.masked = source.masked
        self.language = source.language
        self.lines = LineText(self.text, self.masked)

    @cached_property
    def close(self) -> dict[int, int]:
        """Offset of each opening ``( [ {`` -> offset of its closing bracket. A bracket without a
        partner is not in the map."""
        pairs: dict[int, int] = {}
        stack: list[tuple[str, int]] = []
        for match in _BRACKET.finditer(self.masked):
            ch = match.group()
            if ch in "([{":
                stack.append((ch, match.start()))
            elif stack and stack[-1][0] == _OPENERS[ch]:
                pairs[stack.pop()[1]] = match.start()
        return pairs

    @cached_property
    def balanced(self) -> bool:
        return not self.source.bracket_errors

    def line(self, offset: int) -> int:
        return self.source.line(offset)

    def evidence(self, offset: int) -> Evidence:
        return Evidence(
            path=self.path, line=self.line(offset), excerpt=self.lines.excerpt_at_offset(offset)
        )

    def skip_space(self, i: int, end: int | None = None) -> int:
        limit = len(self.masked) if end is None else end
        while i < limit and self.masked[i] in " \t\r\n":
            i += 1
        return i

    def group_end(self, open_index: int) -> int | None:
        """Offset just past the bracket group opened at ``open_index``, if it is closed."""
        close = self.close.get(open_index)
        return None if close is None else close + 1

    def skip_generic(self, i: int, limit: int = 400) -> int | None:
        """``i`` is at a ``<``: offset just past the matching ``>``, or ``None``. Gives up at a
        character that cannot occur inside a type argument list."""
        depth = 0
        end = min(len(self.masked), i + limit)
        for j in range(i, end):
            ch = self.masked[j]
            if ch == "<":
                depth += 1
            elif ch == ">" and self.masked[j - 1] not in "-=":
                depth -= 1
                if depth == 0:
                    return j + 1
            elif ch in ";{}=":
                return None
        return None


def xml_evidence(text: str | list[str], path: str, line: int | None) -> Evidence:
    """Evidence for a line of an XML file. Comments are removed from the excerpt.

    ``text`` may be the file already split into lines, which callers that ask for many lines of one
    file should do once (splitting a large file per call is quadratic).
    """
    excerpt = ""
    if line:
        lines = text if isinstance(text, list) else text.split("\n")
        if 1 <= line <= len(lines):
            raw = _XML_COMMENT.sub("", lines[line - 1][:MAX_LINE_FOR_EXCERPT])
            excerpt = clip(redact_excerpt(raw), EXCERPT_MAX)
    return Evidence(path=path, line=line if line and line >= 1 else None, excerpt=excerpt)
