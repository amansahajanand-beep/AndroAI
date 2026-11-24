"""M2.9: entry points, Intent targets and application flows.

What is pinned here: an entry point is read from the manifest (never guessed from a class name);
an explicit Intent target is a class literal and is ``confirmed`` only when the code shows the Intent
being started; an implicit target is matched to manifest intent filters and is always ``inferred``;
everything computed or deferred (``PendingIntent``, ``TaskStackBuilder``) is an ``unknown`` fact with
a reason and **no edge**; a flow is a bounded walk that says when it stopped early or met something
it cannot follow.
"""

from __future__ import annotations

import time

import pytest
from analysis_fixtures import (
    ANDROID_NS,
    analyse,
    d,
    edges,
    fact,
    hilt_project,
    java_xml_project,
    mini_app,
    no_errors,
)

from androai_codegen.analysis import AnalysisConfig, AnalysisReport, flows

HEADER = """
    package com.x
    import android.app.Activity
    import android.app.PendingIntent
    import android.app.TaskStackBuilder
    import android.content.ComponentName
    import android.content.Intent
    import android.net.Uri
"""
MAIN_FILTER = (
    '<intent-filter><action android:name="android.intent.action.MAIN"/>'
    '<category android:name="android.intent.category.LAUNCHER"/></intent-filter>'
)


def manifest(*components: str, application: str = '<application android:name=".App">') -> str:
    return f"<manifest {ANDROID_NS}>{application}{''.join(components)}</application></manifest>"


def activity(name: str, *, exported: str | None = None, body: str = "") -> str:
    flag = f' android:exported="{exported}"' if exported is not None else ""
    return f'<activity android:name=".{name}"{flag}>{body}</activity>'


def kt(name: str, body: str = "", *, extends: str = "Activity()") -> str:
    return d(HEADER) + f"class {name} : {extends} {{\n{d(body)}\n}}\n"


def project(components: list[str], sources: dict[str, str], **kwargs) -> AnalysisReport:
    files = mini_app(extra={"app/src/main/AndroidManifest.xml": manifest(*components)}, **sources)
    return analyse(files, **kwargs)


def launches(report: AnalysisReport) -> dict[tuple[str, str], str]:
    """``(source, target)`` -> status of every ``launches_activity`` edge."""
    return {
        (r.source, r.target): r.status
        for r in report.relationships
        if r.kind == "launches_activity"
    }


def one_main(body: str, *others: str) -> AnalysisReport:
    """``MainActivity`` (launcher) with ``body``, plus empty activities ``others``."""
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER)]
    components += [activity(name) for name in others]
    sources = {"MainActivity": kt("MainActivity", body)}
    sources.update({name: kt(name) for name in others})
    return project(components, sources)


MAIN = "type:com.x.MainActivity"


# -- 1. entry points -----------------------------------------------------------------------------


def test_the_launcher_activity_is_an_entry_point_read_from_the_manifest():
    report = one_main("")
    entry = fact(report, "entry_point:com.x.MainActivity")
    assert entry.status == "confirmed" and entry.basis == "manifest"
    assert entry.attributes["categories"] == ("exported_component", "launcher")
    assert entry.attributes["component_kind"] == "activity"
    assert entry.evidence and entry.evidence[0].path.endswith("AndroidManifest.xml")
    assert entry.evidence[0].line == 1
    assert ("entry_point:com.x.MainActivity", "activity:com.x.MainActivity") in edges(
        report, "entry_point_for"
    )


@pytest.mark.parametrize(
    ("exported", "has_filter", "expected"),
    [
        ("true", False, "true"),
        ("true", True, "true"),
        ("false", True, None),  # an explicit false wins over an intent filter
        ("false", False, None),
        (None, True, "implicit"),  # a filter makes it reachable when the flag is absent
        (None, False, None),
    ],
)
def test_a_component_is_an_entry_point_only_when_it_can_be_reached(exported, has_filter, expected):
    body = '<intent-filter><action android:name="com.x.DO"/></intent-filter>' if has_filter else ""
    report = project([activity("Plain", exported=exported, body=body)], {"Plain": kt("Plain")})
    present = any(f.id == "entry_point:com.x.Plain" for f in report.facts)
    assert present == (expected is not None)
    if expected is not None:
        assert fact(report, "entry_point:com.x.Plain").attributes["exposure"] == expected


def test_a_launcher_is_an_entry_point_even_when_exported_is_false():
    report = project([activity("Main", exported="false", body=MAIN_FILTER)], {"Main": kt("Main")})
    assert fact(report, "entry_point:com.x.Main").attributes["categories"] == ("launcher",)


def test_deep_links_and_actions_are_categories_of_an_exported_activity():
    link = (
        '<intent-filter><action android:name="android.intent.action.VIEW"/>'
        '<data android:scheme="https" android:host="example.com" android:pathPrefix="/a"/>'
        "</intent-filter>"
    )
    report = project([activity("Link", exported="true", body=link)], {"Link": kt("Link")})
    entry = fact(report, "entry_point:com.x.Link")
    assert entry.attributes["categories"] == ("deep_link", "exported_component", "intent_action")
    assert entry.attributes["deep_links"] == ("https://example.com/a",)
    assert entry.attributes["actions"] == ("android.intent.action.VIEW",)


def test_a_deep_link_on_a_component_that_is_not_exported_is_not_an_entry_point():
    link = (
        '<intent-filter><action android:name="android.intent.action.VIEW"/>'
        '<data android:scheme="https" android:host="example.com"/></intent-filter>'
    )
    report = project([activity("Hidden", exported="false", body=link)], {"Hidden": kt("Hidden")})
    assert not any(f.id == "entry_point:com.x.Hidden" for f in report.facts)


def test_main_alone_is_not_an_intent_action_category():
    report = one_main("")
    assert (
        "intent_action"
        not in fact(report, "entry_point:com.x.MainActivity").attributes["categories"]
    )


