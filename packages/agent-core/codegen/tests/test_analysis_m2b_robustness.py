"""M2.11: the M2B steps and the result must survive broken, hostile and awkward projects.

Whatever the input, no extractor may fail (that would be an ``extractor_error`` limitation and a
missing step), every fact must keep its status rule, the result must round-trip and a freshness
check must answer. Nothing here is about what a *good* project looks like: ``test_analysis_flows``,
``test_analysis_conventions`` and ``test_analysis_result`` do that.
"""

from __future__ import annotations

import random
import time

import pytest
from analysis_fixtures import (
    ANDROID_NS,
    analyse,
    convention_project,
    hilt_project,
    java_xml_project,
    koin_project,
    mini_app,
)
from test_analysis_conventions import fragments, mvi_models, presenters
from test_analysis_flows import MAIN_FILTER, activity, kt, manifest
from test_analysis_safety import _mutate

from androai_codegen.analysis import (
    AnalysisConfig,
    InvalidAnalysisResult,
    analyse_mapping_result,
    check_freshness,
    dumps_result,
    loads_result,
)

P = "app/src/main/java/com/x"


def intent_project() -> dict[str, str]:
    components = [
        activity("MainActivity", exported="true", body=MAIN_FILTER),
        activity("Detail"),
        activity(
            "Share",
            exported="true",
            body='<intent-filter><action android:name="android.intent.action.SEND"/></intent-filter>',
        ),
    ]
    sources = {
        "MainActivity": kt(
            "MainActivity",
            """
            fun a() { startActivity(Intent(this, Detail::class.java)) }
            fun b() { startActivity(Intent(Intent.ACTION_SEND)) }
            fun c(k: Class<*>) { startActivity(Intent(this, k)) }
            fun e() { PendingIntent.getActivity(this, 0, Intent(this, Share::class.java), 0) }
            """,
        ),
        "Detail": kt(
            "Detail", "fun back() { startActivity(Intent(this, MainActivity::class.java)) }"
        ),
        "Share": kt("Share"),
    }
    files = mini_app(extra={"app/src/main/AndroidManifest.xml": manifest(*components)}, **sources)
    fragments(4, 4, files)
    presenters(3, files)
    mvi_models(3, files)
    return files


def check_everything(files: dict, *, config: AnalysisConfig | None = None) -> None:
    """The properties that must hold for any input."""
    result = analyse_mapping_result(files, config=config)
    report = result.report
    assert [m for m in report.limitations if m.code == "extractor_error"] == []
    present = {f.id for f in report.facts}
    for item in report.facts:
        assert item.status != "confirmed" or item.evidence
        assert item.status != "inferred" or item.note
        assert item.status != "unknown" or item.reason
    for rel in report.relationships:
        assert rel.source in present and rel.target in present
    assert loads_result(dumps_result(result)) == result
    assert check_freshness(result, files, config=config).state in {"fresh", "unknown"}


# -- 1. seeded fuzz over the new steps -----------------------------------------------------------


def test_seeded_mutation_fuzz_never_breaks_the_new_steps_the_result_or_its_round_trip():
    rng = random.Random(20261124)
    projects = [
        intent_project(),
        hilt_project(),
        java_xml_project(),
        koin_project(),
        convention_project(),
    ]
    for iteration in range(120):
        files = dict(rng.choice(projects))
        for path in rng.sample(sorted(files), k=min(len(files), rng.randint(1, 4))):
            files[path] = _mutate(rng, files[path])
        try:
            check_everything(files)
        except AssertionError as exc:  # say which round failed
            raise AssertionError(f"iteration {iteration}: {exc}") from exc


def test_mutated_projects_give_the_same_result_whatever_the_file_order():
    rng = random.Random(11)
    files = intent_project()
    for path in rng.sample(sorted(files), k=6):
        files[path] = _mutate(rng, files[path])
    first = analyse_mapping_result(dict(files))
    second = analyse_mapping_result(dict(reversed(list(files.items()))))
    assert dumps_result(first) == dumps_result(second)


# -- 2. malformed manifests ----------------------------------------------------------------------

