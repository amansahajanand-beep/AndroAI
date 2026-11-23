"""AndroidTarget -> ProjectConfig mapper (Phase 6.1).

The mapper reads any object with the five attributes of the contracts' ``AndroidTarget``. Most tests
use a plain stand-in, so they do not need ``androai-contracts``; the ones that use the real model
skip when it is not installed.
"""

import ast
from dataclasses import FrozenInstanceError, dataclass
from enum import Enum
from pathlib import Path

import pytest

from androai_codegen.review import ProjectFiles, ReviewEngine
from androai_codegen.templates import (
    TOOLCHAIN,
    ProjectConfig,
    ProjectSpec,
    ScreenSpec,
    TargetMappingError,
    TemplateError,
    config_from_target,
    render_files,
    validate_package_name,
    validate_project_name,
)
from androai_codegen.templates import target as target_module


@dataclass
class Target:
    """What AndroidTarget has: the same five attributes, with the contract's defaults."""

    package_name: str = "com.example.notes"
    language: object = "kotlin"
    ui: object = "compose"
    min_sdk: object = 24
    target_sdk: object = 35


class Ui(str, Enum):  # noqa: UP042 - the contracts' UiToolkit is declared exactly like this
    COMPOSE = "compose"
    XML = "xml"


def problems(**kwargs) -> dict[str, str]:
    project_name = kwargs.pop("project_name", "Notes App")
    with pytest.raises(TargetMappingError) as raised:
        config_from_target(Target(**kwargs), project_name=project_name)
    return {p.field: p.message for p in raised.value.problems}


# --- valid mappings -----------------------------------------------------------------------------


def test_a_default_target_maps_to_the_matching_config():
    mapping = config_from_target(Target(), project_name="Notes App")
    config = mapping.config
    assert isinstance(config, ProjectConfig)
    assert (config.project_name, config.package_name) == ("Notes App", "com.example.notes")
    assert (config.min_sdk, config.target_sdk) == (24, 35)
    # Everything the target does not carry is the generator's: pins, compile SDK, version.
    assert (config.compile_sdk, config.compile_sdk_minor) == (37, 1)
    assert (config.version_code, config.version_name, config.application_id) == (1, "1.0", None)
    assert (config.language.value, config.ui_toolkit.value) == ("kotlin", "compose")


def test_the_mapped_config_equals_the_one_built_by_hand():
    by_hand = ProjectConfig(
        project_name="Notes App", package_name="com.example.notes", min_sdk=24, target_sdk=35
    )
    assert config_from_target(Target(), project_name="Notes App").config == by_hand


@pytest.mark.parametrize(
    "min_sdk, target_sdk",
    [(24, 24), (24, 35), (24, 36), (24, 37), (26, 36), (35, 35), (35, 37), (36, 36), (37, 37)],
)
def test_every_combination_the_generator_supports_is_mapped_as_given(min_sdk, target_sdk):
    config = config_from_target(
        Target(min_sdk=min_sdk, target_sdk=target_sdk), project_name="Notes App"
    ).config
    assert (config.min_sdk, config.target_sdk) == (min_sdk, target_sdk)


def test_package_names_and_project_names_are_validated_and_kept():
    config = config_from_target(
        Target(package_name="org.acme.deep.pkg"), project_name="R&D Tracker"
    ).config
    assert config.package_name == "org.acme.deep.pkg" and config.project_name == "R&D Tracker"


def test_enum_members_are_read_by_value_like_the_contracts_do():
    # The contracts use a str enum for ui; a plain string is also accepted.
    assert config_from_target(Target(ui=Ui.COMPOSE), project_name="Notes App").config
    assert problems(ui=Ui.XML)["ui"].startswith("'xml' is not supported yet")


def test_the_mapping_is_deterministic_and_does_not_touch_its_input():
    target = Target(min_sdk=26, target_sdk=36)
    before = (target.package_name, target.language, target.ui, target.min_sdk, target.target_sdk)
    first = config_from_target(target, project_name="Notes App")
    second = config_from_target(target, project_name="Notes App")
    assert first == second
    assert (target.package_name, target.language, target.ui, target.min_sdk, target.target_sdk) == (
        before
    )