def test_the_application_class_is_an_entry_point_and_the_default_one_is_not():
    with_class = project(
        [activity("Main", exported="true", body=MAIN_FILTER)],
        {
            "Main": kt("Main"),
            "App": "package com.x\nimport android.app.Application\nclass App : Application()\n",
        },
    )
    entry = fact(with_class, "entry_point:com.x.App")
    assert entry.attributes["categories"] == ("application",)
    assert entry.attributes["component_kind"] == "application"
    files = mini_app()  # ``<application/>`` names no class
    without = analyse(files)
    assert [f for f in without.facts if f.kind == "entry_point"] == []


def test_an_activity_class_that_the_manifest_does_not_declare_is_not_an_entry_point():
    report = project(
        [activity("Main", exported="true", body=MAIN_FILTER)],
        {"Main": kt("Main"), "Ghost": kt("Ghost")},
    )
    assert not any(f.id == "entry_point:com.x.Ghost" for f in report.facts)
    assert fact(report, "activity:com.x.Ghost")  # it is still an Activity


def test_services_receivers_and_providers_follow_the_same_exposure_rule():
    report = project(
        [
            '<service android:name=".Open" android:exported="true"/>',
            '<service android:name=".Closed" android:exported="false"/>',
            '<receiver android:name=".Boot" android:exported="true"><intent-filter>'
            '<action android:name="android.intent.action.BOOT_COMPLETED"/></intent-filter></receiver>',
            '<provider android:name=".Data" android:authorities="com.x.data" android:exported="true"/>',
        ],
        {},
    )
    ids = {f.subject: f for f in report.facts if f.kind == "entry_point"}
    assert set(ids) == {
        "com.x.App",
        "com.x.Open",
        "com.x.Boot",
        "com.x.Data",
    }  # (App: the manifest names it)
    assert ids["com.x.Boot"].attributes["categories"] == ("exported_component", "intent_action")
    assert ids["com.x.Open"].attributes["component_kind"] == "service"


def test_observation_of_an_entry_point():
    report = one_main("")
    index = report.index()
    assert index.observation("entry_point", "com.x.MainActivity") == "observed"
    assert index.observation("entry_point", "com.x.Nope") == "not_observed"


# -- 2. explicit Intents -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "fun go() { startActivity(Intent(this, Detail::class.java)) }",
        'fun go() { this.startActivity(Intent(this, Detail::class.java).apply { putExtra("a", 1) }) }',
        "fun go() { startActivityForResult(Intent(this, Detail::class.java), 7) }",
        "fun go() { startActivity(Intent(this@MainActivity, Detail::class.java)) }",
        "fun go() { startActivity(Intent(this, com.x.Detail::class.java)) }",
        "fun go() { launcher.launch(Intent(this, Detail::class.java)) }",
        "fun go() { val i = Intent(this, Detail::class.java); startActivity(i) }",
        'fun go() { val i = Intent(this, Detail::class.java)\n  i.putExtra("a", 1)\n  startActivity(i) }',
        "fun go() { startActivity(Intent().setClass(this, Detail::class.java)) }",
        "fun go() { startActivity(Intent().setComponent(ComponentName(this, Detail::class.java))) }",
    ],
)
def test_an_explicit_intent_that_is_started_gives_a_confirmed_edge(snippet: str):
    report = one_main(snippet, "Detail")
    assert launches(report) == {(MAIN, "activity:com.x.Detail"): "confirmed"}


def test_a_java_explicit_intent_is_read_too():
    java = d("""
        package com.x;
        import android.app.Activity;
        import android.content.Intent;
        public class MainActivity extends Activity {
            void go() { startActivity(new Intent(MainActivity.this, Detail.class)); }
            void keep() { Intent i = new Intent(this, Other.class); startActivity(i); }
        }
        """)
    report = project(
        [
            activity("MainActivity", exported="true", body=MAIN_FILTER),
            activity("Detail"),
            activity("Other"),
        ],
        {"MainActivity_java": java, "Detail": kt("Detail"), "Other": kt("Other")},
    )
    assert launches(report) == {
        (MAIN, "activity:com.x.Detail"): "confirmed",
        (MAIN, "activity:com.x.Other"): "confirmed",
    }


def test_an_intent_that_is_built_and_never_started_is_inferred_not_confirmed():
    report = one_main("fun go() { val i = Intent(this, Detail::class.java) }", "Detail")
    assert launches(report) == {(MAIN, "activity:com.x.Detail"): "inferred"}
    edge = next(r for r in report.relationships if r.kind == "launches_activity")
    assert "not seen being started" in (edge.note or "")


def test_an_intent_started_in_another_function_is_not_taken_as_started():
    body = """
        fun build(): Intent = Intent(this, Detail::class.java)
        fun go() { startActivity(build()) }
        """
    report = one_main(body, "Detail")
    assert launches(report) == {(MAIN, "activity:com.x.Detail"): "inferred"}


def test_the_edge_carries_the_line_and_the_text_it_was_read_from():
    report = one_main("fun go() { startActivity(Intent(this, Detail::class.java)) }", "Detail")
    edge = next(r for r in report.relationships if r.kind == "launches_activity")
    assert edge.evidence and edge.evidence[0].path.endswith("MainActivity.kt")
    assert "Intent(this, Detail::class.java)" in edge.evidence[0].excerpt
    assert edge.evidence[0].line and edge.evidence[0].line > 1


def test_an_intent_to_a_class_outside_the_project_or_to_a_non_activity_makes_no_claim():
    body = """
        fun a() { startActivity(Intent(this, SettingsActivity::class.java)) }
        fun b() { startActivity(Intent(this, Worker::class.java)) }
        """
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER)]
    report = project(
        components,
        {"MainActivity": kt("MainActivity", body), "Worker": "package com.x\nclass Worker\n"},
    )
    assert launches(report) == {}
    assert [f for f in report.facts if f.kind == "intent_launch"] == []


def test_an_activity_declared_only_in_source_is_a_valid_target():
    report = project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER)],
        {
            "MainActivity": kt(
                "MainActivity", "fun go() { startActivity(Intent(this, Ghost::class.java)) }"
            ),
            "Ghost": kt("Ghost"),
        },
    )
    assert launches(report) == {(MAIN, "activity:com.x.Ghost"): "confirmed"}


