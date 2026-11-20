"""ProjectConfig: defaults, SDK rules, derived names."""

import pytest
from pydantic import ValidationError

from androai_codegen.templates import (
    TOOLCHAIN,
    Language,
    ProjectConfig,
    UiToolkit,
    get_template,
    render_files,
)
from androai_codegen.templates.naming import (
    FALLBACK_IDENTIFIER,
    gradle_project_name,
    pascal_identifier,
)
from androai_codegen.templates.versions import (
    DEFAULT_COMPILE_SDK,
    DEFAULT_MIN_SDK,
    DEFAULT_TARGET_SDK,
)


def make(**overrides) -> ProjectConfig:
    base = {"project_name": "Notes App", "package_name": "com.example.notes"}
    base.update(overrides)
    return ProjectConfig(**base)


# --- defaults and the application id -------------------------------------------------------


def test_defaults():
    cfg = make()
    assert cfg.language is Language.KOTLIN
    assert cfg.ui_toolkit is UiToolkit.COMPOSE
    assert (cfg.min_sdk, cfg.target_sdk, cfg.compile_sdk) == (
        DEFAULT_MIN_SDK,
        DEFAULT_TARGET_SDK,
        DEFAULT_COMPILE_SDK,
    )
    assert cfg.version_code == 1
    assert cfg.version_name == "1.0"


def test_the_application_id_defaults_to_the_package():
    assert make().effective_application_id == "com.example.notes"


def test_an_explicit_application_id_differs_from_the_namespace():
    cfg = make(application_id="com.acme.NotesPro")
    assert cfg.package_name == "com.example.notes"
    assert cfg.effective_application_id == "com.acme.NotesPro"


def test_an_invalid_application_id_is_rejected_even_when_the_package_is_fine():
    with pytest.raises(ValidationError, match="application ID"):
        make(application_id="notes")


def test_an_empty_application_id_is_not_the_default():
    with pytest.raises(ValidationError):
        make(application_id="")


def test_the_default_sdk_levels_are_inside_the_toolchain_ranges():
    assert TOOLCHAIN.min_sdk_floor <= DEFAULT_MIN_SDK
    assert TOOLCHAIN.compile_sdk_min <= DEFAULT_COMPILE_SDK <= TOOLCHAIN.compile_sdk_max
    assert DEFAULT_MIN_SDK <= DEFAULT_TARGET_SDK <= DEFAULT_COMPILE_SDK


# --- names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("project_name", ""),
        ("project_name", "A/B"),
        ("project_name", "  "),
        ("package_name", "notes"),
        ("package_name", "com.class"),
        ("package_name", "com.Example"),
        ("version_name", ""),
        ("version_name", "1 0"),
    ],
)
def test_invalid_names_are_rejected(field, value):
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        make(package="com.example.notes")


def test_the_config_is_immutable():
    cfg = make()
    with pytest.raises(ValidationError):
        cfg.project_name = "Other"


def test_a_config_round_trips_through_a_dict():
    cfg = make(application_id="com.acme.Notes", version_code=7, version_name="2.1")
    assert ProjectConfig.model_validate(cfg.model_dump()) == cfg


def test_the_name_is_normalised_in_the_config():
    assert make(project_name="Café").project_name == "Café"


