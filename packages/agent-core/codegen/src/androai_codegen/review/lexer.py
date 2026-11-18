"""Comment/string-aware lexing for Kotlin, Java and Gradle (Groovy / Kotlin DSL) sources.

``lex`` returns a *masked* copy of the source: same length, same newlines, with comments and the
contents of string/char literals blanked out. Regexes run on the masked text cannot match inside
a comment or a string, and every offset maps 1:1 back to the original text.

Handled: line and block comments (nested in Kotlin), regular / raw / triple-quoted strings,
Kotlin and Groovy string templates (``${...}`` is lexed as code, recursively; ``$name`` stays
visible), char literals with escapes, Kotlin backtick identifiers, and Groovy single-quoted
strings. Unterminated constructs are reported, never raised.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Literal

Language = Literal["kotlin", "java", "groovy"]

MAX_TEMPLATE_NESTING = 32
MAX_BRACKET_ERRORS = 3

_BLANK = re.compile(r"[^\n]")
_CODE_STOP = {
    "kotlin": re.compile(r"[/\"'`{}]"),
    "java": re.compile(r"[/\"'{}]"),
    "groovy": re.compile(r"[/\"'{}]"),
}
_STR_DQ_TEMPLATE = re.compile(r"[\\\"\n$]")
_STR_DQ_PLAIN = re.compile(r"[\\\"\n]")
_STR_SQ = re.compile(r"[\\'\n]")
_RAW_KOTLIN = re.compile(r'"{3,}|\$')
_RAW_JAVA = re.compile(r'"{3,}|\\')
_RAW_GROOVY_DQ = re.compile(r'"{3,}|\$|\\')
_RAW_GROOVY_SQ = re.compile(r"'{3,}|\\")
_BRACKET = re.compile(r"[()\[\]{}]")
_BLOCK_COMMENT_TOKEN = re.compile(r"/\*|\*/")


@dataclass(frozen=True)
class LexError:
    kind: str  # unterminated_string | unterminated_comment | unterminated_char | nesting | ...
    offset: int
    related: int | None = None  # for a mismatched bracket: where the open bracket is


@dataclass(frozen=True)
class StringLit:
    start: int  # offset of the opening delimiter
    end: int  # offset just past the closing delimiter
    quote_len: int
    terminated: bool = True


@dataclass
class Lexed:
    source: str
    masked: str
    errors: list[LexError] = field(default_factory=list)
    strings: list[StringLit] = field(default_factory=list)
    _line_starts: list[int] = field(default_factory=list, repr=False)
    _by_start: dict[int, StringLit] = field(default_factory=dict, repr=False)

    def position(self, offset: int) -> tuple[int, int]:
        """1-based (line, column) of ``offset``."""
        index = bisect.bisect_right(self._line_starts, offset) - 1
        return index + 1, offset - self._line_starts[index] + 1

    def line(self, offset: int) -> int:
        return self.position(offset)[0]

    def string_value(self, literal: StringLit) -> str:
        """Original text between the delimiters of a literal."""
        end = literal.end - (literal.quote_len if literal.terminated else 0)
        return self.source[literal.start + literal.quote_len : end]

    def string_starting_at(self, offset: int) -> StringLit | None:
        return self._by_start.get(offset)


class _Lexer:
    def __init__(self, source: str, language: Language) -> None:
        self.src = source
        self.n = len(source)
        self.language = language
        self.pieces: list[str] = []
        self.last = 0
        self.errors: list[LexError] = []
        self.strings: list[StringLit] = []

    # -- output -------------------------------------------------------------------------

    def blank(self, start: int, end: int) -> None:
        """Mask ``[start, end)``. Calls must come in increasing order."""
        if end <= start:
            return
        self.pieces.append(self.src[self.last : start])
        self.pieces.append(_BLANK.sub(" ", self.src[start:end]))
        self.last = end

    def run(self) -> Lexed:
        self.scan_code(0, 0, in_template=False)
        self.pieces.append(self.src[self.last :])
        masked = "".join(self.pieces)
        line_starts = [0] + [m.end() for m in re.finditer(r"\n", self.src)]
        return Lexed(
            source=self.src,
            masked=masked,
            errors=self.errors,
            strings=self.strings,
            _line_starts=line_starts,
            _by_start={s.start: s for s in self.strings},
        )

    # -- scanning -----------------------------------------------------------------------

    def scan_code(self, i: int, nest: int, *, in_template: bool) -> int:
        """Scan code from ``i``. In a template, return the index of its closing ``}``."""
        src, n = self.src, self.n
        stop = _CODE_STOP[self.language]
        braces = 0
        while i < n:
            match = stop.search(src, i)
            if match is None:
                return n
            i = match.start()
            ch = src[i]
            if ch == "/":
                following = src[i + 1 : i + 2]
                if following == "/":
                    j = src.find("\n", i)
                    j = n if j < 0 else j
                    self.blank(i, j)
                    i = j
                elif following == "*":
                    i = self.block_comment(i)
                else:
                    i += 1
            elif ch == '"':
                triple = src.startswith('"""', i)
                i = self.raw_string(i, nest) if triple else self.string(i, nest)
            elif ch == "'":
                if self.language == "groovy":
                    i = (
                        self.raw_string(i, nest)
                        if src.startswith("'''", i)
                        else self.string(i, nest)
                    )
                else:
                    i = self.char_literal(i)
            elif ch == "`":
                end = src.find("`", i + 1)
                newline = src.find("\n", i + 1)
                if end == -1 or (newline != -1 and newline < end):
                    i += 1  # stray backtick
                else:
                    i = end + 1  # Kotlin backtick identifier: may contain spaces and quotes
            elif ch == "{":
                braces += 1
                i += 1
            else:  # "}"
                if in_template and braces == 0:
                    return i
                braces = max(0, braces - 1)
                i += 1
        return n

    def block_comment(self, i: int) -> int:
        src = self.src
        if self.language == "kotlin":  # Kotlin block comments nest
            depth, j = 1, i + 2
            while depth:
                token = _BLOCK_COMMENT_TOKEN.search(src, j)
                if token is None:
                    self.errors.append(LexError("unterminated_comment", i))
                    self.blank(i, self.n)
                    return self.n
                depth += 1 if token.group() == "/*" else -1
                j = token.end()
            self.blank(i, j)
            return j
        end = src.find("*/", i + 2)
        if end == -1:
            self.errors.append(LexError("unterminated_comment", i))
            self.blank(i, self.n)
            return self.n
        self.blank(i, end + 2)
        return end + 2

    def _templates(self, quote: str) -> bool:
        if self.language == "kotlin":
            return True
        return self.language == "groovy" and quote == '"'

    def string(self, i: int, nest: int) -> int:
        """Regular single-line string starting at the quote at ``i``."""
        src, n = self.src, self.n
        quote = src[i]
        templates = self._templates(quote)
        double_quote_stop = _STR_DQ_TEMPLATE if templates else _STR_DQ_PLAIN
        stop = _STR_SQ if quote == "'" else double_quote_stop
        text_start = j = i + 1
        while True:
            match = stop.search(src, j)
            if match is None:
                self.errors.append(LexError("unterminated_string", i))
                self.blank(text_start, n)
                self.strings.append(StringLit(i, n, 1, terminated=False))
                return n
            k = match.start()
            ch = src[k]
            if ch == "\\":
                j = k + 2
            elif ch == quote:
                self.blank(text_start, k)
                self.strings.append(StringLit(i, k + 1, 1))
                return k + 1
            elif ch == "\n":
                self.errors.append(LexError("unterminated_string", i))
                self.blank(text_start, k)
                self.strings.append(StringLit(i, k, 1, terminated=False))
                return k
            else:  # "$"
                text_start, j, failed = self._template(k, text_start, nest)
                if failed:
                    return self.n

    def raw_string(self, i: int, nest: int) -> int:
        """Triple-quoted string (Kotlin raw, Java text block, Groovy)."""
        src, n = self.src, self.n
        quote = src[i]
        if quote == "'":
            stop = _RAW_GROOVY_SQ
        elif self.language == "kotlin":
            stop = _RAW_KOTLIN
        elif self.language == "java":
            stop = _RAW_JAVA
        else:
            stop = _RAW_GROOVY_DQ
        text_start = j = i + 3
        while True:
            match = stop.search(src, j)
            if match is None:
                self.errors.append(LexError("unterminated_string", i))
                self.blank(text_start, n)
                self.strings.append(StringLit(i, n, 3, terminated=False))
                return n
            k = match.start()
            ch = src[k]
            if ch == quote:  # a run of 3+ quotes: the last three close the string
                end = match.end()
                self.blank(text_start, end - 3)
                self.strings.append(StringLit(i, end, 3))
                return end
            if ch == "\\":
                j = k + 2
            else:  # "$"
                text_start, j, failed = self._template(k, text_start, nest)
                if failed:
                    return self.n

    def _template(self, k: int, text_start: int, nest: int) -> tuple[int, int, bool]:
        """Handle ``$`` at ``k`` inside a string. Returns (text_start, next index, failed)."""
        src, n = self.src, self.n
        following = src[k + 1 : k + 2]
        if following == "{":
            if nest >= MAX_TEMPLATE_NESTING:
                self.errors.append(LexError("nesting", k))
                return text_start, k + 1, False
            self.blank(text_start, k + 2)  # blank the text so far and the "${"
            end = self.scan_code(k + 2, nest + 1, in_template=True)
            if end >= n or src[end] != "}":
                self.errors.append(LexError("unterminated_string", k))
                return text_start, n, True
            self.blank(end, end + 1)
            return end + 1, end + 1, False
        if following.isalpha() or following == "_":
            self.blank(text_start, k + 1)  # blank the text and "$"; the identifier stays visible
            e = k + 1
            while e < n and (src[e].isalnum() or src[e] == "_"):
                e += 1
            return e, e, False
        return text_start, k + 1, False

    def char_literal(self, i: int) -> int:
        src = self.src
        j = i + 1
        if src[j : j + 1] == "\\":
            end = src.find("'", j + 2, j + 12)
        else:
            end = j + 1 if src[j + 1 : j + 2] == "'" else -1
        if end == -1 or "\n" in src[i:end]:
            self.errors.append(LexError("unterminated_char", i))
            return i + 1  # treat the apostrophe as stray and keep scanning
        self.blank(i + 1, end)
        return end + 1


def normalize_newlines(text: str) -> str:
    """CRLF and lone CR become LF. Every analysis works on the normalized text."""
    return text.replace("\r\n", "\n").replace("\r", "\n") if "\r" in text else text


def lex(source: str, language: Language) -> Lexed:
    return _Lexer(source, language).run()


def check_brackets(lexed: Lexed) -> list[LexError]:
    """Unbalanced or mismatched ``() [] {}`` in code (never inside strings or comments)."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    errors: list[LexError] = []
    for match in _BRACKET.finditer(lexed.masked):
        ch = match.group()
        if ch in "([{":
            stack.append((ch, match.start()))
            continue
        if not stack:
            errors.append(LexError("unexpected_close", match.start()))
        elif stack[-1][0] != pairs[ch]:
            errors.append(LexError("mismatched", match.start(), related=stack[-1][1]))
            return errors[:MAX_BRACKET_ERRORS]  # one mismatch cascades; stop at the first
        else:
            stack.pop()
        if len(errors) >= MAX_BRACKET_ERRORS:
            return errors
    errors.extend(LexError("unclosed", offset) for _, offset in stack)
    return errors[:MAX_BRACKET_ERRORS]
