"""AppSpec: valid and invalid documents, error codes and paths, limits, the JSON Schema."""

import json
import random
import unicodedata
from pathlib import Path

import pytest
from androai_contracts import (
    SCHEMA_VERSION,
    AppSpec,
    ProblemSeverity,
    ScreenPlan,
    UnsupportedCategory,
    UnsupportedRequest,
    ValidationProblem,
    appspec,
    graph_problems,
)
from pydantic import ValidationError

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def screen(id_, title=None, targets=(), description=None) -> dict:
    out = {"id": id_, "title": title or id_, "navigates_to": list(targets)}
    if description is not None:
        out["description"] = description
    return out


def spec(*screens, **extra) -> dict:
    return {"app_name": "Notes App", "screens": list(screens), **extra}


THREE = spec(
    screen("Home", "Home", ["Settings", "About"], "Welcome to Notes"),
    screen("Settings", "Settings", ["About"]),
    screen("About", "About & credits", [], "Made with care"),
)


def errors(data) -> list[dict]:
    with pytest.raises(ValidationError) as raised:
        AppSpec.model_validate(data)
    return raised.value.errors()


def first_error(data) -> dict:
    found = errors(data)
    assert len(found) >= 1
    return found[0]


# --- valid documents -----------------------------------------------------------------------------


def test_a_minimal_spec_is_valid_and_gets_its_defaults():
    one = AppSpec.model_validate(spec(screen("Home")))
    assert one.schema_version == SCHEMA_VERSION == "0.1.0"
    assert (
        one.summary is None
        and one.start_screen is None
        and one.unsupported_requests == []
    )
    assert one.start_id == "Home"
    assert one.screens[0].description is None and one.screens[0].navigates_to == []


def test_a_full_spec_round_trips_through_json():
    full = AppSpec.model_validate(
        {
            **THREE,
            "summary": "A small notes app with a settings screen.",
            "start_screen": "Home",
            "unsupported_requests": [
                {
                    "requirement": "Save notes between sessions",
                    "category": "data_storage",
                    "reason": "The generator builds static screens only",
                    "alternative": "A screen that describes how notes would look",
                }
            ],
        }
    )
    assert full.start_id == "Home" and full.start_screen == "Home"
    assert AppSpec.model_validate_json(full.model_dump_json()) == full
    assert AppSpec.model_validate(json.loads(full.model_dump_json())) == full


def test_cycles_a_chosen_start_and_a_start_that_is_not_first_are_valid():
    cycle = AppSpec.model_validate(
        spec(
            screen("Alpha", targets=["Beta"]),
            screen("Beta", targets=["Alpha"]),
            start_screen="Beta",
        )
    )
    assert cycle.start_id == "Beta"


def test_the_limits_themselves_are_valid():
    # Step0 has the maximum of 8 buttons; Step9 to Step11 are reached in a chain behind Step1.
    edges = {0: range(1, 9), 1: [9], 9: [10], 10: [11]}
    twelve = [
        screen(f"Step{i}", targets=[f"Step{j}" for j in edges.get(i, [])])
        for i in range(12)
    ]
    assert len(twelve[0]["navigates_to"]) == 8
    assert len(AppSpec.model_validate(spec(*twelve)).screens) == 12
    long_id = "A" + "b" * 29
    assert AppSpec.model_validate(
        spec(screen(long_id, title="T" * 40, description="d" * 120))
    )
    assert AppSpec.model_validate({**spec(screen("Home")), "app_name": "N" * 50})
    assert AppSpec.model_validate(
        {
            **spec(screen("Home")),
            "summary": "s" * 300,
            "unsupported_requests": [
                {
                    "requirement": "r" * 200,
                    "category": "other",
                    "reason": "x" * 200,
                    "alternative": "a" * 200,
                }
            ]
            * 20,
        }
    )


@pytest.mark.parametrize(
    "text",
    [
        "Home",
        "About & credits",
        "Tom & Jerry's",
        "C++ (beta) + more!",
        "Notes_2 - v1.0",
        "नमस्ते",
        "こんにちは",
        "Привет мир",
        "Ünïcödé",
        "x",
    ],
)
def test_display_text_accepts_letters_digits_marks_and_the_listed_punctuation(text):
    assert (
        AppSpec.model_validate(spec(screen("Home", title=text))).screens[0].title
        == text
    )


@pytest.mark.parametrize(
    "id_", ["A", "Home", "Step0", "HTTPServer", "A1b2", "Settings2Detail"]
)
def test_screen_ids_may_be_pascal_case_ascii_with_digits(id_):
    assert AppSpec.model_validate(spec(screen(id_))).screens[0].id == id_


def test_texts_are_normalised_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Café")
    assert decomposed != "Café"
    assert (
        AppSpec.model_validate(spec(screen("Home", title=decomposed))).screens[0].title
        == "Café"
    )


# --- screen ids -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_",
    [
        "home",
        "1Home",
        "Home_Page",
        "Home-Page",
        "Home Page",
        "Hôme",
        "Главная",
        "",
        "A" * 31,
    ],
)
def test_invalid_screen_ids_are_refused(id_):
    assert first_error(spec(screen(id_)))["loc"][:3] == ("screens", 0, "id")


