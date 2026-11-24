"""Annotation extraction for Kotlin and Java.

Annotations are located on the lexer-masked text, so ``@Foo`` inside a comment or a string is not
an annotation and parentheses inside a string argument cannot end an argument list early. Argument
values are cut from the *original* text by offset and masked for secrets before they are kept.

Each annotation records the offset of the declaration it belongs to (``target``): the first token
after the annotations and modifiers that follow it. A declaration finds its annotations by asking
for that same offset, so Kotlin's ``@Inject constructor`` and ``@Provides fun``, Java's
``@Provides static Foo foo()`` and ``@Entity class`` all attach the same way.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from androai_codegen.review.source import SourceFile

from .catalog import KNOWN_ANNOTATIONS
from .resolve import Resolution, level_for, resolve_known
from .text import SrcView, safe, split_spans

_ANNOTATION = re.compile(
    r"(?<![\w)\]\"'`$@])@"
    r"(?:(file|get|set|field|param|property|receiver|setparam|delegate)[ \t]*:[ \t]*)?"
    r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
)
_MODIFIERS = frozenset(
    """public private protected internal open abstract final override suspend inline noinline
    crossinline tailrec operator infix external lateinit const vararg data sealed enum annotation
    inner value expect actual reified companion static synchronized native transient volatile
    strictfp default sealed""".split()
)
_ARG_NAME = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)\s*")
_CLASS_REF_KOTLIN = re.compile(r"([A-Za-z_][\w.]*)\s*::\s*class\b")
_CLASS_REF_JAVA = re.compile(r"([A-Za-z_][\w.]*)\.class\b")
MAX_ARGS = 20
ARG_LIMIT = 300


@dataclass(frozen=True)
class Arg:
    name: str | None  # ``None`` for a positional argument
    text: str  # original text, masked for secrets and clipped

    def class_refs(self) -> tuple[str, ...]:
        """Names written as ``Foo::class`` (Kotlin) or ``Foo.class`` (Java) in the value."""
        refs = _CLASS_REF_KOTLIN.findall(self.text) + _CLASS_REF_JAVA.findall(self.text)
        return tuple(dict.fromkeys(refs))

    @property
    def string_value(self) -> str | None:
        """The content, if the whole value is one plain string literal."""
        match = re.fullmatch(r'\s*"((?:[^"\\]|\\.)*)"\s*', self.text)
        return match.group(1) if match else None


@dataclass(frozen=True)
class Annotation:
    name: str  # as written, e.g. ``Inject`` or ``javax.inject.Inject``
    simple: str
    use_site: str | None
    args: tuple[Arg, ...]
    offset: int
    end: int  # offset just past the name and any argument list
    line: int
    target: int  # offset of the declaration this annotation belongs to
    resolution: Resolution

    def arg(self, name: str | None = None, position: int = 0) -> Arg | None:
        """The argument called ``name``; for ``name=None`` (or ``"value"``) also the first
        positional one."""
        for arg in self.args:
            if arg.name == name:
                return arg
        if name in (None, "value"):
            positional = [a for a in self.args if a.name is None]
            if len(positional) > position:
                return positional[position]
            for arg in self.args:
                if arg.name == "value":
                    return arg
        return None

    def level(self, accepted: tuple[str, ...]) -> str | None:
        """``confirmed`` / ``inferred`` / ``None`` for "this is one of ``accepted``"."""
        return level_for(self.resolution, accepted)


def declaration_anchor(view: SrcView, i: int, known: dict[int, int] | None = None) -> int:
    """Offset of the first token after the annotations and modifiers that begin at ``i``.

    ``known`` maps the start of an annotation to the anchor already found for it, so a long run of
    stacked annotations is walked once instead of once per annotation.
    """
    masked = view.masked
    n = len(masked)
    while True:
        i = view.skip_space(i)
        if i >= n:
            return i
        if masked[i] == "@":
            if known is not None and i in known:
                return known[i]
            match = _ANNOTATION.match(masked, i)
            if match is None or match.group(2) == "interface":
                return i
            j = match.end()
            k = j
            while k < n and masked[k] in " \t":
                k += 1
            if k < n and masked[k] == "(":
                end = view.group_end(k)
                if end is None:
                    return i
                j = end
            i = j
            continue
        word = re.match(r"[A-Za-z_]\w*", masked[i : i + 40])
        if word and word.group() in _MODIFIERS:
            i += word.end()
            continue
        return i


def _args(view: SrcView, open_index: int, close_index: int) -> tuple[Arg, ...]:
    out: list[Arg] = []
    for start, end in split_spans(view.masked, open_index + 1, close_index)[:MAX_ARGS]:
        named = _ARG_NAME.match(view.masked[start:end])
        if named:
            out.append(Arg(named.group(1), safe(view.text[start + named.end() : end], ARG_LIMIT)))
        else:
            out.append(Arg(None, safe(view.text[start:end], ARG_LIMIT)))
    return tuple(out)


def _simple_name(written: str, resolution: Resolution) -> str:
    """The name the annotation goes by in the catalogue.

    Normally the last segment as written. A name that an import renamed (``import
    androidx.room.Dao as RoomDao``, then ``@RoomDao``) is the well-known annotation all the
    same: when the import resolves to a catalogued FQN, the catalogue's own name is used, so
    every extractor that looks for ``Dao`` finds it. An alias of anything else keeps the alias.
    """
    simple = written.rsplit(".", 1)[-1]
    fqn = resolution.fqn
    if resolution.how == "explicit" and fqn:
        canonical = fqn.rsplit(".", 1)[-1]
        if canonical != simple and fqn in KNOWN_ANNOTATIONS.get(canonical, ()):
            return canonical
    return simple


def extract_annotations(view: SrcView) -> list[Annotation]:
    """Every annotation of the file, in source order."""
    masked = view.masked
    source: SourceFile = view.source
    matches = list(_ANNOTATION.finditer(masked))
    anchors: dict[int, int] = {}
    found: list[Annotation] = []
    # Last to first, so the anchor of the annotation after this one is already known.
    for match in reversed(matches):
        written = match.group(2)
        if written == "interface":
            continue
        start = match.start()
        j = match.end()
        k = j
        while k < len(masked) and masked[k] in " \t":
            k += 1
        args: tuple[Arg, ...] = ()
        if k < len(masked) and masked[k] == "(":
            close = view.close.get(k)
            if close is not None:
                args = _args(view, k, close)
                j = close + 1
        target = declaration_anchor(view, j, anchors)
        anchors[start] = target
        resolution = resolve_known(source, written, KNOWN_ANNOTATIONS)
        found.append(
            Annotation(
                name=written,
                simple=_simple_name(written, resolution),
                use_site=match.group(1),
                args=args,
                offset=start,
                end=j,
                line=view.line(start),
                target=target,
                resolution=resolution,
            )
        )
    found.reverse()
    return found


class AnnotationIndex:
    """The annotations of one file, by the declaration they belong to."""

    def __init__(self, annotations: list[Annotation]) -> None:
        self.all = annotations
        self._by_target: dict[int, list[Annotation]] = defaultdict(list)
        self._by_end: dict[int, Annotation] = {}
        self._by_offset: dict[int, Annotation] = {a.offset: a for a in annotations}
        for annotation in annotations:
            self._by_target[annotation.target].append(annotation)
            self._by_end[annotation.end] = annotation

    def at(self, target: int) -> tuple[Annotation, ...]:
        return tuple(self._by_target.get(target, ()))

    def starting_at(self, position: int) -> Annotation | None:
        return self._by_offset.get(position)

    def ending_at(self, position: int) -> Annotation | None:
        return self._by_end.get(position)