# -- 3. computed and deferred targets are unknown, never an edge ---------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "fun go(cls: Class<*>) { startActivity(Intent(this, cls)) }",
        "fun go() { startActivity(Intent(this, javaClass)) }",
        "fun go() { startActivity(Intent(this, this::class.java)) }",
        "fun <T> go() { startActivity(Intent(this, T::class.java)) }",
        "fun go(action: String) { startActivity(Intent(action)) }",
        "fun go(a: String) { startActivity(Intent().setAction(a)) }",
        "fun go(c: Class<*>) { startActivity(Intent().setClass(this, c)) }",
    ],
)
def test_a_computed_target_is_unknown_with_a_reason_and_makes_no_edge(snippet: str):
    report = one_main(snippet, "Detail")
    assert launches(report) == {}
    unknowns = [f for f in report.facts if f.kind == "intent_launch"]
    assert len(unknowns) == 1
    assert unknowns[0].status == "unknown" and "computed" in (unknowns[0].reason or "")
    assert unknowns[0].evidence and unknowns[0].evidence[0].line
    assert any(
        r.kind == "launches" and r.status == "unknown" and r.target == unknowns[0].id
        for r in report.relationships
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "fun go() { val pi = PendingIntent.getActivity(this, 0, Intent(this, Detail::class.java), 0) }",
        'fun go() { val pi = PendingIntent.getActivity(\n this, 0,\n Intent(this, Detail::class.java).apply { putExtra("a", 1) },\n 0) }',
        "fun go() { val i = Intent(this, Detail::class.java)\n  val pi = PendingIntent.getActivity(this, 0, i, 0) }",
        "fun go() { TaskStackBuilder.create(this).addNextIntent(Intent(this, Detail::class.java)).startActivities() }",
        "fun go() { PendingIntent.getActivities(this, 0, arrayOf(Intent(this, Detail::class.java)), 0) }",
    ],
)
def test_an_intent_built_for_a_pending_intent_or_task_stack_is_deferred_not_an_edge(snippet: str):
    report = one_main(snippet, "Detail")
    assert launches(report) == {}
    unknowns = [f for f in report.facts if f.kind == "intent_launch"]
    assert len(unknowns) == 1
    assert "PendingIntent" in (unknowns[0].reason or "")


def test_unresolved_intents_do_not_make_the_report_incomplete():
    report = one_main("fun go(c: Class<*>) { startActivity(Intent(this, c)) }")
    limitation = next(m for m in report.limitations if m.code == "dynamic_navigation")
    assert limitation.affects_completeness is False
    assert limitation.scope.endswith("MainActivity.kt")
    assert report.complete is True
    assert report.index().observation("entry_point", "com.x.Nope") == "not_observed"


# -- 4. implicit Intents -------------------------------------------------------------------------

SEND_FILTER = (
    '<intent-filter><action android:name="android.intent.action.SEND"/>'
    '<category android:name="android.intent.category.DEFAULT"/></intent-filter>'
)


def with_share(body: str, *, filters: dict[str, str] | None = None) -> AnalysisReport:
    filters = filters if filters is not None else {"Share": SEND_FILTER}
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER)]
    components += [activity(name, exported="true", body=body_) for name, body_ in filters.items()]
    sources = {"MainActivity": kt("MainActivity", body)}
    sources.update({name: kt(name) for name in filters})
    return project(components, sources)


@pytest.mark.parametrize(
    "snippet",
    [
        "fun go() { startActivity(Intent(Intent.ACTION_SEND)) }",
        'fun go() { startActivity(Intent("android.intent.action.SEND")) }',
        "fun go() { startActivity(Intent().setAction(Intent.ACTION_SEND)) }",
        "fun go() { val i = Intent(Intent.ACTION_SEND); startActivity(i) }",
    ],
)
def test_an_implicit_intent_is_matched_to_the_manifest_and_is_inferred(snippet: str):
    report = with_share(snippet)
    assert launches(report) == {(MAIN, "activity:com.x.Share"): "inferred"}
    edge = next(r for r in report.relationships if r.kind == "launches_activity")
    assert "matches an intent filter" in (edge.note or "")


def test_an_implicit_intent_is_never_confirmed_even_when_started_directly():
    report = with_share("fun go() { startActivity(Intent(Intent.ACTION_SEND)) }")
    assert set(launches(report).values()) == {"inferred"}


def test_an_action_that_no_manifest_filter_declares_gives_no_claim():
    report = with_share("fun go() { startActivity(Intent(Intent.ACTION_DIAL)) }")
    assert launches(report) == {}
    assert [f for f in report.facts if f.kind == "intent_launch"] == []


def test_every_activity_that_declares_the_action_is_a_candidate():
    report = with_share(
        "fun go() { startActivity(Intent(Intent.ACTION_SEND)) }",
        filters={"ShareA": SEND_FILTER, "ShareB": SEND_FILTER},
    )
    assert launches(report) == {
        (MAIN, "activity:com.x.ShareA"): "inferred",
        (MAIN, "activity:com.x.ShareB"): "inferred",
    }
    edge = next(r for r in report.relationships if r.kind == "launches_activity")
    assert "2 match" in (edge.note or "")


VIEW_LINK = (
    '<intent-filter><action android:name="android.intent.action.VIEW"/>'
    '<data android:scheme="https" android:host="example.com"/></intent-filter>'
)


def test_a_view_intent_with_a_literal_uri_is_narrowed_by_the_deep_links():
    report = with_share(
        'fun go() { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com/a"))) }',
        filters={"Link": VIEW_LINK, "Other": VIEW_LINK.replace("example.com", "other.org")},
    )
    assert launches(report) == {(MAIN, "activity:com.x.Link"): "inferred"}


def test_a_view_intent_to_an_address_no_deep_link_covers_gives_no_claim():
    report = with_share(
        'fun go() { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://nowhere.net/a"))) }',
        filters={"Link": VIEW_LINK},
    )
    assert launches(report) == {}


def test_a_view_intent_without_a_literal_uri_keeps_every_view_candidate():
    report = with_share(
        "fun go(u: Uri) { startActivity(Intent(Intent.ACTION_VIEW, u)) }",
        filters={"Link": VIEW_LINK},
    )
    assert launches(report) == {(MAIN, "activity:com.x.Link"): "inferred"}


