"""Deep-link rules (Phase 4b-2a). Basis: Android's "Create deep links" and "Verify App Links" guides.

BROWSABLE is required for a filter to be reachable from a browser; DEFAULT for implicit intents; an
autoVerify filter needs VIEW, BROWSABLE, DEFAULT and http/https and must not mix in other schemes;
the <data> elements of one filter are merged; Compose graphs need hand-written manifest filters and
XML graphs need <nav-graph>. Every finding is a warning. Each has a twin that stays quiet.
"""

# ruff: noqa: E501  (the fixtures embed manifest XML and Kotlin, like tests/sample_project.py)
from sample_project import good_project
from test_review_navigation import LIST_ADD, graph, nav_project, xml_project

from androai_codegen.review import ProjectFiles, ReviewEngine

MANIFEST = "app/src/main/AndroidManifest.xml"
VIEW = "android.intent.action.VIEW"
DEFAULT = "android.intent.category.DEFAULT"
BROWSABLE = "android.intent.category.BROWSABLE"
HTTPS_HOST = ('<data android:scheme="https" android:host="example.com" />',)


def review(files):
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    # a rule that crashes is turned into this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def found(files, prefix="deeplink."):
    return sorted(
        (f.rule, f.key.split(":")[0] if ":" in f.key else f.key)
        for f in review(files).findings
        if f.rule.startswith(prefix)
    )


def rules(files):
    return sorted({rule for rule, _ in found(files)})


def link_filter(
    datas=HTTPS_HOST, *, actions=(VIEW,), categories=(DEFAULT, BROWSABLE), auto_verify=False
) -> str:
    inner = "".join(f'<action android:name="{a}" />' for a in actions)
    inner += "".join(f'<category android:name="{c}" />' for c in categories)
    inner += "".join(datas)
    attr = ' android:autoVerify="true"' if auto_verify else ""
    return f"            <intent-filter{attr}>{inner}</intent-filter>\n"


def with_filters(*filters: str, files: dict | None = None) -> dict:
    out = dict(files or good_project())
    out[MANIFEST] = out[MANIFEST].replace(
        "        </activity>\n", "".join(filters) + "        </activity>\n", 1
    )
    return out


def test_the_known_good_project_has_no_deep_link_findings():
    assert found(good_project()) == []


# --- intent-filter hygiene -------------------------------------------------------------------------


def test_a_valid_app_link_filter_is_quiet():
    assert found(with_filters(link_filter(auto_verify=True))) == []


def test_a_web_link_without_browsable_is_reported():
    files = with_filters(link_filter(categories=(DEFAULT,)))
    assert rules(files) == ["deeplink.missing_browsable"]
    assert rules(with_filters(link_filter())) == []


def test_a_custom_scheme_link_does_not_need_browsable():
    custom = link_filter(
        ('<data android:scheme="todo" android:host="open" />',), categories=(DEFAULT,)
    )
    assert rules(with_filters(custom)) == []


def test_a_link_without_default_can_only_be_started_by_component_name():
    files = with_filters(link_filter(categories=(BROWSABLE,)))
    assert rules(files) == ["deeplink.missing_default"]


def test_filters_that_are_not_links_are_not_judged():
    plain = link_filter((), actions=("android.intent.action.SEND",), categories=(DEFAULT,))
    assert rules(with_filters(plain)) == []


# --- autoVerify ------------------------------------------------------------------------------------


def test_autoverify_with_another_scheme_is_ineffective():
    mixed = link_filter(HTTPS_HOST + ('<data android:scheme="todo" />',), auto_verify=True)
    [item] = [
        f
        for f in review(with_filters(mixed)).findings
        if f.rule == "deeplink.autoverify_ineffective"
    ]
    assert "another scheme (todo)" in item.description and not item.blocking


def test_autoverify_needs_browsable_default_view_and_a_web_scheme():
    cases = {
        "no BROWSABLE": link_filter(categories=(DEFAULT,), auto_verify=True),
        "no DEFAULT": link_filter(categories=(BROWSABLE,), auto_verify=True),
        "no VIEW": link_filter(actions=("android.intent.action.SEND",), auto_verify=True),
        "no http or https scheme": link_filter(
            ('<data android:scheme="todo" android:host="open" />',), auto_verify=True
        ),
    }
    for reason, filter_xml in cases.items():
        [item] = [
            f
            for f in review(with_filters(filter_xml)).findings
            if f.rule == "deeplink.autoverify_ineffective"
        ]
        assert reason in item.description, reason


def test_https_alone_is_a_valid_verified_link():
    assert "deeplink.autoverify_ineffective" not in rules(
        with_filters(link_filter(auto_verify=True))
    )


def test_a_filter_without_autoverify_is_not_judged_for_it():
    assert "deeplink.autoverify_ineffective" not in rules(
        with_filters(link_filter(('<data android:scheme="todo" android:host="x" />',)))
    )


# --- merged <data> elements ------------------------------------------------------------------------


def test_data_elements_that_differ_in_scheme_and_host_are_merged_into_a_cross_product():
    doc_example = link_filter(
        (
            '<data android:scheme="https" android:host="www.example.com" />',
            '<data android:scheme="app" android:host="open.my.app" />',
        )
    )
    assert rules(with_filters(doc_example)) == ["deeplink.merged_data_elements"]