@pytest.mark.parametrize(
    "id_",
    [
        "Home" + chr(0x0A),  # a trailing newline must not slip past "$"
        "Home" + chr(0x0D) + chr(0x0A),
        chr(0x20) + "Home",
        "Home" + chr(0x200B),  # zero-width space
        chr(0xFF28) + "ome",  # full-width H
        chr(0x212A) + "ing",  # Kelvin sign, lower-cases to a plain k
        "Home" + chr(0x0663),  # Arabic-Indic digit three, \d in some engines
        "Home" + chr(0x00B2),  # superscript two
        "Home" + chr(0x0301),  # combining acute
        "H" + chr(0x0435) + "me",  # Cyrillic e inside Latin letters
    ],
)
def test_ids_are_ascii_only_and_a_lookalike_or_trailing_character_is_refused(id_):
    for data in (
        spec(screen(id_)),
        spec(screen("Home", targets=[id_])),
        spec(screen("Home"), start_screen=id_),
    ):
        error = first_error(data)
        assert error["type"] in ("string_pattern_mismatch", "string_too_long"), error


def test_the_start_screen_and_the_targets_use_the_same_id_rule_as_the_id(schema):
    plan = schema["$defs"]["ScreenPlan"]["properties"]
    start = schema["properties"]["start_screen"]["anyOf"][0]
    for rule in (plan["id"], plan["navigates_to"]["items"], start):
        assert rule["pattern"] == appspec.SCREEN_ID_PATTERN == "^[A-Z][A-Za-z0-9]*$"
        assert (
            rule["minLength"] == 1 and rule["maxLength"] == appspec.MAX_SCREEN_ID_LENGTH
        )


@pytest.mark.parametrize("id_", ["HomeScreen", "Screen", "SettingsScreen"])
def test_an_id_ending_in_screen_is_refused_with_a_stable_code(id_):
    error = first_error(spec(screen(id_)))
    assert error["type"] == "reserved_suffix" and error["loc"] == ("screens", 0, "id")


def test_the_screen_suffix_is_refused_in_a_target_too():
    error = first_error(spec(screen("Home", targets=["AboutScreen"])))
    assert error["type"] == "reserved_suffix"
    assert error["loc"] == ("screens", 0, "navigates_to", 0)


def test_ids_that_differ_only_in_case_are_duplicates():
    error = first_error(spec(screen("Home"), screen("HOME")))
    assert (
        error["type"] == "duplicate_screen_id"
        and error["ctx"]["path"] == "screens[1].id"
    )
    assert "ignored" not in error["msg"] and "ignoring letter case" in error["msg"]
    # the message names the offending id and the earlier screen it repeats, so a retry knows what to change
    assert (
        "'HOME'" in error["msg"]
        and "screens[0]" in error["msg"]
        and "'Home'" in error["msg"]
    )


def test_the_same_id_twice_is_a_duplicate():
    assert (
        first_error(spec(screen("Home"), screen("Home")))["type"]
        == "duplicate_screen_id"
    )


# --- display text and plain text ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, code",
    [
        (" Home", "text_not_trimmed"),
        ("Home ", "text_not_trimmed"),
        ("Two  spaces", "text_double_space"),
        ("-Home", "text_bad_start"),
        ("(Home)", "text_bad_start"),
        ("Home <b>", "text_bad_characters"),
        ('Say "hi"', "text_bad_characters"),
        ("a\\b", "text_bad_characters"),
        ("a$b", "text_bad_characters"),
        ("a@b", "text_bad_characters"),
        ("what?", "text_bad_characters"),
        ("50%", "text_bad_characters"),
        ("a:b", "text_bad_characters"),
        ("a/b", "text_bad_characters"),
        ("a\nb", "text_bad_characters"),
        ("a\tb", "text_bad_characters"),
        ("zero\u200bwidth", "text_bad_characters"),
        ("bidi\u202eflip", "text_bad_characters"),
        ("emoji \U0001f600", "text_bad_characters"),
        ("{placeholder}", "text_bad_characters"),
    ],
)
def test_display_text_rules_use_stable_codes(text, code):
    error = first_error(spec(screen("Home", title=text)))
    assert error["type"] == code and error["loc"] == ("screens", 0, "title")


@pytest.mark.parametrize("ch", list('<>"\\$@?%:/{}[]|;=*#~^`'))
def test_each_character_outside_the_allowed_set_is_refused_on_its_own(ch):
    error = first_error(spec(screen("Home", title=f"a{ch}b")))
    assert error["type"] == "text_bad_characters" and repr(ch) in error["msg"]


@pytest.mark.parametrize("mark", [0x0301, 0x093E, 0x0E31])
def test_a_combining_mark_may_be_inside_a_text_but_cannot_start_one(mark):
    assert AppSpec.model_validate(spec(screen("Home", title="a" + chr(mark))))
    error = first_error(spec(screen("Home", title=chr(mark) + "a")))
    assert error["type"] == "text_bad_start"