def test_an_implicit_intent_built_for_a_pending_intent_is_deferred_when_it_matches():
    report = with_share(
        "fun go() { PendingIntent.getActivity(this, 0, Intent(Intent.ACTION_SEND), 0) }"
    )
    assert launches(report) == {}
    assert len([f for f in report.facts if f.kind == "intent_launch"]) == 1


def test_a_custom_action_constant_is_computed_and_so_unknown():
    report = with_share("fun go() { startActivity(Intent(Actions.ACTION_SYNC)) }")
    assert launches(report) == {}
    assert len([f for f in report.facts if f.kind == "intent_launch"]) == 1


def test_an_action_string_literal_with_a_template_is_computed():
    report = with_share('fun go(n: String) { startActivity(Intent("com.x.$n")) }')
    assert launches(report) == {}
    assert len([f for f in report.facts if f.kind == "intent_launch"]) == 1


# -- 5. flows ------------------------------------------------------------------------------------


def chain(n: int, *, cyclic: bool = False) -> AnalysisReport:
    """A0 (launcher) -> A1 -> ... -> A(n-1) by explicit, started Intents."""
    components = [activity("A0", exported="true", body=MAIN_FILTER)]
    components += [activity(f"A{i}") for i in range(1, n)]
    sources = {}
    for i in range(n):
        nxt = i + 1 if i + 1 < n else (0 if cyclic else None)
        body = (
            f"fun go() {{ startActivity(Intent(this, A{nxt}::class.java)) }}"
            if nxt is not None
            else ""
        )
        sources[f"A{i}"] = kt(f"A{i}", body)
    return project(components, sources)


def test_a_flow_lists_the_screens_reached_from_an_entry_point():
    report = chain(4)
    flow = fact(report, "app_flow:com.x.A0")
    assert flow.attributes["screens"] == tuple(f"activity:com.x.A{i}" for i in range(4))
    assert flow.attributes["screen_count"] == 4
    assert flow.attributes["max_depth"] == 3
    assert flow.attributes["truncated"] is False and flow.attributes["dynamic"] is False
    assert flow.status == "confirmed"
    reached = {r.target: r.status for r in report.relationships if r.kind == "reaches"}
    assert reached == {f"activity:com.x.A{i}": "confirmed" for i in range(1, 4)}
    assert ("entry_point:com.x.A0", "app_flow:com.x.A0") in edges(report, "starts_flow")


def test_a_cycle_ends_the_walk_and_lists_each_screen_once():
    flow = fact(chain(3, cyclic=True), "app_flow:com.x.A0")
    assert flow.attributes["screens"] == tuple(f"activity:com.x.A{i}" for i in range(3))
    assert flow.attributes["truncated"] is False


def test_a_flow_that_meets_its_depth_limit_says_so_and_has_an_unknown_gap():
    report = analyse_chain(8, AnalysisConfig(max_flow_depth=3))
    flow = fact(report, "app_flow:com.x.A0")
    assert flow.attributes["truncated"] is True
    assert flow.attributes["screens"] == tuple(f"activity:com.x.A{i}" for i in range(4))
    gap = fact(report, "flow_gap:com.x.A0")
    assert gap.status == "unknown" and "stopped at its limit" in (gap.reason or "")
    assert ("app_flow:com.x.A0", "flow_gap:com.x.A0") in edges(report, "has_gap")
    limitation = next(m for m in report.limitations if m.code == "flow_cap_reached")
    assert limitation.affects_completeness is False and limitation.scope == "com.x.A0"


def analyse_chain(n: int, config: AnalysisConfig) -> AnalysisReport:
    components = [activity("A0", exported="true", body=MAIN_FILTER)]
    components += [activity(f"A{i}") for i in range(1, n)]
    sources = {
        f"A{i}": kt(
            f"A{i}",
            f"fun go() {{ startActivity(Intent(this, A{i + 1}::class.java)) }}"
            if i + 1 < n
            else "",
        )
        for i in range(n)
    }
    return project(components, sources, config=config)


def test_a_flow_is_cut_at_the_screen_limit_but_still_counts_every_screen():
    report = analyse_chain(8, AnalysisConfig(max_flow_screens=3))
    flow = fact(report, "app_flow:com.x.A0")
    assert len(flow.attributes["screens"]) == 3
    assert flow.attributes["screen_count"] == 8
    assert flow.attributes["truncated"] is True
    assert fact(report, "flow_gap:com.x.A0").status == "unknown"
    assert (
        len([r for r in report.relationships if r.kind == "reaches"]) == 2
    )  # the root is not listed


def test_a_walk_stops_at_the_visited_limit():
    report = analyse_chain(30, AnalysisConfig(max_flow_visited=5))
    flow = fact(report, "app_flow:com.x.A0")
    assert flow.attributes["truncated"] is True
    assert flow.attributes["screen_count"] <= 5


def test_an_inferred_link_makes_the_flow_and_the_screens_behind_it_inferred():
    components = [
        activity("MainActivity", exported="true", body=MAIN_FILTER),
        activity("Direct"),
        activity("Maybe"),
        activity("Beyond"),
    ]
    sources = {
        "MainActivity": kt(
            "MainActivity",
            """
            fun a() { startActivity(Intent(this, Direct::class.java)) }
            fun b() { val i = Intent(this, Maybe::class.java) }
            """,
        ),
        "Direct": kt("Direct"),
        "Maybe": kt("Maybe", "fun c() { startActivity(Intent(this, Beyond::class.java)) }"),
        "Beyond": kt("Beyond"),
    }
    report = project(components, sources)
    flow = fact(report, "app_flow:com.x.MainActivity")
    assert flow.status == "inferred" and "2 of 4" in (flow.note or "")
    reached = {r.target: r.status for r in report.relationships if r.kind == "reaches"}
    assert reached == {
        "activity:com.x.Direct": "confirmed",
        "activity:com.x.Maybe": "inferred",
        "activity:com.x.Beyond": "inferred",
    }
    assert flow.attributes["inferred_screens"] == 2


