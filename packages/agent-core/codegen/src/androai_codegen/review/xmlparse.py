"""Hardened XML parsing for Android resources, manifests and navigation graphs.

Uses the standard library's expat with DOCTYPE/entity declarations rejected outright (Android
XML never needs them), so entity-expansion and external-entity attacks are impossible. Element
positions come from expat; namespace prefixes are kept as written (``android:name``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.parsers import expat

MAX_NODES = 200_000
MAX_DEPTH = 300


@dataclass
class XmlNode:
    tag: str
    attrs: dict[str, str]
    line: int
    column: int
    children: list[XmlNode] = field(default_factory=list)
    text: str = ""

    def iter(self) -> Iterator[XmlNode]:
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def find_all(self, tag: str) -> list[XmlNode]:
        return [node for node in self.iter() if node.tag == tag]

    def child_nodes(self, tag: str) -> list[XmlNode]:
        return [child for child in self.children if child.tag == tag]


@dataclass(frozen=True)
class XmlError:
    message: str
    line: int
    column: int


@dataclass
class XmlDoc:
    root: XmlNode | None
    error: XmlError | None = None


class _Rejected(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


DOCTYPE_REFUSED = "DOCTYPE and entity declarations are not allowed"


def parse_xml(text: str) -> XmlDoc:
    """Parse ``text``. Never raises: failures come back as ``XmlDoc.error``."""
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[XmlNode] = []
    roots: list[XmlNode] = []
    count = 0

    def reject_doctype(*_args: object) -> None:
        raise _Rejected(DOCTYPE_REFUSED)

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if count > MAX_NODES or len(stack) >= MAX_DEPTH:
            raise _Rejected("document is too large or too deeply nested")
        node = XmlNode(
            tag=name,
            attrs=dict(attrs),
            line=parser.CurrentLineNumber,
            column=parser.CurrentColumnNumber + 1,
        )
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    def chars(data: str) -> None:
        if stack and data.strip():
            stack[-1].text += data.strip()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.EntityDeclHandler = reject_doctype
    try:
        parser.Parse(text.encode("utf-8"), True)
    except _Rejected as exc:
        return XmlDoc(None, XmlError(exc.message, parser.CurrentLineNumber, 1))
    except expat.ExpatError as exc:
        message = expat.ErrorString(exc.code) if hasattr(exc, "code") else str(exc)
        return XmlDoc(None, XmlError(message, exc.lineno, exc.offset + 1))
    return XmlDoc(roots[0] if roots else None)
