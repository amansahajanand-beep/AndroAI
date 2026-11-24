"""M2.7: the file/symbol relationship graph, tags, and the query helpers."""

from __future__ import annotations

from analysis_fixtures import (
    ANDROID_NS,
    analyse,
    convention_project,
    edges,
    fact,
    hilt_project,
    java_xml_project,
    koin_project,
    mini_app,
)


def file_id(path: str) -> str:
    return f"file:{path}"


KT = "app/src/main/java/com/example/notes"


# -- graph edges --------------------------------------------------------------------------------


def test_files_declare_their_types_and_modules_contain_their_files():
    report = analyse(hilt_project())
    assert (file_id(f"{KT}/MainActivity.kt"), "type:com.example.notes.MainActivity") in edges(
        report, "declares"
    )
    assert ("module:app", file_id(f"{KT}/MainActivity.kt")) in edges(report, "contains")
    data = "core/data/src/main/java/com/example/notes/data/Note.kt"
    assert ("module:core/data", file_id(data)) in edges(report, "contains")
    assert ("module:app", file_id(data)) not in edges(report, "contains")


def test_supertypes_that_are_project_types_become_extends_and_implements_edges():
    report = analyse(java_xml_project())
    assert (
        "type:com.example.legacy.ui.DetailFragment",
        "type:com.example.legacy.ui.BaseFragment",
    ) in edges(report, "extends")
    hilt = analyse(hilt_project())
    assert (
        "type:com.example.notes.data.NoteRepositoryImpl",
        "type:com.example.notes.data.NoteRepository",
    ) in edges(hilt, "implements")
    # a framework base class is not a project type: no edge
    assert not any(t.endswith("ViewModel") and "androidx" in t for _, t in edges(hilt, "extends"))


def test_file_references_are_confirmed_by_import_package_or_wildcard_and_inferred_by_name():
    files = mini_app(
        Main="""
        package com.x
        import com.y.Explicit
        import com.z.*
        class Main {
            val a = Explicit()
            val b = SamePackage()
            val c = FromWildcard()
            val d = OnlyByName()
            val e = Ambiguous()
        }
        class SamePackage
        """,
        Explicit="package com.y\nclass Explicit\n",
        Wild="package com.z\nclass FromWildcard\n",
        Other="package com.q\nclass OnlyByName\nclass Ambiguous\n",
        Other2="package com.r\nclass Ambiguous\n",
    )
    report = analyse(files)
    main = file_id("app/src/main/java/com/x/Main.kt")
    refs = {
        r.target: r for r in report.relationships if r.kind == "references" and r.source == main
    }
    assert refs["type:com.y.Explicit"].status == "confirmed"
    assert refs["type:com.z.FromWildcard"].status == "confirmed"
    assert (
        refs["type:com.q.OnlyByName"].status == "inferred"
        and "no import" in refs["type:com.q.OnlyByName"].note
    )
    assert "type:com.x.SamePackage" not in refs  # declared in this very file
    assert not any("Ambiguous" in t for t in refs)  # two candidates and no import: not guessed


def test_a_name_in_a_comment_or_string_is_not_a_reference():
    files = mini_app(
        A='package com.x\n// Target\nval s = "Target"\nclass A\n',
        T="package com.y\nclass Target\n",
    )
    refs = [r for r in analyse(files).relationships if r.kind == "references"]
    assert refs == []


def test_an_activity_is_credited_with_the_fragments_its_layout_holds_as_an_inferred_edge():
    files = java_xml_project()
    files["app/src/main/res/layout/activity_legacy.xml"] = (
        f'<FrameLayout {ANDROID_NS} android:id="@+id/container">'
        '<androidx.fragment.app.FragmentContainerView android:name="com.example.legacy.ui.HomeFragment"/>'
        "</FrameLayout>"
    )
    report = analyse(files)
    derived = [
        r
        for r in report.relationships
        if r.kind == "hosts_fragment"
        and r.source == "type:com.example.legacy.LegacyActivity"
        and r.target.endswith("HomeFragment")
    ]
    assert derived and derived[0].status == "inferred" and "layout" in derived[0].note


