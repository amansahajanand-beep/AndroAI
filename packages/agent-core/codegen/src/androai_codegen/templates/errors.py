"""Errors of the project templates."""

from __future__ import annotations


class TemplateError(Exception):
    """Base class of every error raised by the template renderer."""


class UnsupportedTemplateError(TemplateError):
    """The requested language / UI toolkit combination has no template yet."""


class TemplateRenderError(TemplateError):
    """A template could not be rendered safely (unknown placeholder, unsafe path, duplicate)."""
