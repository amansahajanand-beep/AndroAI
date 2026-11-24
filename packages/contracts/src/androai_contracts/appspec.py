"""``AppSpec``: the application a user asked for, as structured, reviewable data.

An ``AppSpec`` is produced by the planner from a natural-language request. It says *what the app
is*: its name, its screens and which screen opens which. It is what the user reviews and approves,
and what the code generator turns into a project. It is not an ``ImplementationPlan`` (the steps and
files a worker changes) and it does not repeat ``AndroidTarget`` (language, UI toolkit, SDK levels,
package name), which stays the only Android configuration of a ``CodingTask``.

Where the other names of a project come from:

* **App name** (``app_name``): proposed by the planner, shown to the user with the rest of the spec,
  and used as the project's display name once approved.
* **Package name** and every other Android setting: never produced by the planner. They come from
  ``AndroidTarget``, which the system fills in.

What it can describe is what the generator can build today and no more: 1 to 12 static screens,
each with a title, an optional description and up to 8 buttons that open other screens, one start
screen, and a Back button on every other screen. A button is labelled with the title of the screen
it opens. Anything else the user asked for (a database, a login, a form, search ...) is not part of
the spec: it is listed in ``unsupported_requests`` so that it is shown to the user, never silently
dropped.

Validation. Every rule below is enforced when the model is built; a custom rule fails with a stable
error ``type`` (its code) and, for rules about a place in the document, ``ctx["path"]`` (see
``ValidationProblem`` for the path format); ``ctx["problems"]`` lists every graph problem found, as
``ValidationProblem`` dictionaries. Rules the JSON Schema cannot express are described here:

* ``screens`` ids are unique ignoring letter case (``duplicate_screen_id``);
* ``start_screen``, when given, is one of the ids (``unknown_start_screen``); by default the first
  screen starts the app;
* every ``navigates_to`` entry is an existing screen (``unknown_screen``), not the screen itself
  (``self_navigation``) and not repeated on that screen (``duplicate_navigation``);
* every screen can be reached from the start screen by pressing buttons (``unreachable_screen``);
* texts follow the display-text rules of the generator (see ``DISPLAY_TEXT_PUNCTUATION``): letters,
  digits and combining marks of any script plus a few punctuation marks, starting with a letter or
  digit, with no leading, trailing or doubled spaces. They are Unicode-normalised (NFC).

The rules for texts and ids are a **safe subset** of what the generator accepts, so a valid
``AppSpec`` is never rejected by the generator for these reasons; the generator stays the authority
and reports what it still cannot build. ``summary`` and the texts of ``unsupported_requests`` are
only shown to people: they are never put into generated code or resources.

Producer: the planner (orchestration). Consumers: code generation (ai-agent) and the UI. Ownership
is to be confirmed under ``docs/TEAM_WORKFLOW.md``.
"""

from __future__ import annotations

import unicodedata
from collections import deque
from collections.abc import Sequence
from enum import Enum
from typing import Annotated, Self

from pydantic import AfterValidator, Field, ValidationInfo, model_validator
from pydantic_core import PydanticCustomError

from .base import ContractModel
from .validation import ProblemSeverity, ValidationProblem

MAX_SCREENS = 12
MAX_NAVIGATION_PER_SCREEN = 8
MAX_SCREEN_ID_LENGTH = 30
MAX_APP_NAME_LENGTH = 50
MAX_TITLE_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 120
MAX_SUMMARY_LENGTH = 300
MAX_UNSUPPORTED_REQUESTS = 20
MAX_REQUIREMENT_LENGTH = 200
MAX_REASON_LENGTH = 200
MAX_ALTERNATIVE_LENGTH = 200

SCREEN_ID_PATTERN = r"^[A-Z][A-Za-z0-9]*$"
# Besides letters, digits and combining marks of any script, display text may use these.
DISPLAY_TEXT_PUNCTUATION = " _-.'&,()!+"

_FORBIDDEN_IN_PLAIN_TEXT = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# The longest form in which a value is quoted in a ValidationProblem message (see ``_shown``).
_SHOWN_LENGTH = 40