def test_a_screen_with_a_confirmed_path_and_an_inferred_one_is_confirmed():
    components = [
        activity("MainActivity", exported="true", body=MAIN_FILTER),
        activity("Mid"),
        activity("Target"),
    ]
    sources = {
        "MainActivity": kt(
            "MainActivity",
            """
            fun a() { val i = Intent(this, Target::class.java) }
            fun b() { startActivity(Intent(this, Mid::class.java)) }
            """,
        ),
        "Mid": kt("Mid", "fun c() { startActivity(Intent(this, Target::class.java)) }"),
        "Target": kt("Target"),
    }
    report = project(components, sources)
    reached = {r.target: r.status for r in report.relationships if r.kind == "reaches"}
    assert reached["activity:com.x.Target"] == "confirmed"
    assert fact(report, "app_flow:com.x.MainActivity").status == "confirmed"


def test_a_computed_intent_in_a_reached_screen_makes_the_flow_dynamic_with_a_gap():
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Next")]
    sources = {
        "MainActivity": kt(
            "MainActivity", "fun go() { startActivity(Intent(this, Next::class.java)) }"
        ),
        "Next": kt("Next", "fun go(c: Class<*>) { startActivity(Intent(this, c)) }"),
    }
    report = project(components, sources)
    flow = fact(report, "app_flow:com.x.MainActivity")
    assert flow.attributes["dynamic"] is True
    assert "computed" in (fact(report, "flow_gap:com.x.MainActivity").reason or "")


def test_a_computed_intent_in_an_unreached_class_leaves_the_flow_static():
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Lonely")]
    sources = {
        "MainActivity": kt("MainActivity"),
        "Lonely": kt("Lonely", "fun go(c: Class<*>) { startActivity(Intent(this, c)) }"),
    }
    report = project(components, sources)
    assert fact(report, "app_flow:com.x.MainActivity").attributes["dynamic"] is False
    assert not any(f.id == "flow_gap:com.x.MainActivity" for f in report.facts)


def test_an_activity_with_nothing_beyond_it_still_has_a_one_screen_flow():
    flow = fact(chain(1), "app_flow:com.x.A0")
    assert flow.attributes["screens"] == ("activity:com.x.A0",)
    assert flow.attributes["screen_count"] == 1


def test_an_application_class_that_leads_nowhere_has_no_flow():
    report = project(
        [activity("Main", exported="true", body=MAIN_FILTER)],
        {
            "Main": kt("Main"),
            "App": "package com.x\nimport android.app.Application\nclass App : Application()\n",
        },
    )
    assert not any(f.id == "app_flow:com.x.App" for f in report.facts)


def test_an_application_class_that_starts_an_activity_has_a_flow():
    app = d("""
        package com.x
        import android.app.Application
        import android.content.Intent
        class App : Application() {
            fun boot() { startActivity(Intent(this, Main::class.java)) }
        }
        """)
    report = project(
        [activity("Main", exported="true", body=MAIN_FILTER)], {"Main": kt("Main"), "App": app}
    )
    flow = fact(report, "app_flow:com.x.App")
    assert flow.attributes["screens"] == ("activity:com.x.Main",)


def test_a_receiver_that_starts_an_activity_has_a_flow_from_the_receiver():
    receiver = d("""
        package com.x
        import android.content.BroadcastReceiver
        import android.content.Context
        import android.content.Intent
        class Boot : BroadcastReceiver() {
            fun onReceive(c: Context, i: Intent) { c.startActivity(Intent(c, Main::class.java)) }
        }
        """)
    report = project(
        [
            activity("Main", exported="true", body=MAIN_FILTER),
            '<receiver android:name=".Boot" android:exported="true"><intent-filter>'
            '<action android:name="android.intent.action.BOOT_COMPLETED"/></intent-filter></receiver>',
        ],
        {"Main": kt("Main"), "Boot": receiver},
    )
    assert fact(report, "app_flow:com.x.Boot").attributes["screens"] == ("activity:com.x.Main",)


# -- 6. flows over the navigation M2A already reads ----------------------------------------------


def test_a_compose_flow_reaches_the_routes_and_the_screens_they_show():
    flow = fact(analyse(hilt_project()), "app_flow:com.example.notes.MainActivity")
    screens = set(flow.attributes["screens"])
    assert {"compose_route:list", "compose_route:add"} <= screens
    assert any(s.startswith("composable:") and "NoteListScreen" in s for s in screens)
    assert flow.attributes["dynamic"] is False


def test_an_xml_navigation_flow_reaches_destinations_and_fragments():
    flow = fact(analyse(java_xml_project()), "app_flow:com.example.legacy.MainActivity")
    screens = set(flow.attributes["screens"])
    assert "fragment:com.example.legacy.ui.HomeFragment" in screens
    assert "nav_destination:app|nav_main|homeFragment" in screens
    assert flow.status == "inferred"  # the layout-to-graph link is inferred


def test_an_intent_in_a_composable_continues_the_flow_through_its_route():
    app = d("""
        package com.x
        import android.content.Intent
        import androidx.activity.ComponentActivity
        import androidx.activity.compose.setContent
        import androidx.compose.runtime.Composable
        import androidx.compose.ui.platform.LocalContext
        import androidx.navigation.compose.NavHost
        import androidx.navigation.compose.composable
        import androidx.navigation.compose.rememberNavController
        class MainActivity : ComponentActivity() {
            override fun onCreate(b: android.os.Bundle?) { super.onCreate(b); setContent { AppNav() } }
        }
        @Composable
        fun AppNav() {
            val nav = rememberNavController()
            NavHost(nav, startDestination = "home") { composable("home") { HomeScreen() } }
        }
        @Composable
        fun HomeScreen() {
            val ctx = LocalContext.current
            ctx.startActivity(Intent(ctx, DetailActivity::class.java))
        }
        """)
    report = project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("DetailActivity")],
        {"MainActivity": app, "DetailActivity": kt("DetailActivity")},
    )
    flow = fact(report, "app_flow:com.x.MainActivity")
    screens = flow.attributes["screens"]
    assert "compose_route:home" in screens and "activity:com.x.DetailActivity" in screens
    assert ("composable:com.x#HomeScreen()", "activity:com.x.DetailActivity") in edges(
        report, "launches_activity"
    )
    nav_host_link = next(
        r
        for r in report.relationships
        if r.kind == "starts_at" and r.source.startswith("composable:")
    )
    assert nav_host_link.status == "inferred"
    assert "same composable" in (nav_host_link.note or "")


