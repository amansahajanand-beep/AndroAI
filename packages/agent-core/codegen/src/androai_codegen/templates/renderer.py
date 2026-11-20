"""Render a template into files and into the existing ``PatchSet``.

Nothing here touches the disk. ``render_patch`` returns a ``PatchSet`` of ``CreateFile`` changes;
applying it (with protection, journal, checkpoint and rollback) is the job of ``PatchEngine``, and
``review_patch`` can check it first, exactly as for any other patch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..editing.errors import PathValidationError
from ..editing.models import CreateFile, PatchSet
from ..editing.paths import normalize_relative_path
from . import kotlin_compose
from .config import Language, ProjectConfig, UiToolkit
from .errors import TemplateRenderError, UnsupportedTemplateError
from .render import RenderedFile, TemplateFile, android_string, placeholders, substitute
from .versions import TOOLCHAIN


@dataclass(frozen=True)
class Template:
    """A project template: the files for one language / UI toolkit combination."""

    language: Language
    ui_toolkit: UiToolkit
    description: str
    files: tuple[TemplateFile, ...]


# Adding Java or XML-layout templates later is a new module that defines a ``Template`` plus one
# entry here; nothing in the renderer, the config or the validators changes. A combination that is
# not registered raises ``UnsupportedTemplateError`` (see ``get_template``).
_REGISTRY: dict[tuple[Language, UiToolkit], Template] = {
    (Language.KOTLIN, UiToolkit.COMPOSE): Template(
        Language.KOTLIN,
        UiToolkit.COMPOSE,
        "Single-module Kotlin app with Jetpack Compose, Material 3 and Navigation Compose",
        kotlin_compose.FILES,
    ),
}


def available_templates() -> tuple[Template, ...]:
    return tuple(_REGISTRY.values())


def get_template(language: Language, ui_toolkit: UiToolkit) -> Template:
    try:
        return _REGISTRY[(language, ui_toolkit)]
    except KeyError:
        supported = ", ".join(f"{lang}+{ui}" for lang, ui in _REGISTRY)
        raise UnsupportedTemplateError(
            f"there is no {language}+{ui_toolkit} template yet (available: {supported})"
        ) from None


def placeholder_values(config: ProjectConfig) -> dict[str, str]:
    """Every placeholder a template may use, with its value for ``config``.

    Values are inserted as text and are never expanded again. Each is already safe for the files
    it appears in: package and application ID are restricted to ``[A-Za-z0-9_.]``, identifiers are
    ASCII, versions are fixed pins, and the only free text (the project name) is escaped for an
    Android string resource.
    """
    pins = TOOLCHAIN
    return {
        "PACKAGE": config.package_name,
        "PACKAGE_PATH": config.package_path,
        "APPLICATION_ID": config.effective_application_id,
        "APP_NAME": android_string(config.project_name),
        "THEME_FUNCTION": config.theme_function,
        "THEME_STYLE": config.theme_style,
        "GRADLE_PROJECT_NAME": config.gradle_project_name,
        "MIN_SDK": str(config.min_sdk),
        "TARGET_SDK": str(config.target_sdk),
        "COMPILE_SDK": str(config.compile_sdk),
        "VERSION_CODE": str(config.version_code),
        "VERSION_NAME": config.version_name,
        "JAVA_VERSION": f"VERSION_{pins.jdk}",
        "AGP": pins.agp,
        "GRADLE": pins.gradle,
        "GRADLE_SHA256": pins.gradle_sha256,
        "KOTLIN": pins.kotlin,
        "COMPOSE_BOM": pins.compose_bom,
        "ACTIVITY_COMPOSE": pins.activity_compose,
        "NAVIGATION_COMPOSE": pins.navigation_compose,
    }


def template_placeholders(template: Template) -> set[str]:
    """Every placeholder the files of ``template`` use (paths included)."""
    names: set[str] = set()
    for file in template.files:
        names |= placeholders(file.path) | placeholders(file.content)
    return names


def render_template(template: Template, values: Mapping[str, str]) -> tuple[RenderedFile, ...]:
    """Substitute ``values`` into every file of ``template``; paths are checked and sorted."""
    rendered: dict[str, RenderedFile] = {}
    for file in template.files:
        path = substitute(file.path, values, where=f"path {file.path!r}")
        try:
            canonical = normalize_relative_path(path)
        except PathValidationError as exc:
            raise TemplateRenderError(f"{file.path!r} rendered to an unsafe path: {exc}") from exc
        if canonical != path:
            raise TemplateRenderError(f"{file.path!r} rendered to a non-canonical path {path!r}")
        if path in rendered:
            raise TemplateRenderError(f"two template files render to the same path {path!r}")
        content = substitute(file.content, values, where=path)
        if "\x00" in content or "\r" in content:
            raise TemplateRenderError(f"{path}: content has a NUL or a carriage return")
        if not content.endswith("\n"):
            raise TemplateRenderError(f"{path}: content must end with a newline")
        rendered[path] = RenderedFile(path, content, file.description)
    return tuple(rendered[path] for path in sorted(rendered))


def render_files(config: ProjectConfig) -> tuple[RenderedFile, ...]:
    """The files of the project, sorted by path. Deterministic: same config, same bytes."""
    template = get_template(config.language, config.ui_toolkit)
    return render_template(template, placeholder_values(config))


def render_patch(
    config: ProjectConfig,
    *,
    project_id: str,
    run_id: str,
    task_id: str,
    description: str | None = None,
) -> PatchSet:
    """The project as a ``PatchSet`` that creates every file (it fails on a non-empty target)."""
    files = render_files(config)
    return PatchSet(
        project_id=project_id,
        run_id=run_id,
        task_id=task_id,
        description=description or f"Create the {config.project_name} Android project",
        changes=[
            CreateFile(path=file.path, content=file.content, description=file.description)
            for file in files
        ],
    )
