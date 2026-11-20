"""ProjectSpec / ScreenSpec: names, routes, texts, edges, reachability and limits."""

import pytest
from pydantic import ValidationError

from androai_codegen.templates import (
    ProjectSpec,
    ScreenSpec,
    route_constant,
    route_of,
    validate_display_text,
    validate_screen_name,
)
from androai_codegen.templates.spec import (
    MAX_DESCRIPTION_LENGTH,
    MAX_EDGES_PER_SCREEN,
    MAX_SCREEN_NAME_LENGTH,
    MAX_SCREENS,
    MAX_TITLE_LENGTH,
)


def screen(name="Home", title="Home", **kwargs) -> ScreenSpec:
    return ScreenSpec(name=name, title=title, **kwargs)


def spec_of(*screens: ScreenSpec, **kwargs) -> ProjectSpec:
    return ProjectSpec(screens=screens, **kwargs)


# --- screen names ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Home",
        "A",
        "SettingsDetail",
        "Step2",
        "OAuth",
        "HTTPServer",
        "Item10",
        "A" * MAX_SCREEN_NAME_LENGTH,
    ],
)
def test_valid_screen_names(name):
    assert validate_screen_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "home",
        "settings",
        "1Home",
        "_Home",
        "Home Page",
        "Home-Page",
        "Home_Page",
        "Home.Page",
        "Home/Page",
        "Home\\Page",
        "Hôme",
        "Домой",
        "ホーム",
        "Home\n",
        "Home\u0000",
        "Home;",
        "Home$",
        "A" * (MAX_SCREEN_NAME_LENGTH + 1),
        "HomeScreen",
        "Screen",
        "SettingsScreen",
    ],
)
def test_invalid_screen_names(name):
    with pytest.raises(ValueError):
        validate_screen_name(name)


@pytest.mark.parametrize("value", [None, 5, b"Home", ["Home"], True])
def test_a_screen_name_must_be_a_string(value):
    with pytest.raises(ValueError, match="string"):
        validate_screen_name(value)


def test_the_error_for_an_empty_or_oversized_name_says_so():
    with pytest.raises(ValueError, match="screen name is empty"):
        validate_screen_name("")
    with pytest.raises(ValueError, match="longer than 30 characters"):
        validate_screen_name("A" * (MAX_SCREEN_NAME_LENGTH + 1))


def test_a_name_ending_in_screen_is_explained():
    with pytest.raises(ValueError, match="already called 'SettingsScreenScreen'"):
        validate_screen_name("SettingsScreen")


@pytest.mark.parametrize("name", ["Class", "Object", "Fun", "Package", "Interface", "When", "Val"])
def test_a_name_that_is_a_keyword_in_lower_case_is_fine(name):
    # The generated identifiers are ``ClassScreen`` and the constant ``CLASS``, never a keyword.
    assert validate_screen_name(name) == name


# --- routes -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, route",
    [
        ("Home", "home"),
        ("A", "a"),
        ("SettingsDetail", "settings_detail"),
        ("OAuth", "o_auth"),
        ("HTTPServer", "http_server"),
        ("ABTest", "ab_test"),
        ("Step2", "step2"),
        ("Step2Detail", "step2_detail"),
        ("Item10", "item10"),
        ("UserProfileEdit", "user_profile_edit"),
    ],
)
def test_route_and_constant_derivation(name, route):
    assert route_of(name) == route
    assert route_constant(name) == route.upper()
    assert route.isidentifier() and route == route.lower() and route[0].isalpha()


# --- titles and descriptions --------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["Home", "About & credits", "Bob's notes", "Café", "नमस्ते", "Step 2", "A" * MAX_TITLE_LENGTH],
)
def test_valid_titles(title):
    assert screen(title=title).title == title


@pytest.mark.parametrize(
    "title",
    [
        "",
        " Home",
        "Home ",
        "Two  spaces",
        "<b>Home</b>",
        'Say "hi"',
        "Back\\slash",
        "Cost $5",
        "100%",
        "@string/app_name",
        "?attr/colorPrimary",
        "Line\nbreak",
        "Tab\there",
        "a|b",
        "😀 Home",
        "-Home",
        "A" * (MAX_TITLE_LENGTH + 1),
    ],
)
def test_invalid_titles(title):
    with pytest.raises(ValidationError):
        screen(title=title)


def test_descriptions_follow_the_same_rules_and_are_optional():
    assert screen().description is None
    assert screen(description=None).description is None
    assert (
        screen(description="Welcome back, Bob's friend").description == "Welcome back, Bob's friend"
    )
    for bad in ("", "  x", "x  y", "<x>", "$x", "A" * (MAX_DESCRIPTION_LENGTH + 1), 5):
        with pytest.raises(ValidationError):
            screen(description=bad)


def test_titles_are_nfc_normalised():
    assert screen(title="Café").title == "Café"


def test_display_text_names_what_it_checks():
    with pytest.raises(ValueError, match="widget label is empty"):
        validate_display_text("", "widget label", 10)
    with pytest.raises(ValueError, match="widget label is longer than 10 characters"):
        validate_display_text("x" * 11, "widget label", 10)
    assert validate_display_text("x" * 10, "widget label", 10) == "x" * 10