def test_a_text_that_normalisation_makes_longer_is_measured_after_it():
    # U+0958 is one character that NFC turns into two: 40 of them pass the length limit of the
    # schema (40) and are 80 characters long once normalised.
    long_text = chr(0x0958) * 40
    assert len(unicodedata.normalize("NFC", long_text)) == 80
    assert first_error(spec(screen("Home", title=long_text)))["type"] == "text_length"
    ok = chr(0x0958) * 20
    assert AppSpec.model_validate(spec(screen("Home", title=ok))).screens[0].title == (
        unicodedata.normalize("NFC", ok)
    )


@pytest.mark.parametrize("field", ["app_name", "title", "description"])
def test_every_display_text_field_applies_the_rules(field):
    if field == "app_name":
        data = {**spec(screen("Home")), "app_name": "Bad <name>"}
    else:
        data = spec(
            screen("Home", **({"title": "Bad <t>"} if field == "title" else {}))
        )
        if field == "description":
            data["screens"][0]["description"] = "Bad <d>"
    assert first_error(data)["type"] == "text_bad_characters"


@pytest.mark.parametrize("value", ["", None, 5, [], {}])
def test_an_empty_or_mistyped_title_is_refused(value):
    data = spec(screen("Home"))
    data["screens"][0]["title"] = value
    assert errors(data)


def test_length_limits_are_enforced_for_every_text():
    for field, limit in (("app_name", 50),):
        assert errors({**spec(screen("Home")), field: "x" * (limit + 1)})
    assert errors(spec(screen("Home", title="x" * 41)))
    assert errors(spec(screen("Home", description="x" * 121)))
    assert errors({**spec(screen("Home")), "summary": "x" * 301})


@pytest.mark.parametrize(
    "text",
    [
        "line\nbreak",
        "tab\there",
        "nul\x00",
        "bell\x07",
        "a\u2028b",
        "\u200bhidden",
        "private\ue000use",
    ],
)
def test_plain_text_is_one_line_without_control_or_invisible_characters(text):
    error = first_error({**spec(screen("Home")), "summary": text})
    assert error["type"] == "text_control_characters" and error["loc"] == ("summary",)


@pytest.mark.parametrize(
    "text",
    ["Saves notes, with a <b>tag</b> & more: 100%?", "Zażółć gęślą jaźń", "नमस्ते दुनिया"],
)
def test_plain_text_may_hold_ordinary_sentences_because_it_is_never_put_into_code(text):
    assert (
        AppSpec.model_validate({**spec(screen("Home")), "summary": text}).summary
        == text
    )


def test_plain_text_must_be_trimmed():
    assert (
        first_error({**spec(screen("Home")), "summary": " x"})["type"]
        == "text_not_trimmed"
    )


# --- the screen graph -------------------------------------------------------------------------------


def test_no_screens_and_too_many_screens_are_refused():
    assert errors({"app_name": "Notes App", "screens": []})[0]["loc"] == ("screens",)
    many = [screen(f"S{i}", targets=[f"S{i + 1}"] if i < 12 else []) for i in range(13)]
    assert errors(spec(*many))[0]["loc"] == ("screens",)


def test_more_than_eight_buttons_on_a_screen_are_refused():
    targets = [f"T{i}" for i in range(9)]
    data = spec(screen("Home", targets=targets), *[screen(t) for t in targets])
    assert first_error(data)["loc"] == ("screens", 0, "navigates_to")


def test_an_unknown_target_is_refused_with_its_path():
    error = first_error(
        spec(screen("Home", targets=["About", "Nowhere"]), screen("About"))
    )
    assert error["type"] == "unknown_screen"
    assert error["ctx"]["path"] == "screens[0].navigates_to[1]"
    assert "'Nowhere'" in error["msg"]


def test_a_screen_cannot_open_itself():
    error = first_error(spec(screen("Home", targets=["Home"])))
    assert (
        error["type"] == "self_navigation"
        and error["ctx"]["path"] == "screens[0].navigates_to[0]"
    )


def test_a_repeated_button_is_refused():
    error = first_error(
        spec(screen("Home", targets=["About", "About"]), screen("About"))
    )
    assert error["type"] == "duplicate_navigation"
    assert error["ctx"]["path"] == "screens[0].navigates_to[1]"


def test_an_unknown_start_screen_is_refused():
    error = first_error(spec(screen("Home"), start_screen="Nowhere"))
    assert (
        error["type"] == "unknown_start_screen"
        and error["ctx"]["path"] == "start_screen"
    )


def test_an_unreachable_screen_is_refused_with_its_index():
    error = first_error(spec(screen("Home"), screen("Island")))
    assert (
        error["type"] == "unreachable_screen" and error["ctx"]["path"] == "screens[1]"
    )
    assert "'Island'" in error["msg"] and "'Home'" in error["msg"]


def test_reachability_is_measured_from_the_chosen_start():
    # Home opens About, but the app starts on About, which opens nothing: Home is unreachable.
    data = spec(
        screen("Home", targets=["About"]), screen("About"), start_screen="About"
    )
    assert first_error(data)["ctx"]["path"] == "screens[0]"


def test_reachability_follows_chains_and_ignores_the_direction_of_the_list():
    chain = spec(
        screen("C"),
        screen("B", targets=["C"]),
        screen("A", targets=["B"]),
        start_screen="A",
    )
    assert AppSpec.model_validate(chain)


