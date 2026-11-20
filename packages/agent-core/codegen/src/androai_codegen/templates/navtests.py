"""Generated navigation tests of a ``ProjectSpec`` project (Phase 5.3).

``add_navigation_tests`` takes the files ``screens.apply_spec`` produced and adds what a JVM test
needs: one ``app/src/test/.../navigation/NavigationTest.kt`` and the test-only dependencies in the
version catalog and in ``app/build.gradle.kts``. The test is Robolectric + Compose test + the
Navigation test helper. It drives the real ``AppNavHost`` (given a ``TestNavHostController``) and
checks, for the spec it was generated from:

* the start screen is shown and Back on it leaves the app,
* every screen shows its title, its description and exactly its buttons (nothing else is clickable),
* every button opens its target (the controller's route is the target's ``Routes`` constant),
* Back, both the on-screen button and the system's, returns to the screen the button was pressed on.

Nothing here is a stub: change a ``navigate`` target or an ``onBack`` in the generated navigation
host and a test fails (see the mutation runs in the progress document). Texts are looked up through
the string resources the screens use, never written into Kotlin, so a title cannot break the code.
Several buttons may carry the same text (two screens may share a title, a screen may be called
"Back"): the n-th button with that text is clicked, in the order the screen lays them out.

Test dependencies appear only in a project with a spec, because only then a test exists: without a
spec the output is exactly the Phase 5.1 project. The Compose test libraries take their version from
the Compose BOM (as every Compose library of the catalog does); JUnit and Robolectric are pinned in
``versions.py``, and the navigation test helper shares the version of Navigation Compose.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .config import ProjectConfig
from .errors import TemplateRenderError
from .render import RenderedFile, checked_file
from .screens import BACK_STRING, BACK_TEXT, body_resource, title_resource
from .spec import ProjectSpec, ScreenSpec, route_constant
from .versions import TOOLCHAIN

TEST_CLASS = "NavigationTest"
CATALOG_PATH = "gradle/libs.versions.toml"
APP_BUILD_PATH = "app/build.gradle.kts"

# Robolectric's screen: a tall phone, so that a screen with many buttons is laid out completely
# (the generated screens are a plain Column that does not scroll; the default Robolectric screen is
# 320 x 470 dp). The app itself is not tested on other sizes: see the limitations.
ROBOLECTRIC_QUALIFIERS = "w411dp-h914dp"


def navigation_tests_supported(config: ProjectConfig) -> bool:
    """Whether the navigation tests can run for ``config``.

    Robolectric simulates ``TOOLCHAIN.robolectric_sdk`` (the highest level it runs on JDK 17) and
    refuses an app whose ``minSdk`` is higher (a real run with minSdk 36 failed every test in
    ``ShadowPackageParser``). Such a project gets no tests, and no test dependencies, rather than
    tests that fail.
    """
    return config.min_sdk <= TOOLCHAIN.robolectric_sdk


_CATALOG_VERSIONS_END = "\n\n[libraries]\n"
_CATALOG_LIBRARIES_END = "\n\n[plugins]\n"
_BUILD_DEPENDENCIES_ANCHOR = "    debugImplementation(libs.androidx.compose.ui.tooling)\n}\n"

_CATALOG_LIBRARIES = (
    'androidx-navigation-testing = { group = "androidx.navigation", name = "navigation-testing", '
    'version.ref = "navigationCompose" }',
    'androidx-compose-ui-test-junit4 = { group = "androidx.compose.ui", name = "ui-test-junit4" }',
    'androidx-compose-ui-test-manifest = { group = "androidx.compose.ui", '
    'name = "ui-test-manifest" }',
    'junit = { group = "junit", name = "junit", version.ref = "junit" }',
    'robolectric = { group = "org.robolectric", name = "robolectric", '
    'version.ref = "robolectric" }',
)

_BUILD_DEPENDENCIES = (
    "    debugImplementation(libs.androidx.compose.ui.test.manifest)",
    "    testImplementation(libs.junit)",
    "    testImplementation(libs.robolectric)",
    "    testImplementation(libs.androidx.navigation.testing)",
    "    testImplementation(libs.androidx.compose.ui.test.junit4)",
)

# ``ui-test-manifest`` (which declares the ComponentActivity a Compose test launches) can only be a
# ``debugImplementation``: as a ``testImplementation`` its manifest is not merged (both variants
# failed in a real run), and a ``releaseImplementation`` would put it in the release APK. The
# release unit-test task has to stay enabled (without it AGP 9.5.1 cannot create the Compose Preview
# tasks, see kotlin_compose.py), so it is skipped instead of failing on the missing activity.
_BUILD_RELEASE_TESTS_SKIPPED = (
    "\n"
    "tasks.withType<Test>().configureEach {\n"
    "    // ComponentActivity, which the navigation tests launch, is declared by ui-test-manifest, "
    "and only\n"
    "    // the debug variant has that library. The release unit-test task has to exist (the "
    "Compose\n"
    "    // Preview needs it) but would fail on the missing activity, so it does not run.\n"
    '    enabled = name != "testReleaseUnitTest"\n'
    "}\n"
)

_FIXED_IMPORTS = (
    "androidx.activity.ComponentActivity",
    "androidx.compose.runtime.remember",
    "androidx.compose.ui.platform.LocalContext",
    "androidx.compose.ui.test.assertCountEquals",
    "androidx.compose.ui.test.assertIsDisplayed",
    "androidx.compose.ui.test.hasClickAction",
    "androidx.compose.ui.test.hasText",
    "androidx.compose.ui.test.junit4.v2.createAndroidComposeRule",
    "androidx.compose.ui.test.onFirst",
    "androidx.compose.ui.test.performClick",
    "androidx.navigation.compose.ComposeNavigator",
    "androidx.navigation.testing.TestNavHostController",
    "org.junit.Assert.assertEquals",
    "org.junit.Assert.assertTrue",
    "org.junit.Before",
    "org.junit.Rule",
    "org.junit.Test",
    "org.junit.runner.RunWith",
    "org.robolectric.RobolectricTestRunner",
    "org.robolectric.annotation.Config",
)

# The class every ``NavigationTest`` starts with, whatever the spec. ``__SDK__``,
# ``__QUALIFIERS__`` and ``__THEME__`` are filled in by ``navigation_test_source``.
_PROLOGUE = """\
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [__SDK__], qualifiers = "__QUALIFIERS__")
class NavigationTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<ComponentActivity>()

    private lateinit var navController: TestNavHostController

    @Before
    fun setUp() {
        composeRule.setContent {
            val context = LocalContext.current
            navController = remember {
                TestNavHostController(context).apply {
                    navigatorProvider.addNavigator(ComposeNavigator())
                }
            }
            __THEME__ {
                AppNavHost(navController = navController)
            }
        }
    }

    private fun text(id: Int): String = composeRule.activity.getString(id)

    private fun currentRoute(): String? = navController.currentBackStackEntry?.destination?.route

    private fun assertTextShown(id: Int) {
        composeRule
            .onAllNodes(hasText(text(id)) and !hasClickAction())
            .onFirst()
            .assertIsDisplayed()
    }

    private fun assertScreen(route: String, titleId: Int, bodyId: Int?, buttonIds: List<Int>) {
        composeRule.waitForIdle()
        assertEquals(route, currentRoute())
        assertTextShown(titleId)
        if (bodyId != null) assertTextShown(bodyId)
        composeRule.onAllNodes(hasClickAction()).assertCountEquals(buttonIds.size)
        for ((label, count) in buttonIds.map { text(it) }.groupingBy { it }.eachCount()) {
            composeRule.onAllNodes(hasText(label) and hasClickAction()).assertCountEquals(count)
        }
    }

    private fun clickButton(labelId: Int, occurrence: Int = 0) {
        composeRule
            .onAllNodes(hasText(text(labelId)) and hasClickAction())[occurrence]
            .performClick()
        composeRule.waitForIdle()
    }

    private fun pressSystemBack() {
        composeRule.runOnUiThread { composeRule.activity.onBackPressedDispatcher.onBackPressed() }
        composeRule.waitForIdle()
    }
