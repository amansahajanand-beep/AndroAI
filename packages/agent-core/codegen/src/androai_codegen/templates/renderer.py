"""Render a template into files and into the existing ``PatchSet``.

Nothing here touches the disk. ``render_patch`` returns a ``PatchSet`` of ``CreateFile`` changes;
applying it (with protection, journal, checkpoint and rollback) is the job of ``PatchEngine``, and
``review_patch`` can check it first, exactly as for any other patch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..editing.models import CreateFile, PatchSet
from . import kotlin_compose, screens
from .config import Language, ProjectConfig, UiToolkit
from .errors import TemplateRenderError, UnsupportedTemplateError
from .render import (
    RenderedFile,
    TemplateFile,
    android_string,
    check_content,
    check_rendered_path,
    placeholders,
    substitute,
)
from .spec import ProjectSpec
from .versions import TOOLCHAIN

# Turns the rendered files of a template into those of a project with the screens of a spec.
SpecRenderer = Callable[
    [tuple[RenderedFile, ...], ProjectConfig, ProjectSpec], tuple[RenderedFile, ...]
]


@dataclass(frozen=True)
class Template:
    """A project template: the files for one language / UI toolkit combination.

    ``apply_spec`` is how a template supports a ``ProjectSpec`` (several screens); a template
    without one refuses a spec with ``UnsupportedTemplateError``.
    """

    language: Language
    ui_toolkit: UiToolkit
    description: str
    files: tuple[TemplateFile, ...]
    apply_spec: SpecRenderer | None = None


# Adding Java or XML-layout templates later is a new module that defines a ``Template`` plus one
# entry here; nothing in the renderer, the config or the validators changes. A combination that is
# not registered raises ``UnsupportedTemplateError`` (see ``get_template``).
_REGISTRY: dict[tuple[Language, UiToolkit], Template] = {
    (Language.KOTLIN, UiToolkit.COMPOSE): Template(
        Language.KOTLIN,
        UiToolkit.COMPOSE,
        "Single-module Kotlin app with Jetpack Compose, Material 3 and Navigation Compose",
        kotlin_compose.FILES,
        apply_spec=screens.apply_spec,
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
        "COMPILE_SDK_MINOR": str(config.compile_sdk_minor),
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
        check_rendered_path(file.path, path)
        if path in rendered:
            raise TemplateRenderError(f"two template files render to the same path {path!r}")
        content = substitute(file.content, values, where=path)
        check_content(path, content)
        rendered[path] = RenderedFile(path, content, file.description)
    return tuple(rendered[path] for path in sorted(rendered))


def render_files(
    config: ProjectConfig, spec: ProjectSpec | None = None
) -> tuple[RenderedFile, ...]:
    """The files of the project, sorted by path. Deterministic: same input, same bytes.

    Without a ``spec`` this is exactly the Phase 5.1 project. With one, the screens and the
    navigation of the spec replace the sample screen (see ``screens.py``).
    """
    template = get_template(config.language, config.ui_toolkit)
    files = render_template(template, placeholder_values(config))
    if spec is None:
        return files
    if template.apply_spec is None:
        raise UnsupportedTemplateError(
            f"the {template.language}+{template.ui_toolkit} template does not support "
            "a project spec"
        )
    return template.apply_spec(files, config, spec)


def render_patch(
    config: ProjectConfig,
    *,
    project_id: str,
    run_id: str,
    task_id: str,
    description: str | None = None,
    spec: ProjectSpec | None = None,
) -> PatchSet:
    """The project as a ``PatchSet`` that creates every file (it fails on a non-empty target)."""
    files = render_files(config, spec)
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
