"""F2: generated-looking values do not reach a report, whatever they are called.

The reproduced leaks, all with a 32-digit hex value and an innocent name: ``?s=<hex>`` in an excerpt,
a bare ``meta-data`` value, ``"id=<hex>"`` as a ``meta-data`` value, ``"user:<hex>"`` in an excerpt,
and the matrix parameter ``;jsid=<hex>``. The rule is by shape, not by name, and it does not
claim to recognise a secret that looks like an ordinary word or is shorter than 12 characters.
"""

from __future__ import annotations

import time

import pytest
from analysis_fixtures import ANDROID_NS, APP_NS, analyse, d, fact, ids, mini_app, no_errors

from androai_codegen.analysis import AnalysisReport
from androai_codegen.analysis.store import make_id
from androai_codegen.analysis.text import (
    mask_opaque_runs,
    mask_urls,
    redact_excerpt,
    redact_path,
    redact_url,
    safe,
    safe_value,
    scrub,
)

HEX = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"  # 32 hex digits, no keyword near it
HEX_UPPER = HEX.upper()
UUID = "550e8400-e29b-41d4-a716-446655440000"
B64URL = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRg"
HEX12, HEX11 = "0a1b2c3d4e5f", "0a1b2c3d4e5"
MASKED_VALUES = {"hex": HEX, "HEX": HEX_UPPER, "uuid": UUID, "base64url": B64URL, "hex12": HEX12}


# -- query, fragment and matrix values, whatever the parameter is called -------------------------


@pytest.mark.parametrize("value", MASKED_VALUES.values(), ids=MASKED_VALUES.keys())
@pytest.mark.parametrize("name", ["s", "sid", "code", "otp", "t", "x-id", "v", "ref.id", "r_1"])
@pytest.mark.parametrize("sep", ["?", "&", "#", ";"])
def test_a_generated_value_is_masked_whatever_the_parameter_is_called(name, value, sep):
    url = f"https://api.example.com/v1/items{sep}{name}={value}"
    if sep == "&":
        url = f"https://api.example.com/v1/items?page=2&{name}={value}"
    for helper in (mask_urls, lambda t: safe(t, 300), redact_excerpt):
        masked = helper(url)
        assert value not in masked, (helper, masked)
        assert f"{name}=[REDACTED]" in masked  # the name stays: it says what the value was for
        assert "api.example.com/v1/items" in masked
    assert value not in redact_url(url, 300)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1/items?page=2&sort=name&q=hello_world",
        "https://x.example.com/s?v=1.2.3-SNAPSHOT&lang=en-US&ts=1700000000",
        "https://x.example.com/s?since=2024-01-15T10:30:00Z&until=2024-02-01",
        "https://x.example.com/s?redirect=https://example.com/a/b&next=home",
        "https://x.example.com/s?ids=1,2,3,4,5,6,7,8,9&fields=name,email,created_at",
        "https://x.example.com/s?mode=dark_theme_enabled&layout=GridLayoutManager",
        "https://x.example.com/p;v=2;lang=en?x=1",
        "https://x.example.com/s?count=${count}&name={name}",
        "hook?page=2&sort=name",
    ],
)
def test_ordinary_query_values_are_left_alone(url: str):
    assert mask_urls(url) == url


def test_a_value_is_judged_from_twelve_characters_and_only_by_its_shape():
    assert mask_urls(f"x?s={HEX11}") == f"x?s={HEX11}"  # too short to judge
    assert mask_urls(f"x?s={HEX12}") == "x?s=[REDACTED]"
    assert mask_urls("x?s=hello_world_and_more") == "x?s=hello_world_and_more"  # words
    assert mask_urls("x?s=SNAPSHOT_RELEASE_CANDIDATE") == "x?s=SNAPSHOT_RELEASE_CANDIDATE"
    assert mask_urls(f"x?s={HEX}&t={HEX}") == "x?s=[REDACTED]&t=[REDACTED]"
    assert mask_urls(f"x?s={HEX}&page=2&t={UUID}") == "x?s=[REDACTED]&page=2&t=[REDACTED]"


