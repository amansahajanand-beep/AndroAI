"""Third correction: a generated value in a query is masked whatever stands around it.

The final review reproduced four ways past the rule that masks ``?name=<generated value>``:
standard base64 (it contains ``/``), a bracketed parameter name (``?s[]=``), a query that is only a
token (``?<token>``) and a value followed by an unquoted ``)``. Through plain ``safe()`` the values
reached an application label, compose route subjects, attributes and edge ids, a navigation label
and ``tools:context``. The rule is still by shape: what cannot be told from a name by shape alone
(short values, plain words, capital letters only) is not recognised, and a bare token is judged
only after a ``?``.
"""

from __future__ import annotations

import re
import time

import pytest
from analysis_fixtures import ANDROID_NS, APP_NS, analyse, d, mini_app, no_errors

from androai_codegen.analysis import AnalysisReport
from androai_codegen.analysis.store import make_id
from androai_codegen.analysis.text import (
    mask_opaque_runs,
    mask_urls,
    redact_excerpt,
    redact_url,
    safe,
    safe_value,
    scrub,
)

HEX = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
UUID = "550e8400-e29b-41d4-a716-446655440000"
B64_SLASH = "Zm9vYmFyYmF6cXV4/MTIzNDU2Nzg5MEFCQ0RFRg"  # pieces of 16 and 22
B64_SHORT = "Ab3dE5gH/jK9mN1pQ/sT5vW7yZ/9bC2eF/hI4kL6n"  # a slash every 8 or 9: no piece reaches 12
B64_MIXED = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # one piece of 13, one of 7, one of 26
B64_PERCENT = "Zm9vYmFyYmF6cXV4%2FMTIzNDU2Nzg5MEFCQ0RFRg"
SLASHED = {
    "slash": B64_SLASH,
    "short pieces": B64_SHORT,
    "mixed pieces": B64_MIXED,
    "percent-encoded": B64_PERCENT,
}


def parts_of(value: str) -> list[str]:
    """The distinctive pieces of a value: none of them may survive the masking."""
    return [
        value,
        *[p for p in value.replace("%2F", "/").replace("+", "/").split("/") if len(p) >= 6],
    ]


def helpers_of(text: str) -> dict[str, str]:
    return {
        "mask_urls": mask_urls(text),
        "safe": safe(text, 400),
        "scrub": scrub(text),
        "excerpt": redact_excerpt(f'val u = "{text}"'),
    }


def assert_masked(text: str, value: str) -> None:
    for name, shown in helpers_of(text).items():
        for piece in parts_of(value):
            assert piece not in shown, (name, piece, shown)


# -- 1. standard base64: ``/`` is not a way past the check --------------------------------------


@pytest.mark.parametrize("value", SLASHED.values(), ids=SLASHED.keys())
@pytest.mark.parametrize(
    "template",
    [
        "https://api.example.com/v1/items?s={v}",
        "https://api.example.com/v1/items?page=2&s={v}",
        "https://api.example.com/v1/items#s={v}",
        "https://api.example.com/v1/items;s={v}",
        "hook?s={v}",
        "https://api.example.com/v1/items?a=1&b=2&sig_id={v}&c=3",
    ],
)
def test_a_generated_value_with_slashes_is_masked_in_every_position(template: str, value: str):
    assert_masked(template.format(v=value), value)


def test_a_value_with_slashes_is_judged_whole_so_short_pieces_hide_nothing():
    assert mask_urls(f"x?s={B64_SHORT}") == "x?s=[REDACTED]"
    # pieces of 13 and 26 (the ``+`` joins ``K7MDENG`` to the rest): both go, nothing is left over
    assert mask_urls(f"x?s={B64_MIXED}") == "x?s=[REDACTED]/[REDACTED]"
    assert mask_urls(f"x?s={B64_SLASH}") == "x?s=[REDACTED]/[REDACTED]"  # pieces of 16 and 22