def test_every_graph_problem_is_listed_in_the_error_context():
    data = spec(
        screen("Home", targets=["Home", "Nowhere", "About", "About"]),
        screen("About"),
        screen("ABOUT"),
        screen("Island"),
    )
    error = first_error(data)
    problems = [ValidationProblem.model_validate(p) for p in error["ctx"]["problems"]]
    assert [(p.code, p.path) for p in problems] == [
        ("duplicate_screen_id", "screens[2].id"),
        ("self_navigation", "screens[0].navigates_to[0]"),
        ("unknown_screen", "screens[0].navigates_to[1]"),
        ("duplicate_navigation", "screens[0].navigates_to[3]"),
        ("unreachable_screen", "screens[2]"),  # ABOUT: nothing opens it
        ("unreachable_screen", "screens[3]"),  # Island
    ]
    assert all(p.severity is ProblemSeverity.ERROR for p in problems)
    assert (
        error["type"] == problems[0].code and error["ctx"]["path"] == problems[0].path
    )


def test_graph_problems_can_be_called_on_screens_directly_and_is_empty_when_fine():
    screens = [
        ScreenPlan(id="Home", title="Home", navigates_to=["About"]),
        ScreenPlan(id="About", title="About"),
    ]
    assert graph_problems(screens, None) == []
    assert graph_problems(screens, "About")[0].code == "unreachable_screen"
    assert graph_problems(screens, "Nope")[0].code == "unknown_start_screen"


def test_problem_paths_always_match_the_documented_path_format():
    data = spec(screen("Home", targets=["Home", "X"]), screen("Y"), start_screen="Z")
    for problem in graph_problems(
        [ScreenPlan.model_validate(s) for s in data["screens"]], data["start_screen"]
    ):
        ValidationProblem.model_validate(
            problem.model_dump()
        )  # path and code patterns hold


# --- graph_problems reports every problem, with stable codes and accurate paths ------------------------

GRAPH_CODES = {
    "duplicate_screen_id",
    "unknown_start_screen",
    "self_navigation",
    "unknown_screen",
    "duplicate_navigation",
    "unreachable_screen",
}


def resolve(data, path: str):
    """The value a problem path points at in the raw input (``screens[2].navigates_to[0]``)."""
    node = data
    for part in path.split("."):
        name, _, index = part.partition("[")
        node = node[name]
        if index:
            node = node[int(index.rstrip("]"))]
    return node


def plans(data) -> list[ScreenPlan]:
    return [ScreenPlan.model_validate(s) for s in data["screens"]]


def pairs(data) -> list[tuple[str, str]]:
    return [
        (p.code, p.path) for p in graph_problems(plans(data), data.get("start_screen"))
    ]


def test_every_kind_of_problem_in_one_document_is_reported_in_a_fixed_order():
    data = spec(
        screen("Home", targets=["Home", "Ghost", "About", "About", "Ghost"]),
        screen("About", targets=["Settings"]),
        screen("ABOUT"),
        screen("Settings"),
        screen("Island", targets=["Island", "Nowhere"]),
    )
    found = pairs(data)
    assert found == [
        ("duplicate_screen_id", "screens[2].id"),
        ("self_navigation", "screens[0].navigates_to[0]"),
        ("unknown_screen", "screens[0].navigates_to[1]"),
        ("duplicate_navigation", "screens[0].navigates_to[3]"),
        ("unknown_screen", "screens[0].navigates_to[4]"),
        ("self_navigation", "screens[4].navigates_to[0]"),
        ("unknown_screen", "screens[4].navigates_to[1]"),
        ("unreachable_screen", "screens[2]"),  # ABOUT: no button opens it
        ("unreachable_screen", "screens[4]"),  # Island
    ]
    assert {code for code, _ in found} == GRAPH_CODES - {"unknown_start_screen"}


def test_a_missing_start_screen_is_reported_and_reachability_is_not_guessed():
    data = spec(
        screen("Home", targets=["About"]),
        screen("About"),
        screen("Island"),
        start_screen="Nope",
    )
    assert pairs(data) == [("unknown_start_screen", "start_screen")]


def test_a_missing_start_screen_does_not_hide_the_other_problems():
    data = spec(screen("Home", targets=["Ghost"]), start_screen="Nope")
    assert pairs(data) == [
        ("unknown_start_screen", "start_screen"),
        ("unknown_screen", "screens[0].navigates_to[0]"),
    ]


def test_reachability_is_still_reported_when_ids_are_duplicated():
    data = spec(screen("Home"), screen("HOME"), screen("Island"))
    assert pairs(data) == [
        ("duplicate_screen_id", "screens[1].id"),
        ("unreachable_screen", "screens[1]"),
        ("unreachable_screen", "screens[2]"),
    ]


def test_when_two_screens_share_an_id_the_first_one_is_the_one_buttons_refer_to():
    # The second Home has the button, the first has none: About cannot be reached.
    data = spec(screen("Home"), screen("Home", targets=["About"]), screen("About"))
    assert pairs(data) == [
        ("duplicate_screen_id", "screens[1].id"),
        ("unreachable_screen", "screens[2]"),
    ]
    # With the buttons on the first Home, everything is reachable and only the duplicate remains.
    data = spec(screen("Home", targets=["About"]), screen("Home"), screen("About"))
    assert pairs(data) == [("duplicate_screen_id", "screens[1].id")]


