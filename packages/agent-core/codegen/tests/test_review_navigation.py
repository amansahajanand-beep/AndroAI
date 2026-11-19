"""Navigation rules (Phase 4b-2a): Compose string and type-safe routes, and XML graphs.

Documented basis: ``NavController.navigate(route)`` throws ``IllegalArgumentException`` for an invalid
route, and a graph is not valid without a start destination. Every defect has twins proving the rule
stays quiet when a destination exists, is computed, or the navigation style is not analysed.
"""

# ruff: noqa: E501  (the fixtures embed Kotlin and navigation XML, like tests/sample_project.py)
from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine

TODO_APP = f"{MAIN}/ui/TodoApp.kt"
NAV_XML = "app/src/main/res/navigation/nav_graph.xml"
MANIFEST = "app/src/main/AndroidManifest.xml"
HEADER = """package com.example.todo.ui

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.dialog
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import kotlinx.serialization.Serializable

"""


def review(files):
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    # a rule that crashes is turned into this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def found(files, prefix="navigation."):
    return sorted(
        (f.rule, f.file.rsplit("/", 1)[-1], f.key)
        for f in review(files).findings
        if f.rule.startswith(prefix)
    )


def nav_project(body: str, extra: dict | None = None) -> dict:
    """The known-good project with TodoApp.kt replaced by ``body`` (after a standard header)."""
    files = dict(good_project())
    files[TODO_APP] = HEADER + body
    files.update(extra or {})
    return files


def graph(*lines: str, start: str = '"list"', navigate: tuple[str, ...] = ()) -> str:
    inner = "\n".join(f"        {line}" for line in lines)
    calls = "\n".join(f"    nav.navigate({route})" for route in navigate)
    return (
        "@Composable\nfun TodoApp() {\n    val nav = rememberNavController()\n"
        f"{calls}\n    NavHost(navController = nav, startDestination = {start}) {{\n{inner}\n    }}\n}}\n"
    )


LIST_ADD = ('composable("list") { Text("l") }', 'composable("add") { Text("a") }')


def test_the_known_good_project_has_no_navigation_findings():
    assert found(good_project(), "navigation.") == []
    assert found(good_project(), "deeplink.") == []


# --- string routes ---------------------------------------------------------------------------------


def test_navigating_to_a_route_nothing_declares_is_reported_with_a_hint():
    files = nav_project(graph(*LIST_ADD, navigate=('"adds"',)))
    [item] = [f for f in review(files).findings if f.rule == "navigation.destination_missing"]
    assert item.key == "adds" and item.blocking and "add" in (item.suggested_fix or "")


def test_a_route_that_exists_is_fine():
    assert found(nav_project(graph(*LIST_ADD, navigate=('"add"',)))) == []


def test_argument_routes_match_filled_in_and_templated_calls():
    body = graph(
        *LIST_ADD,
        'composable("detail/{id}") { Text("d") }',
        'composable("search?q={q}") { Text("s") }',
        navigate=('"detail/42"', '"detail/${id}"', '"search?q=abc"', '"search"'),
    )
    assert found(nav_project(body)) == []


def test_a_missing_required_argument_segment_is_reported():
    body = graph(*LIST_ADD, 'composable("detail/{id}") { Text("d") }', navigate=('"detail"',))
    assert found(nav_project(body)) == [("navigation.destination_missing", "TodoApp.kt", "detail")]


def test_a_nested_graph_route_and_its_start_destination_are_destinations():
    body = graph(
        *LIST_ADD,
        'navigation(startDestination = "login", route = "auth") { composable("login") { Text("x") } }',
        navigate=('"auth"', '"login"'),
    )
    assert found(nav_project(body)) == []


def test_dialog_destinations_count():
    body = graph(*LIST_ADD, 'dialog("confirm") { Text("c") }', navigate=('"confirm"',))
    assert found(nav_project(body)) == []


def test_named_route_arguments_are_read():
    body = graph(*LIST_ADD, navigate=('route = "nope"',))
    assert found(nav_project(body)) == [("navigation.destination_missing", "TodoApp.kt", "nope")]


# --- start destinations ----------------------------------------------------------------------------


def test_a_start_destination_nothing_declares_is_reported():
    files = nav_project(graph(*LIST_ADD, start='"home"'))
    assert found(files) == [("navigation.start_destination_missing", "TodoApp.kt", "home")]


# --- constants, computed routes and unrecognised styles ---------------------------------------------

CONSTANTS = 'object Routes {\n    const val HOME = "home"\n    const val ADD = "add"\n}\n\n'


def test_const_routes_are_resolved():
    body = CONSTANTS + graph(
        'composable(Routes.HOME) { Text("h") }',
        'composable(route = Routes.ADD) { Text("a") }',
        start="Routes.HOME",
        navigate=("Routes.ADD", '"missing"'),
    )
    assert found(nav_project(body)) == [("navigation.destination_missing", "TodoApp.kt", "missing")]