def test_the_result_is_immutable():
    mapping = config_from_target(Target(), project_name="Notes App")
    with pytest.raises(FrozenInstanceError):
        mapping.config = None  # type: ignore[misc]
    with pytest.raises(Exception, match="frozen|immutable|Instance is frozen"):
        mapping.config.min_sdk = 30  # type: ignore[misc]


# --- the project name ---------------------------------------------------------------------


def test_a_missing_project_name_is_an_explicit_error_and_is_never_derived():
    found = problems(project_name=None)
    assert list(found) == ["project_name"]
    assert "AndroidTarget has no project name" in found["project_name"]
    assert "caller" in found["project_name"]


@pytest.mark.parametrize(
    "name", ["", " ", " Notes", "Notes ", "Two  spaces", "Bad<name>", "a" * 200]
)
def test_an_invalid_project_name_is_reported_with_the_validators_message(name):
    found = problems(project_name=name)
    assert list(found) == ["project_name"]
    with pytest.raises(ValueError) as expected:
        validate_project_name(name)
    # Exactly the shared validator's message (not pydantic's wrapped "Value error, ..." text).
    assert found["project_name"] == str(expected.value)


def test_the_package_name_is_never_used_as_the_project_name():
    with pytest.raises(TargetMappingError):
        config_from_target(Target(package_name="com.example.notes"), project_name=None)


# --- Java and XML -------------------------------------------------------------------------


def test_java_is_refused_with_a_clear_reason():
    message = problems(language="java")["language"]
    assert "'java' is not supported yet" in message and "no java template" in message
    assert "'kotlin' can be generated" in message


def test_xml_layouts_are_refused_with_a_clear_reason():
    message = problems(ui="xml")["ui"]
    assert "'xml' is not supported yet" in message and "'compose' can be generated" in message


def test_java_and_xml_together_are_both_reported():
    assert set(problems(language="java", ui="xml")) == {"language", "ui"}


@pytest.mark.parametrize("value", ["Kotlin", "KOTLIN", "scala", "", None, 3, "kotlin "])
def test_an_unknown_language_is_refused_not_guessed(value):
    message = problems(language=value)["language"]
    assert message.startswith(f"unknown value {value!r}") and "known: 'kotlin', 'java'" in message


@pytest.mark.parametrize("value", ["Compose", "views", "", None, 1])
def test_an_unknown_ui_toolkit_is_refused_not_guessed(value):
    assert problems(ui=value)["ui"].startswith(f"unknown value {value!r}")


# --- minimum SDK ---------------------------------------------------------------------------------


def test_the_floor_is_the_generators_and_not_the_contracts():
    assert TOOLCHAIN.min_sdk_floor == 24  # the contract allows 21; the pinned libraries do not
    assert config_from_target(Target(min_sdk=24), project_name="Notes App").config.min_sdk == 24


@pytest.mark.parametrize("min_sdk", [21, 22, 23])
def test_a_minimum_sdk_below_the_floor_is_refused_not_raised(min_sdk):
    message = problems(min_sdk=min_sdk, target_sdk=35)["min_sdk"]
    assert f"{min_sdk} is below 24" in message
    assert "not raised for you" in message and "which devices can run the app" in message


@pytest.mark.parametrize("min_sdk", [-1, 0, 1, 10, 20])
def test_nonsense_minimum_levels_are_refused_too(min_sdk):
    assert "is below 24" in problems(min_sdk=min_sdk, target_sdk=35)["min_sdk"]


# --- target SDK ----------------------------------------------------------------------------------


def test_the_contracts_default_target_is_used_as_given_not_the_generators():
    assert TOOLCHAIN.compile_sdk_max == 37
    mapping = config_from_target(Target(target_sdk=35), project_name="Notes App")
    assert mapping.config.target_sdk == 35  # not silently replaced by the generator's 36
    assert any("target_sdk 35 is used as given" in note for note in mapping.notes)
    assert any("generator's default is 36" in note for note in mapping.notes)


def test_a_target_equal_to_the_generators_default_has_no_note():
    assert config_from_target(Target(target_sdk=36), project_name="Notes App").notes == ()


