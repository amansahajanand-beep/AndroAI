"""Fourth correction: a value that contains ``/`` is not masked because one short piece looks unusual.

The third correction let ``/`` join a run so that standard base64 (which contains ``/``) is judged
whole. A run was then masked as a whole when any piece of it that was not masked on its own was not
a plain word, so ordinary values lost their words: ``u1234`` in a CDN path, ``v8a`` in
``lib/arm64-v8a/libnative.so``, ``ab12cd34`` in ``?next=/users/ab12cd34/profile``.

The rule now (``text._mask_run``): every piece between slashes (``/`` or ``%2F``) is judged on its
own, like a URL path segment; pieces that a slash may have cut out of base64 are judged together with
their neighbours, and only then. These tests pin both sides: ordinary values stay readable (false
positives), generated values stay hidden (false negatives), and what the rule cannot tell apart is
said out loud at the end.
"""

from __future__ import annotations

import base64
import random
import re
import time

import pytest
from analysis_fixtures import ANDROID_NS, analyse, mini_app, no_errors

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
AWS = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # the documentation's example: pieces of 13, 7, 17

# the four values the fourth review reproduced
CDN = "https://cdn.example.com/img/avatars/u1234/profile_picture.png"
LIB = "lib/arm64-v8a/libnative.so"
ABI_QUERY = "https://x.example.com/s?abi=armeabi-v7a/arm64-v8a/x86_64"
NEXT_QUERY = "https://x.example.com/s?next=/users/ab12cd34/profile"
REPORTED = [CDN, LIB, ABI_QUERY, NEXT_QUERY]

MARKER = "[REDACTED]"


ORDINARY_WORDS = {"profile"}  # words some test values carry on purpose; they are not secrets


def pieces_of(value: str) -> list[str]:
    """The distinctive pieces of a generated value (6+ characters): none may survive masking."""
    return [
        value,
        *[p for p in re.split(r"[/+]|%2F", value) if len(p) >= 6 and p not in ORDINARY_WORDS],
    ]


def assert_hidden(text: str, value: str) -> None:
    shown = {
        "mask_urls": mask_urls(text),
        "mask_opaque_runs": mask_opaque_runs(text),
        "safe": safe(text, 400),
        "safe_value": safe_value(text, 400),
        "scrub": scrub(text),
    }
    for helper, out in shown.items():
        for piece in pieces_of(value):
            assert piece not in out, (helper, piece, out)


# -- 1. the four reported values -----------------------------------------------------------------


def test_the_four_reported_values_are_unchanged():
    assert safe_value(CDN, 200) == CDN
    assert safe_value(LIB, 200) == LIB
    assert mask_urls(ABI_QUERY) == ABI_QUERY
    assert mask_urls(NEXT_QUERY) == NEXT_QUERY


@pytest.mark.parametrize("text", REPORTED, ids=["cdn", "lib", "abi", "next"])
def test_the_reported_values_survive_every_shared_helper(text: str):
    assert safe(text, 300) == text
    assert safe_value(text, 300) == text
    assert scrub(text) == text
    assert mask_urls(text) == text
    assert mask_opaque_runs(text) == text
    url = text if text.startswith("http") else f"https://h.example.com/{text}"
    assert redact_url(url, 300) == url.split("?")[0]  # (it never shows a query string)


# -- 2. paths with short ids ---------------------------------------------------------------------

SHORT_ID_PATHS = [
    "/users/ab12cd34/profile",
    "users/ab12cd34/posts/ef56gh78/likes",  # two ids, kept apart by a word
    "users/Ab12Cd34/posts/Ef56Gh78/likes",  # the same with capital letters
    "v1/orders/a1b2c3/lines/d4e5f6",
    "cache/7f3/a9c/blob.bin",
    "images/ab12cd/ef34gh",  # two short ids side by side, neither with a capital letter
    "users/u_8f3a/avatar",
    "files/Ab3dE5gH/readme.md",  # one short piece with a capital letter
    "/orders/42/items/7a",
    "avatars/u1234/profile_picture.png",
    "repos/square/okhttp/commit/a1b2c3d",
    "objects/7f/3a9c/pack",
]


