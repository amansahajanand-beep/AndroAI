"""Resources that an Android library ships (Phase 4a).

Found on android/platform-samples: ``@layout/glance_default_loading_layout`` and
``@bool/glance_appwidget_available`` (Glance), ``@color/cardview_shadow_start_color`` (CardView) and
``@animator/nav_default_enter_anim`` (Navigation) were reported as unresolved, because the project
cannot see inside a library. A library's resources come in families (``glance_*``, ``cardview_*``,
``nav_default_*``), so a reference is accepted when the project declares a library that ships that
family. Each test has a twin proving that the same reference is still reported when the library is
not declared, including when a convention plugin might have added it: a name that nothing declares
is not excused on a guess (see the limitation in docs/CODE_GENERATION_PROGRESS.md).
"""

from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine

APP = "app/build.gradle.kts"
MANIFEST = "app/src/main/AndroidManifest.xml"
NAV_COMPOSE = "    implementation(libs.androidx.navigation.compose)\n"
TEST_DEP = "    testImplementation(libs.junit)\n"
XMLNS = 'xmlns:android="http://schemas.android.com/apk/res/android"'
APP_NS = 'xmlns:app="http://schemas.android.com/apk/res-auto"'

GLANCE = 'implementation("androidx.glance:glance-appwidget:1.1.0")'
CARDVIEW = 'implementation("androidx.cardview:cardview:1.0.0")'
MATERIAL = 'implementation("com.google.android.material:material:1.12.0")'
NAVIGATION = 'implementation("androidx.navigation:navigation-ui-ktx:2.8.5")'
LEANBACK = 'implementation("androidx.leanback:leanback:1.0.0")'


def project(*, add: str = "", drop_navigation: bool = False, extra: dict | None = None) -> dict:
    files = dict(good_project())
    if drop_navigation:
        files[APP] = files[APP].replace(NAV_COMPOSE, "", 1)
    if add:
        files[APP] = files[APP].replace(TEST_DEP, f"    {add}\n" + TEST_DEP, 1)
    files.update(extra or {})
    return files


def unresolved(files) -> list[str]:
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    return sorted(f.key for f in report.findings if f.rule == "resource.unresolved")


def widget_info(layout: str) -> dict:
    xml = f'<appwidget-provider {XMLNS} android:initialLayout="@layout/{layout}" />\n'
    return {"app/src/main/res/xml/widget_info.xml": xml}


def layout(attr: str) -> dict:
    xml = f"<FrameLayout {XMLNS} {attr} />\n"
    return {"app/src/main/res/layout/screen.xml": xml}


def nav_graph(*attrs: str) -> dict:
    xml = (
        f"<navigation {XMLNS} {APP_NS}>\n"
        f'    <fragment android:id="@+id/a" android:name="x.A">\n'
        f'        <action android:id="@+id/to_b" app:destination="@id/a" {" ".join(attrs)} />\n'
        f"    </fragment>\n</navigation>\n"
    )
    return {"app/src/main/res/navigation/nav.xml": xml}


# --- Glance ---------------------------------------------------------------------------------------


def test_glance_resources_are_accepted_when_glance_is_a_dependency():
    files = project(add=GLANCE, extra=widget_info("glance_default_loading_layout"))
    assert unresolved(files) == []


def test_glance_resources_are_reported_when_glance_is_absent():
    assert unresolved(project(extra=widget_info("glance_default_loading_layout"))) == [
        "layout/glance_default_loading_layout"
    ]


def test_a_glance_resource_in_the_manifest_and_in_code_is_accepted_too():
    manifest = good_project()[MANIFEST].replace(
        "</application>",
        '<receiver android:name=".W" android:enabled="@bool/glance_appwidget_available" '
        'android:exported="false" /></application>',
    )
    code = (
        "package com.example.todo\n\nimport com.example.todo.R\n\n"
        "val loading = R.layout.glance_default_loading_layout\n"
    )
    files = project(add=GLANCE, extra={MANIFEST: manifest, f"{MAIN}/Loading.kt": code})
    assert unresolved(files) == []
    absent = project(extra={MANIFEST: manifest, f"{MAIN}/Loading.kt": code})
    assert unresolved(absent) == [
        "bool/glance_appwidget_available",
        "layout/glance_default_loading_layout",
    ]


# --- CardView (also shipped by Material Components, which depends on it) -------------------------


def test_cardview_resources_are_accepted_with_cardview_or_material():
    screen = layout('android:background="@color/cardview_shadow_start_color"')
    assert unresolved(project(add=CARDVIEW, extra=screen)) == []
    assert unresolved(project(add=MATERIAL, extra=screen)) == []


def test_cardview_resources_are_reported_when_neither_library_is_present():
    screen = layout('android:background="@color/cardview_shadow_start_color"')
    assert unresolved(project(extra=screen)) == ["color/cardview_shadow_start_color"]


# --- Navigation animations -----------------------------------------------------------------------

NAV_ATTRS = (
    'app:enterAnim="@animator/nav_default_enter_anim"',
    'app:popExitAnim="@anim/nav_default_pop_exit_anim"',
)


def test_navigation_animations_are_accepted_when_navigation_is_a_dependency():
    assert (
        unresolved(project(add=NAVIGATION, drop_navigation=True, extra=nav_graph(*NAV_ATTRS))) == []
    )


def test_navigation_animations_are_reported_when_navigation_is_absent():
    files = project(drop_navigation=True, extra=nav_graph(*NAV_ATTRS))
    assert unresolved(files) == [
        "anim/nav_default_pop_exit_anim",
        "animator/nav_default_enter_anim",
    ]


def test_a_library_family_is_only_trusted_for_the_resource_types_it_ships():
    # nav_default_* are animations; a *string* with that prefix is not the library's
    screen = layout('android:text="@string/nav_default_enter_anim"')
    assert unresolved(project(add=NAVIGATION, extra=screen)) == ["string/nav_default_enter_anim"]


# --- Leanback ------------------------------------------------------------------------------------


def test_leanback_resources_follow_the_same_rule():
    screen = layout('android:background="@color/lb_default_brand_color"')
    assert unresolved(project(add=LEANBACK, extra=screen)) == []
    assert unresolved(project(extra=screen)) == ["color/lb_default_brand_color"]


# --- when the dependencies cannot be read --------------------------------------------------------


def with_convention_plugin(files: dict) -> dict:
    out = dict(files)
    out[APP] = out[APP].replace("plugins {\n", 'plugins {\n    id("myproject.convention")\n', 1)
    return out


def test_a_library_only_a_convention_plugin_might_add_is_still_reported():
    """Documented limit: a library that nothing declares cannot be assumed to be there."""
    files = with_convention_plugin(project(extra=widget_info("glance_default_loading_layout")))
    assert unresolved(files) == ["layout/glance_default_loading_layout"]


def test_ordinary_missing_resources_are_still_reported_when_dependencies_are_unreadable():
    screen = layout('android:text="@string/definitely_not_defined"')
    assert unresolved(with_convention_plugin(project(extra=screen))) == [
        "string/definitely_not_defined"
    ]


def test_exact_library_names_keep_their_declared_dependency_rule():
    # appbar_scrolling_view_behavior ships with Material Components (the existing exact-name table)
    screen = layout('app:layout_behavior="@string/appbar_scrolling_view_behavior"')
    assert unresolved(project(extra=screen)) == ["string/appbar_scrolling_view_behavior"]
    assert unresolved(project(add=MATERIAL, extra=screen)) == []
    assert unresolved(with_convention_plugin(project(extra=screen))) == [
        "string/appbar_scrolling_view_behavior"
    ]