# --- edges ------------------------------------------------------------------------------------


def test_navigates_to_takes_a_list_or_tuple_of_names():
    assert screen(navigates_to=["About", "Settings"]).navigates_to == ("About", "Settings")
    assert screen(navigates_to=("About",)).navigates_to == ("About",)
    assert screen().navigates_to == ()


@pytest.mark.parametrize(
    "targets", ["About", None, 5, {"About"}, [None], ["about"], [""], ["Home Page"]]
)
def test_navigates_to_must_be_a_list_of_valid_names(targets):
    with pytest.raises(ValidationError):
        screen(navigates_to=targets)


def test_a_screen_cannot_open_itself_or_list_a_target_twice():
    with pytest.raises(ValidationError, match="cannot open itself"):
        screen(name="Home", navigates_to=["Home"])
    with pytest.raises(ValidationError, match="same target twice"):
        screen(navigates_to=["About", "About"])


def test_a_screen_has_a_limited_number_of_buttons():
    names = [f"S{i}" for i in range(MAX_EDGES_PER_SCREEN)]
    assert len(screen(navigates_to=names).navigates_to) == MAX_EDGES_PER_SCREEN
    with pytest.raises(ValidationError, match="at most"):
        screen(navigates_to=names + ["Extra"])


# --- the whole spec -------------------------------------------------------------------------------


def test_a_single_screen_is_a_valid_project():
    spec = spec_of(screen())
    assert spec.start_name == "Home"


def test_the_start_defaults_to_the_first_screen_and_can_be_chosen():
    a = screen("Home", "Home", navigates_to=["Detail"])
    b = screen("Detail", "Detail", navigates_to=["Home"])
    assert spec_of(a, b).start_name == "Home"
    assert spec_of(a, b, start="Detail").start_name == "Detail"


def test_the_start_must_be_a_screen():
    with pytest.raises(ValidationError, match="start screen 'Missing'"):
        spec_of(screen(), start="Missing")
    with pytest.raises(ValidationError):
        spec_of(screen(), start="home")


def test_screen_counts():
    def many(count):
        names = [f"S{i}" for i in range(count)]
        return [
            screen(n, n, navigates_to=[names[i + 1]] if i + 1 < count else [])
            for i, n in enumerate(names)
        ]

    assert len(spec_of(*many(MAX_SCREENS)).screens) == MAX_SCREENS
    with pytest.raises(ValidationError):
        spec_of(*many(MAX_SCREENS + 1))
    with pytest.raises(ValidationError):
        ProjectSpec(screens=())


def test_names_must_be_unique_ignoring_case():
    with pytest.raises(ValidationError, match="same name or differ only in letter case"):
        spec_of(screen("Home", "A"), screen("Home", "B"))
    with pytest.raises(ValidationError, match="same name or differ only in letter case"):
        spec_of(screen("Home", "A", navigates_to=["HOME"]), screen("HOME", "B"))


def test_an_edge_to_a_missing_screen_is_refused():
    with pytest.raises(ValidationError, match="opens 'Nowhere', which does not exist"):
        spec_of(screen(navigates_to=["Nowhere"]))


def test_screens_that_the_start_cannot_reach_are_refused():
    home = screen("Home", "Home", navigates_to=["A"])
    with pytest.raises(
        ValidationError, match=r"not reachable from the start screen Home: \['Island'\]"
    ):
        spec_of(home, screen("A", "A"), screen("Island", "Island"))
    # Reachability is judged from the chosen start, not from the first screen.
    a = screen("A", "A", navigates_to=["B"])
    b = screen("B", "B")
    with pytest.raises(ValidationError, match="not reachable"):
        spec_of(a, b, start="B")


def test_cycles_are_allowed():
    a = screen("A", "A", navigates_to=["B"])
    b = screen("B", "B", navigates_to=["A"])
    assert len(spec_of(a, b).screens) == 2


def test_the_spec_is_immutable_strict_and_round_trips():
    spec = spec_of(
        screen("Home", "Home", description="Hi", navigates_to=["About"]), screen("About", "About")
    )
    with pytest.raises(ValidationError):
        spec.start = "About"
    with pytest.raises(ValidationError):
        ProjectSpec(screens=[{"name": "Home", "title": "Home", "colour": "red"}])
    with pytest.raises(ValidationError):
        ProjectSpec(screens=[{"name": "Home", "title": "Home"}], extra=1)
    assert ProjectSpec.model_validate_json(spec.model_dump_json()) == spec
    assert ProjectSpec.model_validate(spec.model_dump()) == spec
    assert spec.screen("About").title == "About"
    with pytest.raises(KeyError):
        spec.screen("Missing")


def test_lists_from_json_are_accepted():
    spec = ProjectSpec.model_validate(
        {
            "screens": [
                {"name": "Home", "title": "Home", "navigates_to": ["About"]},
                {"name": "About", "title": "About"},
            ],
            "start": "Home",
        }
    )
    assert spec.screens[0].navigates_to == ("About",)
