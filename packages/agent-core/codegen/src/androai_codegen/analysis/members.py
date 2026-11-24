"""Types and their members, read from Kotlin and Java sources without a compiler.

Types come from the review engine's lexer-based scan (``SourceFile.types``). This module adds what
that scan does not give: each type's body, primary constructor, supertypes as written, annotations,
and its members (functions, properties, fields, constructors, enum entries), plus the Kotlin
top-level declarations of a file.

It is deliberately conservative:

* Only declarations at the **top level of a body** are members; anything inside a function body,
  a lambda or an initializer is skipped (those are never class members).
* A type declared inside a function body is *local* and is not reported.
* A header that cannot be read (an unbalanced bracket, a generic that never closes) produces a type
  with ``exact=False`` and no members. It is never silently treated as empty.
* Backtick-quoted names (``fun `does a thing`()``) are skipped: they are test names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from androai_codegen.review.source import SourceFile, TypeDecl

from .annotations import (
    _ANNOTATION,
    _MODIFIERS,
    Annotation,
    AnnotationIndex,
    declaration_anchor,
    extract_annotations,
)
from .config import AnalysisConfig
from .text import SrcView, clip, split_spans, strip_generics, type_name

_IDENT = re.compile(r"[A-Za-z_]\w*")
_VISIBILITY = ("public", "private", "protected", "internal")
_KT_KEYWORDS = re.compile(
    r"(?<![\w.:`@$])(?:fun|val|var|constructor|class|object|interface|typealias|companion)\b|[(\[{]"
)
_KT_PARAM = re.compile(
    r"^\s*(?:(?:private|public|protected|internal|override|vararg|noinline|crossinline|final)\s+)*"
    r"(?:(val|var)\s+)?([A-Za-z_]\w*)\s*:\s*(.*)$",
    re.DOTALL,
)
_JAVA_MODS = frozenset("public private protected static final abstract synchronized native".split())
_CALL = re.compile(r"\s*([A-Za-z_][\w.]*)\s*(?:<([^<>\n]{0,120}(?:<[^<>\n]*>[^<>\n]*)*)>)?\s*[({]")
_JAVA_TYPE_WORD = re.compile(r"\b(class|interface|enum|record)\b\s+[A-Za-z_]")
TYPE_TEXT_LIMIT = 160


@dataclass(frozen=True)
class SuperRef:
    written: str  # ``Fragment``, ``androidx.fragment.app.Fragment``, ``RecyclerView.Adapter``
    simple: str


@dataclass(frozen=True)
class Param:
    name: str
    type_text: str
    kind: str | None  # ``val`` / ``var`` for a Kotlin property parameter
    annotations: tuple[Annotation, ...]
    vararg: bool = False
    default_call: str | None = None  # first call of the default value: ``hiltViewModel``
    default_generic: str | None = None  # its type argument: ``viewModel<Home>()``

    @property
    def type_simple(self) -> str:
        return type_name(self.type_text.removesuffix("..."))

    @property
    def signature_type(self) -> str:
        """The type as it appears in a member's signature: its simple name, or for a function
        type (which has none) its text without spaces."""
        return self.type_simple or re.sub(r"\s+", "", self.type_text)[:40] or "?"


@dataclass(frozen=True)
class Member:
    kind: str  # function | property | field | constructor | enum_entry
    name: str
    owner: str
    line: int
    offset: int
    visibility: str
    modifiers: tuple[str, ...]
    annotations: tuple[Annotation, ...]
    type_text: str = ""  # return type of a function, declared type of a property or field
    params: tuple[Param, ...] = ()
    body: tuple[int, int] | None = None  # braces of a block body
    companion: bool = False
    delegated: bool = False  # ``val x by ...``
    init_name: str | None = None  # first call of the initializer / delegate: ``hiltViewModel``
    init_generic: str | None = None  # its type argument: ``hiltViewModel<HomeViewModel>()``

    @property
    def signature(self) -> str:
        if self.kind in ("function", "constructor"):
            return f"{self.name}({','.join(p.signature_type for p in self.params)})"
        return self.name


@dataclass(frozen=True)
class TypeInfo:
    fqn: str
    name: str
    kind: str  # class | interface | object | enum | record | annotation | typealias
    path: str
    line: int
    offset: int
    package: str
    owner: str | None  # fqn of the enclosing type
    visibility: str
    modifiers: tuple[str, ...]
    supertypes: tuple[SuperRef, ...]
    annotations: tuple[Annotation, ...]
    members: tuple[Member, ...]
    body: tuple[int, int] | None
    constructor_params: tuple[Param, ...] = ()
    constructor_annotations: tuple[Annotation, ...] = ()
    entries: tuple[str, ...] = ()
    exact: bool = True
    truncated: bool = False  # members beyond ``max_members_per_type`` exist and are not listed

    @property
    def is_abstract(self) -> bool:
        return "abstract" in self.modifiers or self.kind in ("interface", "annotation")


@dataclass
class FileInfo:
    view: SrcView
    package: str
    annotations: AnnotationIndex
    types: list[TypeInfo] = field(default_factory=list)
    top_level: list[Member] = field(default_factory=list)
    top_level_truncated: bool = False  # more top-level members exist than ``top_level`` holds
    file_annotations: tuple[Annotation, ...] = ()
    issues: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.view.path

    @property
    def source(self) -> SourceFile:
        return self.view.source

    def function_at(self, offset: int) -> Member | None:
        """The innermost function (top level or member) whose block body contains ``offset``."""
        best: Member | None = None
        members = [*self.top_level]
        for info in self.types:
            members.extend(info.members)
        for member in members:
            inside = (
                member.kind == "function"
                and member.body
                and member.offset <= offset < member.body[1]
            )
            if inside and (best is None or member.offset > best.offset):
                best = member
        return best

    def type_at(self, offset: int) -> TypeInfo | None:
        """The innermost type whose body contains ``offset``."""
        best: TypeInfo | None = None
        for info in self.types:
            inside = info.body and info.body[0] < offset < info.body[1]
            if inside and (best is None or info.body[0] > (best.body or (0, 0))[0]):  # type: ignore[index]
                best = info
        return best


# -- modifiers ---------------------------------------------------------------------------------


def modifiers_before(view: SrcView, aindex: AnnotationIndex, anchor: int) -> tuple[str, ...]:
    """Modifier words written between the previous declaration and ``anchor``."""
    found: list[str] = []
    pos = anchor
    masked = view.masked
    for _ in range(24):
        while pos > 0 and masked[pos - 1] in " \t\r\n":
            pos -= 1
        annotation = aindex.ending_at(pos)
        if annotation is not None:
            pos = annotation.offset
            continue
        match = re.search(r"([A-Za-z_]\w*)$", masked[max(0, pos - 24) : pos])
        if not match or match.group(1) not in _MODIFIERS:
            break
        found.append(match.group(1))
        pos -= len(match.group(1))
    return tuple(reversed(found))


def visibility_of(modifiers: tuple[str, ...], *, java: bool) -> str:
    for word in _VISIBILITY:
        if word in modifiers:
            return word
    return "package" if java else "public"


# -- type headers ------------------------------------------------------------------------------


@dataclass
class _Header:
    name_end: int
    body: tuple[int, int] | None
    header_end: int
    ctor: tuple[int, int] | None = None
    ctor_keyword: int | None = None
    colon: int | None = None
    where: int | None = None  # a Kotlin ``where T : Bound`` clause: its colons are not supertypes
    exact: bool = True


def _flat(view: SrcView, start: int, end: int) -> str:
    """``masked[start:end]`` with every ``<...>`` group blanked, so generics hide their commas
    and keywords. Same length as the slice."""
    out: list[str] = []
    depth = 0
    masked = view.masked
    for i in range(start, end):
        ch = masked[i]
        if ch == "<":
            depth += 1
            out.append(" ")
        elif ch == ">" and depth and masked[i - 1] not in "-=":
            depth -= 1
            out.append(" ")
        else:
            out.append(" " if depth else ch)
    return "".join(out)


def _scan_header(view: SrcView, decl: TypeDecl) -> _Header:
    m = view.masked
    n = len(m)
    java = view.language == "java"
    i = max(m.find(decl.name, decl.offset), decl.offset) + len(decl.name)
    header = _Header(name_end=i, body=None, header_end=i)
    if decl.kind == "typealias":
        end = m.find("\n", i)
        header.header_end = n if end < 0 else end
        return header
    limit = min(n, i + 4000)
    last_significant = ""
    while i < limit:
        ch = m[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch == "\n":
            if java:
                i += 1
                continue
            rest = m[i + 1 : i + 80].lstrip()
            # (a tuple, not ``in ",:"``: the empty string is "in" every string, which made a body-
            # less ``class A`` swallow the lines after it)
            if last_significant in (",", ":") or rest.startswith(
                (":", ",", "{", "where ", "by ", "(", "@", "constructor", "<")
            ):
                i += 1
                continue
            header.header_end = i
            return header
        if ch == "<":
            end = view.skip_generic(i)
            if end is None:
                header.exact = False
                header.header_end = i
                return header
            i = end
            last_significant = ">"
            continue
        if ch == "(":
            end = view.group_end(i)
            if end is None:
                header.exact = False
                header.header_end = i
                return header
            if header.ctor is None and header.colon is None and not java:
                header.ctor = (i, end - 1)
            i = end
            last_significant = ")"
            continue
        if ch == "@":
            match = _ANNOTATION.match(m, i)
            if match is None:
                i += 1
                continue
            j = match.end()
            while j < n and m[j] in " \t":
                j += 1
            if j < n and m[j] == "(":
                end = view.group_end(j)
                if end is None:
                    header.exact = False
                    header.header_end = i
                    return header
                j = end
            i = j
            continue
        if ch == "{":
            close = view.close.get(i)
            header.header_end = i
            header.body = (i, close) if close is not None else None
            header.exact = close is not None
            return header
        if ch == ";":
            header.header_end = i
            return header
        if (
            ch == ":"
            and header.colon is None
            and header.where is None
            and not java
            and m[i : i + 2] != "::"
        ):
            header.colon = i
            last_significant = ":"
            i += 1
            continue
        word = _IDENT.match(m, i)
        if word:
            if word.group() == "constructor" and not java:
                header.ctor_keyword = i
            elif word.group() == "where" and not java and header.where is None:
                header.where = i
            last_significant = word.group()[-1]
            i = word.end()
            continue
        last_significant = ch
        i += 1
    header.header_end = min(i, n)
    return header


def _supertypes(view: SrcView, header: _Header) -> tuple[SuperRef, ...]:
    java = view.language == "java"
    if java:
        flat = _flat(view, header.name_end, header.header_end)
        parts: list[tuple[int, int]] = []
        for keyword in re.finditer(r"\b(extends|implements)\b", flat):
            nxt = re.search(r"\b(extends|implements|permits)\b", flat[keyword.end() :])
            end = keyword.end() + nxt.start() if nxt else len(flat)
            parts.extend(split_spans(flat, keyword.end(), end))
        texts = [flat[s:e] for s, e in parts]
    else:
        if header.colon is None:
            return ()
        flat = _flat(view, header.colon + 1, header.header_end)
        flat = re.split(r"\bwhere\b", flat)[0]
        texts = [flat[s:e] for s, e in split_spans(flat, 0, len(flat))]
    refs: list[SuperRef] = []
    for text in texts:
        text = re.split(r"\bby\b", text)[0]
        text = text.split("(", 1)[0].strip().rstrip("?").strip()
        if re.fullmatch(r"[A-Za-z_][\w.]*", text):
            refs.append(SuperRef(text, text.rsplit(".", 1)[-1]))
    return tuple(refs)


# -- parameters --------------------------------------------------------------------------------


def _top_level_equals(masked: str) -> int:
    """Offset of the ``=`` that starts a default value (not ``==``, ``<=``, ``>=``, ``!=``)."""
    depth = 0
    for i, ch in enumerate(masked):
        before = masked[i - 1] if i else " "
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0 and masked[i + 1 : i + 2] != "=" and before not in "=!<>":
            return i
    return -1


def _leading_annotations(
    view: SrcView, aindex: AnnotationIndex, start: int, end: int
) -> tuple[tuple[Annotation, ...], int]:
    """The annotations written at the very start of a parameter, and where its text resumes.
    An annotation inside the parameter's *type* (``content: @Composable () -> Unit``) is not one."""
    found: list[Annotation] = []
    pos = view.skip_space(start, end)
    while pos < end and view.masked[pos] == "@":
        annotation = aindex.starting_at(pos)
        if annotation is None:
            break
        found.append(annotation)
        pos = view.skip_space(annotation.end, end)
    return tuple(found), pos