def test_data_elements_that_only_add_a_scheme_or_a_host_are_fine():
    two_schemes = link_filter(
        (
            '<data android:scheme="http" android:host="example.com" />',
            '<data android:scheme="https" android:host="example.com" />',
        )
    )
    two_hosts = link_filter(
        (
            '<data android:scheme="https" android:host="a.example.com" />',
            '<data android:scheme="https" android:host="b.example.com" />',
        )
    )
    assert rules(with_filters(two_schemes)) == []
    assert rules(with_filters(two_hosts)) == []


# --- the same verified link in two places ----------------------------------------------------------

SECOND = (
    '        <activity android:name=".Second" android:exported="true">\n{filter}'
    "        </activity>\n"
)


def with_second_activity(first: str, second: str) -> dict:
    files = with_filters(first)
    files[MANIFEST] = files[MANIFEST].replace(
        "    </application>", SECOND.format(filter=second) + "    </application>", 1
    )
    return files


def test_the_same_verified_link_in_two_activities_is_reported():
    verified = link_filter(auto_verify=True)
    assert rules(with_second_activity(verified, verified)) == ["deeplink.duplicate_app_link"]


def test_two_filters_of_one_activity_or_different_hosts_are_fine():
    verified = link_filter(auto_verify=True)
    assert rules(with_filters(verified, verified)) == []
    other = link_filter(
        ('<data android:scheme="https" android:host="other.com" />',), auto_verify=True
    )
    assert rules(with_second_activity(verified, other)) == []
    unverified = link_filter()
    assert rules(with_second_activity(verified, unverified)) == []


# --- XML graphs need <nav-graph> -------------------------------------------------------------------

DEEP_LINK_BODY = (
    '    <fragment android:id="@+id/home" android:name="com.example.todo.ui.HomeFragment">\n'
    '        <deepLink app:uri="https://example.com/home" />\n'
    "    </fragment>\n"
)
NAV_GRAPH = '            <nav-graph android:value="@navigation/nav_graph" />\n'


def test_an_xml_graph_deep_link_needs_a_nav_graph_element_in_the_manifest():
    files = xml_project(DEEP_LINK_BODY)
    assert rules(files) == ["deeplink.nav_graph_not_in_manifest"]


def test_a_nav_graph_element_enables_it():
    assert rules(with_filters(NAV_GRAPH, files=xml_project(DEEP_LINK_BODY))) == []


def test_a_graph_included_by_another_is_not_judged_on_its_own():
    files = xml_project(DEEP_LINK_BODY)
    parent = {
        "app/src/main/res/navigation/parent.xml": (
            '<navigation xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    xmlns:app="http://schemas.android.com/apk/res-auto" android:id="@+id/parent"\n'
            '    app:startDestination="@id/nav_graph">\n'
            '    <include app:graph="@navigation/nav_graph" />\n</navigation>\n'
        )
    }
    files.update(parent)
    files[MANIFEST] = files[MANIFEST].replace(
        "        </activity>\n",
        '            <nav-graph android:value="@navigation/parent" />\n        </activity>\n',
        1,
    )
    assert "deeplink.nav_graph_not_in_manifest" not in rules(files)


# --- Compose deep links need manifest filters -------------------------------------------------------


def compose_link(uri: str, form: str = "uri") -> dict:
    if form == "uri":
        link = f'composable("detail", deepLinks = listOf(navDeepLink {{ uriPattern = "{uri}" }})) {{ Text("d") }}'
    else:
        link = f'composable("detail", deepLinks = listOf(navDeepLink<Profile>(basePath = "{uri}"))) {{ Text("d") }}'
    return nav_project(graph(*LIST_ADD, link))


def test_a_compose_deep_link_with_no_matching_manifest_filter_is_reported():
    files = compose_link("https://example.com/p/{id}")
    assert rules(files) == ["deeplink.uri_not_in_manifest"]


def test_a_matching_filter_makes_it_quiet_including_wildcards_and_missing_schemes():
    link = compose_link("https://app.example.com/p/{id}")
    assert rules(with_filters(link_filter(HTTPS_HOST), files=link)) == [
        "deeplink.uri_not_in_manifest"
    ]
    wildcard = link_filter(('<data android:scheme="https" android:host="*.example.com" />',))
    assert rules(with_filters(wildcard, files=link)) == []
    no_scheme = compose_link("example.com/p/{id}")
    assert rules(with_filters(link_filter(HTTPS_HOST), files=no_scheme)) == []


def test_a_custom_scheme_needs_a_filter_for_that_scheme():
    link = compose_link("todo://open/item")
    assert rules(with_filters(link_filter(HTTPS_HOST), files=link)) == [
        "deeplink.uri_not_in_manifest"
    ]
    custom = link_filter(('<data android:scheme="todo" android:host="open" />',))
    assert rules(with_filters(custom, files=link)) == []


def test_the_base_path_form_is_read_too():
    files = compose_link("https://example.com/profile", form="base")
    assert rules(files) == ["deeplink.uri_not_in_manifest"]


def test_templated_hosts_are_not_judged():
    assert rules(compose_link("https://${host}/p")) == []


def test_without_any_manifest_nothing_is_judged():
    files = compose_link("https://example.com/x")
    del files[MANIFEST]
    assert rules(files) == []


def test_navigation_3_silences_the_compose_uri_rule():
    nav3 = "package com.example.todo\n\nimport androidx.navigation3.runtime.NavKey\n\nclass K : NavKey\n"
    files = compose_link("https://example.com/x")
    files["app/src/main/java/com/example/todo/K.kt"] = nav3
    assert rules(files) == []
