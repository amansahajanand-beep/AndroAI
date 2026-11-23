"""Map a contract-shaped Android target onto a ``ProjectConfig`` (Phase 6.1).

The contracts' ``AndroidTarget`` (``language``, ``ui``, ``min_sdk``, ``target_sdk``,
``package_name``) says what the user wants; ``ProjectConfig`` is what the templates can build.
``config_from_target`` is the strict bridge between them. It never repairs a request silently: a
value the generator cannot honour is reported, not changed.

* **No import of the contracts.** ``androai-codegen`` does not depend on ``androai-contracts``
  (nor on the orchestration package). The mapper reads any object that has the five attributes,
  which is what ``androai_contracts.AndroidTarget`` has, so the worker adapter can pass it in as it
  is and the contracts can change without touching this module.
* **The project name is not part of the target.** ``AndroidTarget`` has no such field, so the caller
  supplies it explicitly (``project_name=``); nothing is derived from the package name.
* **Supported:** Kotlin + Compose only (Java and XML have no template), ``min_sdk`` from the
  generator's floor (below it the pinned AndroidX libraries do not work), and a ``target_sdk``
  between ``min_sdk`` and the pinned compile SDK.
* **``target_sdk``.** The contract's default is 35, the generator's default is 36. The value given
  is used as it is, never replaced by the generator's default: a target of 35 maps to 35. When the
  target object says that ``target_sdk`` was not set explicitly (a pydantic model that applied its
  default), a note says that the contract's default was used. The compile SDK, versions and
  everything else about the toolchain are the generator's pins and are not taken from the target.
* **Errors.** Every problem found is reported at once, as a ``TargetMappingError`` (a
  ``ValueError`` and a ``TemplateError``) that lists ``problems`` as ``(field, message)`` pairs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from .config import Language, ProjectConfig, UiToolkit
from .errors import TemplateError
from .navtests import navigation_tests_supported
from .validation import validate_package_name, validate_project_name
from .versions import DEFAULT_TARGET_SDK, TOOLCHAIN

_REQUIRED_ATTRIBUTES = ("language", "ui", "min_sdk", "target_sdk", "package_name")


class TargetLike(Protocol):
    """What ``config_from_target`` reads: the attributes of ``androai_contracts.AndroidTarget``."""

    language: object
    ui: object
    min_sdk: object
    target_sdk: object
    package_name: object


@dataclass(frozen=True)
class TargetProblem:
    """One reason a target cannot be mapped: the field it concerns and what is wrong."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class TargetMappingError(TemplateError, ValueError):
    """The target (or the project name) cannot be turned into a ``ProjectConfig``."""

    def __init__(self, problems: Sequence[TargetProblem]) -> None:
        self.problems: tuple[TargetProblem, ...] = tuple(problems)
        super().__init__("; ".join(str(problem) for problem in self.problems))


@dataclass(frozen=True)
class TargetMapping:
    """The config, and notes about choices the caller may want to show (never errors)."""

    config: ProjectConfig
    notes: tuple[str, ...] = ()


def _plain(value: object) -> object:
    """An enum member's value, any other value as it is."""
    return getattr(value, "value", value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_choice(
    target: object, field: str, supported: str, known: Sequence[str], problems: list[TargetProblem]
) -> bool:
    value = _plain(getattr(target, field))
    if value == supported:
        return True
    if value in known:
        problems.append(
            TargetProblem(
                field,
                f"{value!r} is not supported yet: there is no {value} template, only "
                f"{str(supported)!r} can be generated",
            )
        )
    else:
        problems.append(
            TargetProblem(
                field, f"unknown value {value!r} (known: {', '.join(repr(k) for k in known)})"
            )
        )
    return False


def config_from_target(target: TargetLike, *, project_name: str | None) -> TargetMapping:
    """The ``ProjectConfig`` for ``target``, or a ``TargetMappingError`` listing every problem."""
    problems: list[TargetProblem] = []

    missing = [name for name in _REQUIRED_ATTRIBUTES if not hasattr(target, name)]
    if missing:
        raise TargetMappingError(
            [TargetProblem(name, "the target has no such attribute") for name in missing]
        )

    if project_name is None:
        problems.append(
            TargetProblem(
                "project_name",
                "is required: AndroidTarget has no project name, so the caller has to supply it",
            )
        )
    else:
        try:
            validate_project_name(project_name)
        except ValueError as exc:
            problems.append(TargetProblem("project_name", str(exc)))

    _check_choice(target, "language", Language.KOTLIN, [m.value for m in Language], problems)
    _check_choice(target, "ui", UiToolkit.COMPOSE, [m.value for m in UiToolkit], problems)

    try:
        validate_package_name(target.package_name)
    except ValueError as exc:
        problems.append(TargetProblem("package_name", str(exc)))

    min_sdk, target_sdk = target.min_sdk, target.target_sdk
    ceiling = TOOLCHAIN.compile_sdk_max
    sdk_ok = True
    for name, value in (("min_sdk", min_sdk), ("target_sdk", target_sdk)):
        if not _is_int(value):
            problems.append(TargetProblem(name, f"must be an integer API level, not {value!r}"))
            sdk_ok = False
    if sdk_ok:
        assert isinstance(min_sdk, int) and isinstance(target_sdk, int)
        if min_sdk < TOOLCHAIN.min_sdk_floor:
            problems.append(
                TargetProblem(
                    "min_sdk",
                    f"{min_sdk} is below {TOOLCHAIN.min_sdk_floor}, the lowest API level the "
                    "pinned AndroidX libraries support; it is not raised for you, because that "
                    "would change which devices can run the app",
                )
            )
        if target_sdk < min_sdk:
            problems.append(TargetProblem("target_sdk", f"{target_sdk} is below min_sdk {min_sdk}"))
        if target_sdk > ceiling:
            problems.append(
                TargetProblem(
                    "target_sdk",
                    f"{target_sdk} is above {ceiling}, the compile SDK the generator is pinned to "
                    "(a target cannot be newer than the compile SDK)",
                )
            )

    if problems:
        raise TargetMappingError(problems)

    assert isinstance(min_sdk, int) and isinstance(target_sdk, int)
    assert project_name is not None
    try:
        config = ProjectConfig(
            project_name=project_name,
            package_name=str(target.package_name),
            min_sdk=min_sdk,
            target_sdk=target_sdk,
        )
    except ValidationError as exc:  # defensive: a rule of ProjectConfig the checks above missed
        raise TargetMappingError(
            [
                TargetProblem(".".join(str(part) for part in err["loc"]) or "target", err["msg"])
                for err in exc.errors()
            ]
        ) from exc

    return TargetMapping(config, _notes(target, config))


def _notes(target: object, config: ProjectConfig) -> tuple[str, ...]:
    notes: list[str] = []
    fields_set = getattr(target, "model_fields_set", None)
    if isinstance(fields_set, (set, frozenset)) and "target_sdk" not in fields_set:
        notes.append(
            f"target_sdk was not set: the contract's default {config.target_sdk} is used, not "
            f"the generator's default {DEFAULT_TARGET_SDK}"
        )
    elif config.target_sdk != DEFAULT_TARGET_SDK:
        notes.append(
            f"target_sdk {config.target_sdk} is used as given; the generator's default is "
            f"{DEFAULT_TARGET_SDK}"
        )
    if not navigation_tests_supported(config):
        notes.append(
            f"min_sdk {config.min_sdk} is above {TOOLCHAIN.robolectric_sdk}: a project with a "
            "spec is generated without its navigation tests (Robolectric on JDK 17 cannot run it)"
        )
    return tuple(notes)