@pytest.mark.parametrize("path", SHORT_ID_PATHS)
def test_a_path_with_short_ids_keeps_every_piece(path: str):
    assert mask_opaque_runs(path) == path
    assert safe_value(path, 200) == path
    assert scrub(path) == path
    assert (
        mask_urls(f"https://x.example.com/s?next={path}") == f"https://x.example.com/s?next={path}"
    )
    assert mask_urls(f"https://x.example.com/{path.lstrip('/')}") == (
        f"https://x.example.com/{path.lstrip('/')}"
    )
    assert redact_excerpt(f'val u = "see {path}"') == f'val u = "see {path}"'


# -- 3. Android ABI paths ------------------------------------------------------------------------

ABIS = ["armeabi-v7a", "arm64-v8a", "x86_64", "x86", "armeabi", "mips64", "riscv64"]


@pytest.mark.parametrize("abi", ABIS)
def test_an_abi_directory_is_kept_everywhere(abi: str):
    for text in (
        f"lib/{abi}/libnative.so",
        f"app/src/main/jniLibs/{abi}/libnative.so",
        f"https://x.example.com/s?abi={abi}",
        f"https://x.example.com/s?abi={abi}/{abi}",
        f"https://x.example.com/dl/{abi}/app-release.apk",
    ):
        assert mask_opaque_runs(text) == text, text
        assert safe_value(text, 300) == text, text
        assert mask_urls(text) == text, text
        assert scrub(text) == text, text


def test_all_abis_in_one_value_are_kept():
    value = "/".join(ABIS)
    assert mask_opaque_runs(value) == value
    assert mask_urls(f"https://x.example.com/s?abis={value}") == (
        f"https://x.example.com/s?abis={value}"
    )
    assert redact_excerpt('val abis = "all: armeabi-v7a/arm64-v8a/x86_64"') == (
        'val abis = "all: armeabi-v7a/arm64-v8a/x86_64"'
    )


# -- 4. ordinary and generated pieces in one value -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"build/{HEX}/out", "build/[REDACTED]/out"),
        (f"images/avatars/{UUID}.png", "images/avatars/[REDACTED]"),
        (f"users/{HEX}/posts/ab12cd34/likes", "users/[REDACTED]/posts/ab12cd34/likes"),
        (f"lib/arm64-v8a/{HEX}.so", "lib/arm64-v8a/[REDACTED]"),
        (f"api/v2/items/7f3/{HEX}", "api/v2/items/7f3/[REDACTED]"),
        (f"abi/arm64-v8a/{HEX}/x86_64", "abi/arm64-v8a/[REDACTED]/x86_64"),
        # capital letters make a word no more part of the token: camel-case names stay
        (f"screens/{HEX}/MainActivity", "screens/[REDACTED]/MainActivity"),
        (f"{HEX}/userProfile/Settings", "[REDACTED]/userProfile/Settings"),
        (
            f"https://cdn.example.com/img/avatars/u1234/{UUID}.png",
            "https://cdn.example.com/img/avatars/u1234/[REDACTED]",
        ),
    ],
)
def test_a_generated_piece_is_masked_and_the_ordinary_pieces_around_it_stay(
    text: str, expected: str
):
    assert mask_opaque_runs(text) == expected
    assert safe_value(text, 300) == expected


def test_a_generated_piece_in_a_query_value_is_masked_alone():
    assert mask_urls(f"https://x.example.com/s?next=/users/{HEX}/profile") == (
        "https://x.example.com/s?next=/users/[REDACTED]/profile"
    )
    assert mask_urls(f"https://x.example.com/s?abi=arm64-v8a/{HEX}/x86_64") == (
        "https://x.example.com/s?abi=arm64-v8a/[REDACTED]/x86_64"
    )


# -- 5. base64 that contains ``/`` is still hidden -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (B64_SHORT, MARKER),  # no piece reaches 12: judged together
        (AWS, MARKER),  # the short middle piece is next to masked pieces: one token
        (B64_SLASH, f"{MARKER}/{MARKER}"),  # both pieces are masked on their own
        ("Ab3dE5gH/jK9mN1pQ", MARKER),  # two short pieces with capitals: 16 unusual characters
        (f"{HEX}/K7MDENG", MARKER),  # a short piece with a capital next to a masked one
        (f"K7MDENG/{HEX}", MARKER),
        ("Ab3dE5gH/jK9mN1pQ/profile/sT5vW7yZ/9bC2eF/hI4kL6n", f"{MARKER}/profile/{MARKER}"),
    ],
)
def test_standard_base64_cut_by_slashes_is_masked(value: str, expected: str):
    assert mask_urls(f"x?s={value}") == f"x?s={expected}"
    assert mask_opaque_runs(f"user:{value}") == f"user:{expected}"
    assert_hidden(f"https://x.example.com/p?s={value}", value)
    assert_hidden(f"hook?{value}", value)