MANIFESTS = {
    "empty": "",
    "only a byte order mark": "﻿",
    "not xml": "this is not xml at all <<< >>>",
    "unclosed application": f'<manifest {ANDROID_NS}><application><activity android:name=".A">',
    "unclosed attribute": f'<manifest {ANDROID_NS}><application><activity android:name=".A /></application></manifest>',
    "no root": "<?xml version='1.0'?>",
    "an activity with no name": f"<manifest {ANDROID_NS}><application><activity/></application></manifest>",
    "an empty name": f'<manifest {ANDROID_NS}><application><activity android:name=""/></application></manifest>',
    "a name with spaces": f'<manifest {ANDROID_NS}><application><activity android:name=".A B" android:exported="true"/></application></manifest>',
    "an exported value that is a resource": f'<manifest {ANDROID_NS}><application><activity android:name=".A" android:exported="@bool/flag"><intent-filter><action android:name="x"/></intent-filter></activity></application></manifest>',
    "an intent filter with no action": f'<manifest {ANDROID_NS}><application><activity android:name=".A" android:exported="true"><intent-filter/></activity></application></manifest>',
    "an alias that points nowhere": f'<manifest {ANDROID_NS}><application><activity-alias android:name=".Al" android:targetActivity=".Missing" android:exported="true"/></application></manifest>',
    "a doctype": f'<!DOCTYPE manifest [<!ENTITY x "y">]><manifest {ANDROID_NS}><application/></manifest>',
    "binary garbage": "\x00\x01\x02" * 100,
}


@pytest.mark.parametrize("name", MANIFESTS)
def test_a_broken_manifest_does_not_stop_the_new_steps(name: str):
    files = mini_app(
        extra={"app/src/main/AndroidManifest.xml": MANIFESTS[name]},
        A="package com.x\nimport android.app.Activity\nclass A : Activity()\n",
    )
    check_everything(files)


def test_the_same_component_declared_twice_is_one_entry_point():
    twice = activity("Dup", exported="true", body=MAIN_FILTER) * 2
    report = analyse(mini_app(extra={"app/src/main/AndroidManifest.xml": manifest(twice)}))
    assert [f.id for f in report.facts if f.id == "entry_point:com.x.Dup"] == [
        "entry_point:com.x.Dup"
    ]


def test_an_exported_value_that_is_not_true_or_false_is_decided_by_the_intent_filter():
    files = mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": MANIFESTS["an exported value that is a resource"]
        }
    )
    entry = next(f for f in analyse(files).facts if f.id == "entry_point:com.x.A")
    assert entry.attributes["exposure"] == "implicit"


# -- 3. Intent lookalikes and broken calls -------------------------------------------------------

DECOYS = {
    "a line comment": "// startActivity(Intent(this, Detail::class.java))",
    "a block comment": "/* startActivity(Intent(this, Detail::class.java)) */",
    "a KDoc": "/** startActivity(Intent(this, Detail::class.java)) */",
    "a string": 'val s = "startActivity(Intent(this, Detail::class.java))"',
    "a raw string": 'val s = """startActivity(Intent(this, Detail::class.java))"""',
    "a method called Intent": "fun go() { builder.Intent(this, Detail::class.java) }",
    "a variable named like the class": "val Intent = 1; fun go() { Intent.toString() }",
}


@pytest.mark.parametrize("name", DECOYS)
def test_an_intent_in_a_comment_or_a_string_is_not_an_edge(name: str):
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")]
    files = mini_app(
        extra={"app/src/main/AndroidManifest.xml": manifest(*components)},
        MainActivity=kt("MainActivity", DECOYS[name]),
        Detail=kt("Detail"),
    )
    report = analyse(files)
    assert not any(r.kind == "launches_activity" for r in report.relationships)


BROKEN_CALLS = [
    "fun go() { startActivity(Intent(",
    "fun go() { startActivity(Intent(this,",
    "fun go() { startActivity(Intent(this, Detail::class.java",
    "fun go() { startActivity(Intent(this, ::class.java)) }",
    "fun go() { startActivity(Intent(this, Detail::class)) }",
    "fun go() { startActivity(Intent(this, Detail.class)) }",
    "fun go() { startActivity(Intent(Intent(Intent(this, Detail::class.java)))) }",
    "fun go() { startActivity(Intent(this, Detail::class.java).apply { Intent(this, Detail::class.java) }) }",
    "fun go() { Intent(this, Detail::class.java).also { startActivity(it) } }",
    "fun go() { if (x) startActivity(Intent(this, Detail::class.java)) else finish() }",
    "fun go() = startActivity(Intent(this, Detail::class.java))",
    "val i = Intent(this, Detail::class.java)",
    "fun go() { Intent().setAction().setClass().setComponent(ComponentName()) }",
    'fun go() { startActivity(Intent("")) }',
    "fun go() { startActivity(Intent(,,,)) }",
    "fun go() { startActivity(Intent(this, " + "Detail::class.java, " * 2000 + ")) }",
    "fun go() { " + "startActivity(Intent(this, Detail::class.java)); " * 500 + "}",
    "fun go() { " + "(" * 3000 + "Intent(this, Detail::class.java)" + ")" * 3000 + " }",
]


