"""The input of a project template.

``ProjectConfig`` is internal to the codegen package, like the patch models: mapping a contract
(``androai_contracts.AndroidTarget``, ``CodingTask``) onto it is the worker adapter's job, so the
contracts can change without touching the templates. Invalid input raises
``pydantic.ValidationError`` (a ``ValueError``), as an invalid ``PatchSet`` does.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import naming
from .validation import (
    validate_application_id,
    validate_package_name,
    validate_project_name,
    validate_version_name,
)
from .versions import (
    DEFAULT_COMPILE_SDK,
    DEFAULT_MIN_SDK,
    DEFAULT_TARGET_SDK,
    TOOLCHAIN,
)

MAX_VERSION_CODE = 2_100_000_000  # the Play Store limit


class Language(StrEnum):
    KOTLIN = "kotlin"
    JAVA = "java"  # reserved: no template yet, rendering raises UnsupportedTemplateError


class UiToolkit(StrEnum):
    COMPOSE = "compose"
    XML = "xml"  # reserved: no template yet, rendering raises UnsupportedTemplateError


class ProjectConfig(BaseModel):
    """Everything a template needs to know about the project it renders."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_name: str
    package_name: str
    # Defaults to ``package_name``. It may differ: the namespace is the code's package, the
    # application ID is the identity of the app on a device and in a store.
    application_id: str | None = None
    language: Language = Language.KOTLIN
    ui_toolkit: UiToolkit = UiToolkit.COMPOSE
    min_sdk: int = Field(default=DEFAULT_MIN_SDK, strict=True)
    target_sdk: int = Field(default=DEFAULT_TARGET_SDK, strict=True)
    compile_sdk: int = Field(default=DEFAULT_COMPILE_SDK, strict=True)
    version_code: int = Field(default=1, strict=True, ge=1, le=MAX_VERSION_CODE)
    version_name: str = "1.0"

    @field_validator("project_name", mode="before")
    @classmethod
    def _check_project_name(cls, value: object) -> str:
        return validate_project_name(value)

    @field_validator("package_name", mode="before")
    @classmethod
    def _check_package_name(cls, value: object) -> str:
        return validate_package_name(value)

    @field_validator("application_id", mode="before")
    @classmethod
    def _check_application_id(cls, value: object) -> str | None:
        return None if value is None else validate_application_id(value)

    @field_validator("version_name", mode="before")
    @classmethod
    def _check_version_name(cls, value: object) -> str:
        return validate_version_name(value)

    @model_validator(mode="after")
    def _check_sdk_levels(self) -> Self:
        pins = TOOLCHAIN
        if self.min_sdk < pins.min_sdk_floor:
            raise ValueError(
                f"min_sdk {self.min_sdk} is below {pins.min_sdk_floor}, the lowest API level the "
                "pinned AndroidX libraries support"
            )
        if not pins.compile_sdk_min <= self.compile_sdk <= pins.compile_sdk_max:
            raise ValueError(
                f"compile_sdk {self.compile_sdk} is outside {pins.compile_sdk_min}-"
                f"{pins.compile_sdk_max}, the range the pinned Compose and Android Gradle plugin "
                "versions support (see templates/versions.py)"
            )
        if self.target_sdk < self.min_sdk:
            raise ValueError(f"target_sdk {self.target_sdk} is below min_sdk {self.min_sdk}")
        if self.target_sdk > self.compile_sdk:
            raise ValueError(
                f"target_sdk {self.target_sdk} is above compile_sdk {self.compile_sdk}"
            )
        return self

    # --- derived values -------------------------------------------------------------------

    @property
    def effective_application_id(self) -> str:
        return self.application_id or self.package_name

    @property
    def package_path(self) -> str:
        return self.package_name.replace(".", "/")

    @property
    def identifier(self) -> str:
        """ASCII PascalCase form of the project name (``NotesApp``)."""
        return naming.pascal_identifier(self.project_name)

    @property
    def theme_function(self) -> str:
        return f"{self.identifier}Theme"

    @property
    def theme_style(self) -> str:
        return f"Theme.{self.identifier}"

    @property
    def gradle_project_name(self) -> str:
        return naming.gradle_project_name(self.project_name, self.package_name)