def test_repeated_offences_are_each_reported_at_their_own_button():
    data = spec(
        screen(
            "Home",
            targets=["Home", "Home", "Ghost", "Ghost", "About", "About", "About"],
        ),
        screen("About"),
    )
    assert pairs(data) == [
        ("self_navigation", "screens[0].navigates_to[0]"),
        ("self_navigation", "screens[0].navigates_to[1]"),
        ("unknown_screen", "screens[0].navigates_to[2]"),
        ("unknown_screen", "screens[0].navigates_to[3]"),
        ("duplicate_navigation", "screens[0].navigates_to[5]"),
        ("duplicate_navigation", "screens[0].navigates_to[6]"),
    ]


def test_three_screens_with_one_id_are_two_duplicates():
    data = spec(screen("Home"), screen("Home"), screen("HOME"))
    assert pairs(data)[:2] == [
        ("duplicate_screen_id", "screens[1].id"),
        ("duplicate_screen_id", "screens[2].id"),
    ]


def test_reachability_uses_the_chosen_start_for_every_report():
    data = spec(
        screen("Home", targets=["About"]),
        screen("About", targets=["Home"]),
        screen("Island"),
        screen("Lonely", targets=["Island"]),
        start_screen="About",
    )
    # Starting at About reaches Home and About only; Island is opened by Lonely, which nothing opens.
    assert pairs(data) == [
        ("unreachable_screen", "screens[2]"),
        ("unreachable_screen", "screens[3]"),
    ]
    assert pairs({k: v for k, v in data.items() if k != "start_screen"}) == [
        ("unreachable_screen", "screens[2]"),
        ("unreachable_screen", "screens[3]"),
    ]  # the default start (Home) gives the same answer here


def test_every_problem_path_points_at_what_the_message_names():
    data = spec(
        screen("Home", targets=["Home", "Ghost", "About", "About"]),
        screen("About"),
        screen("ABOUT"),
        screen("Island", targets=["Nowhere"]),
        start_screen="Home",
    )
    for problem in graph_problems(plans(data), data["start_screen"]):
        value = resolve(data, problem.path)
        if problem.code == "duplicate_screen_id":
            assert value == data["screens"][int(problem.path[8:].split("]")[0])]["id"]
            assert repr(value) in problem.message
        elif problem.code in (
            "self_navigation",
            "unknown_screen",
            "duplicate_navigation",
        ):
            assert isinstance(value, str) and repr(value) in problem.message
            screen_index = int(problem.path[8:].split("]")[0])
            assert repr(data["screens"][screen_index]["id"]) in problem.message
        elif problem.code == "unreachable_screen":
            assert repr(value["id"]) in problem.message
            assert repr(data["start_screen"]) in problem.message


def test_the_start_screen_path_points_at_the_start_value():
    data = spec(screen("Home"), start_screen="Nope")
    (problem,) = graph_problems(plans(data), data["start_screen"])
    assert resolve(data, problem.path) == "Nope" and "'Nope'" in problem.message


def test_problems_are_stable_complete_json_and_valid_contract_objects():
    data = spec(
        screen("Home", targets=["Ghost", "Home"]),
        screen("Island"),
        screen("ISLAND"),
    )
    first = graph_problems(plans(data), None)
    assert first == graph_problems(plans(data), None)
    assert len(first) == 5
    for problem in first:
        assert problem.severity is ProblemSeverity.ERROR
        assert (
            ValidationProblem.model_validate_json(problem.model_dump_json()) == problem
        )
        assert json.loads(
            json.dumps(problem.model_dump(mode="json"))
        ) == problem.model_dump(mode="json")
    with pytest.raises(ValidationError) as raised:
        AppSpec.model_validate(data)
    (error,) = raised.value.errors()
    assert [
        ValidationProblem.model_validate(p) for p in error["ctx"]["problems"]
    ] == first
    assert error["type"] == first[0].code and error["ctx"]["path"] == first[0].path


def test_a_valid_graph_has_no_problems_and_an_invalid_one_never_validates():
    # Seeded random graphs: graph_problems is empty exactly when AppSpec accepts the document.
    rng = random.Random(20261121)
    for _ in range(400):
        count = rng.randint(1, 12)
        names = [f"Sc{chr(65 + i)}" for i in range(count)]
        if rng.random() < 0.2 and count > 2:
            names[1] = (
                names[0].upper() if rng.random() < 0.5 else names[0]
            )  # SCA / ScA again
        screens = []
        for name in names:
            pool = names + (["Ghost"] if rng.random() < 0.2 else [])
            targets = [rng.choice(pool) for _ in range(rng.randint(0, 4))]
            screens.append(screen(name, targets=targets))
        data = spec(
            *screens, start_screen=rng.choice([None, None, rng.choice(names), "Nope"])
        )
        found = pairs(data)
        assert {code for code, _ in found} <= GRAPH_CODES
        for code, path in found:
            ValidationProblem(path=path, code=code, message="m")  # format holds
            assert resolve(data, path) is not None
        if found:
            with pytest.raises(ValidationError):
                AppSpec.model_validate(data)
        else:
            assert AppSpec.model_validate(data)