@pytest.mark.parametrize("snippet", BROKEN_CALLS, ids=range(len(BROKEN_CALLS)))
def test_a_broken_or_odd_intent_call_never_raises(snippet: str):
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")]
    files = mini_app(
        extra={"app/src/main/AndroidManifest.xml": manifest(*components)},
        MainActivity=kt("MainActivity", snippet),
        Detail=kt("Detail"),
    )
    check_everything(files)


def test_intents_in_every_place_a_declaration_can_be():
    source = """
        package com.x
        import android.app.Activity
        import android.content.Intent
        class MainActivity : Activity() {
            companion object { fun open(c: Activity) { c.startActivity(Intent(c, Detail::class.java)) } }
            inner class Inner { fun go() { startActivity(Intent(this@MainActivity, Detail::class.java)) } }
            val lazyIntent by lazy { Intent(this, Detail::class.java) }
        }
        object Router { fun to(c: Activity) { c.startActivity(Intent(c, Detail::class.java)) } }
        fun topLevel(c: Activity) { c.startActivity(Intent(c, Detail::class.java)) }
        """
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")]
    files = mini_app(
        extra={"app/src/main/AndroidManifest.xml": manifest(*components)},
        MainActivity=source,
        Detail=kt("Detail"),
    )
    report = analyse(files)
    sources = {r.source for r in report.relationships if r.kind == "launches_activity"}
    assert "type:com.x.MainActivity.Companion" in sources or "type:com.x.MainActivity" in sources
    assert "type:com.x.Router" in sources
    assert "file:app/src/main/java/com/x/MainActivity.kt" in sources  # the top-level function


# -- 4. budgets and deadlines --------------------------------------------------------------------


def test_a_spent_deadline_stops_the_new_steps_cleanly_and_says_so():
    result = analyse_mapping_result(intent_project(), config=AnalysisConfig(deadline_seconds=0.0))
    assert any(m.code == "time_budget_exceeded" for m in result.report.limitations)
    assert [m for m in result.report.limitations if m.code == "extractor_error"] == []
    assert loads_result(dumps_result(result)) == result


def test_a_flow_work_budget_of_one_step_still_yields_a_valid_result():
    config = AnalysisConfig(max_flow_visited=1, max_flow_screens=1, max_flow_depth=1)
    check_everything(intent_project(), config=config)


def test_every_limit_set_to_its_minimum_still_yields_a_valid_result():
    config = AnalysisConfig(
        max_files=1,
        max_file_bytes=1,
        max_facts=1,
        max_members_per_type=1,
        max_evidence_per_fact=1,
        max_types_per_file=1,
        max_flow_screens=1,
        max_flow_visited=1,
        max_flow_depth=1,
        max_intents_per_file=1,
    )
    result = analyse_mapping_result(intent_project(), config=config)
    assert [m for m in result.report.limitations if m.code == "extractor_error"] == []
    assert loads_result(dumps_result(result)) == result


# -- 5. deep and wide graphs ---------------------------------------------------------------------


def test_hostile_input_a_chain_of_thousands_of_composables_is_cut_by_the_depth_limit_quickly():
    n = 3_000
    chain = "\n".join(f"@Composable fun C{i}() {{ C{i + 1}() }}" for i in range(n))
    app = (
        "package com.x\nimport androidx.activity.ComponentActivity\n"
        "import androidx.activity.compose.setContent\nimport androidx.compose.runtime.Composable\n"
        "class MainActivity : ComponentActivity() {\n"
        "    override fun onCreate(b: android.os.Bundle?) { super.onCreate(b); setContent { C0() } }\n}\n"
        f"{chain}\n@Composable fun C{n}() {{}}\n"
    )
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER)]
    started = time.perf_counter()
    report = analyse(
        mini_app(
            extra={"app/src/main/AndroidManifest.xml": manifest(*components)}, MainActivity=app
        )
    )
    flow = next(f for f in report.facts if f.id == "app_flow:com.x.MainActivity")
    assert flow.attributes["truncated"] is True
    assert flow.attributes["max_depth"] <= 12
    assert time.perf_counter() - started < 30