def test_a_token_with_ordinary_words_around_it_is_masked_and_the_words_stay():
    assert mask_urls("x?next=/api/Ab3dE5gH/jK9mN1pQ/v1") == "x?next=/api/[REDACTED]/v1"
    assert mask_opaque_runs(f"/reset/{AWS}/confirm") == "/reset/[REDACTED]/confirm"


@pytest.mark.parametrize("separator", ["/", "%2F", "%2f"])
def test_an_encoded_slash_cuts_a_token_like_a_slash(separator: str):
    short = B64_SHORT.replace("/", separator)
    aws = AWS.replace("/", separator)
    both = B64_SLASH.replace("/", separator)
    assert mask_urls(f"x?s={short}") == f"x?s={MARKER}"
    assert mask_urls(f"x?s={aws}") == f"x?s={MARKER}"
    assert mask_urls(f"x?s={both}") == f"x?s={MARKER}{separator}{MARKER}"


# -- 6. the boundary: a short piece is not evidence by itself ------------------------------------


def test_eleven_unusual_characters_are_not_a_token_and_twelve_are():
    # ``Ab3dE5gH`` (8) and ``jK9`` (3): 11 characters, the length of a short id
    assert mask_opaque_runs("Ab3dE5gH/jK9") == "Ab3dE5gH/jK9"
    # one more character: 12, the length from which a single segment is masked as well
    assert mask_opaque_runs("Ab3dE5gH/jK9m") == MARKER
    assert mask_opaque_runs("x/Ab3dE5gH/jK9m/y") == f"x/{MARKER}/y"


@pytest.mark.parametrize(
    "text",
    [
        "users/Ab3dE5gH/profile",  # one short piece between plain words
        "files/Ab3dE5gH/readme.md",
        "a/Ab3dE5gH/b/jK9mN1pQ/c",  # two of them, kept apart by words
        "users/u1234/posts/v8a/x",
        "/s/ab12cd34/ef56gh78",  # side by side, but neither has a capital letter
    ],
)
def test_short_unusual_pieces_between_ordinary_words_are_kept(text: str):
    assert mask_opaque_runs(text) == text
    assert mask_urls(f"x?next={text}") == f"x?next={text}"


def test_plain_words_inside_a_short_piece_are_not_evidence():
    """Only the characters outside plain words count towards the twelve: ``A1b-user`` is 8
    characters long but holds 3 unusual ones."""
    assert mask_opaque_runs("A1b-user/C2d-item") == "A1b-user/C2d-item"
    assert mask_urls("x?next=A1b-user/C2d-item") == "x?next=A1b-user/C2d-item"


def test_a_short_id_without_a_capital_letter_ends_a_group():
    # ``ab12cd34`` is not a possible piece of base64 cut by a slash (no capital letter), so the
    # group is only what follows it
    assert mask_opaque_runs("ab12cd34/Ab3dE5gH/jK9mN1pQ") == f"ab12cd34/{MARKER}"
    assert mask_opaque_runs("Ab3dE5gH/jK9mN1pQ/ab12cd34") == f"{MARKER}/ab12cd34"


def test_the_separators_around_a_masked_group_are_kept_as_they_were_written():
    assert mask_opaque_runs("x/Ab3dE5gH/jK9mN1pQ/y") == f"x/{MARKER}/y"
    assert mask_opaque_runs("x%2FAb3dE5gH%2FjK9mN1pQ%2Fy") == f"x%2F{MARKER}%2Fy"
    assert mask_opaque_runs("x%2FAb3dE5gH/jK9mN1pQ%2fy") == f"x%2F{MARKER}%2fy"
    assert mask_opaque_runs("/Ab3dE5gH/jK9mN1pQ/") == f"/{MARKER}/"


def test_a_short_id_without_a_capital_letter_is_not_part_of_a_neighbouring_token():
    # judged on its own: 8 characters. Said out loud, see the last section.
    assert mask_opaque_runs(f"{HEX}/ab12cd34") == f"{MARKER}/ab12cd34"


def test_pieces_of_twelve_characters_are_judged_on_their_own_as_before():
    assert mask_opaque_runs("users/0a1b2c3d4e5f/profile") == f"users/{MARKER}/profile"
    assert mask_opaque_runs("users/0a1b2c3d4e5/profile") == "users/0a1b2c3d4e5/profile"  # 11