def _kotlin_params(
    view: SrcView, aindex: AnnotationIndex, open_i: int, close_i: int
) -> tuple[Param, ...]:
    params: list[Param] = []
    for start, end in split_spans(view.masked, open_i + 1, close_i):
        annotations, begin = _leading_annotations(view, aindex, start, end)
        match = _KT_PARAM.match(view.masked[begin:end])
        if not match:
            continue
        rest = match.group(3)
        equals = _top_level_equals(rest)
        type_text = rest[:equals] if equals >= 0 else rest
        default_call = default_generic = None
        if equals >= 0:
            default_call, default_generic = _initializer(view, begin + match.start(3) + equals + 1)
        params.append(
            Param(
                name=match.group(2),
                type_text=clip(type_text, TYPE_TEXT_LIMIT),
                kind=match.group(1),
                annotations=annotations,
                vararg="vararg" in view.masked[begin : begin + match.start(2)],
                default_call=default_call,
                default_generic=default_generic,
            )
        )
    return tuple(params)


def _java_params(
    view: SrcView, aindex: AnnotationIndex, open_i: int, close_i: int
) -> tuple[Param, ...]:
    params: list[Param] = []
    for start, end in split_spans(view.masked, open_i + 1, close_i):
        annotations, begin = _leading_annotations(view, aindex, start, end)
        text = view.masked[begin:end].strip()
        text = re.sub(r"\bfinal\b", " ", text)
        match = re.match(r"(.+?)\s*(\.\.\.)?\s*([A-Za-z_]\w*)\s*(\[\s*\])*$", text, re.DOTALL)
        if not match:
            continue
        params.append(
            Param(
                name=match.group(3),
                type_text=clip(match.group(1) + (match.group(2) or ""), TYPE_TEXT_LIMIT),
                kind=None,
                annotations=annotations,
                vararg=bool(match.group(2)),
            )
        )
    return tuple(params)