def test_an_activity_is_tied_to_the_navigation_graph_its_layout_points_at():
    report = analyse(java_xml_project())
    assert ("layout:app|activity_main", "nav_graph:app|nav_main") in edges(report, "uses_nav_graph")
    derived = next(
        r
        for r in report.relationships
        if r.kind == "uses_nav_graph" and r.source == "type:com.example.legacy.MainActivity"
    )
    assert derived.status == "inferred"


# -- tags ---------------------------------------------------------------------------------------


def test_types_are_tagged_with_module_source_set_language_and_scope():
    report = analyse(hilt_project())
    main = fact(report, "type:com.example.notes.MainActivity")
    assert {"module:app", "source_set:main", "lang:kotlin"} <= set(main.tags)
    test = fact(report, "type:com.example.notes.NoteListViewModelTest")
    assert {"scope:test", "source_set:test"} <= set(test.tags)
    assert "module:core/data" in fact(report, "type:com.example.notes.data.Note").tags
    assert (
        "lang:java"
        in fact(analyse(java_xml_project()), "type:com.example.legacy.MainActivity").tags
    )


def test_roles_and_layers_are_tagged_from_what_the_code_is():
    report = analyse(hilt_project())
    vm = fact(report, "type:com.example.notes.ui.NoteListViewModel")
    assert {"role:viewmodel", "layer:presentation"} <= set(vm.tags)
    note = fact(report, "type:com.example.notes.data.Note")
    assert {"role:room_entity", "layer:data"} <= set(note.tags)
    api = fact(report, "type:com.example.notes.data.NotesApi")
    assert {"role:retrofit_service", "layer:network"} <= set(api.tags)
    module = fact(report, "type:com.example.notes.di.RepositoryModule")
    assert {"role:di_module", "layer:di"} <= set(module.tags)
    activity = fact(report, "activity:com.example.notes.MainActivity")
    assert "layer:ui" in activity.tags


def test_entry_points_are_tagged_on_both_the_role_fact_and_the_type():
    report = analyse(hilt_project())
    for fact_id in (
        "type:com.example.notes.NotesApp",
        "application:com.example.notes.NotesApp",
        "type:com.example.notes.MainActivity",
        "activity:com.example.notes.MainActivity",
    ):
        assert "entry-point" in fact(report, fact_id).tags, fact_id
    assert "launcher" in fact(report, "type:com.example.notes.MainActivity").tags
    assert "entry-point" not in fact(report, "type:com.example.notes.ui.NoteListViewModel").tags


# -- query helpers ------------------------------------------------------------------------------


def test_lookup_by_kind_tag_file_module_and_name():
    index = analyse(hilt_project()).index()
    assert "room_entity" in index.kinds()
    assert [f.subject for f in index.of_kind("room_dao")] == ["com.example.notes.data.NoteDao"]
    assert {f.kind for f in index.with_tag("role:viewmodel")} >= {"type", "viewmodel"}
    assert "layer:data" in index.tags()
    notes = index.in_file("core/data/src/main/java/com/example/notes/data/Note.kt")
    assert {"type:com.example.notes.data.Note", "room_entity:com.example.notes.data.Note"} <= {
        f.id for f in notes
    }
    assert {f.subject for f in index.in_module("core/data") if f.kind == "room_dao"} == {
        "com.example.notes.data.NoteDao"
    }
    assert {"type", "viewmodel", "hilt_viewmodel", "di_injectable"} <= {
        f.kind for f in index.named("com.example.notes.ui.NoteListViewModel")
    }
    assert any(
        f.kind == "composable" for f in index.named("NoteListScreen(()->Unit,NoteListViewModel)")
    )
    assert index.get("type:nope") is None


def test_members_of_a_type():
    index = analyse(hilt_project()).index()
    names = {
        f.attributes["name"] for f in index.members_of("com.example.notes.ui.NoteListViewModel")
    }
    assert names == {"_notes", "notes", "refresh"}


def test_outgoing_incoming_targets_and_sources():
    index = analyse(hilt_project()).index()
    db = "room_database:com.example.notes.data.NotesDatabase"
    assert [r.target for r in index.outgoing(db, ["exposes_dao"])] == [
        "room_dao:com.example.notes.data.NoteDao"
    ]
    entity = "room_entity:com.example.notes.data.Note"
    assert {f.kind for f in index.sources(entity, "accesses")} == {"room_dao"}
    assert [f.kind for f in index.targets(db, "contains_entity")] == ["room_entity"]
    assert index.outgoing("nope") == [] and index.incoming("nope") == []