def test_a_keyword_named_parameter_is_still_masked_whatever_its_value():
    assert mask_urls("x?api_key=hello") == "x?api_key=[REDACTED]"
    assert mask_urls("x?access_token=abc") == "x?access_token=[REDACTED]"
    assert mask_urls("x/p;jsessionid=abc") == "x/p;jsessionid=[REDACTED]"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://x.example.com/p;jsid={HEX}", "https://x.example.com/p;jsid=[REDACTED]"),
        (f"https://x.example.com/p;jsid={HEX}?x=1", "https://x.example.com/p;jsid=[REDACTED]"),
        (
            f"https://x.example.com/a;v=1/b;jsid={HEX}/c",
            "https://x.example.com/a;v=1/b;jsid=[REDACTED]/c",
        ),
        (f"https://x.example.com/p;{HEX}", "https://x.example.com/p;[REDACTED]"),
        (f"https://x.example.com/{HEX};x=1", "https://x.example.com/[REDACTED];x=1"),
        (
            f"https://x.example.com/p;a={HEX};b={UUID}",
            "https://x.example.com/p;a=[REDACTED];b=[REDACTED]",
        ),
        (f"p;jsid={HEX}", "p;jsid=[REDACTED]"),
        (f"/api/p;jsid={HEX}/x", "/api/p;jsid=[REDACTED]/x"),
        (f"https://$host/p;jsid={HEX}", "https://$host/p;jsid=[REDACTED]"),
        ("https://x.example.com/p;v=2;lang=en", "https://x.example.com/p;v=2;lang=en"),
    ],
)
def test_matrix_parameters_are_judged_apart_and_their_keys_stay(url: str, expected: str):
    assert redact_url(url, 300) == expected


def test_redact_path_alone_handles_matrix_parameters():
    assert redact_path(f"/a/b;jsid={HEX}") == "/a/b;jsid=[REDACTED]"
    assert redact_path("/a/b;v=1;w=2") == "/a/b;v=1;w=2"


# -- text around a generated token ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"user:{HEX}", "user:[REDACTED]"),
        (f"id={HEX}", "id=[REDACTED]"),
        (f"a/b/{HEX}", "a/b/[REDACTED]"),
        (f"prefix {HEX} suffix", "prefix [REDACTED] suffix"),
        (f"{HEX},{UUID}", "[REDACTED],[REDACTED]"),
        (f"({B64URL})", "([REDACTED])"),
        ("1.0.0-SNAPSHOT", "1.0.0-SNAPSHOT"),
        ("com.example.app.FeatureFlags", "com.example.app.FeatureFlags"),
        ("androidx.startup", "androidx.startup"),
        ("2024-01-15T10:30:00Z", "2024-01-15T10:30:00Z"),
        ("application/vnd.android.package-archive", "application/vnd.android.package-archive"),
        ("ordinary words only, nothing generated", "ordinary words only, nothing generated"),
        ("short", "short"),
    ],
)
def test_mask_opaque_runs_masks_the_token_and_keeps_the_words_around_it(text: str, expected: str):
    assert mask_opaque_runs(text) == expected
    assert mask_opaque_runs(mask_opaque_runs(text)) == expected  # idempotent


def test_a_number_of_sixteen_digits_or_more_is_treated_as_generated():
    """A known trade-off: such a number may be a card or an account number. ``ca-app-pub-<16
    digits>~<10 digits>`` (an AdMob id) is masked with it."""
    assert mask_opaque_runs("id 1234567890123456 end") == "id [REDACTED] end"
    assert mask_opaque_runs("id 123456789012345 end") == "id 123456789012345 end"


def test_safe_value_masks_before_it_clips_so_a_cut_never_leaves_a_fragment():
    text = "x" * 90 + f" {HEX}"
    for limit in range(95, 125):
        shown = safe_value(text, limit)
        assert HEX[:6] not in shown and len(shown) <= limit