class WithFieldsSet(Target):
    """A pydantic-like target: it knows which fields were given."""

    def __init__(self, fields_set, **kwargs):
        super().__init__(**kwargs)
        self.model_fields_set = fields_set


def test_a_target_that_applied_the_contracts_default_says_so():
    unset = WithFieldsSet({"package_name"}, target_sdk=35)
    notes = config_from_target(unset, project_name="Notes App").notes
    assert notes == (
        "target_sdk was not set: the contract's default 35 is used, not the generator's default 36",
    )
    explicit = WithFieldsSet({"package_name", "target_sdk"}, target_sdk=35)
    assert config_from_target(explicit, project_name="Notes App").notes == (
        "target_sdk 35 is used as given; the generator's default is 36",
    )


def test_a_target_below_the_minimum_is_refused():
    message = problems(min_sdk=30, target_sdk=29)["target_sdk"]
    assert message == "29 is below min_sdk 30"


@pytest.mark.parametrize("target_sdk", [38, 40, 99])
def test_a_target_above_the_pinned_compile_sdk_is_refused(target_sdk):
    message = problems(target_sdk=target_sdk)["target_sdk"]
    assert f"{target_sdk} is above 37" in message and "compile SDK" in message


def test_the_boundaries_of_the_target_are_exact():
    assert (
        config_from_target(Target(target_sdk=37), project_name="Notes App").config.target_sdk == 37
    )
    assert "target_sdk" in problems(target_sdk=38)
    assert (
        config_from_target(Target(min_sdk=30, target_sdk=30), project_name="Notes App").config
    ).target_sdk == 30
    assert "target_sdk" in problems(min_sdk=30, target_sdk=29)


def test_a_minimum_above_the_supported_robolectric_level_gets_a_note_about_the_tests():
    notes = config_from_target(Target(min_sdk=36, target_sdk=36), project_name="Notes App").notes
    assert any("min_sdk 36 is above 35" in note and "navigation tests" in note for note in notes)
    quiet = config_from_target(Target(min_sdk=35, target_sdk=36), project_name="Notes App").notes
    assert not any("navigation tests" in note for note in quiet)


# --- invalid inputs and error quality -----------------------------------------------------


@pytest.mark.parametrize("value", ["24", 24.0, True, None, [24], {"a": 1}])
def test_sdk_levels_must_be_integers(value):
    assert "must be an integer API level" in problems(min_sdk=value)["min_sdk"]
    assert "must be an integer API level" in problems(target_sdk=value)["target_sdk"]


@pytest.mark.parametrize(
    "package",
    ["", "Com.Example", "com..example", ".com.example", "com.example.", "com.class.app", "com.con"],
)
def test_an_invalid_package_name_is_reported_by_the_shared_validator(package):
    found = problems(package_name=package)
    assert list(found) == ["package_name"]
    with pytest.raises(ValueError) as expected:
        validate_package_name(package)
    assert found["package_name"] == str(expected.value)


def test_every_problem_is_reported_at_once():
    found = problems(
        project_name=None, package_name="Bad", language="java", ui="xml", min_sdk=20, target_sdk=99
    )
    assert set(found) == {"project_name", "package_name", "language", "ui", "min_sdk", "target_sdk"}


def test_the_error_is_a_value_error_a_template_error_and_reads_well():
    with pytest.raises(TargetMappingError) as raised:
        config_from_target(Target(language="java", min_sdk=20), project_name=None)
    error = raised.value
    assert isinstance(error, ValueError) and isinstance(error, TemplateError)
    text = str(error)
    assert "\n" not in text  # three problems, one line, in the order the fields are checked
    assert text == "; ".join(str(p) for p in error.problems)
    assert text.startswith("project_name: is required")
    assert "language: 'java' is not supported yet" in text and "min_sdk: 20 is below 24" in text
    assert [(p.field, str(p).startswith(p.field + ": ")) for p in error.problems] == [
        ("project_name", True),
        ("language", True),
        ("min_sdk", True),
    ]


def test_a_target_without_the_attributes_is_refused_by_name():
    class Partial:
        package_name = "com.example.notes"
        language = "kotlin"

    with pytest.raises(TargetMappingError) as raised:
        config_from_target(Partial(), project_name="Notes App")  # type: ignore[arg-type]
    assert [p.field for p in raised.value.problems] == ["ui", "min_sdk", "target_sdk"]
    assert all("no such attribute" in p.message for p in raised.value.problems)


