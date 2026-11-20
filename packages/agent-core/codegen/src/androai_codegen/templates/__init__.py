"""Reusable Android project templates, rendered as a ``PatchSet``.

Phase 5.1 ships one template: Kotlin + Jetpack Compose. Rendering is pure and deterministic and
never touches a workspace; ``PatchEngine`` applies the result. The toolchain versions in
``versions.py`` were built (debug and release APK, AAB, lint, ``build``); ``VERIFIED_BUILD`` says
exactly what that covers, and what it does not (no signing, no tests, one configuration).
"""

from .config import Language, ProjectConfig, UiToolkit
from .errors import TemplateError, TemplateRenderError, UnsupportedTemplateError
from .render import RenderedFile, TemplateFile
from .renderer import (
    Template,
    available_templates,
    get_template,
    placeholder_values,
    render_files,
    render_patch,
    render_template,
    template_placeholders,
)
from .validation import (
    validate_application_id,
    validate_package_name,
    validate_project_name,
    validate_version_name,
)
from .versions import PROVISIONAL, TOOLCHAIN, VERIFIED_BUILD, ToolchainPins

__all__ = [
    "PROVISIONAL",
    "TOOLCHAIN",
    "VERIFIED_BUILD",
    "Language",
    "ProjectConfig",
    "RenderedFile",
    "Template",
    "TemplateError",
    "TemplateFile",
    "TemplateRenderError",
    "ToolchainPins",
    "UiToolkit",
    "UnsupportedTemplateError",
    "available_templates",
    "get_template",
    "placeholder_values",
    "render_files",
    "render_patch",
    "render_template",
    "template_placeholders",
    "validate_application_id",
    "validate_package_name",
    "validate_project_name",
    "validate_version_name",
]