# -- excerpts: short composite strings -----------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (f'const val C = "user:{HEX}"', 'const val C = "user:[REDACTED]"'),
        (f'@GET("hook?s={HEX}") fun a(): Int', '@GET("hook?s=[REDACTED]") fun a(): Int'),
        (f'val x = "k={HEX}"', None),
        (f"val x = '{HEX}'", None),
        (f'val h = mapOf("sid" to "{HEX}")', None),
        (f'val u = "https://x.example.com/p;jsid={HEX}"', None),
    ],
)
def test_an_excerpt_never_shows_a_generated_value(line: str, expected: str | None):
    shown = redact_excerpt(line)
    assert HEX not in shown
    if expected is not None:
        assert shown == expected  # and the rest of the line is kept


@pytest.mark.parametrize(
    "line",
    [
        'val q = "SELECT * FROM notes"',
        'val r = "home/{id}"',
        'val t = "2024-01-15T10:30:00Z"',
        'const val V = "1.0.0-SNAPSHOT"',
        'const val W = "version 2 of the thing"',
        '@Query("SELECT * FROM notes WHERE id = :id") fun byId(id: Int)',
        '@GET("v1/users/{id}/notes?page=2") fun notes()',
        'Log.d("TAG", "loaded")',
    ],
)
def test_an_excerpt_keeps_short_ordinary_strings(line: str):
    assert redact_excerpt(line) == line


def test_an_excerpt_hides_a_string_literal_only_beyond_forty_characters():
    forty = ("w" * 9 + " ") * 3 + "w" * 10  # words and spaces: nothing generated in it
    assert len(forty) == 40
    assert redact_excerpt(f'val s = "{forty}"') == f'val s = "{forty}"'
    assert redact_excerpt(f'val s = "{forty}w"') == 'val s = "…"'
    assert redact_excerpt(f"val s = '{forty}w'") == "val s = '…'"


# -- manifest meta-data --------------------------------------------------------------------------


def manifest(*values: tuple[str, str]) -> dict[str, str]:
    items = "".join(
        f'<meta-data android:name="{n}" android:value="{v.replace("&", "&amp;")}"/>'
        for n, v in values
    )
    return mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": f'<manifest {ANDROID_NS}><application android:name=".App">{items}</application></manifest>'
        }
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (HEX, "[REDACTED]"),  # bare
        (f"id={HEX}", "id=[REDACTED]"),  # composite
        (f"user:{HEX}", "user:[REDACTED]"),
        (UUID, "[REDACTED]"),
        (B64URL, "[REDACTED]"),
        (f"a/b/{HEX}", "a/b/[REDACTED]"),
        (f"prefix {HEX} suffix", "prefix [REDACTED] suffix"),
        (f"https://x.example.com/?s={HEX}", "https://x.example.com/?s=[REDACTED]"),
        (f"https://x.example.com/p;jsid={HEX}", "https://x.example.com/p;jsid=[REDACTED]"),
        (f"https://x.example.com/bot{HEX}/x", "https://x.example.com/[REDACTED]/x"),  # one segment
    ],
)
def test_a_meta_data_value_under_an_innocent_name_is_masked_by_shape(value: str, expected: str):
    report = analyse(manifest(("com.example.sdk.mode", value)))
    meta = fact(report, "meta_data:com.example.sdk.mode")
    assert meta.attributes["value"] == expected
    assert HEX not in report.model_dump_json() and UUID not in report.model_dump_json()


@pytest.mark.parametrize(
    "value",
    [
        "1.0.0-SNAPSHOT",
        "com.example.MyInitializer",
        "androidx.startup",
        "@string/app_name",
        "@integer/google_play_services_version",
        "https://example.com/api?page=2&sort=name",
        "true",
        "12",
        "Material3Theme",
        "en-US",
    ],
)
def test_an_ordinary_meta_data_value_is_kept_as_written(value: str):
    meta = fact(
        analyse(manifest(("com.example.sdk.mode", value))), "meta_data:com.example.sdk.mode"
    )
    assert meta.attributes["value"] == value