def test_a_composable_calls_edge_is_recorded_only_for_composables_a_flow_reaches():
    report = analyse(hilt_project())
    calls = [r for r in report.relationships if r.kind == "calls_composable"]
    assert calls
    assert all(r.evidence and r.evidence[0].line for r in calls)


COMPOSE_HEAD = """
    package com.x
    import androidx.activity.ComponentActivity
    import androidx.activity.compose.setContent
    import androidx.compose.runtime.Composable
    import androidx.navigation.compose.NavHost
    import androidx.navigation.compose.composable
    import androidx.navigation.compose.rememberNavController
    class MainActivity : ComponentActivity() {
        override fun onCreate(b: android.os.Bundle?) { super.onCreate(b); setContent { %s } }
    }
    """


def compose_flow(root: str, body: str) -> AnalysisReport:
    app = d(COMPOSE_HEAD % root) + d(body)
    return project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER)], {"MainActivity": app}
    )


def test_a_flow_through_computed_compose_routes_is_dynamic_and_has_a_gap():
    report = compose_flow(
        'AppNav("a", "b")',
        """
        @Composable
        fun AppNav(start: String, route: String) {
            val nav = rememberNavController()
            NavHost(nav, startDestination = start) { composable(route) { } }
        }
        """,
    )
    flow = fact(report, "app_flow:com.x.MainActivity")
    assert flow.attributes["dynamic"] is True
    gap = fact(report, "flow_gap:com.x.MainActivity")
    assert gap.status == "unknown" and "Compose route" in (gap.reason or "")
    assert not any(
        r.kind == "starts_at" and r.source.startswith("composable:") for r in report.relationships
    )


def test_a_nav_host_is_linked_only_to_the_start_route_written_inside_it():
    report = compose_flow(
        "NavA(); NavB()",
        """
        @Composable
        fun NavA() {
            val nav = rememberNavController()
            NavHost(nav, startDestination = "a") { composable("a") { } }
        }
        @Composable
        fun NavB() {
            val nav = rememberNavController()
            NavHost(nav, startDestination = "b") { composable("b") { } }
        }
        """,
    )
    links = {(r.source, r.target) for r in report.relationships if r.kind == "starts_at"}
    assert links == {
        ("composable:com.x#NavA()", "compose_route:a"),
        ("composable:com.x#NavB()", "compose_route:b"),
    }
    link = next(r for r in report.relationships if r.kind == "starts_at")
    assert link.status == "inferred" and link.evidence and link.evidence[0].line


# -- 7. determinism, size and hostile input ------------------------------------------------------


def test_the_flow_facts_do_not_depend_on_the_order_of_the_files():
    files = mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": manifest(
                activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")
            )
        },
        MainActivity=kt(
            "MainActivity", "fun go() { startActivity(Intent(this, Detail::class.java)) }"
        ),
        Detail=kt("Detail"),
    )
    first = analyse(dict(files))
    second = analyse(dict(reversed(list(files.items()))))
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()
    assert AnalysisReport.model_validate_json(first.model_dump_json()) == first


def test_the_new_facts_and_edges_are_all_explained():
    report = analyse(hilt_project())
    for item in (*report.facts, *report.relationships):
        if item.status == "inferred":
            assert item.note
        if item.status == "unknown":
            assert item.reason
        if item.status == "confirmed":
            assert item.evidence
    assert report.analysis_version == "m2b-1"


def test_many_intents_in_one_file_are_capped_and_say_so():
    body = "\n".join(
        f"fun f{i}() {{ startActivity(Intent(this, Detail::class.java)) }}" for i in range(50)
    )
    report = project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")],
        {"MainActivity": kt("MainActivity", body), "Detail": kt("Detail")},
        config=AnalysisConfig(max_intents_per_file=10),
    )
    limitation = next(m for m in report.limitations if m.code == "intent_cap_reached")
    assert limitation.affects_completeness is False
    assert "40 Intent constructions" in limitation.message


def test_the_work_limit_stops_later_entry_points_and_says_so():
    n = 40
    components = [activity("A0", exported="true", body=MAIN_FILTER)]
    components += [activity(f"A{i}", exported="true") for i in range(1, n)]
    sources = {
        f"A{i}": kt(
            f"A{i}",
            "\n".join(
                f"fun f{j}() {{ startActivity(Intent(this, A{(i + j) % n}::class.java)) }}"
                for j in range(1, 4)
            ),
        )
        for i in range(n)
    }
    report = project(components, sources, config=AnalysisConfig(max_flow_visited=10))
    assert any(m.code == "flow_cap_reached" and m.scope == "project" for m in report.limitations)
    flows = [f for f in report.facts if f.kind == "app_flow"]
    assert 0 < len(flows) < n
    # entries are never dropped (n activities and the Application class the manifest names)
    assert len([f for f in report.facts if f.kind == "entry_point"]) == n + 1


def test_hostile_projects_with_thousands_of_components_and_intents_are_fast():
    started = time.perf_counter()
    n = 2_000
    components = [activity("A0", exported="true", body=MAIN_FILTER)]
    components += [activity(f"A{i}", exported="true") for i in range(1, n)]
    body = "\n".join(
        f"fun f{i}() {{ startActivity(Intent(this, A{i}::class.java)) }}" for i in range(1, 600)
    )
    sources = {"A0": kt("A0", body)}
    sources.update({f"A{i}": kt(f"A{i}") for i in range(1, 60)})
    report = project(components, sources)
    no_errors(report)
    assert len([f for f in report.facts if f.kind == "entry_point"]) == n + 1  # (+ Application)
    assert time.perf_counter() - started < 30


