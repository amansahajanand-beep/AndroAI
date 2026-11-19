"""Facts extracted from Kotlin and Java sources, computed on lexer-masked text.

Because the text is masked, nothing inside a comment or string literal can produce a fact.
This is lexical analysis, not a compiler: the results are accurate for ordinary declarations
and deliberately conservative elsewhere.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from functools import cached_property

from .lexer import Lexed, check_brackets, lex, normalize_newlines

_PACKAGE = re.compile(r"^[ \t]*package[ \t]+([A-Za-z_]\w*(?:\.\w+)*)", re.M)
_IMPORT = re.compile(
    r"^[ \t]*import[ \t]+(static[ \t]+)?([A-Za-z_]\w*(?:\.\w+)*)(\.\*)?"
    r"(?:[ \t]+as[ \t]+(\w+))?[ \t]*;?[ \t]*$"
)
_HEADER_LINE = re.compile(r"^[ \t]*(?:import|package)\b[^\n]*", re.M)
_KOTLIN_TYPE = re.compile(r"(?<![\w.:`@])(class|interface|object|typealias)[ \t]+([A-Za-z_]\w*)")
_JAVA_TYPE = re.compile(r"(?<![\w.:@])(class|interface|enum)\s+([A-Za-z_]\w*)")
_JAVA_RECORD = re.compile(r"(?<![\w.:@])(record)\s+([A-Za-z_]\w*)\s*[(<]")
_JAVA_ANNOTATION_TYPE = re.compile(r"@interface\s+([A-Za-z_]\w*)")
_FUN = re.compile(r"(?<![\w.:`@])fun[ \t]+(?!interface\b)")
_TOP_VAL = re.compile(
    r"^[ \t]*(?:(?:public|internal|private|const|lateinit|inline|override)[ \t]+)*"
    r"(?:val|var)[ \t]+(?:<[^>\n]*>[ \t]*)?(?:[\w.<>?]+\.)?([A-Za-z_]\w*)",
    re.M,
)
_CAP_NAME = re.compile(r"(?<![\w.$`])[A-Z]\w*")
_MODIFIER_LINE = re.compile(
    r"^[ \t]*(?:@[\w.]+(?::[\w.]+)?(?:\([^)\n]*\))?[ \t]*"
    r"|(?:public|private|internal|protected|inline|suspend|operator|infix|tailrec|external"
    r"|override|open|abstract|final|actual|expect|sealed|data|enum|annotation|inner|value"
    r"|const|lateinit)[ \t]+)*$"
)
_MODIFIERS = re.compile(
    r"\b(abstract|sealed|enum|annotation|data|open|inner|private|internal|value|interface)\b"
)
_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_BRACE = re.compile(r"[{}]")
_ANGLE_GROUP = re.compile(r"<[^<>]*>")
_PAREN_GROUP = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class ImportInfo:
    fqn: str  # for a wildcard import, the package
    wildcard: bool
    alias: str | None
    static: bool
    line: int

    @property
    def simple_name(self) -> str | None:
        if self.wildcard:
            return None
        return self.alias or self.fqn.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class TypeDecl:
    name: str
    kind: str  # class | interface | object | enum | record | annotation | typealias
    fqn: str
    line: int
    offset: int
    top_level: bool
    abstract: bool
    private: bool
    supertypes: tuple[str, ...]


@dataclass(frozen=True)
class FunDecl:
    name: str
    line: int
    offset: int
    top_level: bool
    composable: bool
    private: bool
    body: tuple[int, int] | None  # offsets of the body braces, if it has a block body


def matching_close(
    masked: str, open_index: int, opener: str = "{", closer: str = "}"
) -> int | None:
    """Index of the bracket closing the one at ``open_index`` (masked text), or ``None``."""
    pattern = re.compile(re.escape(opener) + "|" + re.escape(closer))
    depth = 0
    for match in pattern.finditer(masked, open_index):
        depth += 1 if match.group() == opener else -1
        if depth == 0:
            return match.start()
    return None


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside (), <> or []."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


_ENUM_CONSTANT = re.compile(r"\s*(?:@[\w.]+(?:\([^)]*\))?\s*)*([A-Za-z_]\w*)")


def _enum_constants(body: str) -> list[str]:
    """Names of the constants at the start of an enum body (up to the first top-level ``;``).

    Handles arguments (``Header(1)``) and constant bodies (``Response { ... }``).
    """
    segments: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(body):
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in ",;":
            segments.append(body[start:index])
            start = index + 1
            if ch == ";":
                break
    else:
        segments.append(body[start:])
    return [m.group(1) for s in segments if (m := _ENUM_CONSTANT.match(s))]


def _simple_type_name(text: str) -> str | None:
    text = re.sub(r"\s+by\s+.*$", "", text.strip(), flags=re.S)
    previous = None
    while previous != text:  # drop balanced (...) and <...> groups, innermost first
        previous = text
        text = _PAREN_GROUP.sub("", _ANGLE_GROUP.sub("", text))
    name = text.strip().rstrip("?").rsplit(".", 1)[-1].strip()
    return name if _IDENT.match(name) else None


class SourceFile:
    """One Kotlin (.kt) or Java (.java) file."""

    def __init__(self, path: str, text: str) -> None:
        self.path = path
        # Windows (CRLF) and old-Mac (CR) line endings become LF, so no pattern has to care.
        # Line numbers and columns are unchanged.
        self.text = normalize_newlines(text)
        self.language: str = "kotlin" if path.endswith(".kt") else "java"
        self.lexed: Lexed = lex(self.text, "kotlin" if self.language == "kotlin" else "java")
        self.masked = self.lexed.masked

    def line(self, offset: int) -> int:
        return self.lexed.line(offset)

    def column(self, offset: int) -> int:
        return self.lexed.position(offset)[1]

    @cached_property
    def bracket_errors(self):
        return check_brackets(self.lexed)

    # -- header -------------------------------------------------------------------------

    @cached_property
    def package(self) -> str:
        match = _PACKAGE.search(self.masked)
        return match.group(1) if match else ""

    @cached_property
    def imports(self) -> list[ImportInfo]:
        found: list[ImportInfo] = []
        for number, line in enumerate(self.masked.split("\n"), start=1):
            if len(line) > 400 or "import" not in line:
                continue
            match = _IMPORT.match(line)
            if match:
                found.append(
                    ImportInfo(
                        fqn=match.group(2),
                        wildcard=bool(match.group(3)),
                        alias=match.group(4),
                        static=bool(match.group(1)),
                        line=number,
                    )
                )
        return found

    @cached_property
    def code(self) -> str:
        """Masked text with the package/import lines blanked (names there are not 'uses')."""
        return _HEADER_LINE.sub(lambda m: " " * len(m.group()), self.masked)

    # -- structure ----------------------------------------------------------------------

    @cached_property
    def _braces(self) -> tuple[list[int], list[int]]:
        positions: list[int] = []
        depths: list[int] = []
        depth = 0
        for match in _BRACE.finditer(self.masked):
            depth += 1 if match.group() == "{" else -1
            positions.append(match.start())
            depths.append(depth)
        return positions, depths

    def depth_at(self, offset: int) -> int:
        positions, depths = self._braces
        index = bisect.bisect_left(positions, offset)
        return max(0, depths[index - 1]) if index else 0

    def _preceding_modifiers(self, offset: int) -> str:
        """Annotations/modifiers directly before a declaration keyword at ``offset``."""
        window = self.masked[max(0, offset - 400) : offset]
        window = re.split(r"[;{}]", window)[-1]
        lines = window.split("\n")
        collected = [lines[-1]]
        for line in reversed(lines[:-1][-8:]):
            if line.strip() and _MODIFIER_LINE.match(line):
                collected.append(line)
            else:
                break
        return "\n".join(reversed(collected))

    @cached_property
    def types(self) -> list[TypeDecl]:
        matches: list[tuple[int, str, str]] = []  # (offset, kind keyword, name)
        if self.language == "kotlin":
            for m in _KOTLIN_TYPE.finditer(self.masked):
                matches.append((m.start(), m.group(1), m.group(2)))
        else:
            for m in _JAVA_TYPE.finditer(self.masked):
                matches.append((m.start(), m.group(1), m.group(2)))
            for m in _JAVA_RECORD.finditer(self.masked):
                matches.append((m.start(), "record", m.group(2)))
            for m in _JAVA_ANNOTATION_TYPE.finditer(self.masked):
                matches.append((m.start(), "annotation", m.group(1)))
        matches.sort()

        declared: list[TypeDecl] = []
        outer: str | None = None
        for offset, keyword, name in matches:
            modifiers = " ".join(_MODIFIERS.findall(self._preceding_modifiers(offset)))
            kind = keyword
            if keyword == "class" and "enum" in modifiers.split():
                kind = "enum"
            elif keyword == "class" and "annotation" in modifiers.split():
                kind = "annotation"
            top_level = self.depth_at(offset) == 0
            if top_level:
                outer = name
                fqn = f"{self.package}.{name}" if self.package else name
            else:
                base = f"{self.package}.{outer}" if self.package and outer else outer or ""
                fqn = f"{base}.{name}" if base else name
            declared.append(
                TypeDecl(
                    name=name,
                    kind=kind,
                    fqn=fqn,
                    line=self.line(offset),
                    offset=offset,
                    top_level=top_level,
                    abstract=bool({"abstract", "sealed"} & set(modifiers.split()))
                    or kind in ("interface", "annotation"),
                    private="private" in modifiers.split(),
                    supertypes=self._supertypes(offset, keyword, name),
                )
            )
        return declared

    def _header(self, start: int) -> str:
        """Text from ``start`` up to the declaration body (bounded and newline-aware)."""
        text = self.masked
        depth = 0
        limit = min(len(text), start + 700)
        i = start
        while i < limit:
            ch = text[i]
            if ch == "-" and text[i + 1 : i + 2] == ">":
                i += 2
                continue
            if ch in "(<[":
                depth += 1
            elif ch in ")>]":
                depth = max(0, depth - 1)
            elif depth == 0 and ch in "{;}":  # "}" ends a one-line body: { object A : B() }
                break
            elif depth == 0 and ch == "\n" and self.language == "kotlin":
                rest = text[i + 1 : i + 40].lstrip()
                if not rest.startswith((":", ",", "{", "where ", "by ")):
                    break
            i += 1
        return text[start:i]

    def _supertypes(self, offset: int, keyword: str, name: str) -> tuple[str, ...]:
        start = self.masked.find(name, offset) + len(name)
        header = self._header(start)
        names: list[str] = []
        if self.language == "kotlin":
            depth = 0
            colon = -1
            for i, ch in enumerate(header):
                if ch in "(<[":
                    depth += 1
                elif ch in ")>]":
                    depth = max(0, depth - 1)
                elif ch == ":" and depth == 0:
                    colon = i
                    break
            if colon == -1:
                return ()
            rest = re.split(r"\bwhere\b", header[colon + 1 :])[0]
            parts = _split_top_level(rest)
        else:
            parts = []
            for word in ("extends", "implements"):
                found = re.search(rf"\b{word}\b(.+?)(?=\bimplements\b|\bpermits\b|$)", header, re.S)
                if found:
                    parts.extend(_split_top_level(found.group(1)))
        for part in parts:
            simple = _simple_type_name(part)
            if simple:
                names.append(simple)
        return tuple(names)

    @cached_property
    def functions(self) -> list[FunDecl]:
        if self.language != "kotlin":
            return []
        found: list[FunDecl] = []
        text = self.masked
        for match in _FUN.finditer(text):
            parsed = self._parse_fun(match.end())
            if parsed is None:
                continue
            name, body = parsed
            modifiers = self._preceding_modifiers(match.start())
            found.append(
                FunDecl(
                    name=name,
                    line=self.line(match.start()),
                    offset=match.start(),
                    top_level=self.depth_at(match.start()) == 0,
                    composable="@Composable" in modifiers,
                    private="private" in modifiers.split(),
                    body=body,
                )
            )
        return found

    def _parse_fun(self, i: int) -> tuple[str, tuple[int, int] | None] | None:
        text = self.masked
        n = len(text)
        while i < n and text[i] in " \t":
            i += 1
        if text[i : i + 1] == "<":  # generics before the name
            close = matching_close(text, i, "<", ">")
            if close is None or close - i > 300:
                return None
            i = close + 1
        paren = text.find("(", i, i + 250)
        if paren == -1 or "\n" in text[i:paren]:
            return None
        token = text[i:paren].strip()
        while True:  # drop receiver generics, e.g. List<String>.foo
            reduced = _ANGLE_GROUP.sub("", token)
            if reduced == token:
                break
            token = reduced
        name = token.rsplit(".", 1)[-1].strip()
        if not _IDENT.match(name):
            return None
        close_paren = matching_close(text, paren, "(", ")")
        if close_paren is None:
            return name, None
        body = None
        j = close_paren + 1
        depth = 0
        limit = min(n, j + 300)
        while j < limit:
            ch = text[j]
            if ch in "(<[":
                depth += 1
            elif ch in ")>]":
                depth = max(0, depth - 1)
            elif depth == 0 and ch == "{":
                end = matching_close(text, j)
                body = (j, end) if end is not None else None
                break
            elif depth == 0 and ch == "=":
                break
            j += 1
        return name, body

    @cached_property
    def top_level_values(self) -> list[str]:
        """Names of top-level ``val``/``var`` declarations (Kotlin)."""
        if self.language != "kotlin":
            return []
        return [m.group(1) for m in _TOP_VAL.finditer(self.masked) if self.depth_at(m.start()) == 0]

    # -- usage --------------------------------------------------------------------------

    @cached_property
    def enum_entries(self) -> set[str]:
        """Names of enum constants declared in this file (declarations, not uses of a type)."""
        names: set[str] = set()
        for decl in self.types:
            if decl.kind != "enum":
                continue
            open_index = self.masked.find("{", decl.offset)
            if open_index < 0:
                continue
            close = matching_close(self.masked, open_index)
            names.update(_enum_constants(self.masked[open_index + 1 : close]))
        return names

    @cached_property
    def used_names(self) -> dict[str, int]:
        """Capitalized identifiers used as names, with the offset of the first use.

        Skipped: qualified members (``a.Name``), constants (ALL_CAPS), 1-2 letter generics, and
        Kotlin labels (``return@Name``, ``this@Name``).
        """
        found: dict[str, int] = {}
        code = self.code
        for match in _CAP_NAME.finditer(code):
            name = match.group()
            if len(name) <= 2 or name.isupper() or name in found:
                continue
            start = match.start()
            if (
                start > 0
                and code[start - 1] == "@"
                and start > 1
                and (code[start - 2].isalnum() or code[start - 2] in "_)")
            ):
                continue  # a label such as this@MainActivity
            found[name] = start
        return found

    @cached_property
    def class_literals(self) -> list[tuple[str, int]]:
        """``Name::class`` (Kotlin) or ``Name.class`` (Java) references, unqualified only."""
        if self.language == "kotlin":
            pattern = re.compile(r"(?<![\w.$`])([A-Z]\w*)[ \t]*::[ \t]*class\b")
        else:
            pattern = re.compile(r"(?<![\w.$])([A-Z]\w*)\.class\b")
        return [(m.group(1), m.start(1)) for m in pattern.finditer(self.code)]