# -- Kotlin members ----------------------------------------------------------------------------


def _read_type(view: SrcView, i: int, stop_at_by: bool = True) -> int:
    """End offset of a type written at ``i`` (Kotlin): up to ``{``, ``=``, ``;``, a newline, a
    closing bracket that belongs to something around it (``{ fun f(): T }``), or ``by``/``where``,
    jumping bracket groups and generic arguments."""
    m = view.masked
    n = len(m)
    limit = min(n, i + 600)
    while i < limit:
        ch = m[i]
        if ch in "([":
            end = view.group_end(i)
            if end is None:
                return i
            i = end
            continue
        if ch == "<":
            end = view.skip_generic(i)
            if end is None:
                return i
            i = end
            continue
        if ch in "{;\n)]}":  # a closer seen here was not opened inside the type
            return i
        if ch == "=" and m[i + 1 : i + 2] != "=":
            return i
        word = _IDENT.match(m, i)
        if word:
            if word.group() == "where" or (stop_at_by and word.group() == "by"):
                return i
            i = word.end()
            continue
        i += 1
    return min(i, n)


def _initializer(view: SrcView, i: int) -> tuple[str | None, str | None]:
    """First call written at ``i`` (after ``=`` or ``by``): its name and type argument."""
    match = _CALL.match(view.masked, i, min(len(view.masked), i + 200))
    if not match:
        return None, None
    generic = match.group(2)
    return match.group(1), clip(generic, 80) if generic else None