# -- 7. percent-encoded values -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://x.example.com/cb?redirect_uri=https%3A%2F%2Fexample.com%2Fusers%2Fab12cd34%2Fprofile",
        "https://x.example.com/s?path=lib%2Farm64-v8a%2Flibnative.so",
        "https://x.example.com/s?path=lib%2farm64-v8a%2flibnative.so",
        "https://x.example.com/s?next=%2Fusers%2Fab12cd34%2Fposts%2Fef56gh78",
        "https://x.example.com/s?abi=armeabi-v7a%2Farm64-v8a%2Fx86_64",
        "https://x.example.com/s?img=https%3A%2F%2Fcdn.example.com%2Favatars%2Fu1234%2Fprofile_picture.png",
        "https://x.example.com/s?q=android%20studio%2Ftutorial%2Fv8a",
        "https://x.example.com/cb?redirect_uri=https%3A%2F%2Fexample.com%2Fcallback&state=ok",
        "https://x.example.com/s?file=images%2Favatars%2Fprofile_picture_large.png",
    ],
)
def test_an_ordinary_percent_encoded_url_is_kept(text: str):
    assert mask_urls(text) == text
    assert scrub(text) == text
    assert safe(text, 300) == text


@pytest.mark.parametrize(
    "text",
    [
        f"https://x.example.com/s?next=%2Fusers%2F{HEX}%2Fprofile",
        f"https://x.example.com/s?redirect_uri=https%3A%2F%2Fexample.com%2Fcb%2F{UUID}",
        f"https://x.example.com/s?s={HEX}",
        f"https://x.example.com/s?s={B64_SLASH.replace('/', '%2F')}",
        f"https://x.example.com/s?s={AWS.replace('/', '%2F')}",
    ],
)
def test_a_generated_value_in_a_percent_encoded_url_is_masked(text: str):
    out = mask_urls(text)
    assert MARKER in out
    for secret in (
        HEX,
        UUID,
        "K7MDENG",
        "bPxRfiCYEXAMPLEKEY",
        "Zm9vYmFyYmF6cXV4",
        "MTIzNDU2Nzg5MEFCQ0RFRg",
    ):
        assert secret not in out or secret not in text
    assert mask_urls(out) == out  # idempotent


def test_the_encoded_structure_around_a_masked_piece_is_kept():
    assert (
        mask_urls(f"x?next=%2Fusers%2F{HEX}%2Fprofile") == "x?next=%2Fusers%2F[REDACTED]%2Fprofile"
    )


# -- 8. query values and meta-data values, in the report -----------------------------------------

ROUTE = "files/{id}?abi=armeabi-v7a/arm64-v8a/x86_64"


def project(label: str, meta: dict[str, str], route: str) -> dict[str, str]:
    kt = f"""
        package com.x
        import androidx.navigation.compose.composable
        import androidx.navigation.NavController
        fun androidx.navigation.NavGraphBuilder.g(nav: NavController) {{
            composable("{route}") {{ }}
        }}
        fun go(nav: NavController) {{ nav.navigate("{route}") }}
        """
    metadata = "".join(
        f'<meta-data android:name="{name}" android:value="{value}"/>'
        for name, value in meta.items()
    )
    manifest = (
        f'<manifest {ANDROID_NS}><application android:name=".App" android:label="{label}">'
        f"{metadata}</application></manifest>"
    )
    return mini_app(extra={"app/src/main/AndroidManifest.xml": manifest}, Code=kt)


def test_ordinary_values_with_slashes_are_readable_in_the_report():
    meta = {"abi": LIB, "next": NEXT_QUERY, "cdn": CDN}
    report = analyse(project(CDN, meta, ROUTE))
    no_errors(report)
    application = next(f for f in report.facts if f.kind == "application")
    assert application.attributes["label"] == CDN
    values = {f.subject: f.attributes["value"] for f in report.facts if f.kind == "meta_data"}
    assert values == meta
    route = next(f for f in report.facts if f.kind == "compose_route")
    assert route.subject == ROUTE and route.attributes["route"] == ROUTE
    edge = next(r for r in report.relationships if r.kind == "navigates_to")
    assert edge.target == f"compose_route:{ROUTE}"


