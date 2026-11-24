"""M2.5: Activities, Fragments, Compose screens, layouts, bindings and navigation facts."""

from __future__ import annotations

from analysis_fixtures import (
    ANDROID_NS,
    APP_NS,
    analyse,
    d,
    edges,
    fact,
    hilt_project,
    ids,
    java_xml_project,
    koin_project,
    no_errors,
)


def kotlin_app(**sources: str) -> dict[str, str]:
    files = {
        "settings.gradle.kts": 'include(":app")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "app/src/main/AndroidManifest.xml": f"<manifest {ANDROID_NS}><application/></manifest>",
    }
    for name, text in sources.items():
        files[f"app/src/main/java/com/x/{name}.kt"] = d(text)
    return files


# -- Compose: composables and screens -----------------------------------------------------------


def test_composables_previews_wrappers_and_nav_hosts_are_told_apart():
    report = analyse(hilt_project())
    list_screen = fact(
        report, "composable:com.example.notes.ui#NoteListScreen(()->Unit,NoteListViewModel)"
    )
    assert list_screen.attributes["preview"] is False and list_screen.status == "confirmed"
    assert (
        fact(report, "composable:com.example.notes.ui#NoteListPreview()").attributes["preview"]
        is True
    )
    assert (
        fact(
            report, "composable:com.example.notes.ui.theme#NotesTheme(@Composable()->Unit)"
        ).attributes["wrapper"]
        is True
    )
    assert (
        fact(report, "composable:com.example.notes.ui#NotesNavHost()").attributes["nav_host"]
        is True
    )


def test_a_screen_is_confirmed_when_a_navigation_destination_shows_it():
    report = analyse(hilt_project())
    screens = ids(report, "compose_screen")
    assert [s.split("#")[1].split("(")[0] for s in screens] == [
        "AddNoteScreen",
        "NoteDetailScreen",
        "NoteListScreen",
    ]
    for screen in screens:
        found = fact(report, f"compose_screen:{screen}")
        assert found.status == "confirmed" and found.basis == "navigation"
    # not screens: the preview, the theme wrapper, the nav host, a plain helper
    for name in ("NoteListPreview", "NotesTheme", "NotesNavHost", "Banner"):
        assert not any(f"#{name}(" in s for s in screens)


def test_a_screen_matched_only_by_its_name_is_inferred_and_says_so():
    report = analyse(
        kotlin_app(
            S="""
            package com.x
            import androidx.compose.runtime.Composable
            @Composable fun SettingsScreen() {}
            @Composable private fun HiddenScreen() {}
            @Composable fun Other(navController: androidx.navigation.NavController) {}
            @Composable fun Plain() {}
            """
        )
    )
    found = {
        s.split("#")[1].split("(")[0]: fact(report, f"compose_screen:{s}")
        for s in ids(report, "compose_screen")
    }
    assert set(found) == {"SettingsScreen", "Other"}
    assert (
        found["SettingsScreen"].status == "inferred"
        and "named like a screen" in found["SettingsScreen"].note
    )
    assert found["Other"].status == "inferred" and "NavController" in found["Other"].note


def test_content_shown_by_setcontent_is_hosted_by_the_activity_and_inferred_as_a_screen():
    report = analyse(
        kotlin_app(
            A="""
            package com.x
            import androidx.activity.ComponentActivity
            import androidx.activity.compose.setContent
            import androidx.compose.runtime.Composable
            class A : ComponentActivity() {
                override fun onCreate(b: android.os.Bundle?) {
                    super.onCreate(b)
                    setContent { Theme { Home() } }
                }
            }
            @Composable fun Theme(content: @Composable () -> Unit) { content() }
            @Composable fun Home() {}
            """
        )
    )
    hosted = {t for s, t in edges(report, "hosts_content") if s == "type:com.x.A"}
    assert hosted == {"composable:com.x#Home()"}  # the theme wrapper is not hosted content
    home = fact(report, "compose_screen:com.x#Home()")
    assert home.status == "inferred" and "setContent" in home.note
    assert fact(report, "type:com.x.A").tags  # tagged


def test_a_composable_annotation_from_another_library_is_not_compose():
    report = analyse(
        kotlin_app(
            C="""
            package com.x
            import some.other.Composable
            @Composable fun NotCompose() {}
            """
        )
    )
    assert ids(report, "composable") == []