"""


@dataclass(frozen=True)
class _Button:
    """A clickable of a screen, in layout order: one per target, then Back (unless the start)."""

    resource: str  # string resource of its label
    text: str  # what it says (equal texts are told apart by position)


def _buttons(spec: ProjectSpec, screen: ScreenSpec) -> list[_Button]:
    buttons = [
        _Button(title_resource(spec.screen(target)), spec.screen(target).title)
        for target in screen.navigates_to
    ]
    if screen.name != spec.start_name:
        buttons.append(_Button(BACK_STRING, BACK_TEXT))
    return buttons


def _occurrence(buttons: list[_Button], index: int) -> int:
    """How many buttons before ``buttons[index]`` say the same."""
    return sum(1 for button in buttons[:index] if button.text == buttons[index].text)


def _first_ways(spec: ProjectSpec) -> dict[str, tuple[str, int]]:
    """For each screen but the start: the screen and the button position it is first reached by.

    Breadth-first from the start, buttons in their order, so the choice is deterministic and every
    way is as short as it can be. A project spec guarantees every screen is reachable.
    """
    ways: dict[str, tuple[str, int]] = {}
    seen = {spec.start_name}
    queue = deque([spec.start_name])
    while queue:
        name = queue.popleft()
        for position, target in enumerate(spec.screen(name).navigates_to):
            if target not in seen:
                seen.add(target)
                ways[target] = (name, position)
                queue.append(target)
    return ways


def _click(buttons: list[_Button], index: int) -> str:
    occurrence = _occurrence(buttons, index)
    suffix = f", occurrence = {occurrence}" if occurrence else ""
    return f"clickButton(R.string.{buttons[index].resource}{suffix})"


def _lower_first(name: str) -> str:
    return name[0].lower() + name[1:]


class _Names:
    """Function names of the test class: unique, whatever the screens are called."""

    def __init__(self, taken: set[str]) -> None:
        self._taken = set(taken)

    def take(self, wanted: str) -> str:
        name, number = wanted, 1
        while name in self._taken:
            number += 1
            name = f"{wanted}{number}"
        self._taken.add(name)
        return name


def navigation_test_path(config: ProjectConfig) -> str:
    return f"app/src/test/java/{config.package_path}/navigation/{TEST_CLASS}.kt"


def _assert_on(spec: ProjectSpec, screen: ScreenSpec) -> list[str]:
    body = f"R.string.{body_resource(screen)}" if screen.description else "null"
    buttons = _buttons(spec, screen)
    if buttons:
        ids = ["        buttonIds = listOf("]
        ids += [f"            R.string.{button.resource}," for button in buttons]
        ids.append("        ),")
    else:
        ids = ["        buttonIds = emptyList(),"]
    return [
        f"    private fun assertOn{screen.name}() = assertScreen(",
        f"        route = Routes.{route_constant(screen.name)},",
        f"        titleId = R.string.{title_resource(screen)},",
        f"        bodyId = {body},",
        *ids,
        "    )",
    ]


def _go_to(spec: ProjectSpec, screen: ScreenSpec, ways: dict[str, tuple[str, int]]) -> list[str]:
    came_from, position = ways[screen.name]
    lines = [f"    private fun goTo{screen.name}() {{"]
    if came_from != spec.start_name:
        lines.append(f"        goTo{came_from}()")
    lines += [
        f"        {_click(_buttons(spec, spec.screen(came_from)), position)}",
        f"        assertOn{screen.name}()",
        "    }",
    ]
    return lines


def _edge_test(spec: ProjectSpec, screen: ScreenSpec, position: int, name: str) -> list[str]:
    target = spec.screen(screen.navigates_to[position])
    here = _buttons(spec, screen)
    there = _buttons(spec, target)
    open_target = _click(here, position)
    lines = ["    @Test", f"    fun {name}() {{"]
    if screen.name != spec.start_name:
        lines.append(f"        goTo{screen.name}()")
    lines += [f"        {open_target}", f"        assertOn{target.name}()"]
    if target.name != spec.start_name:
        # The on-screen Back button, then the same way once more with the system's Back.
        lines += [
            f"        {_click(there, len(there) - 1)}",
            f"        assertOn{screen.name}()",
            f"        {open_target}",
        ]
    lines += ["        pressSystemBack()", f"        assertOn{screen.name}()", "    }"]
    return lines


def navigation_test_source(config: ProjectConfig, spec: ProjectSpec) -> str:
    start = spec.screen(spec.start_name)
    ways = _first_ways(spec)
    names = _Names(
        {"setUp", "text", "currentRoute", "assertTextShown", "assertScreen", "clickButton"}
        | {"pressSystemBack", "backOnTheStartScreenLeavesTheApp"}
        | {f"{prefix}{screen.name}" for screen in spec.screens for prefix in ("goTo", "assertOn")}
    )

    imports = sorted(
        {
            *_FIXED_IMPORTS,
            f"{config.package_name}.R",
            f"{config.package_name}.ui.theme.{config.theme_function}",
        }
    )
    out = [f"package {config.package_name}.navigation", ""]
    out += [f"import {item}" for item in imports]
    out += [""]
    out += (
        _PROLOGUE.replace("__SDK__", str(TOOLCHAIN.robolectric_sdk))
        .replace("__QUALIFIERS__", ROBOLECTRIC_QUALIFIERS)
        .replace("__THEME__", config.theme_function)
        .splitlines()
    )

    for screen in spec.screens:
        out += [""] + _assert_on(spec, screen)
    for screen in spec.screens:
        if screen.name != start.name:
            out += [""] + _go_to(spec, screen, ways)

    out += ["", "    @Test", f"    fun {names.take('startsOn' + start.name)}() {{"]
    out += [f"        assertOn{start.name}()", "    }"]
    out += [
        "",
        "    @Test",
        "    fun backOnTheStartScreenLeavesTheApp() {",
        "        pressSystemBack()",
        "        assertTrue(composeRule.activity.isFinishing)",
        "    }",
    ]
    for screen in spec.screens:
        if screen.name != start.name:
            out += ["", "    @Test", f"    fun {names.take('shows' + screen.name)}() {{"]
            out += [f"        goTo{screen.name}()", "    }"]
    for screen in spec.screens:
        for position, target in enumerate(screen.navigates_to):
            name = names.take(f"{_lower_first(screen.name)}Opens{target}")
            out += [""] + _edge_test(spec, screen, position, name)
    out.append("}")
    return "\n".join(out) + "\n"


def _replace_once(text: str, anchor: str, replacement: str, where: str) -> str:
    if text.count(anchor) != 1:
        raise TemplateRenderError(
            f"{where}: expected exactly one {anchor.strip()!r} to add the test dependencies to, "
            f"found {text.count(anchor)}"
        )
    return text.replace(anchor, replacement)


def with_test_dependencies(catalog: str, build_gradle: str) -> tuple[str, str]:
    """The version catalog and the app build file with the test-only dependencies added."""
    versions = (f'junit = "{TOOLCHAIN.junit}"', f'robolectric = "{TOOLCHAIN.robolectric}"')
    catalog = _replace_once(
        catalog,
        _CATALOG_VERSIONS_END,
        "\n" + "\n".join(versions) + _CATALOG_VERSIONS_END,
        CATALOG_PATH,
    )
    catalog = _replace_once(
        catalog,
        _CATALOG_LIBRARIES_END,
        "\n" + "\n".join(_CATALOG_LIBRARIES) + _CATALOG_LIBRARIES_END,
        CATALOG_PATH,
    )
    build_gradle = _replace_once(
        build_gradle,
        _BUILD_DEPENDENCIES_ANCHOR,
        _BUILD_DEPENDENCIES_ANCHOR.removesuffix("}\n")
        + "\n".join(_BUILD_DEPENDENCIES)
        + "\n}\n"
        + _BUILD_RELEASE_TESTS_SKIPPED,
        APP_BUILD_PATH,
    )
    return catalog, build_gradle


def add_navigation_tests(
    files: tuple[RenderedFile, ...], config: ProjectConfig, spec: ProjectSpec
) -> tuple[RenderedFile, ...]:
    """``files`` plus the navigation test and the test dependencies (sorted by path).

    ``files`` unchanged when the tests cannot run for ``config`` (``navigation_tests_supported``).
    """
    if not navigation_tests_supported(config):
        return files
    by_path = {file.path: file for file in files}
    for path in (CATALOG_PATH, APP_BUILD_PATH):
        if path not in by_path:
            raise TemplateRenderError(f"the project has no {path} to add the test dependencies to")
    test_path = navigation_test_path(config)
    if test_path in by_path:
        raise TemplateRenderError(f"the navigation test would overwrite {test_path}")

    catalog, build_gradle = with_test_dependencies(
        by_path[CATALOG_PATH].content, by_path[APP_BUILD_PATH].content
    )
    for path, content in ((CATALOG_PATH, catalog), (APP_BUILD_PATH, build_gradle)):
        old = by_path[path]
        by_path[path] = checked_file(path, content, old.description)
    by_path[test_path] = checked_file(
        test_path,
        navigation_test_source(config, spec),
        "Navigation tests of the screens (Robolectric, Compose test)",
    )
    return tuple(by_path[path] for path in sorted(by_path))