def test_reachability_and_shortest_path_are_deterministic_and_bounded():
    index = analyse(hilt_project()).index()
    start = "compose_route:list"
    reach = index.reachable(start, ["navigates_to", "renders"], max_depth=1)
    assert "compose_route:add" in reach
    deeper = index.reachable(start, ["navigates_to", "renders"])
    assert set(reach) <= set(deeper) and len(deeper) >= len(reach)
    chain = index.path(
        "compose_route:list",
        "composable:com.example.notes.ui#AddNoteScreen()",
        ["navigates_to", "renders"],
    )
    assert [r.kind for r in chain] == ["navigates_to", "renders"]
    assert index.path("compose_route:add", "compose_route:list", ["navigates_to"]) is None
    assert index.path(start, start) == []
    assert (
        index.path(
            start,
            "composable:com.example.notes.ui#AddNoteScreen()",
            ["navigates_to", "renders"],
            max_depth=1,
        )
        is None
    )
    again = (
        analyse(hilt_project())
        .index()
        .path(
            "compose_route:list",
            "composable:com.example.notes.ui#AddNoteScreen()",
            ["navigates_to", "renders"],
        )
    )
    assert [r.id for r in again] == [r.id for r in chain]


def test_explain_gathers_evidence_edges_and_the_limitations_that_bear_on_a_fact():
    index = analyse(convention_project()).index()
    explained = index.explain("sdk_level:app|minSdk")
    assert explained["fact"].status == "unknown"
    assert any(m.code == "convention_plugin_dependencies_unknown" for m in explained["limitations"])
    assert index.explain("missing") is None
    good = (
        analyse(hilt_project())
        .index()
        .explain("room_database:com.example.notes.data.NotesDatabase")
    )
    assert good["evidence"] and good["outgoing"] and good["limitations"] is not None


def test_unknown_and_inferred_facts_can_be_listed():
    index = analyse(convention_project()).index()
    assert {f.kind for f in index.unknowns()} >= {"sdk_level", "module_type", "dependencies"}
    assert all(f.status == "unknown" for f in index.unknowns())
    hilt = analyse(hilt_project()).index()
    assert all(f.status == "inferred" for f in hilt.inferred())


# -- observation: presence is claimed, absence never is ------------------------------------------


def test_observation_reports_what_was_seen():
    index = analyse(hilt_project()).index()
    assert index.observation("room_database") == "observed"
    assert index.observation("room_database", "com.example.notes.data.NotesDatabase") == "observed"
    assert index.observation("koin_module") == "not_observed"  # complete project, none seen


def test_observation_is_unknown_not_not_observed_when_the_project_could_not_be_fully_read():
    index = analyse(convention_project()).index()
    assert index.observation("room_database") == "unknown"
    assert index.observation("retrofit_service") == "unknown"
    # something that was positively seen stays observed
    assert index.observation("activity") == "observed"


def test_observation_is_unknown_when_an_unknown_fact_of_that_kind_exists():
    index = analyse(convention_project()).index()
    assert index.observation("sdk_level", "app|minSdk") == "unknown"
    assert index.observation("dependencies", "app") == "unknown"


def test_observation_can_be_scoped_to_a_module():
    files = hilt_project()
    files["feature/build.gradle.kts"] = 'plugins { id("conv.thing") }\n'
    files["settings.gradle.kts"] = (
        'rootProject.name = "Notes"\ninclude(":app", ":core:data", ":feature")\n'
    )
    index = analyse(files).index()
    assert index.observation("koin_module", module="core/data") == "not_observed"
    assert index.observation("koin_module", module="feature") == "unknown"
    assert index.observation("koin_module") == "unknown"  # the whole project is not fully readable


def test_observation_ignores_limitations_that_do_not_affect_completeness():
    index = analyse(java_xml_project()).index()
    assert index.observation("koin_module") == "not_observed"


def test_koin_graph_queries():
    index = analyse(koin_project()).index()
    start = index.of_kind("koin_start")[0].id
    modules = {f.subject for f in index.targets(start, "loads_module")}
    assert modules == {"com.example.koinapp#appModule", "com.example.koinapp#dataModule"}