def test_a_computed_route_silences_the_rules():
    body = graph(*LIST_ADD, 'composable(Screen.Home.route) { Text("h") }', navigate=('"nope"',))
    assert found(nav_project(body)) == []


def test_a_computed_start_destination_silences_the_rules():
    body = graph(*LIST_ADD, start="startDestination", navigate=('"nope"',))
    assert found(nav_project(body)) == []


def test_pop_back_stack_is_not_checked():
    body = graph(*LIST_ADD).replace("NavHost(", 'nav.popBackStack("nope", false)\n    NavHost(', 1)
    assert found(nav_project(body)) == []


def test_navigate_on_something_that_is_not_a_nav_controller_is_ignored():
    router = (
        "package com.example.todo\n\nclass Router { fun navigate(to: String) {} }\n\n"
        'fun go(router: Router) { router.navigate("zzz") }\n'
    )
    files = nav_project(graph(*LIST_ADD), {f"{MAIN}/Router.kt": router})
    assert found(files) == []


def test_navigate_in_a_navigation_file_without_a_nav_controller_is_ignored():
    """The file mentions androidx.navigation, so it is read, but nothing in it is a NavController."""
    router = (
        "package com.example.todo\n\nimport androidx.navigation.compose.composable\n\n"
        "class Router { fun navigate(to: String) {} }\n\n"
        'fun go(router: Router) { router.navigate("zzz") }\n'
    )
    files = nav_project(graph(*LIST_ADD), {f"{MAIN}/Router.kt": router})
    assert found(files) == []


def test_navigation_3_silences_the_compose_rules():
    nav3 = "package com.example.todo\n\nimport androidx.navigation3.runtime.NavKey\n\nclass K : NavKey\n"
    files = nav_project(graph(*LIST_ADD, navigate=('"nope"',)), {f"{MAIN}/K.kt": nav3})
    assert found(files) == []


def test_a_project_with_no_visible_graph_is_not_judged():
    files = dict(good_project())
    files[TODO_APP] = (
        HEADER + '@Composable\nfun TodoApp(nav: NavHostController) { nav.navigate("x") }\n'
    )
    assert found(files) == []


# --- duplicates ------------------------------------------------------------------------------------


def test_the_same_route_twice_in_one_builder_is_a_warning():
    body = graph(*LIST_ADD, 'composable("list") { Text("again") }')
    [item] = [
        f
        for f in review(nav_project(body)).findings
        if f.rule == "navigation.duplicate_destination"
    ]
    assert item.key == "list" and not item.blocking


def test_the_same_route_in_two_separate_graphs_is_fine():
    two = (
        graph(*LIST_ADD)
        + '\n@Composable\nfun Other() {\n    NavHost(rememberNavController(), "list") {\n        composable("list") { Text("x") }\n    }\n}\n'
    )
    assert found(nav_project(two)) == []


# --- type-safe routes ------------------------------------------------------------------------------

ROUTES = (
    "@Serializable\nobject Home\n\n@Serializable\ndata class Profile(val id: String)\n\n"
    "@Serializable\nobject Settings\n\nobject Plain\n\n"
)


def typed(*declared: str, start: str = "Home", navigate: tuple[str, ...] = ()) -> str:
    return ROUTES + graph(*declared, start=start, navigate=navigate)


TYPED_DECLS = ('composable<Home> { Text("h") }', 'composable<Profile> { Text("p") }')


def test_type_safe_navigation_to_a_declared_route_is_fine():
    assert found(nav_project(typed(*TYPED_DECLS, navigate=('Profile("1")', "Home")))) == []


def test_type_safe_navigation_to_a_route_type_nothing_declares_is_reported():
    files = nav_project(typed(*TYPED_DECLS, navigate=("Settings",)))
    assert found(files) == [("navigation.destination_missing", "TodoApp.kt", "Settings")]


def test_a_type_safe_start_destination_nothing_declares_is_reported():
    files = nav_project(typed(*TYPED_DECLS, start="Settings"))
    assert found(files) == [("navigation.start_destination_missing", "TodoApp.kt", "Settings")]


def test_only_serializable_project_classes_are_judged_as_routes():
    assert found(nav_project(typed(*TYPED_DECLS, navigate=("Plain", "Unknown(1)")))) == []


def test_string_navigation_is_not_judged_against_only_type_safe_destinations():
    assert found(nav_project(typed(*TYPED_DECLS, navigate=('"anything"',)))) == []


def test_a_generic_destination_type_silences_the_rules():
    body = typed(*TYPED_DECLS, 'composable<T> { Text("t") }', navigate=("Settings",))
    assert found(nav_project(body)) == []


# --- XML graphs ------------------------------------------------------------------------------------