def test_a_path_with_one_generated_piece_keeps_its_words():
    assert mask_urls(f"x?next=/users/{HEX}/profile") == "x?next=/users/[REDACTED]/profile"
    assert mask_opaque_runs(f"build/{HEX}/out") == "build/[REDACTED]/out"
    assert mask_opaque_runs(f"images/avatars/{UUID}.png") == "images/avatars/[REDACTED]"
    # a short id next to a generated piece is kept: nothing says the slash cut a token (a capital
    # letter would, see test_analysis_slash_runs.py); the generated piece is masked on its own
    assert mask_opaque_runs(f"api/v2/items/7f3/{HEX}") == "api/v2/items/7f3/[REDACTED]"


@pytest.mark.parametrize("value", SLASHED.values(), ids=SLASHED.keys())
def test_a_meta_data_value_and_a_short_literal_with_slashes_are_masked_whole(value: str):
    # nothing but markers and the separators between them (``/`` or its encoding ``%2F``)
    assert re.fullmatch(r"\[REDACTED\]((/|%2F)\[REDACTED\])*", safe_value(value, 200))
    assert safe_value(f"id={value}", 200).startswith("id=[REDACTED]")
    for piece in parts_of(value):
        assert piece not in safe_value(f"user:{value}", 200)
        assert piece not in redact_excerpt(f'val s = "u:{value[:30]}"')


# -- 2. bracketed parameter names ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["s[]", "filter[id]", "a[b][c]", "ids[0]", "user[token_ref]", "f%5B%5D"]
)
@pytest.mark.parametrize("value", [HEX, UUID, B64_SLASH], ids=["hex", "uuid", "base64"])
def test_a_bracketed_parameter_name_does_not_hide_the_value(name: str, value: str):
    for text in (
        f"https://x.example.com/p?{name}={value}",
        f"https://x.example.com/p?a=1&{name}={value}",
        f"https://x.example.com/p#{name}={value}",
    ):
        assert_masked(text, value)
        assert f"{name}=[REDACTED]" in mask_urls(text)  # the name is kept


def test_ordinary_values_of_bracketed_names_are_kept():
    for text in (
        "https://x.example.com/s?filter[status]=active&filter[type]=premium_member",
        "https://x.example.com/s?tags[]=android&tags[]=kotlin&order[]=created_at_desc",
        "https://x.example.com/s?page[number]=2&page[size]=50",
    ):
        assert mask_urls(text) == text


# -- 3. a query that is only a token -------------------------------------------------------------


@pytest.mark.parametrize(
    "value", [HEX, UUID, "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRg", B64_SLASH, B64_SHORT]
)
@pytest.mark.parametrize(
    "template",
    [
        "https://x.example.com/p?{v}",
        "https://x.example.com/a/b/c?{v}",
        "hook?{v}",
        "https://x.example.com/p?{v}#top",
    ],
)
def test_a_bare_query_token_is_masked(template: str, value: str):
    text = template.format(v=value)
    assert_masked(text, value)
    assert "?[REDACTED]" in mask_urls(text)  # the structure around it stays


def test_a_bare_token_is_judged_only_after_a_question_mark():
    """``&<token>`` and ``#<token>`` look like Kotlin, ids and anchors too often to be judged."""
    assert mask_urls(f"a&&someIdentifierWithDigits123 and x&{HEX}") == (
        f"a&&someIdentifierWithDigits123 and x&{HEX}"
    )
    assert mask_urls(f"https://x.example.com/p#{HEX}") == f"https://x.example.com/p#{HEX}"
    assert mask_urls(f"https://x.example.com/p?a=1&{HEX}") == f"https://x.example.com/p?a=1&{HEX}"
    assert mask_urls(f"foo();{HEX}") == f"foo();{HEX}"  # free text: ``;`` ends statements
    # (inside a URL path a bare matrix token is masked by the path rule, see test_analysis_opaque_values)
    assert mask_urls(f"https://x.example.com/p;{HEX}") == "https://x.example.com/p;[REDACTED]"