def test_an_unimported_composable_annotation_is_inferred_not_confirmed():
    report = analyse(kotlin_app(C="package com.x\n@Composable fun Maybe() {}\n"))
    maybe = fact(report, "composable:com.x#Maybe()")
    assert maybe.status == "inferred" and "name only" in maybe.note


def test_a_function_without_the_annotation_and_commented_annotations_are_not_composables():
    report = analyse(
        kotlin_app(
            C="""
            package com.x
            // @Composable fun Commented() {}
            val s = "@Composable fun InString() {}"
            fun plain() {}
            """
        )
    )
    assert ids(report, "composable") == []


# -- Compose navigation -------------------------------------------------------------------------


def test_routes_start_destination_arguments_and_destination_contents():
    report = analyse(hilt_project())
    assert ids(report, "compose_route") == ["add", "detail/{id}", "list"]  # Routes.LIST resolved
    assert fact(report, "compose_route:list").attributes["start_destination"] is True
    assert fact(report, "compose_route:detail/{id}").attributes["arguments"] == ("id",)
    rendered = {(s, t.split("#")[1].split("(")[0]) for s, t in edges(report, "renders")}
    assert rendered == {
        ("compose_route:list", "NoteListScreen"),
        ("compose_route:add", "AddNoteScreen"),
        ("compose_route:detail/{id}", "NoteDetailScreen"),
    }


def test_navigation_between_routes_is_confirmed_inside_a_destination_and_inferred_through_a_screen():
    report = analyse(hilt_project())
    nav = {(r.source, r.target): r for r in report.relationships if r.kind == "navigates_to"}
    inside = nav[("compose_route:list", "compose_route:add")]
    assert inside.status == "confirmed"
    through = nav[("compose_route:detail/{id}", "compose_route:list")]
    assert through.status == "inferred" and "NoteDetailScreen" in through.note


def test_typed_routes_and_dialog_destinations():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.compose.runtime.Composable
            import androidx.navigation.compose.NavHost
            import androidx.navigation.compose.composable
            import androidx.navigation.compose.dialog
            data class Detail(val id: Int)
            object Home
            @Composable fun Host(nav: androidx.navigation.NavHostController) {
                NavHost(nav, startDestination = Home) {
                    composable<Home> { HomeScreen() }
                    composable<Detail> { DetailScreen() }
                    dialog("confirm") { ConfirmDialog() }
                }
            }
            @Composable fun HomeScreen() {}
            @Composable fun DetailScreen() {}
            @Composable fun ConfirmDialog() {}
            """
        )
    )
    assert ids(report, "compose_route") == ["confirm", "typed:Detail", "typed:Home"]
    assert fact(report, "compose_route:typed:Home").attributes.get("start_destination") is True
    assert ("compose_route:typed:Detail", "type:com.x.Detail") in edges(report, "route_type")
    renders = edges(report, "renders")
    assert ("compose_route:confirm", "composable:com.x#ConfirmDialog()") in renders
    assert ("compose_route:typed:Home", "composable:com.x#HomeScreen()") in renders


def test_a_computed_route_is_an_unknown_fact_and_a_limitation_not_silence():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.compose.runtime.Composable
            import androidx.navigation.compose.NavHost
            import androidx.navigation.compose.composable
            @Composable fun Host(nav: androidx.navigation.NavHostController, routes: List<String>) {
                NavHost(nav, startDestination = "a") {
                    composable("a") { }
                    routes.forEach { composable(it) { } }
                }
            }
            """
        )
    )
    assert fact(report, "navigation:compose").status == "unknown"
    assert any(
        m.code == "dynamic_navigation" and m.affects_completeness for m in report.limitations
    )
    assert report.complete is False
    assert ids(report, "compose_route") == ["a"]  # the one that can be read is still reported


def test_navigation_3_is_reported_as_unsupported():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.navigation3.runtime.NavKey
            import androidx.navigation3.ui.NavDisplay
            class Home : NavKey
            """
        )
    )
    assert fact(report, "navigation:navigation3").status == "unknown"
    assert any(m.code == "navigation3_unsupported" for m in report.limitations)
    assert report.complete is False


def test_a_template_route_is_not_listed_as_a_destination():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.navigation.compose.composable
            fun androidx.navigation.NavGraphBuilder.build(id: Int) {
                composable("item/$id") { }
            }
            """
        )
    )
    assert ids(report, "compose_route") == []
    assert fact(report, "navigation:compose").status == "unknown"