XML_HEAD = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<navigation xmlns:android="http://schemas.android.com/apk/res/android"\n'
    '    xmlns:app="http://schemas.android.com/apk/res-auto"\n'
    '    android:id="@+id/nav_graph"{start}>\n'
)


def xml_graph(body: str, start: str = ' app:startDestination="@id/home"') -> dict:
    return {NAV_XML: XML_HEAD.format(start=start) + body + "</navigation>\n"}


GOOD_BODY = (
    '    <fragment android:id="@+id/home" android:name="com.example.todo.ui.HomeFragment">\n'
    '        <action android:id="@+id/to_detail" app:destination="@id/detail" />\n'
    "    </fragment>\n"
    '    <fragment android:id="@+id/detail" android:name="com.example.todo.ui.DetailFragment" />\n'
)
FRAGMENTS = {
    f"{MAIN}/ui/HomeFragment.kt": "package com.example.todo.ui\n\nclass HomeFragment\n",
    f"{MAIN}/ui/DetailFragment.kt": "package com.example.todo.ui\n\nclass DetailFragment\n",
}


def xml_project(body: str = GOOD_BODY, start: str = ' app:startDestination="@id/home"') -> dict:
    files = dict(good_project())
    files.update(FRAGMENTS)
    files.update(xml_graph(body, start))
    return files


def test_a_well_formed_xml_graph_has_no_findings():
    assert found(xml_project()) == []


def test_a_graph_without_a_start_destination_is_reported():
    assert found(xml_project(start="")) == [
        ("navigation.start_destination_missing", "nav_graph.xml", "nav_graph")
    ]


def test_a_start_destination_that_is_not_in_the_graph_is_reported():
    files = xml_project(start=' app:startDestination="@id/nowhere"')
    assert found(files) == [("navigation.start_destination_missing", "nav_graph.xml", "nowhere")]


def test_an_action_to_an_unknown_destination_is_reported_with_a_hint():
    files = xml_project(GOOD_BODY.replace('@id/detail"', '@id/detial"'))
    [item] = [f for f in review(files).findings if f.rule == "navigation.action_target_missing"]
    assert item.key == "detial" and "detail" in (item.suggested_fix or "")


def test_an_action_may_target_a_destination_of_another_graph():
    other = {
        "app/src/main/res/navigation/other.xml": XML_HEAD.format(
            start=' app:startDestination="@id/elsewhere"'
        ).replace("@+id/nav_graph", "@+id/other")
        + '    <fragment android:id="@+id/elsewhere" android:name="com.example.todo.ui.HomeFragment" />\n</navigation>\n'
    }
    files = xml_project(GOOD_BODY.replace('@id/detail"', '@id/elsewhere"'))
    files.update(other)
    assert found(files) == []


def test_a_duplicate_destination_id_is_a_warning():
    body = (
        GOOD_BODY
        + '    <fragment android:id="@+id/home" android:name="com.example.todo.ui.HomeFragment" />\n'
    )
    [item] = [
        f
        for f in review(xml_project(body)).findings
        if f.rule == "navigation.duplicate_destination"
    ]
    assert item.key == "home" and not item.blocking


def test_a_destination_class_in_the_apps_own_package_must_exist():
    files = xml_project(GOOD_BODY.replace("DetailFragment", "DetialFragment"))
    assert found(files) == [
        (
            "navigation.destination_class_missing",
            "nav_graph.xml",
            "com.example.todo.ui.DetialFragment",
        )
    ]


def test_library_classes_and_relative_names_are_not_checked():
    body = GOOD_BODY.replace("com.example.todo.ui.DetailFragment", "androidx.fragment.app.Fragment")
    assert found(xml_project(body)) == []


def test_a_nested_graph_needs_its_own_start_destination():
    nested = (
        GOOD_BODY + '    <navigation android:id="@+id/inner" app:startDestination="@id/missing">\n'
        '        <fragment android:id="@+id/leaf" android:name="com.example.todo.ui.HomeFragment" />\n'
        "    </navigation>\n"
    )
    assert found(xml_project(nested)) == [
        ("navigation.start_destination_missing", "nav_graph.xml", "missing")
    ]


def test_an_included_graph_is_a_valid_start_and_an_unresolved_include_is_not_judged():
    inc = {
        "app/src/main/res/navigation/auth.xml": XML_HEAD.format(
            start=' app:startDestination="@id/login"'
        ).replace("@+id/nav_graph", "@+id/auth")
        + '    <fragment android:id="@+id/login" android:name="com.example.todo.ui.HomeFragment" />\n</navigation>\n'
    }
    body = GOOD_BODY + '    <include app:graph="@navigation/auth" />\n'
    files = xml_project(body, start=' app:startDestination="@id/auth"')
    files.update(inc)
    assert found(files) == []
    unresolved = xml_project(
        GOOD_BODY + '    <include app:graph="@navigation/gone" />\n',
        start=' app:startDestination="@id/whatever"',
    )
    assert found(unresolved) == []
