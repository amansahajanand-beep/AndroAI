"""Placeholder substitution, escaping and the safety checks of the renderer."""

import xml.etree.ElementTree as ET

import pytest

from androai_codegen.templates import (
    Language,
    ProjectConfig,
    Template,
    TemplateFile,
    TemplateRenderError,
    UiToolkit,
    get_template,
    placeholder_values,
    render_files,
    render_template,
    template_placeholders,
)
from androai_codegen.templates.render import android_string, placeholders, substitute


def make(**overrides) -> ProjectConfig:
    base = {"project_name": "Notes App", "package_name": "com.example.notes"}
    base.update(overrides)
    return ProjectConfig(**base)


def template_of(*files: TemplateFile) -> Template:
    return Template(Language.KOTLIN, UiToolkit.COMPOSE, "test", tuple(files))


# --- substitution ---------------------------------------------------------------------------


def test_placeholders_are_found():
    assert placeholders("a __PACKAGE__ b __APPLICATION_ID__ c __X1__") == {
        "PACKAGE",
        "APPLICATION_ID",
        "X1",
    }


@pytest.mark.parametrize(
    "text",
    ["__init__", "__lower__", "__ __", "____", "_PACKAGE_", "__PACKAGE_", "_ _PACKAGE__", "__1A__"],
)
def test_things_that_are_not_placeholders_are_left_alone(text):
    assert placeholders(text) == set()
    assert substitute(text, {"PACKAGE": "x"}, where="t") == text


def test_substitution_replaces_every_occurrence():
    assert substitute("__A__ __A__ __B__", {"A": "1", "B": "2"}, where="t") == "1 1 2"


def test_substitution_is_a_single_pass():
    # A value that looks like a placeholder is inserted as it is, never expanded.
    assert substitute("x __A__ y", {"A": "__B__", "B": "boom"}, where="t") == "x __B__ y"


def test_an_unknown_placeholder_is_an_error_not_an_empty_string():
    with pytest.raises(TemplateRenderError, match=r"strings\.xml.*__NOPE__"):
        substitute("a __NOPE__ b", {"A": "1"}, where="strings.xml")


def test_values_with_regex_or_format_characters_are_inserted_literally():
    value = r"\1 \g<0> $1 {x} %s \\"
    assert substitute("[__A__]", {"A": value}, where="t") == f"[{value}]"


def test_every_placeholder_of_the_template_has_a_value():
    used = template_placeholders(get_template(Language.KOTLIN, UiToolkit.COMPOSE))
    assert used <= set(placeholder_values(make()))


def test_every_value_is_used_by_the_template():
    # A value nobody uses is dead weight that hides a typo in a template.
    used = template_placeholders(get_template(Language.KOTLIN, UiToolkit.COMPOSE))
    assert set(placeholder_values(make())) == used


def test_a_project_name_that_looks_like_a_placeholder_is_not_expanded():
    files = {f.path: f.content for f in render_files(make(project_name="X__PACKAGE__"))}
    assert "X__PACKAGE__</string>" in files["app/src/main/res/values/strings.xml"]


# --- android_string -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("Notes", "Notes"),
        ("R&D", "R&amp;D"),
        ("Bob's", "Bob\\'s"),
        ("a<b>c", "a&lt;b&gt;c"),
        ('say "hi"', 'say \\"hi\\"'),
        ("back\\slash", "back\\\\slash"),
        ("@leading", "\\@leading"),
        ("?leading", "\\?leading"),
        ("mid@dle", "mid@dle"),
        ("", ""),
    ],
)
def test_android_string_escapes(raw, escaped):
    assert android_string(raw) == escaped


@pytest.mark.parametrize("name", ["R&D Tracker", "Bob's Notes", "Notes (beta)", "C++ & Co's"])
def test_the_name_in_strings_xml_parses_back_to_the_android_text(name):
    files = {f.path: f.content for f in render_files(make(project_name=name))}
    root = ET.fromstring(files["app/src/main/res/values/strings.xml"])
    (app_name,) = [e for e in root if e.get("name") == "app_name"]
    # AAPT removes the backslash that escapes an apostrophe; the XML parser removes the rest.
    assert app_name.text.replace("\\'", "'") == name


# --- path safety ----------------------------------------------------------------------------

UNSAFE_PATHS = [
    "../outside.txt",
    "app/../../outside.txt",
    "/etc/passwd",
    "C:/Windows/x.txt",
    "app\\build.gradle.kts",
    ".git/config",
    "app/.git/hooks/pre-commit",
    "GIT~1/config",
    "app/con.txt",
    "app/NUL",
    "app/a b./x",
    "app/x:stream",
    "app//x.txt",
    "app/./x.txt",
    "",
    "app/",
    "app/x\x00.txt",
]


@pytest.mark.parametrize("path", UNSAFE_PATHS)
def test_an_unsafe_template_path_is_refused(path):
    template = template_of(TemplateFile(path, "x\n", "d"))
    with pytest.raises(TemplateRenderError):
        render_template(template, {})


@pytest.mark.parametrize(
    "package",
    ["com.example.notes", "a.b", "com.example.a_b"],
)
def test_a_rendered_package_path_never_leaves_the_source_root(package):
    for f in render_files(make(package_name=package)):
        assert not f.path.startswith("/")
        assert ".." not in f.path.split("/")
        assert "\\" not in f.path


def test_a_placeholder_value_cannot_inject_a_traversal_into_a_path():
    template = template_of(TemplateFile("src/__PACKAGE_PATH__/A.kt", "x\n", "d"))
    for evil in ["../../etc", "a/../..", "/abs", "a\\b", ".git", "CON"]:
        with pytest.raises(TemplateRenderError):
            render_template(template, {"PACKAGE_PATH": evil})


def test_two_files_cannot_render_to_the_same_path():
    template = template_of(
        TemplateFile("a/__X__.kt", "1\n", "d"), TemplateFile("a/__Y__.kt", "2\n", "d")
    )
    with pytest.raises(TemplateRenderError, match="same path"):
        render_template(template, {"X": "same", "Y": "same"})


def test_a_non_canonical_rendered_path_is_refused():
    template = template_of(TemplateFile("a/__X__", "1\n", "d"))
    with pytest.raises(TemplateRenderError):
        render_template(template, {"X": "./b.kt"})


@pytest.mark.parametrize("content", ["no newline", "crlf\r\n", "nul\x00\n", "cr\rx\n"])
def test_unsafe_content_is_refused(content):
    template = template_of(TemplateFile("a.txt", content, "d"))
    with pytest.raises(TemplateRenderError):
        render_template(template, {})


def test_output_is_sorted_by_path():
    paths = [f.path for f in render_files(make())]
    assert paths == sorted(paths)


def test_an_unknown_placeholder_in_a_path_is_an_error():
    template = template_of(TemplateFile("a/__NOPE__.kt", "x\n", "d"))
    with pytest.raises(TemplateRenderError, match="NOPE"):
        render_template(template, {})