# --- oversized or malformed input gives a controlled result, never an unexpected exception ---------------

HUGE = 1_000_000


class HugeRepr:
    def __repr__(self) -> str:
        return "H" * HUGE


BAD_STARTS = {
    "one over the id limit": "X" * 31,
    "a thousand characters": "X" * 1_000,
    "a million characters": "X" * HUGE,
    "a real id followed by a million characters": "Home" + "x" * HUGE,
    "characters that escape to ten in a repr": chr(0x10FFFF) * 5_000,
    "lone surrogates": chr(0xD800) * 5_000,
    "newlines": "\n" * 5_000,
    "both quote marks": "'" * 5_000 + '"' * 5_000,
    "empty string": "",
    "an id that does not exist": "Nope",
    "an int": 12345,
    "a float": 1.5,
    "bytes": b"Home",
    "an unhashable list": ["Home"],
    "an unhashable dict": {"id": "Home"},
    "an object with a million-character repr": HugeRepr(),
}


@pytest.mark.parametrize("start", list(BAD_STARTS.values()), ids=list(BAD_STARTS))
def test_a_start_screen_that_is_not_a_screen_id_is_a_problem_whatever_its_size_or_type(
    start,
):
    screens = plans(spec(screen("Home", targets=["About"]), screen("About")))
    problems = graph_problems(screens, start)
    assert [(p.code, p.path) for p in problems] == [
        ("unknown_start_screen", "start_screen")
    ]
    (problem,) = problems
    assert problem.severity is ProblemSeverity.ERROR
    # a short, readable excerpt of the value, not the value
    assert 1 <= len(problem.message) <= 120 and problem.message.isprintable()
    assert ValidationProblem.model_validate_json(problem.model_dump_json()) == problem


def test_an_oversized_start_screen_does_not_hide_the_other_problems():
    screens = plans(spec(screen("Home", targets=["Ghost", "Home"])))
    assert [(p.code, p.path) for p in graph_problems(screens, "X" * HUGE)] == [
        ("unknown_start_screen", "start_screen"),
        ("unknown_screen", "screens[0].navigates_to[0]"),
        ("self_navigation", "screens[0].navigates_to[1]"),
    ]


def test_every_kind_of_problem_stays_short_even_for_screens_built_without_validation():
    # ScreenPlan.model_construct skips validation: ids of a million characters reach graph_problems.
    first, second = "A" * HUGE, "C" * HUGE
    screens = [
        ScreenPlan.model_construct(
            id=first,
            title="T",
            description=None,
            navigates_to=[first, "B" * HUGE, second, second],
        ),
        ScreenPlan.model_construct(
            id=second, title="T", description=None, navigates_to=[]
        ),
        ScreenPlan.model_construct(
            id=first.lower(), title="T", description=None, navigates_to=[]
        ),
    ]
    problems = graph_problems(screens, None)
    assert {p.code for p in problems} == GRAPH_CODES - {"unknown_start_screen"}
    assert all(len(p.message) <= 200 for p in problems), [
        len(p.message) for p in problems
    ]
    assert [p.path for p in problems] == [
        "screens[2].id",
        "screens[0].navigates_to[0]",
        "screens[0].navigates_to[1]",
        "screens[0].navigates_to[3]",
        "screens[2]",
    ]


def test_a_quoted_value_is_cut_to_forty_characters_and_a_valid_id_is_shown_in_full():
    shown = appspec._shown
    assert shown("A" * 30) == repr("A" * 30)  # the longest valid id, quoted in full
    assert len(shown("A" * 38)) == 40 and shown("A" * 38) == repr("A" * 38)
    for value in ("A" * 39, "A" * 41, "A" * HUGE, chr(0x10FFFF) * 100, HugeRepr()):
        text = shown(value)
        assert len(text) == 40 and text.endswith("...")
    assert shown(None) == "None" and shown(7) == "7"


@pytest.mark.parametrize(
    "case",
    [
        "start_screen",
        "screen id",
        "navigation target",
        "app name",
        "title",
        "description",
        "summary",
        "unsupported requirement",
        "unsupported reason",
        "many screens",
        "many buttons",
        "many unsupported requests",
    ],
)
def test_oversized_input_anywhere_is_a_validation_error_and_nothing_else(case):
    big = "A" * HUGE
    unsupported = {"requirement": "r", "category": "other", "reason": "r"}
    documents = {
        "start_screen": spec(screen("Home"), start_screen=big),
        "screen id": spec(screen(big)),
        "navigation target": spec(screen("Home", targets=[big])),
        "app name": {**spec(screen("Home")), "app_name": big},
        "title": spec(screen("Home", title=big)),
        "description": spec(screen("Home", description=big)),
        "summary": spec(screen("Home"), summary=big),
        "unsupported requirement": spec(
            screen("Home"), unsupported_requests=[{**unsupported, "requirement": big}]
        ),
        "unsupported reason": spec(
            screen("Home"), unsupported_requests=[{**unsupported, "reason": big}]
        ),
        "many screens": spec(*[screen(f"S{i}") for i in range(5_000)]),
        "many buttons": spec(screen("Home", targets=[f"S{i}" for i in range(5_000)])),
        "many unsupported requests": spec(
            screen("Home"), unsupported_requests=[unsupported] * 5_000
        ),
    }
    data = documents[case]
    for parse in (
        lambda: AppSpec.model_validate(data),
        lambda: AppSpec.model_validate_json(json.dumps(data)),
    ):
        with pytest.raises(ValidationError) as raised:
            parse()
        found = raised.value.errors()
        assert found and all(
            e["type"] in ("string_too_long", "too_long") for e in found
        ), found[:3]
        assert len(json.loads(raised.value.json())) == len(found)


