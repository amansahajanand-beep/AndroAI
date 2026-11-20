"""Reusable Android project templates, rendered as a ``PatchSet``.

Phase 5.1 ships one template: Kotlin + Jetpack Compose. Phase 5.2 adds ``ProjectSpec``: a
structured, validated description of several screens and the navigation between them, rendered
into the same project (``render_patch(config, spec=...)``). Phase 5.3 adds, to a project with a
spec, a generated JVM navigation test (Robolectric + Compose test) and its test-only dependencies.
Rendering is pure and deterministic and never touches a workspace; ``PatchEngine`` applies the
result. The toolchain versions in ``versions.py`` were built (debug and release APK, AAB, lint,
``build``, and for spec projects the navigation tests); ``VERIFIED_BUILD`` says exactly what that
covers, and what it does not (no signing, no instrumented test, a few configurations).
"""

from .config import Language, ProjectConfig, UiToolkit
from .errors import TemplateError, TemplateRenderError, UnsupportedTemplateError
from .navtests import navigation_tests_supported
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
from .spec import ProjectSpec, ScreenSpec, route_constant, route_of, validate_screen_name
from .validation import (
    validate_application_id,
    validate_display_text,
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
    "ProjectSpec",
    "RenderedFile",
    "ScreenSpec",
    "Template",
    "TemplateError",
    "TemplateFile",
    "TemplateRenderError",
    "ToolchainPins",
    "UiToolkit",
    "UnsupportedTemplateError",
    "available_templates",
    "get_template",
    "navigation_tests_supported",
    "placeholder_values",
    "render_files",
    "render_patch",
    "render_template",
    "route_constant",
    "route_of",
    "template_placeholders",
    "validate_application_id",
    "validate_display_text",
    "validate_package_name",
    "validate_screen_name",
    "validate_project_name",
    "validate_version_name",
]