def test_a_secret_named_meta_data_value_is_still_hidden_whole():
    report = analyse(manifest(("com.example.sdk.api_key", "anything at all"), ("x.AUTH", HEX)))
    assert fact(report, "meta_data:com.example.sdk.api_key").attributes["value"] == "[REDACTED]"
    assert fact(report, "meta_data:x.AUTH").attributes["value"] == "[REDACTED]"


# -- the whole report ----------------------------------------------------------------------------

PLANTED = {
    "hex": HEX,
    "hex2": "f9e8d7c6b5a4938271605f4e3d2c1b0a",
    "uuid": UUID,
    "b64": B64URL,
    "hexup": HEX_UPPER,
}


def sweep_project() -> dict[str, str]:
    h, h2, u, b = PLANTED["hex"], PLANTED["hex2"], PLANTED["uuid"], PLANTED["b64"]
    kt = f'''
        package com.x
        import dagger.Provides
        import javax.inject.Named
        import retrofit2.Retrofit
        import retrofit2.http.GET
        import retrofit2.http.POST

        const val A = "user:{h}"
        const val B = "id={h2}"
        const val C = "{b}"
        interface Api {{
            @GET("hook?s={h}") fun a(): Int
            @GET("v1/data?id={h2}&x=1") fun b(): Int
            @GET("page;jsid={h}/x") fun c(): Int
            @POST("items/{{id}}?ref={u}") fun d(): Int
        }}
        object M {{
            @Provides @Named("user:{h2}") fun a(): String = ""
        }}
        fun one() = Retrofit.Builder().baseUrl("https://x.example.com/p;jsid={h}/").build()
        fun two() = Retrofit.Builder().baseUrl("https://x.example.com/?s={h}").build()
        '''
    nav = f'<navigation {ANDROID_NS} {APP_NS} android:id="@+id/nav"><fragment android:id="@+id/home" android:name="com.x.H"><deepLink app:uri="https://x.example.com/v?s={h}&amp;t={u}"/></fragment></navigation>'
    manifest_xml = f"""<manifest {ANDROID_NS}><application android:name=".App">
      <meta-data android:name="n1" android:value="{h}"/>
      <meta-data android:name="n2" android:value="id={h2}"/>
      <meta-data android:name="n3" android:value="user:{h}"/>
      <meta-data android:name="n4" android:value="https://x.example.com/?s={h}"/>
      <activity android:name=".A" android:exported="true"><intent-filter>
        <action android:name="android.intent.action.VIEW"/><category android:name="android.intent.category.DEFAULT"/>
        <data android:scheme="https" android:host="x.example.com" android:pathPrefix="/r;jsid={h}"/>
      </intent-filter></activity></application></manifest>"""
    return mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": manifest_xml,
            "app/src/main/res/navigation/nav.xml": nav,
            "app/build.gradle.kts": d(f"""
                plugins {{ id("com.android.application") }}
                android {{ namespace = "com.x" }}
                repositories {{ maven {{ url = uri("https://repo.example.com/m;jsid={h}/") }} }}
                """),
        },
        Api=kt,
    )


def strings_of(report: AnalysisReport) -> list[str]:
    out: list[str] = []
    for item in report.facts:
        out += [item.id, item.subject, item.note or "", item.reason or ""]
        out += [str(v) for v in item.attributes.values()]
        out += [e.excerpt for e in item.evidence]
        out += [e.path for e in item.evidence]
        out += list(item.tags)
    for rel in report.relationships:
        out += [rel.id, rel.source, rel.target, rel.note or "", rel.reason or ""]
        out += [e.excerpt for e in rel.evidence]
    for limitation in report.limitations:
        out += [limitation.scope, limitation.message]
    return out


