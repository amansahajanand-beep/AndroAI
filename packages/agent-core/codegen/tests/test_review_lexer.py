import random
import time

import pytest

from androai_codegen.review.lexer import check_brackets, lex


def masked(source: str, language: str = "kotlin") -> str:
    return lex(source, language).masked


def kinds(source: str, language: str = "kotlin") -> list[str]:
    return [e.kind for e in lex(source, language).errors]


# --- the invariant everything else relies on -------------------------------------------


def assert_invariants(source: str, language: str) -> None:
    result = lex(source, language)
    assert len(result.masked) == len(source)
    assert [i for i, c in enumerate(result.masked) if c == "\n"] == [
        i for i, c in enumerate(source) if c == "\n"
    ]


SAMPLES = [
    'val a = "x // y" // trailing\n/* block\nspans */ val b = 1\n',
    'val s = """raw "quoted" \n multi""" + "t${f("n${g()}")}"\n',
    "val c = '\"'; val d = '\\''; val e = '\\u0041'\n",
    "fun `it's fine`() {}\n",
    'String t = """\n  text block\n  """;\n',
    "implementation 'a:b:1' // dep\n",
]


@pytest.mark.parametrize("language", ["kotlin", "java", "groovy"])
@pytest.mark.parametrize("source", SAMPLES)
def test_length_and_newlines_are_preserved(source, language):
    assert_invariants(source, language)


@pytest.mark.parametrize("language", ["kotlin", "java", "groovy"])
def test_random_garbage_never_crashes_or_breaks_invariants(language):
    rng = random.Random(1234)
    alphabet = ['"', "'", "`", "/", "*", "\n", "{", "}", "$", "\\", "(", ")", "a", " ", "\u00e9"]
    for _ in range(1500):
        source = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        assert_invariants(source, language)
        check_brackets(lex(source, language))  # must not raise either


@pytest.mark.parametrize(
    "source",
    [
        '"' * 400_000,
        "/*" * 200_000,
        "${" * 100_000,
        '"${' * 50_000,
        "'" * 300_000,
        "`" * 300_000,
        "\\" * 500_000,
        '"""' * 100_000,
        "{" * 300_000,
    ],
)
def test_pathological_inputs_finish_quickly(source):
    started = time.perf_counter()
    for language in ("kotlin", "java", "groovy"):
        assert_invariants(source, language)
        check_brackets(lex(source, language))
    assert time.perf_counter() - started < 15


# --- comments --------------------------------------------------------------------------


def test_comments_are_blanked_but_code_stays():
    result = masked("val a = 1 // note\nval b = 2 /* c */ + 3\n")
    assert "note" not in result and "c */" not in result
    assert "val a = 1" in result and "val b = 2" in result and "+ 3" in result


def test_kotlin_block_comments_nest_but_java_ones_do_not():
    source = "/* a /* b */ still comment */ code"
    assert masked(source, "kotlin").strip() == "code"
    assert "still comment" in masked(source, "java")  # Java ends at the first */


def test_slashes_inside_strings_are_not_comments():
    result = masked('val url = "http://example.com/path" + x')
    assert "example" not in result and "+ x" in result


# --- strings, templates, chars ---------------------------------------------------------


def test_string_contents_are_blanked_and_quotes_kept():
    result = masked('val s = "secret value"')
    assert result == 'val s = "            "'


def test_escaped_quote_does_not_end_the_string():
    # the 4 characters  a \ " b  are all string content
    assert masked(r'val s = "a\"b" + c') == 'val s = "    " + c'


def test_kotlin_template_expression_is_code_and_text_is_not():
    # blanked: "hello " and "${" (8), then code, then "}" (1) and " world" (6)
    expected = 'val s = "' + " " * 8 + 'user.name(" ")' + " " + " " * 6 + '"'
    assert masked('val s = "hello ${user.name("x")} world"') == expected


def test_simple_template_identifier_stays_visible():
    # blanked: "Hi " and "$" (4), identifier visible, "!" blanked
    assert masked('val s = "Hi $name!"') == 'val s = "' + " " * 4 + "name" + " " + '"'


def test_nested_templates():
    # "a " + "${" (4 blanked), b(, inner string: "c " + "${" (4 blanked), d(), inner "}" blanked
    expected = 'val s = "' + " " * 4 + 'b("' + " " * 4 + "d()" + " " + '")' + " " + " " * 2 + '"'
    assert masked('val s = "a ${b("c ${d()}")} e"') == expected


