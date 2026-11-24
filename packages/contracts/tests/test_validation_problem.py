"""ValidationProblem: path and code formats, severity, round trip, schema."""

import json
from pathlib import Path

import pytest
from androai_contracts import SCHEMA_VERSION, ProblemSeverity, ValidationProblem
from androai_contracts import validation as v
from pydantic import ValidationError

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def problem(**kwargs) -> ValidationProblem:
    return ValidationProblem(
        **{"path": "screens[2]", "code": "unknown_screen", "message": "m"} | kwargs
    )


def test_a_problem_has_a_path_a_code_a_message_and_defaults_to_an_error():
    p = problem()
    assert (p.path, p.code, p.message) == ("screens[2]", "unknown_screen", "m")
    assert p.severity is ProblemSeverity.ERROR and p.schema_version == SCHEMA_VERSION


def test_a_problem_round_trips_through_json():
    p = problem(severity="warning", path="screens[0].navigates_to[3]")
    assert ValidationProblem.model_validate_json(p.model_dump_json()) == p
    assert json.loads(p.model_dump_json())["severity"] == "warning"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "app_name",
        "screens",
        "screens[0]",
        "screens[12].id",
        "screens[0].navigates_to[7]",
        "a.b.c",
        "start_screen",
        "_x",
        "a_1[10].b_2",
    ],
)
def test_valid_paths(path):
    assert problem(path=path).path == path


@pytest.mark.parametrize(
    "path",
    [
        "Screens",
        "screens[]",
        "screens[-1]",
        "screens[a]",
        "screens.",
        ".screens",
        "screens..id",
        "screens[0][1]",
        "screens[0]id",
        "screens 0",
        "screens/0",
        "1screens",
        "screens[0].",
        "$.x",
        "a" * 201,
        "screens[0]\n",
    ],
)
def test_invalid_paths(path):
    with pytest.raises(ValidationError):
        problem(path=path)


@pytest.mark.parametrize(
    "code", ["unknown_screen", "a", "text.bad_start", "x1", "a.b.c_d"]
)
def test_valid_codes(code):
    assert problem(code=code).code == code


@pytest.mark.parametrize(
    "code",
    ["", "Unknown", "1abc", "a-b", "a..b", ".a", "a.", "a b", "a" * 65, "_a", "a\n"],
)
def test_invalid_codes(code):
    with pytest.raises(ValidationError):
        problem(code=code)


def test_messages_are_required_and_bounded():
    with pytest.raises(ValidationError):
        problem(message="")
    with pytest.raises(ValidationError):
        problem(message="x" * 501)
    assert problem(message="x" * 500)


@pytest.mark.parametrize("severity", ["error", "warning"])
def test_both_severities_are_accepted(severity):
    assert problem(severity=severity).severity.value == severity


def test_an_unknown_severity_and_unknown_fields_are_refused():
    with pytest.raises(ValidationError):
        problem(severity="fatal")
    with pytest.raises(ValidationError):
        ValidationProblem(path="", code="x", message="m", bogus=1)


@pytest.mark.parametrize("missing", ["path", "code", "message"])
def test_required_fields(missing):
    data = {"path": "", "code": "x", "message": "m"}
    del data[missing]
    with pytest.raises(ValidationError) as raised:
        ValidationProblem(**data)
    assert raised.value.errors()[0]["type"] == "missing"


def test_the_schema_carries_the_same_patterns_and_limits():
    schema = json.loads(
        (SCHEMAS / "ValidationProblem.json").read_text(encoding="utf-8")
    )
    assert schema == ValidationProblem.model_json_schema()
    props = schema["properties"]
    assert props["path"]["pattern"] == v.PROBLEM_PATH_PATTERN
    assert props["code"]["pattern"] == v.PROBLEM_CODE_PATTERN
    assert props["code"]["maxLength"] == 64 and props["message"]["maxLength"] == 500
    assert props["path"]["maxLength"] == 200
    assert schema["required"] == ["path", "code", "message"]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["ProblemSeverity"]["enum"] == ["error", "warning"]