def _display_text_check(max_length: int):
    def check(value: str, info: ValidationInfo) -> str:
        what = info.field_name or "text"
        value = unicodedata.normalize("NFC", value)
        if not value or len(value) > max_length:
            raise PydanticCustomError(
                "text_length",
                "{what} must have 1 to {max_length} characters",
                {"what": what, "max_length": max_length},
            )
        if value != value.strip():
            raise PydanticCustomError(
                "text_not_trimmed",
                "{what} must not start or end with a space",
                {"what": what},
            )
        bad = sorted(
            {
                ch
                for ch in value
                if ch not in DISPLAY_TEXT_PUNCTUATION
                and unicodedata.category(ch)[0] not in "LNM"
            }
        )
        if bad:
            raise PydanticCustomError(
                "text_bad_characters",
                "{what} contains characters that are not allowed: {characters}",
                {"what": what, "characters": " ".join(repr(ch) for ch in bad)},
            )
        if unicodedata.category(value[0])[0] not in "LN":
            raise PydanticCustomError(
                "text_bad_start",
                "{what} must start with a letter or digit",
                {"what": what},
            )
        if "  " in value:
            raise PydanticCustomError(
                "text_double_space",
                "{what} must not contain consecutive spaces",
                {"what": what},
            )
        return value

    return check


def _plain_text_check(max_length: int):
    def check(value: str, info: ValidationInfo) -> str:
        what = info.field_name or "text"
        value = unicodedata.normalize("NFC", value)
        if not value or len(value) > max_length:
            raise PydanticCustomError(
                "text_length",
                "{what} must have 1 to {max_length} characters",
                {"what": what, "max_length": max_length},
            )
        if value != value.strip():
            raise PydanticCustomError(
                "text_not_trimmed",
                "{what} must not start or end with a space",
                {"what": what},
            )
        if any(unicodedata.category(ch) in _FORBIDDEN_IN_PLAIN_TEXT for ch in value):
            raise PydanticCustomError(
                "text_control_characters",
                "{what} must be one line without control or invisible characters",
                {"what": what},
            )
        return value

    return check


def _screen_id_check(value: str, info: ValidationInfo) -> str:
    if value.endswith("Screen"):
        raise PydanticCustomError(
            "reserved_suffix",
            "{what} {value} must not end with 'Screen': the generator adds that suffix itself",
            {"what": info.field_name or "screen id", "value": value},
        )
    return value


ScreenId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_SCREEN_ID_LENGTH, pattern=SCREEN_ID_PATTERN),
    AfterValidator(_screen_id_check),
]
AppName = Annotated[
    str,
    Field(min_length=1, max_length=MAX_APP_NAME_LENGTH),
    AfterValidator(_display_text_check(MAX_APP_NAME_LENGTH)),
]
Title = Annotated[
    str,
    Field(min_length=1, max_length=MAX_TITLE_LENGTH),
    AfterValidator(_display_text_check(MAX_TITLE_LENGTH)),
]
Description = Annotated[
    str,
    Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH),
    AfterValidator(_display_text_check(MAX_DESCRIPTION_LENGTH)),
]
Summary = Annotated[
    str,
    Field(min_length=1, max_length=MAX_SUMMARY_LENGTH),
    AfterValidator(_plain_text_check(MAX_SUMMARY_LENGTH)),
]
Requirement = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REQUIREMENT_LENGTH),
    AfterValidator(_plain_text_check(MAX_REQUIREMENT_LENGTH)),
]
Reason = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REASON_LENGTH),
    AfterValidator(_plain_text_check(MAX_REASON_LENGTH)),
]
Alternative = Annotated[
    str,
    Field(min_length=1, max_length=MAX_ALTERNATIVE_LENGTH),
    AfterValidator(_plain_text_check(MAX_ALTERNATIVE_LENGTH)),
]