def test_a_file_without_intents_is_not_scanned_and_gives_no_intent_facts():
    report = project(
        [activity("Main", exported="true", body=MAIN_FILTER)],
        {"Main": kt("Main", "fun go() { println(1) }")},
    )
    assert [f for f in report.facts if f.kind == "intent_launch"] == []
    assert launches(report) == {}


def test_unbalanced_brackets_in_an_intent_call_do_not_raise():
    report = one_main("fun go() { startActivity(Intent(this, Detail::class.java) }", "Detail")
    no_errors(report)


# -- 8. the scanners behind "is this Intent started?", and the boundaries ------------------------


def callees(text: str) -> list[str]:
    return flows._enclosing_callees(text, text.index("Intent("))


def test_the_calls_around_an_intent_are_listed_innermost_first_and_at_most_three():
    assert callees("outer(mid(inner(Intent(this))))") == ["inner", "mid", "outer"]
    assert callees("l4(l3(l2(l1(Intent(this)))))") == ["l1", "l2", "l3"]
    assert callees("startActivity(Intent(this))") == ["startActivity"]
    assert callees("a.b.startActivity(Intent(this))") == ["a.b.startActivity"]


def test_a_call_that_has_already_closed_is_not_around_the_intent():
    assert callees("f(g(1), Intent(this))") == ["f"]
    assert callees("f(a[0], h { 1 }, Intent(this))") == ["f"]
    assert callees("g(1) + Intent(this)") == []


def test_the_search_for_the_calls_around_an_intent_stops_at_a_block_a_semicolon_and_the_lookback():
    assert callees("run { startActivity(Intent(this))") == ["startActivity"]
    assert callees("foo(1); Intent(this)") == []
    assert callees("f(" + "x" * 300 + " Intent(this))") == ["f"]
    assert callees("f(" + "x" * 500 + " Intent(this))") == []


def start_of(text: str) -> int:
    return flows._statement_start(text, text.index("Intent("))


def test_a_statement_starts_after_the_last_semicolon_or_opening_brace_before_it():
    text = "val a = 1; val i = Intent(this)"
    assert start_of(text) == text.index(";") + 1
    text = "fun f() { val i = Intent(this)"
    assert start_of(text) == text.index("{") + 1
    assert start_of("val i = Intent(this)") == 0
    text = "x = foo(a; b) val i = Intent(this)"  # a semicolon inside brackets ends nothing
    assert start_of(text) == 0
    text = "x" * 500 + " val i = Intent(this)"
    assert start_of(text) == text.index("Intent(") - 400


def test_an_intent_kept_in_a_property_is_found_started_by_a_method_of_the_class():
    body = "val i = Intent(this, Detail::class.java)\nfun go() { startActivity(i) }"
    assert launches(one_main(body, "Detail")) == {(MAIN, "activity:com.x.Detail"): "confirmed"}


def test_a_top_level_intent_is_matched_to_a_start_in_the_same_file():
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")]
    source = (
        kt("MainActivity")
        + "val top = Intent(null, Detail::class.java)\nfun go2() { startActivity(top) }\n"
    )
    report = project(components, {"MainActivity": source, "Detail": kt("Detail")})
    assert launches(report) == {
        ("file:app/src/main/java/com/x/MainActivity.kt", "activity:com.x.Detail"): "confirmed"
    }


def test_a_component_name_alone_names_its_target():
    source = d("""
        package com.x
        import android.app.Activity
        import android.content.ComponentName
        class MainActivity : Activity() { fun go() { val c = ComponentName(this, Detail::class.java) } }
        """)
    components = [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")]
    report = project(components, {"MainActivity": source, "Detail": kt("Detail")})
    assert launches(report) == {(MAIN, "activity:com.x.Detail"): "inferred"}


FILLER = "val filler = " + " + ".join(["1"] * 120) + "\n"  # more than 200 characters of code


def test_set_class_on_something_that_is_not_an_intent_is_no_claim():
    report = one_main(
        FILLER + "fun go(w: Widget) { w.setClass(this, Detail::class.java) }", "Detail"
    )
    assert launches(report) == {}
    assert [f for f in report.facts if f.kind == "intent_launch"] == []


def test_a_class_argument_that_is_not_a_class_is_unknown_only_next_to_an_intent():
    near = one_main(
        "fun go(c: Class<*>) { startActivity(Intent().setComponent(ComponentName(this, c))) }"
    )
    assert len([f for f in near.facts if f.kind == "intent_launch"]) == 1
    far = one_main(FILLER + "fun go(c: Class<*>) { val n = ComponentName(this, c) }")
    assert [f for f in far.facts if f.kind == "intent_launch"] == []


def test_set_class_with_a_single_argument_is_not_a_class_target():
    report = one_main("fun go() { startActivity(Intent().setClass(this)) }")
    assert [f for f in report.facts if f.kind == "intent_launch"] == []
    assert launches(report) == {}


def test_a_view_intent_with_a_literal_uri_does_not_match_a_filter_that_has_no_data():
    plain = '<intent-filter><action android:name="android.intent.action.VIEW"/></intent-filter>'
    report = with_share(
        'fun go() { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com/a"))) }',
        filters={"Plain": plain},
    )
    assert launches(report) == {}


def test_exactly_as_many_intents_as_the_cap_is_not_over_the_cap():
    body = "\n".join(
        f"fun f{i}() {{ startActivity(Intent(this, Detail::class.java)) }}" for i in range(10)
    )
    report = project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER), activity("Detail")],
        {"MainActivity": kt("MainActivity", body), "Detail": kt("Detail")},
        config=AnalysisConfig(max_intents_per_file=10),
    )
    assert not any(m.code == "intent_cap_reached" for m in report.limitations)


def test_the_calls_around_an_intent_continue_past_an_index_but_not_past_a_block_or_a_semicolon():
    assert callees("outer(arr[inner(Intent(this))])") == ["inner", "outer"]
    assert callees("wrap(run { startActivity(Intent(this)) })") == ["startActivity"]
    assert callees("f(a; Intent(this))") == []


def test_an_entry_point_carries_its_module_and_the_entry_point_tag():
    entry = fact(one_main(""), "entry_point:com.x.MainActivity")
    assert {"entry-point", "module:app"} <= set(entry.tags)
    assert entry.attributes["module"] == "app"