def test_no_generated_value_appears_anywhere_in_the_report_or_its_json():
    report = analyse(sweep_project())
    no_errors(report)
    text = report.model_dump_json()
    leaves = strings_of(report)
    assert len(leaves) > 150
    for name, secret in PLANTED.items():
        assert secret not in text, f"{name} leaked into the JSON"
        assert secret[:12] not in text, f"a fragment of {name} leaked into the JSON"
        for leaf in leaves:
            assert secret not in leaf, (name, leaf[:100])


def test_the_useful_part_of_each_surface_survives():
    report = analyse(sweep_project())
    meta = {f.subject: f.attributes["value"] for f in report.facts if f.kind == "meta_data"}
    assert meta == {
        "n1": "[REDACTED]",
        "n2": "id=[REDACTED]",
        "n3": "user:[REDACTED]",
        "n4": "https://x.example.com/?s=[REDACTED]",
    }
    assert sorted(ids(report, "base_url")) == [
        "https://x.example.com/",
        "https://x.example.com/p;jsid=[REDACTED]/",
    ]
    paths = sorted(f.attributes["path"] for f in report.facts if f.kind == "http_endpoint")
    assert paths == sorted(["items/{id}", "page;jsid=[REDACTED]/x", "v1/data", "hook"])
    assert ids(report, "deep_link") == ["https://x.example.com/v"]
    activity = fact(report, "activity:com.x.A")
    assert activity.attributes["deep_links"] == ("https://x.example.com/r;jsid=[REDACTED]",)


def test_identifiers_are_not_masked_only_values_are():
    """A class or function named like a hex string keeps its name: ids must stay unambiguous."""
    name = "A9F8E7D6C5B4A392"
    report = analyse(mini_app(Names=f"package com.x\nclass {name}\nfun h0a1b2c3d4e5f6071() {{}}\n"))
    assert f"type:com.x.{name}" in {f.id for f in report.facts}
    assert any(f.id == "member:com.x#h0a1b2c3d4e5f6071()" for f in report.facts)


def test_make_id_and_scrub_mask_a_generated_value_in_a_url_shaped_subject():
    assert scrub(f"https://x.example.com/?s={HEX}") == "https://x.example.com/?s=[REDACTED]"
    assert make_id("deep_link", f"https://x.example.com/p;jsid={HEX}") == (
        "deep_link:https://x.example.com/p;jsid=[REDACTED]"
    )


# -- adversarial input and determinism -----------------------------------------------------------


def test_the_new_rules_survive_hostile_input_quickly():
    started = time.perf_counter()
    big = 200_000
    for text in (
        "?a=" * big,
        "?s=" + "a" * 600_000,
        "?s=" + "aB1" * 200_000,
        ";a=b" * big,
        "#a=" + "0f" * 300_000,
        "/p" + ";k=v" * big,
        "x" * 1_000_000,
        "-".join(["ab"] * big),
        "a.b" * big,
        ("?s=" + "f" * 12 + "&") * big,
    ):
        mask_urls(text)
        mask_opaque_runs(text)
        redact_excerpt(f'val s = "{text[:5000]}"')
        redact_url("https://h.example.com/" + text, 300)
    assert time.perf_counter() - started < 20


def test_masking_is_idempotent_and_never_touches_its_own_marker():
    for text in (
        f"https://x.example.com/p;jsid={HEX}?s={HEX}#t={HEX}",
        f'const val A = "user:{HEX}"',
        f"id={HEX} and {UUID}",
        "https://x.example.com/p?s=[REDACTED]",
    ):
        once = mask_urls(text)
        assert mask_urls(once) == once
        assert mask_opaque_runs(mask_opaque_runs(text)) == mask_opaque_runs(text)
        assert redact_excerpt(redact_excerpt(text)) == redact_excerpt(text)


def test_the_report_is_deterministic_and_round_trips():
    files = sweep_project()
    first = analyse(dict(files))
    second = analyse(dict(reversed(list(files.items()))))
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()
    assert AnalysisReport.model_validate_json(first.model_dump_json()) == first