def test_destinations_written_with_an_explicit_receiver_are_read_too():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.compose.runtime.Composable
            import androidx.navigation.NavGraphBuilder
            import androidx.navigation.compose.composable
            fun register(graph: NavGraphBuilder) {
                graph.composable("home/{id}") { HomeScreen() }
                graph.composable(route = "about") { AboutScreen() }
            }
            @Composable fun HomeScreen() {}
            @Composable fun AboutScreen() {}
            """
        )
    )
    assert ids(report, "compose_route") == ["about", "home/{id}"]
    assert fact(report, "compose_route:home/{id}").attributes["arguments"] == ("id",)
    assert ("compose_route:about", "composable:com.x#AboutScreen()") in edges(report, "renders")
    assert report.complete is True


def test_an_explicit_receiver_destination_with_a_computed_route_is_unknown_not_silent():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.navigation.NavGraphBuilder
            import androidx.navigation.compose.composable
            fun register(graph: NavGraphBuilder, name: String) {
                graph.composable(name) { }
                graph.composable("tpl/$name") { }
            }
            """
        )
    )
    assert ids(report, "compose_route") == []
    assert fact(report, "navigation:compose").status == "unknown"
    assert any(m.code == "dynamic_navigation" for m in report.limitations)


def test_a_dialog_call_on_something_else_in_a_file_without_navigation_is_not_a_route():
    report = analyse(kotlin_app(D='package com.x\nfun f(ui: Ui) { ui.dialog("title") { } }\n'))
    assert ids(report, "compose_route") == []
    assert [f for f in report.facts if f.kind == "navigation"] == []


def test_compose_deep_links_are_recorded_without_their_query_strings():
    report = analyse(
        kotlin_app(
            N="""
            package com.x
            import androidx.navigation.compose.composable
            import androidx.navigation.navDeepLink
            fun build(b: androidx.navigation.NavGraphBuilder) {
                b.composable("a", deepLinks = listOf(navDeepLink { uriPattern = "https://app.example.com/a?token=abc" })) { }
            }
            """
        )
    )
    assert ids(report, "deep_link") == ["https://app.example.com/a"]


# -- XML navigation -----------------------------------------------------------------------------


def test_an_xml_graph_has_destinations_arguments_start_actions_and_deep_links():
    report = analyse(java_xml_project())
    assert ids(report, "nav_graph") == ["app|nav_main"]
    assert ids(report, "nav_destination") == [
        "app|nav_main|detailFragment",
        "app|nav_main|homeFragment",
    ]
    detail = fact(report, "nav_destination:app|nav_main|detailFragment")
    assert detail.attributes["arguments"] == ("itemId",)
    assert detail.attributes["class"] == "com.example.legacy.ui.DetailFragment"
    e = edges(report, "navigates_to")
    assert (
        "nav_destination:app|nav_main|homeFragment",
        "nav_destination:app|nav_main|detailFragment",
    ) in e
    assert ("nav_graph:app|nav_main", "nav_destination:app|nav_main|homeFragment") in edges(
        report, "starts_at"
    )
    assert (
        "nav_destination:app|nav_main|homeFragment",
        "deep_link:https://legacy.example.com/home",
    ) in edges(report, "handles_deep_link")
    assert (
        "nav_destination:app|nav_main|homeFragment",
        "fragment:com.example.legacy.ui.HomeFragment",
    ) in edges(report, "implemented_by")


def test_code_that_navigates_by_id_or_safe_args_is_linked_to_the_destination():
    files = java_xml_project()
    files["app/src/main/java/com/example/legacy/ui/ById.java"] = d("""
        package com.example.legacy.ui;

        public class ById {
            void go(androidx.navigation.NavController c) {
                c.navigate(R.id.detailFragment);
            }
        }
        """)
    files["app/src/main/java/com/example/legacy/ui/ByAction.java"] = d("""
        package com.example.legacy.ui;

        public class ByAction {
            void go(androidx.navigation.NavController c) {
                c.navigate(R.id.action_home_to_detail);
            }
        }
        """)
    files["app/src/main/java/com/example/legacy/ui/BySafeArgs.java"] = d("""
        package com.example.legacy.ui;

        public class BySafeArgs {
            void go(androidx.navigation.NavController c) {
                c.navigate(HomeFragmentDirections.actionHomeToDetail(1));
            }
        }
        """)
    report = analyse(files)
    target = "nav_destination:app|nav_main|detailFragment"

    def status_from(name: str) -> str | None:
        found = [
            r.status
            for r in report.relationships
            if r.kind == "navigates_to"
            and r.source == f"type:com.example.legacy.ui.{name}"
            and r.target == target
        ]
        return found[0] if found else None

    assert status_from("ById") == "confirmed"
    assert status_from("ByAction") == "confirmed"
    assert status_from("BySafeArgs") == "inferred"  # a method name mapped to an action id