def test_a_flow_that_never_reaches_compose_is_not_dynamic_because_another_screen_is():
    computed = d("""
        package com.x
        import androidx.activity.ComponentActivity
        import androidx.activity.compose.setContent
        import androidx.compose.runtime.Composable
        import androidx.navigation.compose.NavHost
        import androidx.navigation.compose.composable
        import androidx.navigation.compose.rememberNavController
        class Composey : ComponentActivity() {
            override fun onCreate(b: android.os.Bundle?) { super.onCreate(b); setContent { Nav("a", "b") } }
        }
        @Composable
        fun Nav(start: String, route: String) {
            val nav = rememberNavController()
            NavHost(nav, startDestination = start) { composable(route) { } }
        }
        """)
    report = project(
        [
            activity("Plain", exported="true", body=MAIN_FILTER),
            activity("Composey", exported="true"),
        ],
        {"Plain": kt("Plain"), "Composey": computed},
    )
    assert fact(report, "app_flow:com.x.Plain").attributes["dynamic"] is False
    assert fact(report, "app_flow:com.x.Composey").attributes["dynamic"] is True
    assert any(f.id == "navigation:compose" for f in report.facts)


def test_each_reached_composable_is_expanded_once(monkeypatch):
    from collections import Counter

    seen: Counter[str] = Counter()
    original = flows._Graph._expand_composable

    def counting(self, node):
        seen[node] += 1
        return original(self, node)

    monkeypatch.setattr(flows._Graph, "_expand_composable", counting)
    report = analyse(hilt_project())
    assert fact(report, "app_flow:com.example.notes.MainActivity")
    assert seen and max(seen.values()) == 1


def composable_file(root: str, body: str, *, extra_imports: str = "") -> AnalysisReport:
    head = d(COMPOSE_HEAD % root).replace(
        "import androidx.compose.runtime.Composable\n",
        "import androidx.compose.runtime.Composable\n" + extra_imports,
    )
    return project(
        [activity("MainActivity", exported="true", body=MAIN_FILTER)],
        {"MainActivity": head + d(body)},
    )


def calls_from(report: AnalysisReport, source: str) -> list[str]:
    return sorted(
        r.target
        for r in report.relationships
        if r.kind == "calls_composable" and r.source == source
    )


def test_a_composable_that_calls_the_same_composable_many_times_still_reaches_the_next_one():
    calls = "A(); " * 45 + "B()"
    report = composable_file(
        "Root()",
        f"@Composable fun Root() {{ {calls} }}\n@Composable fun A() {{}}\n@Composable fun B() {{}}",
    )
    assert calls_from(report, "composable:com.x#Root()") == [
        "composable:com.x#A()",
        "composable:com.x#B()",
    ]


def test_a_composable_has_at_most_forty_distinct_called_composables():
    names = [f"C{i}" for i in range(45)]
    calls = "".join(f"{n}(); " for n in names)
    funs = "\n".join(f"@Composable fun {n}() {{}}" for n in names)
    report = composable_file("Root()", f"@Composable fun Root() {{ {calls} }}\n{funs}")
    assert len(calls_from(report, "composable:com.x#Root()")) == 40
    assert calls_from(report, "composable:com.x#Root()") == sorted(
        f"composable:com.x#{n}()" for n in names[:40]
    )


def test_a_preview_and_the_composable_itself_are_not_called_composables():
    report = composable_file(
        "Root()",
        """
        @Composable fun Root() { Root(); RootPreview(); Other() }
        @Preview @Composable fun RootPreview() {}
        @Composable fun Other() {}
        """,
        extra_imports="import androidx.compose.ui.tooling.preview.Preview\n",
    )
    assert calls_from(report, "composable:com.x#Root()") == ["composable:com.x#Other()"]


def test_a_composable_call_matched_by_name_only_is_inferred_and_says_so():
    other = d("""
        package com.x.other
        import androidx.compose.runtime.Composable
        @Composable fun Elsewhere() {}
        """)
    app = d(COMPOSE_HEAD % "Root()") + d("@Composable fun Root() { Elsewhere() }")
    files = mini_app(
        extra={
            "app/src/main/AndroidManifest.xml": manifest(
                activity("MainActivity", exported="true", body=MAIN_FILTER)
            ),
            f"{P}/other/Elsewhere.kt": other,
        },
        MainActivity=app,
    )
    report = analyse(files)
    call = next(r for r in report.relationships if r.kind == "calls_composable")
    assert call.status == "inferred" and "matches one composable by name only" in (call.note or "")
    sure = composable_file(
        "Root()", "@Composable fun Root() { Local() }\n@Composable fun Local() {}"
    )
    assert next(r for r in sure.relationships if r.kind == "calls_composable").status == "confirmed"


P = "app/src/main/java/com/x"


def test_a_flow_counts_every_link_it_followed_exactly_once():
    app = composable_file(
        "AppNav()",
        """
        @Composable
        fun AppNav() {
            val nav = rememberNavController()
            NavHost(nav, startDestination = "home") { composable("home") { HomeScreen() } }
        }
        @Composable fun HomeScreen() {}
        """,
    )
    flow = fact(app, "app_flow:com.x.MainActivity")
    # hosts_content, calls_composable, starts_at, renders; a role fact "implemented by" its own
    # class is not a link
    assert flow.attributes["edge_count"] == 4
    assert flow.attributes["max_depth"] == 2


def test_a_reached_screen_is_backed_by_the_link_that_reached_it_not_by_the_manifest():
    report = chain(3)
    reaches = [r for r in report.relationships if r.kind == "reaches"]
    assert reaches
    for edge in reaches:
        assert edge.evidence and edge.evidence[0].path.endswith(".kt")
        assert "Intent(this" in edge.evidence[0].excerpt


def test_a_flow_that_is_not_truncated_says_so_and_a_status_note_matches_the_reached_screens():
    report = chain(3)
    flow = fact(report, "app_flow:com.x.A0")
    assert flow.attributes["truncated"] is False and flow.attributes["dynamic"] is False
    assert not any(f.kind == "flow_gap" for f in report.facts)