class ScreenPlan(ContractModel):
    """One screen: its identity, what it shows and which screens its buttons open."""

    id: ScreenId = Field(
        description="PascalCase ASCII identifier (letters and digits, starting with a capital, "
        "not ending in 'Screen'), unique ignoring letter case. The generator derives code from it."
    )
    title: Title = Field(
        description="The headline of the screen, and the label of every button that opens it. "
        "Display text: letters, digits and a few marks (space _ - . ' & , ( ) ! +), no markup."
    )
    description: Description | None = Field(
        default=None,
        description="Optional line of text under the title (display text).",
    )
    navigates_to: list[ScreenId] = Field(
        default_factory=list,
        max_length=MAX_NAVIGATION_PER_SCREEN,
        description="Ids of the screens this screen opens, one button each, in this order. "
        "Each must exist, not be this screen and not repeat.",
    )


class UnsupportedCategory(str, Enum):
    """Why a requested feature is out of reach. New values may be added; handle unknown ones."""

    DATA_STORAGE = "data_storage"  # databases, saving or syncing data
    AUTHENTICATION = "authentication"  # accounts, login, sign-up
    USER_INPUT = "user_input"  # forms, text entry, settings that can be changed
    SEARCH = "search"
    LISTS_AND_MEDIA = "lists_and_media"  # lists of items, images, video, audio, maps
    NETWORKING = "networking"  # calling a service or a website
    APP_LOGIC = (
        "app_logic"  # calculations, state, game rules, anything that does something
    )
    DEVICE_FEATURES = "device_features"  # camera, location, notifications, permissions
    DISTRIBUTION = "distribution"  # signing, a store listing, other platforms
    OTHER = "other"


class UnsupportedRequest(ContractModel):
    """A requirement the generator cannot build. Shown to the user; never silently dropped."""

    requirement: Requirement = Field(
        description="What the user asked for, in the planner's words (one line, shown to people)."
    )
    category: UnsupportedCategory
    reason: Reason = Field(description="Why it is not part of the app (one line).")
    alternative: Alternative | None = Field(
        default=None, description="What the app does instead, if anything (one line)."
    )


def _shown(value: object) -> str:
    """``repr(value)`` cut to 40 characters, for quoting a value in a problem message.

    ``graph_problems`` is public and may be given values that were never validated, so the size of
    an input must never decide the size of a message (a ``ValidationProblem`` message is limited).
    A valid screen id is at most 30 characters and is shown in full.
    """
    text = repr(value[: _SHOWN_LENGTH + 1] if isinstance(value, str) else value)
    return text if len(text) <= _SHOWN_LENGTH else text[: _SHOWN_LENGTH - 3] + "..."