@pytest.mark.parametrize(
    "text",
    [
        "https://x.example.com/p?page",
        "https://x.example.com/p?refresh_token_list",
        "https://x.example.com/p?SomeLongCamelCaseFlagName",
        "https://x.example.com/p?utm_source_newsletter",
        "https://x.example.com/p?0a1b2c3d",  # shorter than 12
        f"https://x.example.com/p?{HEX}=1",  # followed by '=': a name, not a token
        "val a = b?.someLongPropertyName123 ?: other",
        "val s: String? = null; val t = x ?: y",
        "list.map { it?.toString() }.filterNotNull()",
        "if (cond) a?.let { useSomeVeryLongFunctionName2024(it) }",
        'Regex("(?:abc)?[a-z0-9]{12,}")',
        "SELECT * FROM t WHERE a = ? AND b = ?",
    ],
)
def test_a_question_mark_in_code_or_a_name_is_left_alone(text: str):
    assert mask_urls(text) == text
    assert redact_excerpt(text) == text or "…" in redact_excerpt(text)  # (an older rule may hide)


def test_ids_with_hash_and_question_marks_are_not_corrupted():
    for subject in (
        "com.x.Foo#someVeryLongFunctionName2024()",
        "com.x#parseAnd9Validate3Input(String)",
        "detail?item={id}&mode=dark_theme_enabled",
        "com.x.Foo#getSomethingFromCache2024Result(Int)",
    ):
        assert scrub(subject) == subject
        assert make_id("member", subject) == f"member:{subject}"


# -- 4. a value followed by punctuation ----------------------------------------------------------


@pytest.mark.parametrize("tail", [")", "]", "}", ",", ".", "!", ":", "),", ").", ")]", ");"])
@pytest.mark.parametrize(
    "value", [HEX, B64_SLASH, B64_SHORT, UUID], ids=["hex", "slash", "short", "uuid"]
)
@pytest.mark.parametrize(
    "template",
    ["f(https://x.example.com/p?s={v}{t}", "f(https://x.example.com/p?{v}{t}", "x?s[]={v}{t}"],
)
def test_punctuation_after_a_value_does_not_expose_it(template: str, value: str, tail: str):
    text = template.format(v=value, t=tail)
    assert_masked(text, value)
    assert mask_urls(text).endswith(tail)  # and the punctuation is kept


def test_a_trailing_full_stop_is_kept_outside_the_mask():
    assert (
        mask_urls(f"see https://x.example.com/p?s={HEX}.")
        == "see https://x.example.com/p?s=[REDACTED]."
    )
    assert (
        mask_urls(f"see https://x.example.com/p?{HEX}.")
        == "see https://x.example.com/p?[REDACTED]."
    )
    assert mask_urls(f"x?s={HEX}==") == "x?s=[REDACTED]=="  # padding is not part of the secret


def test_ordinary_values_followed_by_punctuation_are_kept():
    for text in (
        "f(https://x.example.com/p?page=2)",
        "f(https://x.example.com/p?lang=en-US&sort=name),",
        "[https://x.example.com/p?q=hello_world].",
        "f(https://x.example.com/p?mode=dark_theme_enabled)",
    ):
        assert mask_urls(text) == text


# -- harmless values stay useful -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://api.example.com/v1/items?page=2&sort=name&q=hello_world",
        "https://x.example.com/s?v=1.2.3-SNAPSHOT&lang=en-US&ts=1700000000",
        "https://x.example.com/s?since=2024-01-15T10:30:00Z&until=2024-02-01",
        "https://x.example.com/cb?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback&state=ok",
        "https://x.example.com/cb?redirect=https://example.com/a/b&next=home",
        "https://x.example.com/s?path=users/profile/settings/notifications",
        "https://x.example.com/s?file=images/avatars/profile_picture_large.png",
        "https://x.example.com/s?ids=1,2,3,4,5,6,7,8,9&fields=name,email,created_at",
        "https://x.example.com/s?mode=dark_theme_enabled&layout=GridLayoutManager",
        "https://x.example.com/search?q=android+studio+tutorial&hl=en",
        "https://x.example.com/search?q=android%20studio%20tutorial%20for%20beginners",
        "https://x.example.com/p?utm_source=newsletter&utm_campaign=spring_sale_2024",
        "https://x.example.com/p;v=2;lang=en?x=1",
        "https://x.example.com/a/b/c.html#section-two",
        "https://x.example.com/download?file=app-release-1.4.2.apk",
        "https://x.example.com/s?count=${count}&name={name}",
        "hook?page=2&sort=name",
    ],
)
def test_ordinary_queries_are_not_changed(text: str):
    assert mask_urls(text) == text
    assert scrub(text) == text