def test_raw_string_is_blanked_across_lines():
    source = 'val s = """line1\nline "quoted" 2\nline3"""\nval t = 1\n'
    result = masked(source)
    assert "line" not in result and "val t = 1" in result
    assert result.count("\n") == source.count("\n")


def test_raw_string_ends_at_the_last_quote_of_a_run():
    result = masked('val s = """text"""" + z')  # Kotlin: """" ends with a quote inside
    assert "+ z" in result


def test_java_text_block():
    result = masked('String t = """\n  hidden\n  """; int x;', "java")
    assert "hidden" not in result and "int x;" in result


def test_char_literals_including_quote_and_escapes():
    source = "val a = '\"'; val b = '\\''; val c = '\\n'; val d = '\\u0041'; val e = 'x'\n"
    assert kinds(source) == []
    assert "val e" in masked(source)


def test_kotlin_backtick_identifier_may_contain_an_apostrophe():
    source = "@Test fun `it's working`() { x() }\n"
    assert kinds(source) == []
    assert "x()" in masked(source)


def test_groovy_single_quoted_strings_and_templates():
    source = "implementation 'androidx.core:core-ktx:1.12.0' // dep\nval x = \"v$ver\"\n"
    result = masked(source, "groovy")
    assert kinds(source, "groovy") == []
    assert "androidx" not in result and "dep" not in result and "ver" in result


# --- string literal extraction ---------------------------------------------------------


def test_string_values_come_from_the_original_text():
    lexed = lex('route = "home/{id}" ; other = "x"', "kotlin")
    assert [lexed.string_value(s) for s in lexed.strings] == ["home/{id}", "x"]
    first = lexed.strings[0]
    assert lexed.string_starting_at(first.start) is first
    assert lexed.string_starting_at(first.start + 1) is None


def test_string_inside_a_comment_is_not_a_literal():
    lexed = lex('// "not a string"\nval a = "real"', "kotlin")
    assert [lexed.string_value(s) for s in lexed.strings] == ["real"]


# --- lexical errors --------------------------------------------------------------------


def test_unterminated_string_is_reported_at_its_start():
    lexed = lex('val a = 1\nval b = "oops\nval c = 3\n', "kotlin")
    assert [e.kind for e in lexed.errors] == ["unterminated_string"]
    assert lexed.position(lexed.errors[0].offset) == (2, 9)
    assert "val c = 3" in lexed.masked  # lexing recovers at the line end


def test_unterminated_block_comment_and_raw_string():
    assert kinds("val a = 1 /* never closed\n more") == ["unterminated_comment"]
    assert kinds('val a = """never closed\nmore') == ["unterminated_string"]
    assert kinds('val a = "${never closed') == ["unterminated_string"]


def test_stray_apostrophe_is_reported_without_swallowing_code():
    lexed = lex("val a = 'ab'\nval keep = 1\n", "kotlin")
    assert "unterminated_char" in [e.kind for e in lexed.errors]
    assert "val keep = 1" in lexed.masked


def test_position_is_one_based_line_and_column():
    lexed = lex("ab\ncd\nef", "java")
    assert lexed.position(0) == (1, 1)
    assert lexed.position(4) == (2, 2)
    assert lexed.position(6) == (3, 1)


# --- bracket balance -------------------------------------------------------------------


def balance(source: str, language: str = "kotlin") -> list[str]:
    return [e.kind for e in check_brackets(lex(source, language))]


def test_balanced_code_has_no_bracket_errors():
    assert balance("fun f(a: List<Int>) { val x = arrayOf(1)[0]; g { h() } }") == []


def test_brackets_inside_strings_and_comments_are_ignored():
    assert balance("val a = \"((( {{{\"  // )))\n/* ]]] */ val b = '}'\n") == []


def test_unclosed_unexpected_and_mismatched():
    assert balance("fun f() { val x = 1") == ["unclosed"]
    assert balance("fun f() }") == ["unexpected_close"]
    assert balance("val a = (1]") == ["mismatched"]


def test_template_braces_do_not_unbalance_the_file():
    assert balance('val s = "a ${if (x) { 1 } else { 2 }} b"') == []


def test_bracket_errors_are_capped():
    assert len(check_brackets(lex("(" * 100, "java"))) == 3