def test_the_worst_case_document_gives_one_bounded_complete_error():
    # 12 screens, 6 of them case-duplicates, each with 8 buttons to a screen that does not exist.
    names = [f"S{c}" for c in "abcdef"] + [f"S{c.upper()}" for c in "abcdef"]
    data = spec(*[screen(n, targets=["Ghost"] * 8) for n in names])
    with pytest.raises(ValidationError) as raised:
        AppSpec.model_validate(data)
    (error,) = raised.value.errors()
    problems = [ValidationProblem.model_validate(p) for p in error["ctx"]["problems"]]
    kinds = [p.code for p in problems]
    assert kinds.count("duplicate_screen_id") == 6
    assert kinds.count("unknown_screen") == 96
    assert kinds.count("unreachable_screen") == 11  # only the start screen is reached
    assert len(problems) == 113 and error["type"] == "duplicate_screen_id"
    assert len(json.loads(raised.value.json())[0]["ctx"]["problems"]) == 113


# --- the start screen defaults to the first screen, also after a round trip -------------------------


def test_an_omitted_start_screen_means_the_first_screen_after_every_kind_of_round_trip():
    parsed = AppSpec.model_validate(THREE)
    assert parsed.start_screen is None and parsed.start_id == "Home"
    trips = [
        AppSpec.model_validate_json(parsed.model_dump_json()),
        AppSpec.model_validate(parsed.model_dump()),
        AppSpec.model_validate(parsed.model_dump(mode="json")),
        AppSpec.model_validate(parsed.model_dump(exclude_none=True)),
        AppSpec.model_validate(parsed.model_dump(exclude_defaults=True)),
        AppSpec.model_validate_json(parsed.model_dump_json(exclude_unset=True)),
        AppSpec.model_validate(json.loads(json.dumps(parsed.model_dump(mode="json")))),
        parsed.model_copy(deep=True),
    ]
    for trip in trips:
        assert trip.start_screen is None and trip.start_id == "Home" and trip == parsed


def test_an_explicit_null_and_an_omitted_start_screen_are_the_same_document():
    omitted = AppSpec.model_validate(THREE)
    explicit_null = AppSpec.model_validate({**THREE, "start_screen": None})
    assert omitted == explicit_null and explicit_null.start_id == "Home"
    assert "start_screen" not in json.loads(omitted.model_dump_json(exclude_none=True))
    assert json.loads(omitted.model_dump_json())["start_screen"] is None


def test_the_first_screen_in_the_list_is_the_default_start_whatever_its_name():
    reordered = spec(screen("About", targets=["Home"]), screen("Home"))
    parsed = AppSpec.model_validate_json(json.dumps(reordered))
    assert parsed.start_id == "About"
    assert AppSpec.model_validate_json(parsed.model_dump_json()).start_id == "About"


def test_an_explicit_start_survives_a_round_trip_and_beats_the_default():
    parsed = AppSpec.model_validate(
        spec(
            screen("Home", targets=["About"]),
            screen("About", targets=["Home"]),
            start_screen="About",
        )
    )
    again = AppSpec.model_validate_json(parsed.model_dump_json())
    assert (
        again.start_screen == "About" == again.start_id == parsed.start_id
        and again == parsed
    )


def test_the_default_start_is_in_the_schema_as_null_with_the_rule_in_words(schema):
    start = schema["properties"]["start_screen"]
    assert start["default"] is None and "first screen" in start["description"]


def test_start_id_and_graph_problems_agree_on_the_default_start():
    # Island is only opened by Home; with the first screen as the (default) start it is reachable,
    # with Island as the start Home is not.
    data = spec(screen("Home", targets=["Island"]), screen("Island"))
    assert pairs(data) == []
    assert pairs({**data, "start_screen": "Island"}) == [
        ("unreachable_screen", "screens[0]")
    ]


# --- strictness ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["root", "screen", "unsupported"])
def test_unknown_fields_are_refused_at_every_level(where):
    data = spec(
        screen("Home"),
        unsupported_requests=[{"requirement": "r", "category": "other", "reason": "x"}],
    )
    if where == "root":
        data["bogus"] = 1
    elif where == "screen":
        data["screens"][0]["bogus"] = 1
    else:
        data["unsupported_requests"][0]["bogus"] = 1
    assert errors(data)[0]["type"] == "extra_forbidden"


def test_android_settings_and_the_package_name_are_not_part_of_the_spec():
    for field in (
        "package_name",
        "target",
        "min_sdk",
        "target_sdk",
        "language",
        "ui",
        "project_name",
        "dependencies",
        "architecture",
        "steps",
    ):
        assert (
            errors({**spec(screen("Home")), field: "x"})[0]["type"] == "extra_forbidden"
        ), field