def test_percent_escapes_are_separators_not_part_of_a_word():
    """Before this correction ``redirect_uri=https%3A%2F%2Fexample.com`` was masked."""
    assert mask_urls("x?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback") == (
        "x?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback"
    )
    assert mask_urls("x?q=android%20studio%20tutorial%20for%20beginners") == (
        "x?q=android%20studio%20tutorial%20for%20beginners"
    )
    # encoded base64 is still masked; ``%2F`` cuts it into pieces just as ``/`` does (fourth correction)
    assert mask_urls(f"x?s={B64_PERCENT}") == "x?s=[REDACTED]%2F[REDACTED]"


# -- the report: every surface the review found --------------------------------------------------

PLANTED = {
    "slash": (f"https://x.example.com/p?s={B64_SLASH}", [B64_SLASH, *parts_of(B64_SLASH)]),
    "short pieces": (f"https://x.example.com/p?s={B64_SHORT}", parts_of(B64_SHORT)),
    "array name": (f"https://x.example.com/p?s[]={HEX}", [HEX]),
    "bare token": (f"https://x.example.com/p?{HEX}", [HEX]),
    "bare base64": (f"https://x.example.com/p?{B64_SLASH}", parts_of(B64_SLASH)),
    "closing paren": (f"fetch(https://x.example.com/p?s={HEX})", [HEX]),
    "control": (f"https://x.example.com/p?s={HEX}", [HEX]),
}


def surface_project(url: str) -> dict[str, str]:
    xml = url.replace("&", "&amp;")  # the same text as an XML attribute value
    kt = f"""
        package com.x
        import androidx.navigation.compose.composable
        import androidx.navigation.NavController
        fun androidx.navigation.NavGraphBuilder.g(nav: NavController) {{
            composable("reset?u={url}") {{ }}
        }}
        fun go(nav: NavController) {{ nav.navigate("reset?u={url}") }}
        """
    manifest = (
        f'<manifest {ANDROID_NS}><application android:name=".App" android:label="{xml}">'
        f'<meta-data android:name="n" android:value="{xml}"/></application></manifest>'
    )
    nav = (
        f'<navigation {ANDROID_NS} {APP_NS} android:id="@+id/nav"><fragment android:id="@+id/home" '
        f'android:name="com.x.H" android:label="{xml}"/></navigation>'
    )
    layout = f'<LinearLayout {ANDROID_NS} xmlns:tools="http://schemas.android.com/tools" tools:context="{xml}"/>'
    return mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": manifest,
            "app/src/main/res/navigation/nav.xml": nav,
            "app/src/main/res/layout/main.xml": layout,
        },
        Code=kt,
    )


def strings_of(report: AnalysisReport) -> list[str]:
    out: list[str] = []
    for item in report.facts:
        out += [item.id, item.subject, item.note or "", item.reason or ""]
        out += [str(v) for v in item.attributes.values()]
        out += [e.excerpt for e in item.evidence]
    for rel in report.relationships:
        out += [rel.id, rel.source, rel.target, rel.note or ""]
        out += [e.excerpt for e in rel.evidence]
    for limitation in report.limitations:
        out += [limitation.scope, limitation.message]
    return out


@pytest.mark.parametrize("form", PLANTED)
def test_no_generated_query_value_reaches_any_report_field(form: str):
    url, secrets = PLANTED[form]
    report = analyse(surface_project(url))
    no_errors(report)
    text = report.model_dump_json()
    leaves = strings_of(report)
    assert len(leaves) > 40
    for secret in secrets:
        assert secret not in text, f"{form}: {secret[:10]} reached the JSON"
        assert all(secret not in leaf for leaf in leaves), (form, secret[:10])


