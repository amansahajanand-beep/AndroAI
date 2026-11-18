"""Android resource index and reference scanning (``R.type.name`` and ``@type/name``)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .catalog import LIBRARY_RESOURCE_PREFIXES, LIBRARY_STYLE_PREFIXES
from .xmlparse import XmlDoc, XmlNode

# directory type -> resource type, for file-based resources
FILE_RESOURCE_DIRS = {
    "drawable": "drawable",
    "mipmap": "mipmap",
    "layout": "layout",
    "menu": "menu",
    "navigation": "navigation",
    "xml": "xml",
    "raw": "raw",
    "anim": "anim",
    "animator": "animator",
    "color": "color",
    "font": "font",
    "transition": "transition",
    "interpolator": "interpolator",
}
VALUE_TAGS = {
    "string": "string",
    "color": "color",
    "dimen": "dimen",
    "style": "style",
    "integer": "integer",
    "bool": "bool",
    "array": "array",
    "string-array": "array",
    "integer-array": "array",
    "plurals": "plurals",
    "attr": "attr",
    "drawable": "drawable",
    "fraction": "fraction",
    "declare-styleable": "styleable",
}
# Resource types that the app itself defines in practice, so an unknown name is a real error.
STRICT_TYPES = frozenset(
    """string layout menu navigation mipmap xml raw anim animator array plurals integer bool font
    transition interpolator fraction color dimen drawable id""".split()
)
KNOWN_TYPES = STRICT_TYPES | {"style", "attr", "styleable"}

_RES_PATH = re.compile(r"(?:^|/)res/([a-z]+)((?:-[^/]+)?)/([^/]+)$")
_XML_REF = re.compile(r"(?<![\w:])@(\+?)([a-z]+)/([\w.]+)")
CODE_REF = re.compile(r"(?<![\w.])R\.([a-z]+)\.(\w+)")


def normalize_name(name: str) -> str:
    return name.replace(".", "_")


@dataclass(frozen=True)
class ResDef:
    type: str
    name: str  # normalized (dots -> underscores)
    path: str
    line: int
    directory: str  # e.g. "app/src/main/res/values": duplicates are per directory
    file_based: bool = False  # the resource is a whole file (drawable/x.png), not a value


@dataclass(frozen=True)
class XmlRef:
    type: str
    name: str
    line: int
    path: str


class ResourceIndex:
    def __init__(self, paths: frozenset[str], xml: dict[str, XmlDoc]) -> None:
        self.defs: dict[tuple[str, str], list[ResDef]] = defaultdict(list)
        self._xml = xml
        for path in sorted(paths):
            match = _RES_PATH.search(path)
            if not match:
                continue
            kind, _qualifier, filename = match.groups()
            directory = path.rsplit("/", 1)[0]
            doc = xml.get(path)
            if kind == "values":
                if doc and doc.root:
                    self._index_values(path, directory, doc.root)
                continue
            if kind in FILE_RESOURCE_DIRS:
                name = normalize_name(filename.split(".", 1)[0])
                self._add(FILE_RESOURCE_DIRS[kind], name, path, 1, directory, file_based=True)
            if doc and doc.root:
                self._index_ids(path, directory, doc.root)

    def _add(
        self,
        kind: str,
        name: str,
        path: str,
        line: int,
        directory: str,
        *,
        file_based: bool = False,
    ) -> None:
        normalized = normalize_name(name)
        self.defs[(kind, normalized)].append(
            ResDef(kind, normalized, path, line, directory, file_based)
        )

    def _index_values(self, path: str, directory: str, root: XmlNode) -> None:
        for child in root.children:
            name = child.attrs.get("name")
            if not name:
                continue
            kind = VALUE_TAGS.get(child.tag)
            if child.tag == "item":
                kind = child.attrs.get("type")
            if kind:
                self._add(kind, name, path, child.line, directory)
            if child.tag == "declare-styleable":
                for attr in child.children:
                    if attr.tag == "attr" and attr.attrs.get("name"):
                        self._add("attr", attr.attrs["name"], path, attr.line, directory)
        self._index_ids(path, directory, root)

    def _index_ids(self, path: str, directory: str, root: XmlNode) -> None:
        for node in root.iter():
            for value in node.attrs.values():
                for match in _XML_REF.finditer(value):
                    if match.group(1) and match.group(2) == "id":
                        self._add("id", match.group(3), path, node.line, directory)

    def has(self, kind: str, name: str) -> bool:
        return (kind, normalize_name(name)) in self.defs

    def duplicates(self) -> list[tuple[str, str, list[ResDef]]]:
        """(type, name, defs) defined more than once in the same resource directory."""
        found = []
        for (kind, name), defs in self.defs.items():
            if kind == "id":
                continue  # @+id/x may legitimately appear many times
            groups: dict[str, list[ResDef]] = defaultdict(list)
            for definition in defs:
                groups[definition.directory].append(definition)
            for same_directory in groups.values():
                if len(same_directory) > 1:
                    found.append((kind, name, same_directory))
        return found

    def is_library_resource(self, kind: str, name: str) -> bool:
        """True if the name looks like one a dependency would provide."""
        if kind == "style":
            normalized = normalize_name(name)
            return normalized.startswith(LIBRARY_STYLE_PREFIXES)
        return name.startswith(LIBRARY_RESOURCE_PREFIXES)

    def xml_refs(self, path: str) -> list[XmlRef]:
        doc = self._xml.get(path)
        if not doc or not doc.root:
            return []
        refs: list[XmlRef] = []
        for node in doc.root.iter():
            for value in [*node.attrs.values(), node.text]:
                for match in _XML_REF.finditer(value):
                    if match.group(1):
                        continue  # a definition (@+id/...), not a reference
                    refs.append(XmlRef(match.group(2), match.group(3), node.line, path))
        return refs