@dataclass
class _Ctx:
    view: SrcView
    aindex: AnnotationIndex
    config: AnalysisConfig
    headers: dict[int, _Header]  # type keyword offset -> header
    companion_types: set[int]  # offsets of ``object`` keywords that are companions


@dataclass
class _Members:
    """The members found in one scope (a type, or the top level of a file), up to the limit.

    ``overflow`` is true only when a member *beyond* the limit really exists: the scan goes on
    until it finds one, so a scope with exactly ``cap`` members is not reported as truncated and
    the work stays bounded at ``cap + 1`` members.
    """

    cap: int
    items: list[Member] = field(default_factory=list)
    overflow: bool = False

    def add(self, member: Member) -> None:
        if len(self.items) >= self.cap:
            self.overflow = True
        else:
            self.items.append(member)


def _kotlin_scan(
    ctx: _Ctx,
    start: int,
    end: int,
    owner: str,
    out: _Members,
    *,
    companion: bool = False,
) -> None:
    view, aindex = ctx.view, ctx.aindex
    m = view.masked
    pos = start
    while pos < end and not out.overflow:
        hit = _KT_KEYWORDS.search(m, pos, end)
        if hit is None:
            break
        word = hit.group()
        if word in "([{":
            close = view.close.get(hit.start())
            if close is None:
                break  # an unbalanced bracket: nothing after it can be trusted
            pos = close + 1
            continue
        at = hit.start()
        if word in ("class", "object", "interface", "typealias"):
            header = ctx.headers.get(at)
            pos = header.header_end if header else hit.end()
            continue
        if word == "companion":
            nxt = view.skip_space(hit.end(), end)
            if m.startswith("object", nxt):
                after_object = nxt + len("object")
                brace = m.find("{", after_object, min(end, after_object + 300))
                close = view.close.get(brace) if brace >= 0 else None
                body = (brace, close) if close is not None else None
                if body is not None:
                    _kotlin_scan(ctx, body[0] + 1, body[1], owner, out, companion=True)
                    pos = body[1] + 1
                    continue
            pos = hit.end()
            continue
        modifiers = modifiers_before(view, aindex, at)
        annotations = aindex.at(at)
        if word == "fun":
            member = _kotlin_function(ctx, at, hit.end(), owner, modifiers, annotations, companion)
        elif word in ("val", "var"):
            member = _kotlin_property(
                ctx, at, hit.end(), owner, modifiers, annotations, word, companion
            )
        else:  # constructor
            member = _kotlin_constructor(ctx, at, hit.end(), owner, modifiers, annotations)
        if member is not None:
            out.add(member)
        pos = hit.end()