def test_graph_includes_nested_graphs_and_global_actions():
    files = {
        "settings.gradle.kts": 'include(":app")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "app/src/main/res/navigation/main.xml": d(f"""
            <navigation {ANDROID_NS} {APP_NS} android:id="@+id/main" app:startDestination="@id/a">
                <fragment android:id="@+id/a" android:name="com.x.A"/>
                <action android:id="@+id/global_to_a" app:destination="@id/a"/>
                <navigation android:id="@+id/inner" app:startDestination="@id/b">
                    <fragment android:id="@+id/b" android:name="com.x.B"/>
                </navigation>
                <include app:graph="@navigation/other"/>
            </navigation>
            """),
        "app/src/main/res/navigation/other.xml": f'<navigation {ANDROID_NS} {APP_NS} android:id="@+id/other"/>',
    }
    report = analyse(files)
    assert ids(report, "nav_graph") == ["app|main", "app|other"]
    assert ids(report, "nav_nested_graph") == ["app|main|inner"]
    assert ("nav_graph:app|main", "nav_graph:app|other") in edges(report, "includes")
    assert ("nav_graph:app|main", "nav_destination:app|main|a") in edges(
        report, "navigates_to"
    )  # global action


def test_a_destination_class_that_is_not_in_the_project_gets_a_fact_but_no_edge():
    files = java_xml_project()
    path = "app/src/main/res/navigation/nav_main.xml"
    files[path] = files[path].replace(
        "com.example.legacy.ui.DetailFragment", "com.library.RemoteFragment"
    )
    report = analyse(files)
    assert (
        fact(report, "nav_destination:app|nav_main|detailFragment").attributes["class"]
        == "com.library.RemoteFragment"
    )
    assert not any(s.endswith("|detailFragment") for s, _ in edges(report, "implemented_by"))


# -- layouts ------------------------------------------------------------------------------------


def test_layout_facts_fold_variants_and_record_ids_includes_and_custom_views():
    report = analyse(java_xml_project())
    assert ids(report, "layout") == [
        "app|activity_legacy",
        "app|activity_main",
        "app|fragment_home",
        "app|item_row",
    ]
    row = fact(report, "layout:app|item_row")
    assert row.attributes["variants"] == ("layout", "layout-land")
    assert row.attributes["view_ids"] == ("row_label",)
    home = fact(report, "layout:app|fragment_home")
    assert home.attributes["custom_views"] == ("com.example.legacy.ui.CounterView",)
    assert home.attributes["includes"] == ("item_row",)
    assert ("layout:app|fragment_home", "layout:app|item_row") in edges(report, "includes")
    assert ("layout:app|fragment_home", "type:com.example.legacy.ui.CounterView") in edges(
        report, "uses_view"
    )


def test_a_layout_links_to_the_activity_it_was_designed_for_as_a_hint_only():
    report = analyse(java_xml_project())
    hint = next(
        r
        for r in report.relationships
        if r.kind == "designed_for" and r.source == "layout:app|activity_main"
    )
    assert hint.status == "inferred" and "design-time" in hint.note


def test_a_layout_that_does_not_parse_is_unknown_and_a_limitation():
    files = java_xml_project()
    files["app/src/main/res/layout/broken.xml"] = "<LinearLayout><TextView></LinearLayout>"
    report = analyse(files)
    assert fact(report, "layout:app|broken").status == "unknown"
    assert any(
        m.code == "malformed_source" and m.scope.endswith("broken.xml") for m in report.limitations
    )
    assert report.complete is False


def test_data_binding_layouts_record_variables_and_note_that_expressions_are_not_analysed():
    files = java_xml_project()
    files["app/src/main/res/layout/fragment_bound.xml"] = d(f"""
        <layout {ANDROID_NS}>
            <data><variable name="vm" type="com.example.legacy.Vm"/></data>
            <TextView android:text="@{{vm.title}}" android:layout_width="wrap_content" android:layout_height="wrap_content"/>
        </layout>
        """)
    report = analyse(files)
    bound = fact(report, "layout:app|fragment_bound")
    assert bound.attributes["data_binding"] is True
    assert bound.attributes["binding_variables"] == ("vm: com.example.legacy.Vm",)
    assert bound.attributes["has_binding_expressions"] is True
    info = [m for m in report.limitations if m.code == "data_binding_expressions_not_analysed"]
    assert info and not info[0].affects_completeness


# -- bindings and layout use --------------------------------------------------------------------


def test_a_binding_class_imported_from_databinding_is_confirmed_and_tied_to_its_layout():
    report = analyse(java_xml_project())
    binding = fact(report, "binding:app|ActivityMainBinding")
    assert binding.status == "confirmed"
    assert binding.attributes["layout"] == "activity_main"
    assert binding.attributes["binding_kind"] == "view_binding"
    assert ("binding:app|ActivityMainBinding", "layout:app|activity_main") in edges(
        report, "generated_from"
    )
    assert ("type:com.example.legacy.MainActivity", "binding:app|ActivityMainBinding") in edges(
        report, "uses_binding"
    )
    assert ("type:com.example.legacy.MainActivity", "layout:app|activity_main") in edges(
        report, "uses_layout"
    )


def test_a_binding_name_used_without_an_import_is_only_inferred():
    files = java_xml_project()
    path = "app/src/main/java/com/example/legacy/MainActivity.java"
    files[path] = files[path].replace(
        "import com.example.legacy.databinding.ActivityMainBinding;\n", ""
    )
    binding = fact(analyse(files), "binding:app|ActivityMainBinding")
    assert binding.status == "inferred" and "no import" in binding.note


def test_a_class_that_merely_ends_in_binding_is_not_a_view_binding():
    files = java_xml_project()
    files["app/src/main/java/com/example/legacy/Wire.java"] = d("""
        package com.example.legacy;

        public class Wire {
            private final WireBinding binding = new WireBinding();
        }
        """)
    files["app/src/main/java/com/example/legacy/WireBinding.java"] = (
        "package com.example.legacy;\npublic class WireBinding {}\n"
    )
    assert "app|WireBinding" not in ids(analyse(files), "binding")


def test_r_layout_references_link_activities_and_fragments_to_layouts():
    report = analyse(java_xml_project())
    uses = edges(report, "uses_layout")
    assert ("type:com.example.legacy.LegacyActivity", "layout:app|activity_legacy") in uses
    assert ("type:com.example.legacy.ui.HomeFragment", "layout:app|fragment_home") in uses
    assert fact(report, "fragment:com.example.legacy.ui.HomeFragment").attributes["ui"] == "xml"


def test_an_ambiguous_layout_name_across_modules_is_inferred_for_each_candidate():
    files = {
        "settings.gradle.kts": 'include(":app", ":a", ":b")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "a/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.a" }\n',
        "b/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.b" }\n',
        "a/src/main/res/layout/shared.xml": f"<FrameLayout {ANDROID_NS}/>",
        "b/src/main/res/layout/shared.xml": f"<FrameLayout {ANDROID_NS}/>",
        "app/src/main/java/com/x/A.kt": "package com.x\nclass A { fun f() { setContentView(R.layout.shared) } }\n",
    }
    report = analyse(files)
    found = [
        r for r in report.relationships if r.kind == "uses_layout" and r.source == "type:com.x.A"
    ]
    assert {r.target for r in found} == {"layout:a|shared", "layout:b|shared"}
    assert all(r.status == "inferred" and "several modules" in r.note for r in found)


def test_kotlin_synthetic_imports_name_the_layout():
    files = kotlin_app(
        S="package com.x\nimport kotlinx.android.synthetic.main.activity_x.*\nclass S\n"
    )
    files["app/src/main/res/layout/activity_x.xml"] = f"<FrameLayout {ANDROID_NS}/>"
    assert ("file:app/src/main/java/com/x/S.kt", "layout:app|activity_x") in edges(
        analyse(files), "uses_layout"
    )


def test_fragments_placed_in_code_or_in_xml_are_hosted_by_their_container():
    kotlin = analyse(koin_project())
    inferred = next(
        r
        for r in kotlin.relationships
        if r.kind == "hosts_fragment" and r.source.endswith("HostActivity")
    )
    assert inferred.status == "inferred" and inferred.target.endswith("HomeFragment")
    java = analyse(java_xml_project())
    assert (
        "type:com.example.legacy.LegacyActivity",
        "fragment:com.example.legacy.ui.DetailFragment",
    ) in edges(java, "hosts_fragment")


def test_no_ui_extractor_fails_on_any_fixture():
    for files in (hilt_project(), java_xml_project(), koin_project()):
        no_errors(analyse(files))