# --- sdk levels ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_sdk": TOOLCHAIN.min_sdk_floor - 1},
        {"min_sdk": 21},
        {"min_sdk": 0},
        {"min_sdk": -1},
        {"min_sdk": 37, "target_sdk": 36},  # above target
        {"target_sdk": 23},  # below the default min
        {"target_sdk": DEFAULT_COMPILE_SDK + 1},  # above compile
        {"compile_sdk": TOOLCHAIN.compile_sdk_min - 1},
        {"compile_sdk": TOOLCHAIN.compile_sdk_max + 1},
        {"compile_sdk": 35, "target_sdk": 35},
        {"version_code": 0},
        {"version_code": -3},
        {"version_code": 2_100_000_001},
    ],
)
def test_invalid_sdk_levels_and_version_codes(kwargs):
    with pytest.raises(ValidationError):
        make(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_sdk": "24"},
        {"target_sdk": 36.0},
        {"compile_sdk": True},
        {"min_sdk": True},
        {"version_code": "1"},
        {"version_code": 1.5},
        {"min_sdk": None},
    ],
)
def test_integers_are_strict(kwargs):
    with pytest.raises(ValidationError):
        make(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_sdk": TOOLCHAIN.min_sdk_floor},
        {"min_sdk": 30, "target_sdk": 30},
        {"min_sdk": 36, "target_sdk": 36},
        {"target_sdk": 37},
        {"version_code": 2_100_000_000},
    ],
)
def test_valid_sdk_levels(kwargs):
    cfg = make(**kwargs)
    assert cfg.min_sdk <= cfg.target_sdk <= cfg.compile_sdk


def test_sdk_levels_reach_the_gradle_file():
    files = {f.path: f.content for f in render_files(make(min_sdk=26, target_sdk=36))}
    app = files["app/build.gradle.kts"]
    assert "minSdk = 26\n" in app
    assert "targetSdk = 36\n" in app
    assert f"compileSdk = {DEFAULT_COMPILE_SDK}\n" in app


# --- language / UI toolkit ------------------------------------------------------------------


def test_the_kotlin_compose_template_is_registered():
    template = get_template(Language.KOTLIN, UiToolkit.COMPOSE)
    assert template.files


@pytest.mark.parametrize(
    "kwargs",
    [
        {"language": "java"},
        {"ui_toolkit": "xml"},
        {"language": "java", "ui_toolkit": "xml"},
        {"language": Language.JAVA, "ui_toolkit": UiToolkit.COMPOSE},
    ],
)
def test_templates_that_do_not_exist_yet_are_refused_clearly(kwargs):
    from androai_codegen.templates import UnsupportedTemplateError

    cfg = make(**kwargs)  # a valid config...
    with pytest.raises(UnsupportedTemplateError, match="no .* template yet"):
        render_files(cfg)  # ...for a template that is not there


@pytest.mark.parametrize(
    "kwargs", [{"language": "swift"}, {"ui_toolkit": "flutter"}, {"language": 1}]
)
def test_unknown_language_or_toolkit_is_invalid_config(kwargs):
    with pytest.raises(ValidationError):
        make(**kwargs)


# --- derived identifiers --------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, identifier",
    [
        ("Notes App", "NotesApp"),
        ("notes", "Notes"),
        ("my notes-app", "MyNotesApp"),
        ("iOS Tracker", "IOSTracker"),
        ("R&D Tracker", "RDTracker"),
        ("Bob's Notes", "BobSNotes"),
        ("Café", "Cafe"),
        ("2048 Game", "App2048Game"),
        ("1", "App1"),
        ("नमस्ते", FALLBACK_IDENTIFIER),
        ("メモ帳", FALLBACK_IDENTIFIER),
        ("Notes (beta)", "NotesBeta"),
    ],
)
def test_pascal_identifier(name, identifier):
    assert pascal_identifier(name) == identifier
    assert identifier.isascii() and identifier.isidentifier() and not identifier[0].isdigit()


@pytest.mark.parametrize(
    "name, package, expected",
    [
        ("Notes App", "com.example.notes", "Notes-App"),
        ("Bob's Notes", "com.example.notes", "Bob-s-Notes"),
        ("C++ Tutor", "com.example.tutor", "C-Tutor"),
        ("नमस्ते", "com.example.hello", "hello"),
        ("メモ帳", "com.example.memo", "memo"),
    ],
)
def test_gradle_project_name(name, package, expected):
    assert gradle_project_name(name, package) == expected


def test_derived_names_of_a_config():
    cfg = make(project_name="My Notes", package_name="org.acme.notes")
    assert cfg.identifier == "MyNotes"
    assert cfg.theme_function == "MyNotesTheme"
    assert cfg.theme_style == "Theme.MyNotes"
    assert cfg.gradle_project_name == "My-Notes"
    assert cfg.package_path == "org/acme/notes"