@pytest.mark.parametrize("secret", [B64_SHORT, AWS, B64_SLASH, f"x/{HEX}/y", f"{HEX}/K7MDENG"])
def test_a_generated_value_with_slashes_does_not_reach_the_report(secret: str):
    report = analyse(project(f"https://x.example.com/p?s={secret}", {"k": secret}, f"r?s={secret}"))
    no_errors(report)
    text = report.model_dump_json()
    for piece in pieces_of(secret):
        assert piece not in text, piece
    value = next(f.attributes["value"] for f in report.facts if f.kind == "meta_data")
    assert MARKER in value


# -- 9. excerpt literals -------------------------------------------------------------------------
# (a literal that is long, or a single unbroken token of 16+ characters, is already replaced by an
# ellipsis by an older rule, so these are short strings with a space or a ``?`` in them)


@pytest.mark.parametrize(
    "literal",
    [
        "abis: armeabi-v7a/arm64-v8a/x86_64",
        "go: lib/arm64-v8a/libnative.so",
        "see /users/ab12cd34/profile",
        "x.com/s?next=/users/ab12cd34/profile",
        "x.com/s?abi=armeabi-v7a/arm64-v8a",
        "u: avatars/u1234/profile_picture.png",
    ],
)
def test_an_ordinary_literal_in_an_excerpt_is_kept(literal: str):
    assert redact_excerpt(f'val s = "{literal}"') == f'val s = "{literal}"'
    assert redact_excerpt(f"val s = '{literal}'") == f"val s = '{literal}'"


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("k: Ab3dE5gH/jK9mN1pQ", f"k: {MARKER}"),
        ("x: 5f3c2a1b9e8d/K7MDENG", f"x: {MARKER}"),
        (f"id: {HEX}", f"id: {MARKER}"),
        ("p: users/0a1b2c3d4e5f/profile", f"p: users/{MARKER}/profile"),
    ],
)
def test_a_generated_literal_in_an_excerpt_is_masked(literal: str, expected: str):
    assert redact_excerpt(f'val s = "{literal}"') == f'val s = "{expected}"'


# -- 10. both sides, over many values ------------------------------------------------------------

WORDS = [
    "api", "v1", "v2", "users", "posts", "items", "orders", "lines", "profile", "images",
    "avatars", "lib", "files", "cache", "static", "assets", "comments", "likes", "reviews",
]  # fmt: skip
ABI_NAMES = ["armeabi-v7a", "arm64-v8a", "x86_64", "x86"]
ALNUM_LOWER = "abcdefghijklmnopqrstuvwxyz0123456789"
ALNUM_MIXED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def ordinary_path(rng: random.Random) -> str:
    """Words, short lowercase ids (anywhere, even side by side), ABI names, and short ids with a
    capital letter only between words: never a token, whatever the slashes make of it."""
    pieces: list[str] = []
    for _ in range(rng.randint(2, 7)):
        kind = rng.random()
        if kind < 0.45:
            pieces.append(rng.choice(WORDS))
        elif kind < 0.7:
            pieces.append("".join(rng.choice(ALNUM_LOWER) for _ in range(rng.randint(2, 9))))
        elif kind < 0.8:
            pieces.append(rng.choice(ABI_NAMES))
        else:
            if pieces and pieces[-1] not in WORDS:
                pieces.append(rng.choice(WORDS))
            pieces.append("".join(rng.choice(ALNUM_MIXED) for _ in range(rng.randint(2, 8))))
            pieces.append(rng.choice(WORDS))
    return "/".join(pieces)


def test_ordinary_paths_with_short_ids_are_never_changed():
    rng = random.Random(4242)
    for _ in range(4000):
        path = ordinary_path(rng)
        assert mask_opaque_runs(path) == path, path
        assert mask_urls(f"https://x.example.com/s?next=/{path}") == (
            f"https://x.example.com/s?next=/{path}"
        ), path
        encoded = path.replace("/", "%2F")
        assert mask_urls(f"https://x.example.com/s?next=%2F{encoded}") == (
            f"https://x.example.com/s?next=%2F{encoded}"
        ), path


def random_base64_with_slash(rng: random.Random, low: int, high: int) -> str:
    while True:
        token = base64.b64encode(rng.randbytes(rng.randint(low, high))).decode().rstrip("=")
        if "/" in token:
            return token