def _kotlin_function(
    ctx: _Ctx,
    at: int,
    after: int,
    owner: str,
    modifiers: tuple[str, ...],
    annotations: tuple[Annotation, ...],
    companion: bool,
) -> Member | None:
    view = ctx.view
    m = view.masked
    i = view.skip_space(after)
    if m.startswith("interface", i):
        return None  # ``fun interface``: a type
    if m[i : i + 1] == "<":
        end = view.skip_generic(i)
        if end is None:
            return None
        i = end
    paren = m.find("(", i, i + 250)
    if paren < 0 or "\n" in m[i:paren]:
        return None
    token = strip_generics(m[i:paren]).strip()
    name = token.rsplit(".", 1)[-1].strip()
    if not _IDENT.fullmatch(name):
        return None
    close = view.close.get(paren)
    if close is None:
        return None
    params = _kotlin_params(ctx.view, ctx.aindex, paren, close)
    j = view.skip_space(close + 1, min(len(m), close + 4))
    type_text = ""
    if m[j : j + 1] == ":":
        type_end = _read_type(view, j + 1)
        type_text = clip(view.text[j + 1 : type_end], TYPE_TEXT_LIMIT)
        j = type_end
    j = view.skip_space(j, min(len(m), j + 200))
    body = None
    if m[j : j + 1] == "{":
        end = view.close.get(j)
        body = (j, end) if end is not None else None
    return Member(
        kind="function",
        name=name,
        owner=owner,
        line=view.line(at),
        offset=at,
        visibility=visibility_of(modifiers, java=False),
        modifiers=modifiers,
        annotations=annotations,
        type_text=type_text,
        params=params,
        body=body,
        companion=companion,
    )