def graph_problems(
    screens: Sequence[ScreenPlan], start_screen: str | None
) -> list[ValidationProblem]:
    """Every problem in how the screens are connected, in a stable order (empty if none).

    ``AppSpec`` uses it for its own validation and raises the first one; a caller that wants to
    show or feed back all of them (the planner's retry loop) can call it on the screens it has.

    The order is fixed: duplicate ids (by screen index), the start screen, then the buttons (by
    screen, then by button), then unreachable screens (by screen index). Codes: ``duplicate_screen_id``
    (path ``screens[i].id``, i is the later screen), ``unknown_start_screen`` (``start_screen``),
    ``self_navigation``, ``unknown_screen`` and ``duplicate_navigation`` (``screens[i].navigates_to[j]``,
    the offending button) and ``unreachable_screen`` (``screens[i]``). Every problem is reported in one
    pass, except that nothing can be said about reachability when the start screen does not exist.
    When two screens share an id, the first one is the screen the buttons refer to.

    The function never raises because of what it is given: a ``start_screen`` that is not a screen
    id (too long, not even a string) is an ``unknown_start_screen`` problem, and every id quoted in a
    message is cut to 40 characters, so each problem is a valid ``ValidationProblem`` whatever the
    size of the input. (Screens built without validation, e.g. ``model_construct``, are the caller's
    responsibility: their ids must be strings.)
    """
    problems: list[ValidationProblem] = []

    def add(path: str, code: str, message: str) -> None:
        problems.append(ValidationProblem(path=path, code=code, message=message))

    first_with: dict[str, int] = {}
    for i, screen in enumerate(screens):
        earlier = first_with.setdefault(screen.id.lower(), i)
        if earlier != i:
            add(
                f"screens[{i}].id",
                "duplicate_screen_id",
                f"screen id {_shown(screen.id)} repeats screens[{earlier}] "
                f"({_shown(screens[earlier].id)}); "
                "ids are compared ignoring letter case",
            )

    ids = {screen.id for screen in screens}
    start_ok = True
    if start_screen is not None and (
        not isinstance(start_screen, str) or start_screen not in ids
    ):
        start_ok = False
        add(
            "start_screen",
            "unknown_start_screen",
            f"start screen {_shown(start_screen)} is not one of the screens",
        )

    for i, screen in enumerate(screens):
        seen: set[str] = set()
        for j, target in enumerate(screen.navigates_to):
            path = f"screens[{i}].navigates_to[{j}]"
            if target == screen.id:
                add(
                    path,
                    "self_navigation",
                    f"screen {_shown(screen.id)} cannot open itself",
                )
            elif target not in ids:
                add(
                    path,
                    "unknown_screen",
                    f"screen {_shown(screen.id)} opens {_shown(target)}, "
                    "which does not exist",
                )
            elif target in seen:
                add(
                    path,
                    "duplicate_navigation",
                    f"screen {_shown(screen.id)} has more than one button to "
                    f"{_shown(target)}",
                )
            seen.add(target)

    if screens and start_ok:
        start = start_screen if start_screen is not None else screens[0].id
        by_id: dict[str, ScreenPlan] = {}
        for screen in screens:
            by_id.setdefault(screen.id, screen)
        reached = {start}
        queue = deque([start])
        while queue:
            for target in by_id[queue.popleft()].navigates_to:
                if target in by_id and target not in reached:
                    reached.add(target)
                    queue.append(target)
        for i, screen in enumerate(screens):
            if screen.id not in reached:
                add(
                    f"screens[{i}]",
                    "unreachable_screen",
                    f"screen {_shown(screen.id)} cannot be reached from the start "
                    f"screen {_shown(start)} by pressing buttons",
                )
    return problems


class AppSpec(ContractModel):
    """The application a user asked for: a name, 1 to 12 static screens and how they connect.

    Rules beyond the field limits: screen ids are unique ignoring letter case; start_screen (default:
    the first screen) exists; every navigation target exists, is not its own screen and is not
    repeated on a screen; every screen can be reached from the start screen by pressing buttons.
    Requirements that cannot be built are listed in unsupported_requests, never dropped. The package
    name and all Android settings are not part of this document (they come from AndroidTarget).
    """

    app_name: AppName = Field(
        description="Display name of the app (display text, up to 50 characters). Proposed by the "
        "planner, shown to the user, used as the project's name once approved."
    )
    summary: Summary | None = Field(
        default=None,
        description="One or two plain sentences for the approval screen. Shown to people only; "
        "never put into code or resources.",
    )
    screens: list[ScreenPlan] = Field(
        min_length=1, max_length=MAX_SCREENS, description="The screens, 1 to 12."
    )
    start_screen: ScreenId | None = Field(
        default=None,
        description="Id of the screen the app opens on. Defaults to the first screen.",
    )
    unsupported_requests: list[UnsupportedRequest] = Field(
        default_factory=list,
        max_length=MAX_UNSUPPORTED_REQUESTS,
        description="Everything the user asked for that the generator cannot build.",
    )

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        problems = [
            p
            for p in graph_problems(self.screens, self.start_screen)
            if p.severity is ProblemSeverity.ERROR
        ]
        if problems:
            first = problems[0]
            raise PydanticCustomError(
                first.code,
                "{message}",
                {
                    "message": first.message,
                    "path": first.path,
                    "problems": [p.model_dump(mode="json") for p in problems],
                },
            )
        return self

    @property
    def start_id(self) -> str:
        """The id of the screen the app opens on."""
        return (
            self.start_screen if self.start_screen is not None else self.screens[0].id
        )
