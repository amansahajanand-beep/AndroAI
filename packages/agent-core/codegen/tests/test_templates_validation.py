"""Validation of the names a generated project is built from."""

import pytest

from androai_codegen.templates import (
    validate_application_id,
    validate_package_name,
    validate_project_name,
    validate_version_name,
)
from androai_codegen.templates.validation import (
    JAVA_RESERVED_WORDS,
    KOTLIN_HARD_KEYWORDS,
    MAX_PACKAGE_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    MAX_VERSION_NAME_LENGTH,
)

# --- package name (the namespace) ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "com.example",
        "com.example.notes",
        "org.acme.my_app",
        "io.a1.b2",
        "com.example.app2",
        "a.b",
        "com.example.x_",
        "com." + "a" * 90,
    ],
)
def test_valid_package_names(value):
    assert validate_package_name(value) == value


@pytest.mark.parametrize(
    "value, why",
    [
        ("", "empty"),
        ("example", "one segment"),
        (".com.example", "leading dot"),
        ("com.example.", "trailing dot"),
        ("com..example", "empty segment"),
        ("com.Example", "uppercase"),
        ("Com.example", "uppercase first segment"),
        ("com.1example", "digit first"),
        ("com._example", "underscore first"),
        ("com.exa-mple", "hyphen"),
        ("com.exa mple", "space"),
        ("com.exämple", "non-ascii"),
        ("com.example/notes", "slash"),
        ("com.example\\notes", "backslash"),
        ("com.example\n", "newline"),
        ("com.example;rm", "semicolon"),
        ("com.example$x", "dollar"),
        ("com.example\u0000", "nul"),
        ("com.class", "kotlin and java keyword"),
        ("com.fun", "kotlin keyword"),
        ("com.val.app", "kotlin keyword in the middle"),
        ("com.new", "java keyword"),
        ("com.int", "java primitive"),
        ("com.true", "literal"),
        ("com.null", "literal"),
        ("com._", "single underscore"),
        ("com.con", "windows device"),
        ("com.aux.app", "windows device in the middle"),
        ("com.nul", "windows device"),
        ("com.lpt1", "windows device with digit"),
        ("com." + "a" * (MAX_PACKAGE_LENGTH), "too long"),
        ("com.example‮", "bidi control"),
    ],
)
def test_invalid_package_names(value, why):
    with pytest.raises(ValueError):
        validate_package_name(value)


@pytest.mark.parametrize("value", [".com.example", "com.example.", "com..example", "com.."])
def test_an_empty_segment_is_named_as_such(value):
    # The segment regex would refuse it too; the explicit message is what a user can act on.
    with pytest.raises(ValueError, match="empty segment"):
        validate_package_name(value)


@pytest.mark.parametrize("value", [None, 5, b"com.example", ["com", "example"], True])
def test_package_name_must_be_a_string(value):
    with pytest.raises(ValueError, match="string"):
        validate_package_name(value)


@pytest.mark.parametrize("word", sorted(KOTLIN_HARD_KEYWORDS | JAVA_RESERVED_WORDS - {"_"}))
def test_every_reserved_word_is_refused_as_a_package_segment(word):
    with pytest.raises(ValueError):
        validate_package_name(f"com.{word}")
    with pytest.raises(ValueError):
        validate_package_name(f"{word}.app")


def test_the_reserved_word_tables_are_complete():
    # JLS 3.9: 50 keywords plus ``_`` are reserved; true / false / null are literals.
    assert len(JAVA_RESERVED_WORDS) == 54
    assert {"const", "goto", "strictfp", "_", "true", "null"} <= JAVA_RESERVED_WORDS
    # Kotlin hard keywords (kotlinlang.org/docs/keyword-reference.html): 31 tokens, of which
    # ``as?``, ``!in`` and ``!is`` are not words and cannot be a package segment anyway.
    assert len(KOTLIN_HARD_KEYWORDS) == 28
    assert {"fun", "val", "typealias", "typeof", "when"} <= KOTLIN_HARD_KEYWORDS


def test_a_soft_keyword_is_a_valid_package_segment():
    # ``value``, ``data``, ``inner`` ... are only keywords in some positions.
    assert validate_package_name("com.example.data") == "com.example.data"
    assert validate_package_name("com.example.value") == "com.example.value"


# --- application id ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "com.example",
        "com.example.MyApp",
        "com.Example.app",
        "org.acme.my_app2",
        "a.B",
        # An application ID is not a Kotlin package, so a keyword segment is allowed.
        "com.example.class",
    ],
)
def test_valid_application_ids(value):
    assert validate_application_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example",
        ".com.example",
        "com.example.",
        "com..example",
        "com.1example",
        "com._example",
        "com.exa-mple",
        "com.exa mple",
        "com.exämple",
        "com.example\n",
        "com.example/x",
        "com." + "a" * MAX_PACKAGE_LENGTH,
    ],
)
def test_invalid_application_ids(value):
    with pytest.raises(ValueError):
        validate_application_id(value)


@pytest.mark.parametrize("value", [None, 5, b"com.example"])
def test_application_id_must_be_a_string(value):
    with pytest.raises(ValueError, match="string"):
        validate_application_id(value)


# --- project name --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "Notes",
        "My Notes App",
        "Notes 2",
        "R&D Tracker",
        "Bob's Notes",
        "Notes (beta)",
        "to-do_list.v2",
        "Hello, World!",
        "C++ Tutor",
        "Café",
        "नमस्ते",
        "メモ帳",
        "1Password",
        "A" * MAX_PROJECT_NAME_LENGTH,
    ],
)
def test_valid_project_names(value):
    assert validate_project_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        " Notes",
        "Notes ",
        "My  Notes",
        "-Notes",
        "(Notes)",
        "'Notes",
        "Notes<script>",
        'Notes "quoted"',
        "Notes\\n",
        "Notes\n",
        "Notes\tApp",
        "a/b",
        "a:b",
        "$HOME",
        "Notes$",
        "@string/app_name",
        "?attr/x",
        "100%",
        "a|b",
        "a*b",
        "a=b",
        "a;b",
        "a{b}",
        "a[b]",
        "a`b",
        " Notes",
        "Notes\u0000",
        "Notes‮",
        "Notes​",
        "😀 Notes",
        "A" * (MAX_PROJECT_NAME_LENGTH + 1),
        "́Notes",
    ],
)
def test_invalid_project_names(value):
    with pytest.raises(ValueError):
        validate_project_name(value)


@pytest.mark.parametrize("value", [None, 7, b"Notes"])
def test_project_name_must_be_a_string(value):
    with pytest.raises(ValueError, match="string"):
        validate_project_name(value)


def test_project_name_is_nfc_normalised():
    decomposed = "Café"  # e + combining acute
    assert validate_project_name(decomposed) == "Café"


# --- version name --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1.0", "1", "2.3.4", "1.0-beta.1", "1.0+build5", "v1_2"])
def test_valid_version_names(value):
    assert validate_version_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".1",
        "-1",
        '1"0',
        "1 0",
        "1.0\n",
        "1.0;",
        "1.0/2",
        "$x",
        "1" * (MAX_VERSION_NAME_LENGTH + 1),
    ],
)
def test_invalid_version_names(value):
    with pytest.raises(ValueError):
        validate_version_name(value)


@pytest.mark.parametrize("value", [None, 1.0, 1])
def test_version_name_must_be_a_string(value):
    with pytest.raises(ValueError, match="string"):
        validate_version_name(value)