def _kotlin_property(
    ctx: _Ctx,
    at: int,
    after: int,
    owner: str,
    modifiers: tuple[str, ...],
    annotations: tuple[Annotation, ...],
    word: str,
    companion: bool,
) -> Member | None:
    view = ctx.view
    m = view.masked
    i = view.skip_space(after)
    if m[i : i + 1] == "<":
        end = view.skip_generic(i)
        if end is None:
            return None
        i = end
        i = view.skip_space(i)
    limit = min(len(m), i + 200)  # a name is short: never scan on to the end of the file
    stop = limit
    for char in ":=\n;{":
        found = m.find(char, i, limit)
        if 0 <= found < stop:
            stop = found
    by = re.search(r"\s+by\b", m[i:stop])  # untyped and delegated: ``val x by lazy { }``
    name_stop = i + by.start() if by else stop
    token = strip_generics(m[i:name_stop]).strip()
    name = token.rsplit(".", 1)[-1].strip()
    if not _IDENT.fullmatch(name):
        return None
    j = name_stop
    type_text = ""
    if m[j : j + 1] == ":":
        type_end = _read_type(view, j + 1)
        type_text = clip(view.text[j + 1 : type_end], TYPE_TEXT_LIMIT)
        j = type_end
    j = view.skip_space(j, min(len(m), j + 80))
    delegated = False
    init_name = init_generic = None
    if m.startswith("by", j) and not (m[j + 2 : j + 3].isalnum() or m[j + 2 : j + 3] == "_"):
        delegated = True
        init_name, init_generic = _initializer(view, view.skip_space(j + 2))
    elif m[j : j + 1] == "=" and m[j + 1 : j + 2] != "=":
        init_name, init_generic = _initializer(view, j + 1)
    return Member(
        kind="property",
        name=name,
        owner=owner,
        line=view.line(at),
        offset=at,
        visibility=visibility_of(modifiers, java=False),
        modifiers=(*modifiers, word),
        annotations=annotations,
        type_text=type_text,
        companion=companion,
        delegated=delegated,
        init_name=init_name,
        init_generic=init_generic,
    )


def _kotlin_constructor(
    ctx: _Ctx,
    at: int,
    after: int,
    owner: str,
    modifiers: tuple[str, ...],
    annotations: tuple[Annotation, ...],
) -> Member | None:
    view = ctx.view
    i = view.skip_space(after)
    if view.masked[i : i + 1] != "(":
        return None
    close = view.close.get(i)
    if close is None:
        return None
    return Member(
        kind="constructor",
        name=owner.rsplit(".", 1)[-1],
        owner=owner,
        line=view.line(at),
        offset=at,
        visibility=visibility_of(modifiers, java=False),
        modifiers=modifiers,
        annotations=annotations,
        params=_kotlin_params(view, ctx.aindex, i, close),
    )


# -- Java members ------------------------------------------------------------------------------


def _enum_entries(view: SrcView, open_i: int, close_i: int) -> tuple[tuple[str, ...], int]:
    """Names of the enum constants of a body, and the offset where its members begin."""
    m = view.masked
    names: list[str] = []
    i = open_i + 1
    item = i
    while i < close_i:
        ch = m[i]
        if ch in "([{":
            end = view.group_end(i)
            if end is None:
                return tuple(names), close_i
            i = end
            continue
        if ch in ",;":
            name = _entry_name(m[item:i].strip())
            if name:
                names.append(name)
            item = i + 1
            if ch == ";":
                return tuple(names), i + 1
        i += 1
    name = _entry_name(m[item:close_i].strip())
    if name:
        names.append(name)
    return tuple(names), close_i


def _entry_name(text: str) -> str | None:
    text = re.sub(r"@[\w.]+(\s*\([^)]*\))?", " ", text).strip()
    match = _IDENT.match(text)
    return match.group() if match else None