@pytest.mark.parametrize(
    "data", [None, [], "text", 5, {}, {"app_name": "x"}, {"screens": []}]
)
def test_a_document_of_the_wrong_shape_is_refused(data):
    with pytest.raises(ValidationError):
        AppSpec.model_validate(data)


def test_wrong_types_are_not_coerced():
    assert errors({**spec(screen("Home")), "app_name": 5})
    assert errors(spec({"id": 7, "title": "x"}))
    assert errors(spec(screen("Home"), start_screen=3))
    assert errors(spec({"id": "Home", "title": "Home", "navigates_to": "About"}))


# --- unsupported requests -----------------------------------------------------------------------------


def test_every_category_is_accepted_and_the_set_is_what_the_schema_says():
    for category in UnsupportedCategory:
        item = UnsupportedRequest.model_validate(
            {"requirement": "r", "category": category.value, "reason": "x"}
        )
        assert item.category is category
    assert {c.value for c in UnsupportedCategory} == {
        "data_storage",
        "authentication",
        "user_input",
        "search",
        "lists_and_media",
        "networking",
        "app_logic",
        "device_features",
        "distribution",
        "other",
    }


def test_an_unknown_category_is_refused():
    assert errors(
        spec(
            screen("Home"),
            unsupported_requests=[
                {"requirement": "r", "category": "magic", "reason": "x"}
            ],
        )
    )


def test_an_unsupported_request_needs_its_requirement_and_reason():
    for missing in ("requirement", "category", "reason"):
        item = {"requirement": "r", "category": "other", "reason": "x"}
        del item[missing]
        assert (
            errors(spec(screen("Home"), unsupported_requests=[item]))[0]["type"]
            == "missing"
        )


def test_more_than_twenty_unsupported_requests_are_refused():
    item = {"requirement": "r", "category": "other", "reason": "x"}
    assert errors(spec(screen("Home"), unsupported_requests=[item] * 21))[0]["loc"] == (
        "unsupported_requests",
    )


def test_unsupported_requests_never_change_the_screen_rules():
    data = spec(
        screen("Home"),
        screen("Island"),
        unsupported_requests=[
            {
                "requirement": "Login",
                "category": "authentication",
                "reason": "Not supported",
            }
        ],
    )
    assert first_error(data)["type"] == "unreachable_screen"


# --- the JSON Schema ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads((SCHEMAS / "AppSpec.json").read_text(encoding="utf-8"))


def test_the_committed_schema_is_what_the_model_generates(schema):
    assert schema == AppSpec.model_json_schema()
    assert (SCHEMAS / "AppSpec.json").read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    ) == (json.dumps(AppSpec.model_json_schema(), indent=2) + "\n")


def test_the_schema_states_the_limits_and_forbids_unknown_fields(schema):
    props = schema["properties"]
    assert schema["additionalProperties"] is False and schema["required"] == [
        "app_name",
        "screens",
    ]
    assert (
        props["screens"]["minItems"] == 1
        and props["screens"]["maxItems"] == appspec.MAX_SCREENS == 12
    )
    assert props["unsupported_requests"]["maxItems"] == 20
    assert props["app_name"]["maxLength"] == 50 and props["app_name"]["minLength"] == 1
    plan = schema["$defs"]["ScreenPlan"]
    assert plan["additionalProperties"] is False and plan["required"] == ["id", "title"]
    assert plan["properties"]["id"]["pattern"] == "^[A-Z][A-Za-z0-9]*$"
    assert plan["properties"]["id"]["maxLength"] == 30
    assert plan["properties"]["title"]["maxLength"] == 40
    assert plan["properties"]["navigates_to"]["maxItems"] == 8
    assert (
        plan["properties"]["navigates_to"]["items"]["pattern"] == "^[A-Z][A-Za-z0-9]*$"
    )
    assert schema["$defs"]["UnsupportedRequest"]["required"] == [
        "requirement",
        "category",
        "reason",
    ]


def test_the_schema_explains_itself_to_a_reader_who_never_sees_the_python(schema):
    assert "Rules beyond the field limits" in schema["description"]
    assert "AndroidTarget" in schema["description"]
    for name, definition in {
        **schema["properties"],
        **schema["$defs"]["ScreenPlan"]["properties"],
    }.items():
        if name != "schema_version":
            assert definition.get("description"), name


def test_the_schema_does_not_leak_android_settings(schema):
    assert not {"package_name", "target", "min_sdk", "target_sdk", "language"} & set(
        schema["properties"]
    )


def test_constants_match_the_schema_and_each_other():
    assert (appspec.MAX_SCREENS, appspec.MAX_NAVIGATION_PER_SCREEN) == (12, 8)
    assert (
        appspec.MAX_TITLE_LENGTH,
        appspec.MAX_DESCRIPTION_LENGTH,
        appspec.MAX_SCREEN_ID_LENGTH,
    ) == (40, 120, 30)
    assert appspec.SCREEN_ID_PATTERN == "^[A-Z][A-Za-z0-9]*$"