@pytest.mark.parametrize("form", ["slash", "array name", "bare token", "closing paren"])
def test_the_surfaces_that_leaked_still_show_their_structure(form: str):
    url, _ = PLANTED[form]
    report = analyse(surface_project(url))
    by_kind = {
        f.kind: f for f in report.facts if f.kind in ("application", "nav_destination", "layout")
    }
    assert by_kind["application"].attributes["label"].startswith("https://x.example.com/p?") or (
        "fetch(" in by_kind["application"].attributes["label"]
    )
    assert "[REDACTED]" in by_kind["application"].attributes["label"]
    assert "[REDACTED]" in by_kind["nav_destination"].attributes["label"]
    assert "[REDACTED]" in by_kind["layout"].attributes["tools_context"]
    route = next(f for f in report.facts if f.kind == "compose_route")
    assert route.subject.startswith("reset?u=") and "[REDACTED]" in route.subject
    edge = next(r for r in report.relationships if r.kind == "navigates_to")
    assert "[REDACTED]" in edge.id and edge.id.startswith("member:")


def test_a_harmless_query_in_those_surfaces_is_kept_as_written():
    url = "https://x.example.com/p?page=2&sort=name&redirect_uri=https%3A%2F%2Fexample.com%2Fcb"
    report = analyse(surface_project(url))
    label = next(f for f in report.facts if f.kind == "application").attributes["label"]
    route = next(f for f in report.facts if f.kind == "compose_route").subject
    assert label == url and route == f"reset?u={url}"


def test_the_report_is_deterministic_and_round_trips():
    files = surface_project(PLANTED["slash"][0])
    first = analyse(dict(files))
    second = analyse(dict(reversed(list(files.items()))))
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()
    assert AnalysisReport.model_validate_json(first.model_dump_json()) == first


# -- adversarial input ---------------------------------------------------------------------------


def test_the_new_rules_survive_hostile_input_quickly():
    started = time.perf_counter()
    n = 150_000
    for text in (
        "?" * n,
        "?a[" * n,
        "?a[]=" * n,
        "?a[]=" + "a/" * n,
        "?" + "a/" * n,
        "?s=" + "a/b" * n,
        ("?" + "f" * 14 + "&") * (n // 2),
        "?" + "Ab/" * n + ")",
        "/" * n,
        ("a/" * 6 + " ") * (n // 6),
        "https://x.example.com/p?s=" + ("0f/" * 5000) * 20,
        ")" * n + "?" + "f" * 20,
        "?s=" + "f" * 100_000 + ")" * 100_000,
        "?" + "%2F" * n,
    ):
        mask_urls(text)
        mask_opaque_runs(text)
        safe_value(text, 200)
        redact_excerpt(f'val s = "{text[:5000]}"')
        redact_url("https://h.example.com/" + text, 300)
    assert time.perf_counter() - started < 25


def test_masking_is_idempotent_and_never_touches_its_own_marker():
    for url, _ in PLANTED.values():
        once = mask_urls(url)
        assert mask_urls(once) == once
        assert safe(once, 400) == safe(safe(once, 400), 400)
    for text in (f"build/{HEX}/out", f"x?s={B64_SHORT}", f"user:{B64_MIXED}", f"?{HEX}"):
        once = mask_opaque_runs(text)
        assert mask_opaque_runs(once) == once


# -- what is still not recognised, said out loud -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "qwertyuiopasdfghjklzxcvbnm",  # plain lower-case letters look like a word
        "QWERTYUIOPASDFGHJKLZXCVBNM",  # capital letters only look like a constant
        "SuperSecretPassphraseNumberOne",  # camel-case words
        "correct-horse-battery-staple",  # words
        "12345678901234",  # a number of up to 15 digits
        "k9Zx3Lp7Qw",  # shorter than 12 characters
    ],
)
def test_a_value_that_cannot_be_told_from_a_name_by_shape_is_not_masked(value: str):
    assert mask_urls(f"x?s={value}") == f"x?s={value}"
    assert mask_urls(f"x?{value}") == f"x?{value}"


def test_the_rule_does_not_need_a_keyword_in_the_name():
    for name in ("s", "sid", "code", "otp", "t", "x-id", "v", "ref.id", "r_1", "s[]", "q[id]"):
        assert mask_urls(f"x?{name}={HEX}") == f"x?{name}=[REDACTED]"
    assert (
        d("""
        a
        """)
        == "a\n"
    )  # keep the shared helper imported and exercised