def _java_scan(
    ctx: _Ctx, start: int, end: int, owner: str, out: _Members, *, interface: bool = False
) -> None:
    view, aindex = ctx.view, ctx.aindex
    m = view.masked
    i = start
    simple_owner = owner.rsplit(".", 1)[-1]
    while i < end and not out.overflow:
        i = view.skip_space(i, end)
        if i >= end:
            break
        if m[i] == ";":
            i += 1
            continue
        anchor = declaration_anchor(view, i)
        if anchor >= end:
            break
        paren = eq = brace = None
        stop = end
        j = anchor
        while j < end:
            ch = m[j]
            if ch == "<":
                skipped = view.skip_generic(j)
                j = skipped if skipped is not None else j + 1
                continue
            if ch == "[":
                skipped = view.group_end(j)
                j = skipped if skipped is not None else end
                continue
            if ch == "(":
                skipped = view.group_end(j)
                if skipped is None:
                    j = stop = end
                    break
                if paren is None and eq is None:
                    paren = j
                j = skipped
                continue
            if ch == "=" and paren is None and eq is None:
                eq = j
                j = _skip_to_semicolon(view, j, end)
                stop = min(j + 1, end)
                break
            if ch == "{":
                close = view.close.get(j)
                if close is None:
                    j = stop = end
                    break
                brace = (j, close)
                stop = close + 1
                break
            if ch == ";":
                stop = j + 1
                break
            j += 1
        else:
            stop = end
        first = min(x for x in (paren, eq, brace[0] if brace else None, stop - 1) if x is not None)
        header = m[anchor:first]
        next_i = max(stop, i + 1)
        modifiers = modifiers_before(view, aindex, anchor)
        annotations = aindex.at(anchor)
        if _JAVA_TYPE_WORD.search(header):  # also matches ``@interface Name``
            i = next_i
            continue
        if paren is not None and (eq is None or paren < eq):
            member = _java_method(
                ctx, anchor, paren, brace, owner, simple_owner, modifiers, annotations, interface
            )
        elif brace is not None and paren is None and eq is None:
            member = None  # an initializer block
        else:
            member = _java_field(ctx, anchor, header, owner, modifiers, annotations, interface)
        if member is not None:
            out.add(member)
        i = next_i


def _skip_to_semicolon(view: SrcView, i: int, end: int) -> int:
    m = view.masked
    while i < end:
        ch = m[i]
        if ch in "([{":
            nxt = view.group_end(i)
            if nxt is None:
                return end
            i = nxt
            continue
        if ch == ";":
            return i
        i += 1
    return end


def _java_method(
    ctx: _Ctx,
    anchor: int,
    paren: int,
    brace: tuple[int, int] | None,
    owner: str,
    simple_owner: str,
    modifiers: tuple[str, ...],
    annotations: tuple[Annotation, ...],
    interface: bool,
) -> Member | None:
    view = ctx.view
    m = view.masked
    before = m[anchor:paren]
    match = re.search(r"([A-Za-z_]\w*)\s*$", before)
    if not match:
        return None
    name = match.group(1)
    lead = before[: match.start()].strip()
    if lead.startswith("<"):  # method type parameters
        end = view.skip_generic(anchor + (len(before) - len(before.lstrip())))
        lead = m[end : anchor + match.start()].strip() if end else lead
    close = view.close.get(paren)
    if close is None:
        return None
    constructor = not lead and name == simple_owner
    if not lead and not constructor:
        return None
    visibility = visibility_of(modifiers, java=True)
    if interface and visibility == "package":
        visibility = "public"
    return Member(
        kind="constructor" if constructor else "function",
        name=name,
        owner=owner,
        line=view.line(anchor),
        offset=anchor,
        visibility=visibility,
        modifiers=modifiers,
        annotations=annotations,
        type_text="" if constructor else clip(lead, TYPE_TEXT_LIMIT),
        params=_java_params(view, ctx.aindex, paren, close),
        body=brace,
    )


def _java_field(
    ctx: _Ctx,
    anchor: int,
    header: str,
    owner: str,
    modifiers: tuple[str, ...],
    annotations: tuple[Annotation, ...],
    interface: bool,
) -> Member | None:
    text = header.strip()
    match = re.search(r"([A-Za-z_]\w*)\s*(?:\[\s*\]\s*)*$", text)
    if not match or match.start() == 0:
        return None
    type_text = text[: match.start()].strip()
    if not type_text:
        return None
    visibility = visibility_of(modifiers, java=True)
    if interface and visibility == "package":
        visibility = "public"
    return Member(
        kind="field",
        name=match.group(1),
        owner=owner,
        line=ctx.view.line(anchor),
        offset=anchor,
        visibility=visibility,
        modifiers=modifiers,
        annotations=annotations,
        type_text=clip(type_text, TYPE_TEXT_LIMIT),
    )