def test_random_base64_with_slashes_is_hidden_in_nearly_every_case():
    """Measured, not promised: pieces that a slash cuts to under 12 characters and that look like
    ordinary camel-case words (``ulbiwTw``) cannot be told from names by shape, so a few tokens
    keep a piece of up to 11 characters. 3,000 random tokens measured 94-96 % fully hidden; the
    bound here is lower so that the test only fails when the rule really gets worse."""
    rng = random.Random(7)
    tokens = [random_base64_with_slash(rng, 24, 60) for _ in range(600)]
    hidden = 0
    for token in tokens:
        out = mask_urls(f"https://x.example.com/p?s={token}")
        if not any(piece in out for piece in pieces_of(token)[1:]):
            hidden += 1
        assert token not in out  # the token as a whole never survives
    assert hidden / len(tokens) >= 0.88, hidden / len(tokens)


def test_a_token_is_never_hidden_by_masking_its_neighbours_only():
    rng = random.Random(11)
    for _ in range(300):
        token = random_base64_with_slash(rng, 30, 60)
        out = mask_opaque_runs(f"reset/{token}/confirm")
        assert out.startswith("reset/") and out.endswith("/confirm")
        assert token not in out


# -- 11. hostile input ---------------------------------------------------------------------------


def test_slash_heavy_input_is_masked_quickly():
    started = time.perf_counter()
    n = 100_000
    for text in (
        "/" * n,
        "%2F" * n,
        "a/" * n,
        "Ab3dE5gH/" * n,
        "Ab3dE5gH%2F" * (n // 2),
        "/".join(["Ab3dE5gH"] * n),
        "users/Ab3dE5gH/" * (n // 4),
        "u1234/" * n,
        "arm64-v8a/" * (n // 2),
        "x/" * 5 + "Ab3dE5gH/jK9mN1pQ/" * (n // 4),
        ("Ab3dE5gH/" * 500 + "profile/") * 200,
        "A1/" * n,
    ):
        mask_opaque_runs(text)
        mask_urls("x?s=" + text)
        safe_value(text, 200)
        redact_excerpt(f'val s = "{text[:5000]}"')
        redact_url("https://h.example.com/" + text, 300)
    assert time.perf_counter() - started < 25


def test_masking_is_idempotent_and_never_touches_its_own_marker():
    for text in (
        *REPORTED,
        *SHORT_ID_PATHS,
        f"x?s={B64_SHORT}",
        f"x?s={AWS}",
        f"build/{HEX}/out",
        f"x?s={AWS.replace('/', '%2F')}",
        f"user:{HEX}/K7MDENG",
    ):
        once = mask_opaque_runs(text)
        assert mask_opaque_runs(once) == once
        url_once = mask_urls(text)
        assert mask_urls(url_once) == url_once


# -- 12. what the rule cannot tell apart, said out loud ------------------------------------------


def test_a_slash_cut_token_of_pieces_that_look_like_words_keeps_them():
    """``ulbiwTw`` is shaped like the camel-case word ``userId``: nothing marks it as part of the
    token next to it. This is the rule's limit, not a promise: the 11 characters stay."""
    assert mask_urls(f"x?s=ulbiwTw/{HEX}") == f"x?s=ulbiwTw/{MARKER}"


@pytest.mark.parametrize(
    "name",
    [
        "app-arm64-v8a-release.apk",
        "libnative-armeabi-v7a.so",
        "layout-sw600dp-land",
        "ic_launcher_2x.png",
    ],
)
def test_a_long_name_with_one_short_unusual_word_is_masked_as_a_piece_known_false_positive(
    name: str,
):
    """Unchanged by the fourth correction and not part of it: a piece of 12+ characters with a
    word that is not a plain word (``v8a``, ``sw600dp``, ``2x``) is masked by the same rule that
    judges a URL path segment, with or without slashes around it. Pinned so that a later change to
    the piece criterion is a decision, not an accident (see the progress document)."""
    assert mask_opaque_runs(name) == MARKER
    assert mask_opaque_runs(f"dl/{name}") == f"dl/{MARKER}"
    assert mask_urls(f"https://x.example.com/dl/{name}") == f"https://x.example.com/dl/{MARKER}"


def test_two_adjacent_short_names_that_are_unusual_together_are_one_token():
    """Twelve unusual characters in a row are masked whether or not a slash cuts them (the same
    reason a 12-character segment is masked): two adjacent device names are an accepted false
    positive, while a name between plain words is kept."""
    assert mask_opaque_runs("devices/S21Ultra/Nexus5X/specs") == f"devices/{MARKER}/specs"
    assert mask_opaque_runs("devices/S21Ultra/specs/Nexus5X") == "devices/S21Ultra/specs/Nexus5X"