def test_hostile_input_a_composable_that_calls_thousands_of_others_is_capped():
    n = 5_000
    calls = "".join(f"C{i}(); " for i in range(n))
    funs = "\n".join(f"@Composable fun C{i}() {{}}" for i in range(n))
    app = (
        "package com.x\nimport androidx.activity.ComponentActivity\n"
        "import androidx.activity.compose.setContent\nimport androidx.compose.runtime.Composable\n"
        "class MainActivity : ComponentActivity() {\n"
        "    override fun onCreate(b: android.os.Bundle?) { super.onCreate(b); setContent { Root() } }\n}\n"
        f"@Composable fun Root() {{ {calls} }}\n{funs}\n"
    )
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER)]
    started = time.perf_counter()
    report = analyse(
        mini_app(
            extra={"app/src/main/AndroidManifest.xml": manifest(*components)}, MainActivity=app
        )
    )
    calls_made = [r for r in report.relationships if r.kind == "calls_composable"]
    assert 0 < len(calls_made) <= 40 * 3
    assert time.perf_counter() - started < 30


def test_hostile_input_thousands_of_packages_and_types_are_described_quickly():
    files = mini_app()
    for i in range(1_500):
        files[f"{P}/p{i}/F{i}.kt"] = (
            f"package com.x.p{i}\nimport androidx.fragment.app.Fragment\nclass F{i} : Fragment()\n"
        )
    started = time.perf_counter()
    report = analyse(files)
    layout = [f for f in report.facts if f.id.startswith("convention:package_layout|")]
    assert layout
    assert time.perf_counter() - started < 60


# -- 6. awkward text -----------------------------------------------------------------------------


def test_crlf_files_give_the_same_conventions_as_lf_files():
    def build(eol: str) -> dict[str, str]:
        body = "".join(f"    val x{i} = {i}{eol}" for i in range(12))
        return mini_app(S=f"package com.x{eol}class S {{{eol}{body}}}{eol}")

    def formatting(files):
        return {
            f.id: f.attributes
            for f in analyse(files).facts
            if f.id.startswith("convention:formatting|")
        }

    lf, crlf = formatting(build("\n")), formatting(build("\r\n"))
    assert (
        lf["convention:formatting|indent"]["width"]
        == crlf["convention:formatting|indent"]["width"]
        == 4
    )
    assert (
        lf["convention:formatting|line_length"]["max"]
        == crlf["convention:formatting|line_length"]["max"]
    )


def test_cr_only_line_ends_and_nul_bytes_do_not_break_the_steps():
    files = mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": manifest(
                activity("A", exported="true", body=MAIN_FILTER)
            )
        },
        A="package com.x\rimport android.app.Activity\rclass A : Activity() {\r  fun go() { startActivity(Intent(this, A::class.java)) }\r}\r",
        B="package com.x\n\x00\x00class B\n",
    )
    check_everything(files)


def test_non_ascii_names_survive_the_json_round_trip_as_ascii():
    components = [activity("Café", exported="true", body=MAIN_FILTER)]
    files = mini_app(
        extra={"app/src/main/AndroidManifest.xml": manifest(*components)},
        Café="package com.x\nimport android.app.Activity\nclass Café : Activity()\n",
    )
    result = analyse_mapping_result(files)
    text = dumps_result(result)
    assert text.isascii() and "Caf\\u00e9" in text
    assert loads_result(text) == result


def test_paths_that_differ_only_by_case_are_two_inputs():
    files = mini_app()
    files[f"{P}/A.kt"] = "package com.x\nclass A\n"
    files[f"{P}/a.kt"] = "package com.x\nclass A2\n"
    result = analyse_mapping_result(files)
    paths = [f.path for f in result.provenance.input_files]
    assert f"{P}/A.kt" in paths and f"{P}/a.kt" in paths
    assert check_freshness(result, files).state == "fresh"


def test_loads_survives_a_truncated_result_at_every_cut():
    text = dumps_result(analyse_mapping_result(mini_app(K="package com.x\nclass K\n")))
    rng = random.Random(3)
    for _ in range(60):
        cut = rng.randrange(1, len(text) - 2)
        with pytest.raises(InvalidAnalysisResult):
            loads_result(text[:cut])