# -- whole files -------------------------------------------------------------------------------


def parse_file(source: SourceFile, config: AnalysisConfig) -> FileInfo:
    """Read one Kotlin or Java file. Never raises for malformed input: problems are listed in
    ``FileInfo.issues`` and the affected types are marked ``exact=False``."""
    view = SrcView(source)
    java = view.language == "java"
    annotations = extract_annotations(view)
    aindex = AnnotationIndex(annotations)
    info = FileInfo(
        view=view,
        package=source.package,
        annotations=aindex,
        file_annotations=tuple(a for a in annotations if a.use_site == "file"),
    )
    if source.lexed.errors:
        info.issues.append("lexer")
    if source.bracket_errors:
        info.issues.append("brackets")
    decls = source.types
    if len(decls) > config.max_types_per_file:
        info.issues.append("too_many_types")
        decls = decls[: config.max_types_per_file]
    headers = {decl.offset: _scan_header(view, decl) for decl in decls}
    ctx = _Ctx(view, aindex, config, headers, set())
    for decl in decls:
        if "companion" in modifiers_before(view, aindex, decl.offset):
            ctx.companion_types.add(decl.offset)

    # nesting by containing body, then local types dropped
    located: list[tuple[TypeDecl, _Header, str | None, int]] = []  # decl, header, owner fqn, depth
    stack: list[tuple[TypeDecl, _Header, str]] = []  # the real (non-local) types around this one
    fqns: dict[int, str] = {}
    for decl in sorted(decls, key=lambda d: d.offset):
        header = headers[decl.offset]
        while stack and not (
            stack[-1][1].body and stack[-1][1].body[0] < decl.offset < stack[-1][1].body[1]
        ):
            stack.pop()
        parent = stack[-1] if stack else None
        depth = source.depth_at(decl.offset)
        expected = 0 if parent is None else source.depth_at(parent[1].body[0]) + 1  # type: ignore[index]
        if depth != expected:
            continue  # a local type, or one inside a local type: not reported
        fqn = (
            f"{parent[2]}.{decl.name}"
            if parent
            else (f"{source.package}.{decl.name}" if source.package else decl.name)
        )
        fqns[decl.offset] = fqn
        located.append((decl, header, parent[2] if parent else None, depth))
        if header.body:
            stack.append((decl, header, fqn))

    for decl, header, owner, _depth in located:
        if decl.offset in ctx.companion_types:
            continue
        fqn = fqns[decl.offset]
        modifiers = modifiers_before(view, aindex, decl.offset)
        found = _Members(config.max_members_per_type)
        entries: tuple[str, ...] = ()
        exact = header.exact
        if header.body is not None:
            start = header.body[0] + 1
            if decl.kind == "enum":
                entries, start = _enum_entries(view, header.body[0], header.body[1])
            if java:
                _java_scan(
                    ctx, start, header.body[1], fqn, found, interface=decl.kind == "interface"
                )
            else:
                _kotlin_scan(ctx, start, header.body[1], fqn, found)
        ctor_params: tuple[Param, ...] = ()
        if header.ctor is not None:
            ctor_params = _kotlin_params(view, aindex, header.ctor[0], header.ctor[1])
        ctor_annotations = aindex.at(header.ctor_keyword) if header.ctor_keyword is not None else ()
        info.types.append(
            TypeInfo(
                fqn=fqn,
                name=decl.name,
                kind=decl.kind,
                path=source.path,
                line=decl.line,
                offset=decl.offset,
                package=source.package,
                owner=owner,
                visibility=visibility_of(modifiers, java=java),
                modifiers=modifiers,
                supertypes=_supertypes(view, header),
                annotations=aindex.at(decl.offset),
                members=tuple(found.items),
                body=header.body,
                constructor_params=ctor_params,
                constructor_annotations=ctor_annotations,
                entries=entries,
                exact=exact,
                truncated=found.overflow,
            )
        )
    if not java:
        top = _Members(config.max_members_per_type)
        _kotlin_scan(ctx, 0, len(view.masked), source.package, top)
        info.top_level = top.items
        info.top_level_truncated = top.overflow
    return info
