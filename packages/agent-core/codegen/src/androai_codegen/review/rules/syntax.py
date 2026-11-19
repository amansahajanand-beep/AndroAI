"""Syntax problems: unterminated strings/comments, unbalanced brackets, malformed XML/TOML."""

from __future__ import annotations

from collections.abc import Iterator

from ..analysis import ProjectAnalysis
from ..lexer import Lexed, LexError
from ..models import Finding, Severity, finding

_LEXICAL = {
    "unterminated_string": (
        "syntax.unterminated_string",
        "String literal is not closed before the end of the line or file.",
        "Add the closing quote. Single-line strings cannot contain a raw line break.",
    ),
    "unterminated_comment": (
        "syntax.unterminated_comment",
        "Block comment is never closed.",
        "Add the closing '*/'.",
    ),
    "unterminated_char": (
        "syntax.invalid_char_literal",
        "Character literal is not closed or holds more than one character.",
        "Use double quotes for strings; a char literal holds exactly one character.",
    ),
}
_BRACKET = {
    "unclosed": "'{char}' is opened here but never closed.",
    "unexpected_close": "'{char}' closes something that was never opened.",
    "mismatched": "'{char}' does not match the bracket it closes.",
}


def _lexical(path: str, lexed: Lexed, bracket_errors: list[LexError]) -> Iterator[Finding]:
    for error in lexed.errors:
        entry = _LEXICAL.get(error.kind)
        if entry is None:
            continue
        rule, description, fix = entry
        line, column = lexed.position(error.offset)
        yield finding(
            Severity.ERROR,
            rule,
            "syntax",
            path,
            description,
            line=line,
            column=column,
            fix=fix,
            key=error.kind,
        )
    for error in bracket_errors:
        line, column = lexed.position(error.offset)
        char = lexed.masked[error.offset]
        description = _BRACKET[error.kind].format(char=char)
        if error.related is not None:
            opener = lexed.masked[error.related]
            description = (
                f"'{char}' does not match '{opener}', which is still open from line "
                f"{lexed.line(error.related)} (a closing bracket is probably missing there)."
            )
        yield finding(
            Severity.ERROR,
            "syntax.unbalanced_brackets",
            "syntax",
            path,
            description,
            line=line,
            column=column,
            fix="Balance the brackets; a missing '}' or ')' near here is the usual cause.",
            key=f"{error.kind}:{char}",
        )


def check(a: ProjectAnalysis) -> Iterator[Finding]:
    for path, source in a.sources.items():
        yield from _lexical(path, source.lexed, source.bracket_errors)
    for path, script in a.gradle_scripts.items():
        yield from _lexical(path, script.lexed, script.bracket_errors)
    for path, doc in a.xml_docs.items():
        if doc.error and path not in a.template_xml and path not in a.refused_xml:
            yield finding(
                Severity.ERROR,
                "xml.malformed",
                "syntax",
                path,
                f"XML is not well-formed: {doc.error.message}.",
                line=doc.error.line,
                column=doc.error.column,
                fix="Fix the markup; mismatched or unclosed tags are the usual cause.",
                key=doc.error.message,
            )
    if a.catalog_path and a.catalog and a.catalog.error:
        yield finding(
            Severity.ERROR,
            "toml.malformed",
            "syntax",
            a.catalog_path,
            f"Version catalog is not valid TOML: {a.catalog.error}.",
            line=a.catalog.error_line,
            fix="Fix the TOML syntax.",
            key="toml",
        )
