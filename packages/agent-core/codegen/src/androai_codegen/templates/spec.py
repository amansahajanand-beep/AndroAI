"""The structured input of a multi-screen project (Phase 5.2).

A ``ProjectSpec`` says which screens an app has, what each shows and which screen opens which. It
is an internal model, like ``ProjectConfig``: mapping a planner's output (the contracts'
``ImplementationPlan``, once its shape is agreed) onto it is the worker adapter's job.

Everything that ends up in generated code is derived from validated names, never taken from free
text: a screen ``name`` is a PascalCase ASCII identifier, its route is that name in snake case, and
its route constant is the same in upper case. Titles and descriptions only ever reach a string
resource, escaped. Invalid input raises ``pydantic.ValidationError`` (a ``ValueError``).
"""

from __future__ import annotations

import re
from collections import deque
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .validation import validate_display_text

MAX_SCREENS = 12
MAX_EDGES_PER_SCREEN = 8
MAX_SCREEN_NAME_LENGTH = 30
MAX_TITLE_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 120

_SCREEN_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
# ``SettingsDetail`` -> Settings|Detail, ``HTTPServer`` -> HTTP|Server,
# ``Step2Detail`` -> Step2|Detail
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def validate_screen_name(value: object) -> str:
    """A PascalCase ASCII identifier that the generated ``<Name>Screen`` composable can carry."""
    if not isinstance(value, str):
        raise ValueError("screen name must be a string")
    if not value:
        raise ValueError("screen name is empty")
    if len(value) > MAX_SCREEN_NAME_LENGTH:
        raise ValueError(f"screen name is longer than {MAX_SCREEN_NAME_LENGTH} characters")
    if not _SCREEN_NAME.fullmatch(value):
        raise ValueError(
            f"screen name {value!r} must start with an upper-case ASCII letter and contain only "
            "ASCII letters and digits (PascalCase, for example 'SettingsDetail')"
        )
    if value.endswith("Screen"):
        raise ValueError(
            f"screen name {value!r} must not end with 'Screen': the generated composable is "
            f"already called '{value}Screen'"
        )
    return value


def route_of(name: str) -> str:
    """The route of a screen: its name in snake case (``SettingsDetail`` -> ``settings_detail``)."""
    return "_".join(word.lower() for word in _WORD_BOUNDARY.split(name))


def route_constant(name: str) -> str:
    """The ``const val`` in ``Routes`` (``SettingsDetail`` -> ``SETTINGS_DETAIL``)."""
    return route_of(name).upper()


class ScreenSpec(BaseModel):
    """One screen: its identity, what it shows and where its buttons lead."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    title: str
    description: str | None = None
    navigates_to: tuple[str, ...] = ()

    @field_validator("name", mode="before")
    @classmethod
    def _check_name(cls, value: object) -> str:
        return validate_screen_name(value)

    @field_validator("title", mode="before")
    @classmethod
    def _check_title(cls, value: object) -> str:
        return validate_display_text(value, "screen title", MAX_TITLE_LENGTH)

    @field_validator("description", mode="before")
    @classmethod
    def _check_description(cls, value: object) -> str | None:
        if value is None:
            return None
        return validate_display_text(value, "screen description", MAX_DESCRIPTION_LENGTH)

    @field_validator("navigates_to", mode="before")
    @classmethod
    def _check_targets(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("navigates_to must be a list of screen names")
        return tuple(validate_screen_name(item) for item in value)

    @model_validator(mode="after")
    def _check_edges(self) -> Self:
        if len(self.navigates_to) > MAX_EDGES_PER_SCREEN:
            raise ValueError(
                f"screen {self.name} opens {len(self.navigates_to)} screens; at most "
                f"{MAX_EDGES_PER_SCREEN} are allowed"
            )
        if self.name in self.navigates_to:
            raise ValueError(f"screen {self.name} cannot open itself")
        if len(set(self.navigates_to)) != len(self.navigates_to):
            raise ValueError(f"screen {self.name} lists the same target twice")
        return self


class ProjectSpec(BaseModel):
    """The screens of an app and how they are connected. ``start`` defaults to the first screen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    screens: tuple[ScreenSpec, ...] = Field(min_length=1, max_length=MAX_SCREENS)
    start: str | None = None

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        names = [screen.name for screen in self.screens]
        # A route is the lower-cased name with underscores between words, so two names that differ
        # in more than letter case never share a route: this check makes routes unique too.
        by_lower: dict[str, str] = {}
        for name in names:
            if name.lower() in by_lower:
                raise ValueError(
                    f"screens {by_lower[name.lower()]!r} and {name!r} are the same name or differ "
                    "only in letter case"
                )
            by_lower[name.lower()] = name
        if self.start is not None and self.start not in names:
            raise ValueError(f"start screen {self.start!r} is not one of the screens")
        for screen in self.screens:
            for target in screen.navigates_to:
                if target not in names:
                    raise ValueError(f"screen {screen.name} opens {target!r}, which does not exist")
        reachable = self._reachable(self.start_name)
        unreachable = [name for name in names if name not in reachable]
        if unreachable:
            raise ValueError(
                f"screens not reachable from the start screen {self.start_name}: {unreachable}"
            )
        return self

    @property
    def start_name(self) -> str:
        return self.start if self.start is not None else self.screens[0].name

    def screen(self, name: str) -> ScreenSpec:
        for screen in self.screens:
            if screen.name == name:
                return screen
        raise KeyError(name)

    def _reachable(self, start: str) -> set[str]:
        seen = {start}
        queue = deque([start])
        while queue:
            for target in self.screen(queue.popleft()).navigates_to:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen
