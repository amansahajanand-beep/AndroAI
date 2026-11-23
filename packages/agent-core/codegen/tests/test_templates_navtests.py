"""Generated navigation tests and their test-only dependencies (Phase 5.3).

The Kotlin itself is only proven by Gradle (see the progress document). What is proven here: the
text that was built does not change unnoticed, every approved dependency is declared exactly once
with the approved version, the generated test script is *correct for the spec it was made from*
(a small simulator runs it against a model of the app built independently from the spec, and fails
for four kinds of broken navigation) and the unsupported cases are refused cleanly.
"""

import re
import tomllib
from dataclasses import dataclass, field

import pytest
from test_templates_kotlin_compose import top_level_blocks
from test_templates_screens import (
    CYCLE,
    KEYWORDS,
    NAV,
    ONE,
    ROOT,
    SPECS,
    STRINGS,
    TEST,
    THREE,
    big_spec,
    combined,
    make,
    rendered,
    review_rules,
    sc,
    strings_of,
)

from androai_codegen.review import ProjectFiles, ReviewEngine
from androai_codegen.templates import (
    TOOLCHAIN,
    VERIFIED_BUILD,
    ProjectSpec,
    TemplateRenderError,
    navtests,
    render_files,
    renderer,
    route_constant,
    route_of,
)
from androai_codegen.templates.render import RenderedFile

CATALOG = "gradle/libs.versions.toml"
BUILD = "app/build.gradle.kts"

# Two screens with the same title, a screen whose title is the text of every Back button, an
# edge back into the start screen and a name that other names' functions could collide with.
DUPLICATES = ProjectSpec(
    screens=(
        sc("Home", "Start", navigates_to=("First", "Second", "Back")),
        sc("First", "Same", navigates_to=("Second", "Back")),
        sc("Second", "Same", navigates_to=("Home",)),
        sc("Back", "Back", navigates_to=("Second", "First")),
    )
)
COLLIDING_NAMES = ProjectSpec(
    screens=(
        sc("X", navigates_to=("OpensY", "XOpens")),
        sc("XOpens", navigates_to=("Y",)),
        sc("OpensY"),
        sc("Y"),
    )
)
# The screen "GoToX" opens "Y": its edge test would be called ``goToXOpensY``, which is also the
# name of the helper that goes to the screen "XOpensY".
HELPER_COLLISION = ProjectSpec(
    screens=(
        sc("Home", navigates_to=("GoToX", "XOpensY")),
        sc("GoToX", navigates_to=("Y",)),
        sc("XOpensY"),
        sc("Y"),
    )
)
# Two ways to Goal: by Detour (two button presses) or by Quick and Mid (three). Breadth-first takes
# Detour; a depth-first search would take the longer way.
SHORTCUT = ProjectSpec(
    screens=(
        sc("Start", navigates_to=("Detour", "Quick")),
        sc("Detour", navigates_to=("Goal",)),
        sc("Quick", navigates_to=("Mid",)),
        sc("Mid", navigates_to=("Goal",)),
        sc("Goal"),
    )
)
ALL_SPECS = {
    **SPECS,
    "duplicates": DUPLICATES,
    "colliding": COLLIDING_NAMES,
    "helper_collision": HELPER_COLLISION,
    "shortcut": SHORTCUT,
}
EXPECTED_DEPENDENCY_LINES = [
    "    debugImplementation(libs.androidx.compose.ui.test.manifest)",
    "    testImplementation(libs.junit)",
    "    testImplementation(libs.robolectric)",
    "    testImplementation(libs.androidx.navigation.testing)",
    "    testImplementation(libs.androidx.compose.ui.test.junit4)",
]


def source_of(spec=THREE, **config) -> str:
    return rendered(make(**config), spec)[TEST]


def edges(spec: ProjectSpec) -> int:
    return sum(len(s.navigates_to) for s in spec.screens)


# --- dependencies -------------------------------------------------------------------------------


def test_the_approved_versions_are_the_pins():
    assert TOOLCHAIN.junit == "4.13.2"
    assert TOOLCHAIN.robolectric == "4.18.1"
    assert TOOLCHAIN.navigation_compose == "2.10.2"  # navigation-testing shares this version
    assert TOOLCHAIN.compose_bom == "2026.11.01"  # manages ui-test-junit4 / ui-test-manifest 1.13.0


def test_the_five_test_libraries_are_declared_with_the_approved_versions():
    catalog = tomllib.loads(rendered(spec=THREE)[CATALOG])
    libraries = catalog["libraries"]
    assert catalog["versions"] == {
        "agp": TOOLCHAIN.agp,
        "kotlin": TOOLCHAIN.kotlin,
        "composeBom": TOOLCHAIN.compose_bom,
        "activityCompose": TOOLCHAIN.activity_compose,
        "navigationCompose": TOOLCHAIN.navigation_compose,
        "junit": "4.13.2",
        "robolectric": "4.18.1",
    }
    assert libraries["junit"] == {"group": "junit", "name": "junit", "version": {"ref": "junit"}}
    assert libraries["robolectric"] == {
        "group": "org.robolectric",
        "name": "robolectric",
        "version": {"ref": "robolectric"},
    }
    assert libraries["androidx-navigation-testing"] == {
        "group": "androidx.navigation",
        "name": "navigation-testing",
        "version": {"ref": "navigationCompose"},
    }
    # The Compose test libraries take their version (1.13.0) from the BOM, like every Compose entry.
    assert libraries["androidx-compose-ui-test-junit4"] == {
        "group": "androidx.compose.ui",
        "name": "ui-test-junit4",
    }
    assert libraries["androidx-compose-ui-test-manifest"] == {
        "group": "androidx.compose.ui",
        "name": "ui-test-manifest",
    }
    assert len(libraries) == 8 + 5  # the Phase 5.1 entries plus exactly the five approved ones


def test_only_the_five_libraries_and_two_versions_were_added_to_the_catalog():
    before = rendered()[CATALOG].split("\n")
    after = rendered(spec=THREE)[CATALOG].split("\n")
    assert [line for line in before if line not in after] == []
    added = [line for line in after if line not in before]
    assert len(added) == 2 + 5
    assert sorted(line.split(" = ")[0] for line in added) == sorted(
        [
            "junit",
            "robolectric",
            "androidx-navigation-testing",
            "androidx-compose-ui-test-junit4",
            "androidx-compose-ui-test-manifest",
            "junit",
            "robolectric",
        ]
    )


def test_the_build_file_gets_five_dependency_lines_and_nothing_else():
    before = rendered()[BUILD]
    after = rendered(spec=THREE)[BUILD]
    assert before.endswith("    debugImplementation(libs.androidx.compose.ui.tooling)\n}\n")
    assert after == before.removesuffix("}\n") + "\n".join(EXPECTED_DEPENDENCY_LINES) + "\n}\n"
    block = top_level_blocks(after)["dependencies"].split("\n")
    assert block[-5:] == EXPECTED_DEPENDENCY_LINES


def test_no_unit_test_task_is_switched_off_any_more():
    # Phase 5.3 skipped the release unit-test task; Phase 5.4 runs the test on both variants.
    after = rendered(spec=THREE)[BUILD]
    for word in ("enabled = ", "withType<Test>", "testReleaseUnitTest", "onlyIf"):
        assert word not in after, word
    # The release variant keeps its unit tests (AGP 9.5.1 needs them to create the Preview tasks).
    blocks = top_level_blocks(after)
    assert blocks["androidComponents"] == top_level_blocks(rendered()[BUILD])["androidComponents"]
    assert "UNIT_TEST_TYPE]?.enable = true" in blocks["androidComponents"]
    # ui-test-manifest is a debug-only dependency (a release APK must not contain it).
    assert after.count("ui.test.manifest") == 1
    assert "    debugImplementation(libs.androidx.compose.ui.test.manifest)\n" in after


def test_test_libraries_reach_only_the_test_and_debug_configurations():
    dependencies = top_level_blocks(rendered(spec=THREE)[BUILD])["dependencies"]
    for line in dependencies.split("\n"):
        if any(word in line for word in ("junit", "robolectric", "test", "testing")):
            assert line.strip().startswith(("testImplementation(", "debugImplementation(")), line
    # Nothing a release build packages (``implementation``, ``releaseImplementation``) is a test
    # library.
    assert "releaseImplementation" not in dependencies
    assert re.findall(r"(?m)^    implementation\((.+)\)$", dependencies) == [
        "platform(libs.androidx.compose.bom)",
        "libs.androidx.activity.compose",
        "libs.androidx.navigation.compose",
        "libs.androidx.compose.ui",
        "libs.androidx.compose.ui.graphics",
        "libs.androidx.compose.ui.tooling.preview",
        "libs.androidx.compose.material3",
    ]


def test_every_catalog_accessor_is_used_and_exists_with_the_test_libraries():
    catalog = tomllib.loads(rendered(spec=THREE)[CATALOG])
    defined = {"libs." + re.sub(r"[-_]", ".", alias) for alias in catalog["libraries"]} | {
        "libs.plugins." + re.sub(r"[-_]", ".", alias) for alias in catalog["plugins"]
    }
    used = set()
    for path in ("build.gradle.kts", BUILD):
        code = "\n".join(
            line
            for line in rendered(spec=THREE)[path].split("\n")
            if not line.lstrip().startswith("//")
        )
        used |= set(re.findall(r"(?<![\w/.])libs(?:\.[A-Za-z0-9]+)+", code))
    assert used == defined, used ^ defined


def test_nothing_is_added_without_a_spec():
    files = rendered()
    assert not [p for p in files if "/src/test/" in p or "/androidTest/" in p]
    for text in (files[CATALOG], files[BUILD]):
        for word in ("junit", "robolectric", "navigation-testing", "ui-test"):
            assert word not in text


def test_the_pins_of_the_test_libraries_are_not_spelled_anywhere_else():
    # Versions live in versions.py: the Kotlin never names one.
    blob = "\n".join(
        content for path, content in rendered(spec=THREE).items() if path.endswith(".kt")
    )
    for version in ("4.13.2", "4.18.1", "2.10.2", "1.13.0"):
        assert version not in blob


# --- the generated test class -------------------------------------------------------------------


def test_the_test_lives_next_to_the_navigation_host_in_the_test_source_set():
    assert navtests.navigation_test_path(make()) == TEST
    assert f"app/src/test/java/com/example/notes/navigation/{navtests.TEST_CLASS}.kt" == TEST
    files = rendered(make(package_name="org.acme.deep.pkg"), THREE)
    path = "app/src/test/java/org/acme/deep/pkg/navigation/NavigationTest.kt"
    assert path in files
    assert files[path].startswith("package org.acme.deep.pkg.navigation\n")
    assert "import org.acme.deep.pkg.R\n" in files[path]
    assert not [p for p in files if "com/example" in p]


def test_the_test_scrolls_to_what_it_clicks_and_checks():
    # Phase 5.4: the screens scroll, so the test scrolls to a button before it taps it and to a
    # title before it checks it is displayed (a scroll position is kept when Back returns). On a
    # screen without a scroll container performScrollTo fails, so removing the scroll is caught.
    source = source_of()
    assert "import androidx.compose.ui.test.performScrollTo\n" in source
    assert source.count(".performScrollTo()") == 2
    assert (
        "            .onFirst()\n            .performScrollTo()\n            .assertIsDisplayed()\n"
    ) in source
    assert "            .performScrollTo()\n            .performClick()\n" in source


def test_the_test_registers_its_activity_before_the_compose_rule_launches_it():
    # Phase 5.4: this is what lets the same test pass on the release unit-test task, whose classpath
    # has no ui-test-manifest. The registration rule has to run first (order 0), because the Compose
    # rule starts the activity as it is applied, before any @Before method runs.
    source = source_of()
    registration = (
        "    @get:Rule(order = 0)\n"
        "    val activityRegistration = object : ExternalResource() {\n"
        "        override fun before() {\n"
        "            val app = RuntimeEnvironment.getApplication()\n"
        "            shadowOf(app.packageManager)\n"
        "                .addActivityIfNotPresent("
        "ComponentName(app, ComponentActivity::class.java))\n"
        "        }\n"
        "    }\n"
        "\n"
        "    @get:Rule(order = 1)\n"
        "    val composeRule = createAndroidComposeRule<ComponentActivity>()\n"
    )
    assert registration in source
    for item in (
        "android.content.ComponentName",
        "org.junit.rules.ExternalResource",
        "org.robolectric.RuntimeEnvironment",
        "org.robolectric.Shadows.shadowOf",
    ):
        assert f"import {item}\n" in source
    assert source.count("@get:Rule") == 2


def test_the_runner_the_sdk_and_the_compose_rule():
    source = source_of()
    assert "@RunWith(RobolectricTestRunner::class)\n" in source
    # Robolectric 4.18.1 needs Java 21 for API 36; the generated build is JDK 17.
    # No screen-size qualifier: the generated screens scroll, so Robolectric's default small screen
    # is used (Phase 5.3 needed a tall one).
    assert "@Config(sdk = [35])\n" in source
    assert "qualifiers" not in source and "w411dp" not in source
    assert TOOLCHAIN.robolectric_sdk == 35
    assert "import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule\n" in source
    assert "androidx.compose.ui.test.junit4.createAndroidComposeRule" not in source  # deprecated
    assert "    val composeRule = createAndroidComposeRule<ComponentActivity>()\n" in source
    assert "TestNavHostController(context)" in source
    assert "AppNavHost(navController = navController)" in source
    assert "NotesAppTheme {" in source


def test_the_theme_function_follows_the_project_name():
    source = source_of(project_name="R&D Tracker")
    assert "RDTrackerTheme {" in source and "NotesAppTheme" not in source
    assert "import com.example.notes.ui.theme.RDTrackerTheme\n" in source


def test_texts_are_looked_up_in_resources_and_never_written_into_kotlin():
    for spec in ALL_SPECS.values():
        # The class has no string literal at all.
        assert re.findall(r'"[^"\n]*"', source_of(spec)) == []
    # Words of THREE's texts ("About & credits", "Made with Bob's help") appear nowhere.
    assert "credits" not in source_of() and "Bob" not in source_of()


@pytest.mark.parametrize("name", ALL_SPECS)
def test_the_class_is_well_formed(name):
    source = source_of(ALL_SPECS[name])
    imports = [line for line in source.split("\n") if line.startswith("import ")]
    assert imports == sorted(imports) and len(imports) == len(set(imports))
    body = "\n".join(line for line in source.split("\n") if not line.startswith("import "))
    for line in imports:
        assert re.search(rf"\b{re.escape(line.rsplit('.', 1)[-1])}\b", body), line
    assert source.count("{") == source.count("}") and source.count("(") == source.count(")")
    assert source.count("[") == source.count("]")
    assert "\t" not in source and "$" not in source and "__" not in source
    assert all(line == line.rstrip() for line in source.split("\n"))
    assert source.endswith("\n}\n") and source.count("\nclass NavigationTest {\n") == 1
    assert max(len(line) for line in source.split("\n")) <= 100


@pytest.mark.parametrize("name", ALL_SPECS)
def test_one_test_per_expectation(name):
    spec = ALL_SPECS[name]
    source = source_of(spec)
    names = re.findall(r"    @Test\n    fun (\w+)\(\)", source)
    assert len(names) == 1 + 1 + (len(spec.screens) - 1) + edges(spec)
    assert len(names) == len(set(names))
    assert f"startsOn{spec.start_name}" in names and "backOnTheStartScreenLeavesTheApp" in names
    for screen in spec.screens:
        assert (f"shows{screen.name}" in names) == (screen.name != spec.start_name)


@pytest.mark.parametrize("name", ALL_SPECS)
def test_function_names_are_unique_identifiers_and_not_keywords(name):
    source = source_of(ALL_SPECS[name])
    functions = re.findall(r"\n    (?:private )?fun (\w+)\(", source)
    assert len(functions) == len(set(functions))
    hard_keywords = {"class", "object", "fun", "val", "var", "in", "is", "as", "if", "else", "for"}
    assert not set(functions) & hard_keywords
    assert all(re.fullmatch(r"[A-Za-z_]\w*", f) for f in functions)
    # One assertOn per screen, one goTo per screen but the start.
    spec = ALL_SPECS[name]
    for screen in spec.screens:
        assert f"assertOn{screen.name}" in functions
        assert (f"goTo{screen.name}" in functions) == (screen.name != spec.start_name)


def test_names_that_would_collide_get_a_number():
    source = source_of(COLLIDING_NAMES)
    names = re.findall(r"    @Test\n    fun (\w+)\(\)", source)
    assert names.count("xOpensOpensY") == 1 and "xOpensOpensY2" in names
    assert len(names) == len(set(names))


def test_a_single_screen_project_tests_the_start_and_back_only():
    source = source_of(ONE)
    assert re.findall(r"    @Test\n    fun (\w+)\(\)", source) == [
        "startsOnHome",
        "backOnTheStartScreenLeavesTheApp",
    ]
    assert "goTo" not in source
    assert "        buttonIds = emptyList(),\n" in source


def test_the_first_test_of_a_deep_screen_replays_the_way_in_from_the_start():
    source = source_of()
    assert (
        "    @Test\n"
        "    fun settingsOpensAbout() {\n"
        "        goToSettings()\n"
        "        clickButton(R.string.screen_about_title)\n"
        "        assertOnAbout()\n"
        "        clickButton(R.string.action_back)\n"
        "        assertOnSettings()\n"
        "        clickButton(R.string.screen_about_title)\n"
        "        pressSystemBack()\n"
        "        assertOnSettings()\n"
        "    }\n"
    ) in source
    assert (
        "    private fun goToSettings() {\n"
        "        clickButton(R.string.screen_settings_title)\n"
        "        assertOnSettings()\n"
        "    }\n"
    ) in source
    # Shortest way in, in button order: About is reached from Home, not by way of Settings.
    assert (
        "    private fun goToAbout() {\n        clickButton(R.string.screen_about_title)\n"
        in source
    )


def distances(spec: ProjectSpec) -> dict[str, int]:
    """Button presses from the start to each screen, by an independent breadth-first search."""
    dist = {spec.start_name: 0}
    queue = [spec.start_name]
    for name in queue:  # the list grows while it is walked: a first-in first-out queue
        for target in spec.screen(name).navigates_to:
            if target not in dist:
                dist[target] = dist[name] + 1
                queue.append(target)
    return dist


@pytest.mark.parametrize("name", ALL_SPECS)
def test_the_way_into_every_screen_is_a_shortest_one(name):
    spec = ALL_SPECS[name]
    ways = navtests._first_ways(spec)
    wanted = distances(spec)
    for screen in spec.screens:
        if screen.name == spec.start_name:
            continue
        hops, here = 0, screen.name
        while here != spec.start_name:
            here = ways[here][0]
            hops += 1
        assert hops == wanted[screen.name], (name, screen.name)


def test_a_shorter_way_wins_over_the_one_found_first_by_depth():
    ways = navtests._first_ways(SHORTCUT)
    assert ways["Goal"] == ("Detour", 0)  # not ("Mid", 0): two presses, not three
    assert ways["Mid"] == ("Quick", 0)
    source = source_of(SHORTCUT)
    assert (
        "    private fun goToGoal() {\n"
        "        goToDetour()\n"
        "        clickButton(R.string.screen_goal_title)\n"
        "        assertOnGoal()\n"
        "    }\n"
    ) in source


def test_an_edge_test_never_takes_the_name_of_a_helper():
    source = source_of(HELPER_COLLISION)
    assert "    private fun goToXOpensY() {\n" in source  # the helper that goes to XOpensY
    assert "    fun goToXOpensY2() {\n" in source  # the test of the edge GoToX -> Y, renamed


def test_the_screens_are_applied_before_the_tests_are_added():
    # Without AppNavHost and the catalog, the layer that knows about screens complains first.
    files = tuple(
        f
        for f in render_files(make())
        if not f.path.endswith("AppNavHost.kt") and f.path != CATALOG
    )
    with pytest.raises(TemplateRenderError, match=r"AppNavHost\.kt"):
        renderer._kotlin_compose_spec(files, make(), THREE)


def test_the_way_into_a_screen_follows_the_recorded_edges_and_ends_at_the_start():
    spec = big_spec()
    source = source_of(spec)
    ways = navtests._first_ways(spec)
    assert set(ways) == {s.name for s in spec.screens} - {spec.start_name}
    for screen, (came_from, position) in ways.items():
        assert spec.screen(came_from).navigates_to[position] == screen
        body = re.search(
            rf"private fun goTo{screen}\(\) \{{\n((?:        .*\n)*?)    \}}\n", source
        )
        assert (f"        goTo{came_from}()\n" in body.group(1)) == (came_from != spec.start_name)
    for screen in ways:  # following the chain always reaches the start in at most 11 hops
        hops, here = 0, screen
        while here != spec.start_name:
            here = ways[here][0]
            hops += 1
            assert hops < len(spec.screens)


def test_an_edge_into_the_start_screen_is_left_with_the_system_back_only():
    source = source_of(CYCLE)  # Alpha opens Beta, Beta (the start) opens Alpha
    alpha_opens_beta = re.search(
        r"fun alphaOpensBeta\(\) \{\n((?:        .*\n)*?)    \}\n", source
    ).group(1)
    assert alpha_opens_beta == (
        "        goToAlpha()\n"
        "        clickButton(R.string.screen_beta_title)\n"
        "        assertOnBeta()\n"
        "        pressSystemBack()\n"
        "        assertOnAlpha()\n"
    )
    beta_opens_alpha = re.search(
        r"fun betaOpensAlpha\(\) \{\n((?:        .*\n)*?)    \}\n", source
    ).group(1)
    assert "action_back" in beta_opens_alpha  # Alpha is not the start: it has the Back button


def test_equal_texts_are_told_apart_by_their_position():
    source = source_of(DUPLICATES)
    # Home: First and Second are both "Same": the second one is the second "Same" button.
    assert "clickButton(R.string.screen_second_title, occurrence = 1)" in source
    # First shows [Second "Same", the screen titled "Back", the Back button "Back"]: coming back
    # from it the Back button is the *second* "Back"; on the screen titled "Back" it is the only
    # one.
    assert re.search(
        r"fun homeOpensFirst\(\) \{\n(?:        .*\n)*?"
        r"        clickButton\(R\.string\.action_back, occurrence = 1\)\n",
        source,
    )
    assert re.search(
        r"fun firstOpensBack\(\) \{\n        goToFirst\(\)\n"
        r"        clickButton\(R\.string\.screen_back_title\)\n        assertOnBack\(\)\n"
        r"        clickButton\(R\.string\.action_back\)\n",
        source,
    )
    assert source.count("occurrence = ") >= 4


# --- the script is right for its spec: a simulator runs it against a model of the app ---------


@dataclass
class Model:
    """The app as the spec describes it, written without looking at the generated Kotlin."""

    spec: ProjectSpec
    texts: dict[str, str]
    wrong_target: dict[tuple[str, int], str] = field(default_factory=dict)
    back_does_nothing: bool = False
    back_goes_to_start: bool = False
    system_back_does_nothing: bool = False

    def __post_init__(self) -> None:
        self.stack = [self.spec.start_name]
        self.finished = False

    def buttons(self, name: str) -> list[tuple[str, tuple[str, str | int]]]:
        screen = self.spec.screen(name)
        out = [
            (self.texts[f"screen_{route_of(t)}_title"], ("open", i))
            for i, t in enumerate(screen.navigates_to)
        ]
        if name != self.spec.start_name:
            out.append((self.texts["action_back"], ("back", 0)))
        return out

    def click(self, text: str, occurrence: int) -> None:
        here = self.stack[-1]
        matching = [action for label, action in self.buttons(here) if label == text]
        assert len(matching) > occurrence, f"no button #{occurrence} saying {text!r} on {here}"
        kind, index = matching[occurrence]
        if kind == "open":
            target = self.wrong_target.get((here, index))
            self.stack.append(target or self.spec.screen(here).navigates_to[index])
        elif self.back_does_nothing:
            return
        elif self.back_goes_to_start:
            self.stack = [self.spec.start_name]
        else:
            self.stack.pop()

    def system_back(self) -> None:
        if self.system_back_does_nothing:
            return
        if len(self.stack) > 1:
            self.stack.pop()
        else:
            self.finished = True


ASSERT_ON = re.compile(
    r"    private fun assertOn(\w+)\(\) = assertScreen\(\n"
    r"        route = Routes\.(\w+),\n"
    r"        titleId = R\.string\.(\w+),\n"
    r"        bodyId = (null|R\.string\.\w+),\n"
    r"        buttonIds = (emptyList\(\)|listOf\(\n(?:            R\.string\.\w+,\n)+        \)),\n"
    r"    \)\n"
)
FUNCTION = re.compile(
    r"(    @Test\n)?    (private )?fun (\w+)\(\) \{\n((?:        .*\n)*?)    \}\n"
)
CLICK = re.compile(r"clickButton\(R\.string\.(\w+)(?:, occurrence = (\d+))?\)")


def run_script(source: str, spec: ProjectSpec, texts: dict[str, str], **faults) -> list[str]:
    """Run every ``@Test`` of the generated class on a model of the app; return the failures."""
    expectations = {}
    for match in ASSERT_ON.finditer(source):
        name, route, title, body, buttons = match.groups()
        expectations[name] = (
            route,
            title,
            None if body == "null" else body.removeprefix("R.string."),
            re.findall(r"R\.string\.(\w+)", buttons),
        )
    functions = {m.group(3): (bool(m.group(1)), m.group(4)) for m in FUNCTION.finditer(source)}
    assert len(expectations) == len(spec.screens)

    def execute(model: Model, name: str) -> None:
        for line in functions[name][1].split("\n"):
            line = line.strip()
            if not line:
                continue
            if match := CLICK.fullmatch(line):
                model.click(texts[match.group(1)], int(match.group(2) or 0))
            elif line == "pressSystemBack()":
                model.system_back()
            elif line == "assertTrue(composeRule.activity.isFinishing)":
                assert model.finished
            elif match := re.fullmatch(r"assertOn(\w+)\(\)", line):
                route, title, body, buttons = expectations[match.group(1)]
                here = model.stack[-1]
                assert route == route_constant(here), (route, here)
                assert title == f"screen_{route_of(here)}_title"
                assert body == (
                    f"screen_{route_of(here)}_body" if spec.screen(here).description else None
                )
                assert sorted(texts[b] for b in buttons) == sorted(
                    label for label, _ in model.buttons(here)
                )
            elif match := re.fullmatch(r"goTo(\w+)\(\)", line):
                execute(model, f"goTo{match.group(1)}")
            else:
                raise AssertionError(f"the simulator does not know {line!r}")

    failures = []
    for name, (is_test, _) in functions.items():
        if not is_test:
            continue
        model = Model(spec, texts, **faults)
        try:
            execute(model, name)
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
    return failures


def script_of(spec, **config):
    files = rendered(make(**config), spec)
    return files[TEST], strings_of(files)


@pytest.mark.parametrize("name", ALL_SPECS)
def test_the_script_passes_on_the_app_the_spec_describes(name):
    spec = ALL_SPECS[name]
    source, texts = script_of(spec)
    assert run_script(source, spec, texts) == []


def first_edge(spec: ProjectSpec) -> tuple[str, int, str]:
    for screen in spec.screens:
        if screen.navigates_to:
            return screen.name, 0, screen.navigates_to[0]
    raise AssertionError("no edge")


@pytest.mark.parametrize("name", [n for n in ALL_SPECS if n != "one"])
def test_the_script_fails_when_a_button_opens_the_wrong_screen(name):
    spec = ALL_SPECS[name]
    source, texts = script_of(spec)
    for screen in spec.screens:
        for index, target in enumerate(screen.navigates_to):
            other = next(
                (s.name for s in spec.screens if s.name not in (target, screen.name)), screen.name
            )
            failures = run_script(source, spec, texts, wrong_target={(screen.name, index): other})
            # The test of exactly that edge fails (its name may carry a number for uniqueness).
            wanted = f"{screen.name[0].lower()}{screen.name[1:]}Opens{target}"
            assert any(f.startswith(wanted) for f in failures), (screen.name, index, failures)


BACK_FAULTS = [
    (name, fault)
    for name in ALL_SPECS
    if name != "one"
    for fault in ("back_does_nothing", "back_goes_to_start", "system_back_does_nothing")
    # In a two-screen cycle the start is where Back leads anyway: that fault changes nothing there.
    if (name, fault) != ("cycle", "back_goes_to_start")
]


@pytest.mark.parametrize("name, fault", BACK_FAULTS)
def test_the_script_fails_when_back_is_broken(name, fault):
    spec = ALL_SPECS[name]
    source, texts = script_of(spec)
    assert run_script(source, spec, texts, **{fault: True}), fault


def test_the_script_fails_when_back_on_the_start_screen_does_not_leave():
    source, texts = script_of(THREE)
    failures = run_script(source, THREE, texts, system_back_does_nothing=True)
    assert any(f.startswith("backOnTheStartScreenLeavesTheApp") for f in failures)


def test_the_script_depends_on_resource_ids_not_on_words():
    # The same script passes on an app whose texts are all different, as long as they are
    # consistent: it never reads a word, only string resources.
    source, texts = script_of(THREE)
    renamed = {key: f"<{key}>" for key in texts}
    assert run_script(source, THREE, renamed) == []
    # ... and it does fail when two titles become equal and the script still counts one button each.
    merged = dict(texts, screen_about_title=texts["screen_settings_title"])
    assert run_script(source, THREE, merged)


# --- unsupported projects and refusals ---------------------------------------------------------


def test_the_boundary_of_the_supported_minimum_sdk():
    assert TOOLCHAIN.robolectric_sdk == 35
    assert navtests.navigation_tests_supported(make(min_sdk=24))
    assert navtests.navigation_tests_supported(make(min_sdk=35, target_sdk=36))
    assert not navtests.navigation_tests_supported(make(min_sdk=36, target_sdk=36))
    assert not navtests.navigation_tests_supported(make(min_sdk=37, target_sdk=37))


def test_a_project_whose_minimum_sdk_is_above_what_robolectric_runs_gets_no_tests():
    config = make(min_sdk=36, target_sdk=36)
    files = rendered(config, THREE)
    assert not [p for p in files if "/src/test/" in p]
    for text in (files[CATALOG], files[BUILD]):
        for word in ("junit", "robolectric", "navigation-testing", "ui-test"):
            assert word not in text
    # Everything else of the spec project is there, and the navigation host is the same.
    assert f"{ROOT}/ui/screens/SettingsScreen.kt" in files
    assert "navController: NavHostController = rememberNavController()," in files[NAV]
    supported = rendered(make(min_sdk=35, target_sdk=36), THREE)
    assert set(supported) - set(files) == {TEST}
    assert len(files) == 21


def test_a_project_at_the_highest_supported_minimum_sdk_has_the_test():
    files = rendered(make(min_sdk=35, target_sdk=36), THREE)
    assert TEST in files and "@Config(sdk = [35]" in files[TEST]


def test_the_dependency_lines_are_refused_when_the_anchor_is_not_found_exactly_once():
    catalog, build = rendered()[CATALOG], rendered()[BUILD]
    assert navtests.with_test_dependencies(catalog, build) != (catalog, build)
    with pytest.raises(TemplateRenderError, match=r"expected exactly one .*found 0"):
        navtests.with_test_dependencies(catalog.replace("[libraries]", "[libs]"), build)
    with pytest.raises(TemplateRenderError, match=r"expected exactly one .*found 0"):
        navtests.with_test_dependencies(catalog.replace("[plugins]", "[plug]"), build)
    with pytest.raises(TemplateRenderError, match=r"expected exactly one .*found 0"):
        navtests.with_test_dependencies(
            catalog, build.replace("debugImplementation(libs.androidx.compose.ui.tooling)", "")
        )
    with pytest.raises(TemplateRenderError, match=r"expected exactly one .*found 2"):
        navtests.with_test_dependencies(catalog + "\n\n[plugins]\n", build)


def test_the_test_layer_refuses_a_project_it_does_not_recognise():
    files = render_files(make())
    config = make()
    without_catalog = tuple(f for f in files if f.path != CATALOG)
    with pytest.raises(TemplateRenderError, match=r"has no gradle/libs.versions.toml"):
        navtests.add_navigation_tests(without_catalog, config, ONE)
    without_build = tuple(f for f in files if f.path != BUILD)
    with pytest.raises(TemplateRenderError, match=r"has no app/build.gradle.kts"):
        navtests.add_navigation_tests(without_build, config, ONE)
    existing = (*files, RenderedFile(TEST, "package x\n", "already there"))
    with pytest.raises(TemplateRenderError, match="would overwrite"):
        navtests.add_navigation_tests(existing, config, ONE)


def test_the_test_layer_leaves_files_it_does_not_touch_alone():
    files = render_files(make())
    result = navtests.add_navigation_tests(files, make(), ONE)
    before = {f.path: f for f in files}
    after = {f.path: f for f in result}
    assert set(after) - set(before) == {TEST}
    assert {p for p in before if before[p] != after[p]} == {CATALOG, BUILD}
    assert [f.path for f in result] == sorted(after)
    assert after[CATALOG].description == before[CATALOG].description


# --- navigation host and review ------------------------------------------------------------------


def test_the_navigation_host_accepts_a_controller_and_keeps_the_default():
    nav = rendered(spec=THREE)[NAV]
    assert (
        "fun AppNavHost(\n"
        "    modifier: Modifier = Modifier,\n"
        "    navController: NavHostController = rememberNavController(),\n"
        ") {\n"
        "    NavHost(\n"
    ) in nav
    assert "import androidx.navigation.NavHostController\n" in nav
    assert "val navController = rememberNavController()" not in nav
    # The launcher activity is the one of Phase 5.1: it still calls AppNavHost() with no argument.
    assert "                AppNavHost()\n" in rendered(spec=THREE)[f"{ROOT}/MainActivity.kt"]
    assert rendered(spec=THREE)[f"{ROOT}/MainActivity.kt"] == rendered()[f"{ROOT}/MainActivity.kt"]


@pytest.mark.parametrize("name", ALL_SPECS)
def test_the_review_finds_nothing_in_the_project_with_its_test(name):
    for overrides in ({}, {"package_name": "org.acme.deep.pkg"}, {"project_name": "R&D Tracker"}):
        files = rendered(make(**overrides), ALL_SPECS[name])
        report = ReviewEngine().review(ProjectFiles.from_mapping(files))
        assert report.findings == [], [(f.rule, f.file) for f in report.findings]
        assert any(path.startswith("app/src/test/") for path in files)
        assert not report.files_unparsed


def test_a_broken_test_file_is_noticed_by_the_review():
    files = rendered(spec=THREE)
    files[TEST] = files[TEST].replace(
        "    private fun pressSystemBack() {", "    private fun pressSystemBack() {{", 1
    )
    assert "syntax.unbalanced_brackets" in review_rules(files)


def test_the_navigation_facts_still_cover_the_whole_graph_with_the_controller_parameter():
    from androai_codegen.review import ReviewConfig
    from androai_codegen.review.analysis import ProjectAnalysis

    files = ProjectFiles.from_mapping(rendered(spec=THREE))
    nav = ProjectAnalysis(files, ReviewConfig()).navigation.compose
    assert not nav.dynamic and not nav.unsupported and not nav.typed
    assert [u.route for u in nav.starts] == ["home"]
    assert len(nav.navigates) == edges(THREE) and len(nav.declared) == 3


# --- determinism, size and the pin of what was built -------------------------------------------


@pytest.mark.parametrize("name", ALL_SPECS)
def test_rendering_with_tests_is_deterministic(name):
    spec = ALL_SPECS[name]
    assert render_files(make(), spec) == render_files(make(), spec)
    assert render_files(make(), spec) == render_files(
        make(), ProjectSpec.model_validate_json(spec.model_dump_json())
    )


def test_the_largest_project_with_its_test_is_far_inside_the_patch_limits():
    files = render_files(make(), big_spec(12))
    assert len(files) == 19 - 1 + 12 + 1 <= 500
    source = {f.path: f.content for f in files}[TEST]
    assert len(source.encode()) < 100 * 1024
    assert sum(len(f.content.encode()) for f in files) < 2 * 1024 * 1024


def test_the_strings_stay_exactly_what_the_code_uses_with_the_test():
    for spec in ALL_SPECS.values():
        files = rendered(spec=spec)
        used = set()
        for path, content in files.items():
            if path.endswith(".kt"):
                used |= set(re.findall(r"R\.string\.(\w+)", content))
        used |= set(re.findall(r"@string/(\w+)", files["app/src/main/AndroidManifest.xml"]))
        # No string the test needs is missing, and the test makes none unused (lint).
        assert used == set(strings_of(files)), used ^ set(strings_of(files))
    assert STRINGS in rendered(spec=THREE)


FULL_CONFIG = {
    "project_name": "R&D Tracker",
    "package_name": "org.acme.deep.pkg",
    "application_id": "com.acme.NotesPro",
    "version_code": 3,
    "version_name": "2.1",
}
# The four projects the Gradle runs of "Phase 5.3 verification" built (the same samples as Phase
# 5.2, now with their navigation test): SHA-256 over every file's path, a NUL and its content, the
# files sorted by path. If one changes after a deliberate edit, build the project again and update
# this and the progress document together.
BUILT = [
    ("one", {}, ONE, "d80872148f35cc380b4d2623ed03bd96e26cf98606b3954f11c844123434394a"),
    ("three", {}, THREE, "4735dcfb1269989a94117f3b355575004a8e1555a87a4c99ff7cd08a2b9d044c"),
    ("keywords", {}, KEYWORDS, "654cd0bd2823d37c6ceee6edd50806f6e62ef0e86bf4882b0da58aaa04dd9180"),
    (
        "twelve-full",
        FULL_CONFIG,
        SPECS["twelve"],
        "bb6be1a22a6998b119801bee1949deb657f76e578902d8b8e7d1a5f2f2f99748",
    ),
]


@pytest.mark.parametrize("name, config, spec, digest", BUILT, ids=[b[0] for b in BUILT])
def test_the_spec_projects_that_were_built_are_still_what_is_generated(name, config, spec, digest):
    assert combined(render_files(make(**config), spec)) == digest


def test_verified_build_records_the_test_run_and_the_pins_it_used():
    assert VERIFIED_BUILD["junit"] == TOOLCHAIN.junit
    assert VERIFIED_BUILD["robolectric"] == TOOLCHAIN.robolectric
    assert VERIFIED_BUILD["robolectric_sdk"] == TOOLCHAIN.robolectric_sdk
    assert VERIFIED_BUILD["navigation_testing"] == TOOLCHAIN.navigation_compose
    # The Compose test libraries come from the BOM: if the BOM is bumped, this has to be checked.
    assert VERIFIED_BUILD["compose_bom"] == TOOLCHAIN.compose_bom == "2026.11.01"
    assert VERIFIED_BUILD["compose_ui_test"] == "1.13.0"
    tasks = VERIFIED_BUILD["spec_tasks"]
    assert isinstance(tasks, tuple)
    for task in ("build", "tasks --all", "assembleRelease", "bundleRelease", "lint"):
        assert task in tasks
    assert ":app:testDebugUnitTest --rerun" in tasks
    assert len(VERIFIED_BUILD["spec_projects"]) == len(BUILT)


def test_the_default_project_still_claims_no_test_and_the_spec_projects_no_release_test():
    # The default (no spec) project has none: its record never mentions a unit-test task.
    default_claim = str(VERIFIED_BUILD["outputs"]) + " ".join(VERIFIED_BUILD["tasks"])
    assert "UnitTest" not in default_claim and "navigation" not in default_claim.lower()
    # Phase 5.4: the spec projects' record claims both unit-test tasks, and says nothing is skipped.
    assert ":app:testReleaseUnitTest --rerun" in VERIFIED_BUILD["spec_tasks"]
    assert "debug AND the release unit-test task" in str(VERIFIED_BUILD["spec_tests"])
    assert "skipped" not in str(VERIFIED_BUILD["spec_tests"])
    assert "scroll" in str(VERIFIED_BUILD["spec_scroll"])
    # What is still not claimed anywhere in the record: signed outputs, instrumented tests.
    claim = " ".join(str(value) for value in VERIFIED_BUILD.values())
    for not_verified in ("connected", "androidTest", "signed release"):
        assert not_verified not in claim.replace("unsigned", ""), not_verified