# --- the result is a config the generator accepts -----------------------------------------


def test_the_mapped_config_renders_and_the_review_finds_nothing():
    for kwargs in (
        {},
        {"min_sdk": 26, "target_sdk": 36},
        {"min_sdk": 36, "target_sdk": 37, "package_name": "org.acme.deep.pkg"},
    ):
        config = config_from_target(Target(**kwargs), project_name="R&D Tracker").config
        spec = ProjectSpec(
            screens=(
                ScreenSpec(name="Home", title="Home", navigates_to=("About",)),
                ScreenSpec(name="About", title="About"),
            )
        )
        for with_spec in (None, spec):
            files = {f.path: f.content for f in render_files(config, with_spec)}
            report = ReviewEngine().review(ProjectFiles.from_mapping(files))
            assert report.findings == [], (kwargs, [(f.rule, f.file) for f in report.findings])
            assert f"minSdk = {config.min_sdk}\n" in files["app/build.gradle.kts"]
            assert f"targetSdk = {config.target_sdk}\n" in files["app/build.gradle.kts"]


# --- boundaries of the module ----------------------------------------------------------


def test_the_mapper_imports_neither_the_contracts_nor_orchestration():
    tree = ast.parse(Path(target_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert not [name for name in imported if "contracts" in name or "orchestration" in name]


def test_no_template_module_imports_the_contracts_or_orchestration():
    root = Path(target_module.__file__).parent
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(("import ", "from ")):
                assert "androai_contracts" not in line and "androai_orchestration" not in line, path


# --- the real contract model --------------------------------------------------------------


@pytest.fixture
def contracts():
    return pytest.importorskip("androai_contracts")


def test_the_real_android_target_maps(contracts):
    target = contracts.AndroidTarget(package_name="com.example.notes")
    mapping = config_from_target(target, project_name="Notes App")
    assert (mapping.config.min_sdk, mapping.config.target_sdk) == (24, 35)
    # The contract applied its default target_sdk of 35: the note says so.
    assert mapping.notes[0].startswith("target_sdk was not set: the contract's default 35")


def test_the_real_android_target_with_explicit_values_has_no_default_note(contracts):
    target = contracts.AndroidTarget(package_name="com.example.notes", min_sdk=26, target_sdk=36)
    assert config_from_target(target, project_name="Notes App").notes == ()


def test_the_real_android_target_refuses_what_the_generator_cannot_build(contracts):
    java = contracts.AndroidTarget(package_name="com.example.notes", language="java")
    xml = contracts.AndroidTarget(package_name="com.example.notes", ui="xml")
    low = contracts.AndroidTarget(package_name="com.example.notes", min_sdk=21)
    for target, field in ((java, "language"), (xml, "ui"), (low, "min_sdk")):
        with pytest.raises(TargetMappingError) as raised:
            config_from_target(target, project_name="Notes App")
        assert [p.field for p in raised.value.problems] == [field]


def test_the_contract_fields_the_mapper_reads_still_exist(contracts):
    fields = set(contracts.AndroidTarget.model_fields)
    assert set(target_module._REQUIRED_ATTRIBUTES) <= fields
    # AndroidTarget still has no project name: that is why the caller supplies it.
    assert "project_name" not in fields


def test_a_rule_of_project_config_the_checks_missed_still_becomes_a_mapping_error(monkeypatch):
    # Defensive path: every rule of ProjectConfig is checked first, so real input cannot reach it.
    # A config that raises its own ValidationError must still surface as a TargetMappingError.
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        ProjectConfig(project_name="Notes App", package_name="com.example.notes", min_sdk=1)

    def failing(**_kwargs):
        raise raised.value

    monkeypatch.setattr(target_module, "ProjectConfig", failing)
    with pytest.raises(TargetMappingError) as error:
        config_from_target(Target(), project_name="Notes App")
    assert error.value.__cause__ is raised.value
    assert len(error.value.problems) == len(raised.value.errors())
    assert all(p.field and p.message for p in error.value.problems)
    assert "below 24" in error.value.problems[0].message
