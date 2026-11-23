"""Multi-screen projects: ProjectSpec rendered into the Kotlin + Compose template (Phase 5.2)."""

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest

from androai_codegen.editing import CreateFile, PatchRejected, ProblemCode
from androai_codegen.review import ProjectFiles, ReviewConfig, ReviewEngine, review_patch
from androai_codegen.review.analysis import ProjectAnalysis
from androai_codegen.templates import (
    Language,
    ProjectConfig,
    ProjectSpec,
    RenderedFile,
    ScreenSpec,
    TemplateRenderError,
    UiToolkit,
    UnsupportedTemplateError,
    render_files,
    render_patch,
    renderer,
    route_constant,
    route_of,
    screens,
)

ROOT = "app/src/main/java/com/example/notes"
STRINGS = "app/src/main/res/values/strings.xml"
NAV = f"{ROOT}/navigation/AppNavHost.kt"
IDS = {"project_id": "proj-1", "run_id": "run-1", "task_id": "task-1"}


def make(**overrides) -> ProjectConfig:
    base = {"project_name": "Notes App", "package_name": "com.example.notes"}
    base.update(overrides)
    return ProjectConfig(**base)


def sc(name, title=None, **kwargs) -> ScreenSpec:
    return ScreenSpec(name=name, title=title or name, **kwargs)


ONE = ProjectSpec(screens=(sc("Home"),))
THREE = ProjectSpec(
    screens=(
        sc("Home", description="Welcome to Notes", navigates_to=("Settings", "About")),
        sc("Settings", navigates_to=("About",)),
        sc("About", "About & credits", description="Made with Bob's help"),
    )
)
CYCLE = ProjectSpec(
    screens=(sc("Alpha", navigates_to=("Beta",)), sc("Beta", navigates_to=("Alpha",))), start="Beta"
)
KEYWORDS = ProjectSpec(
    screens=(
        sc("Class", navigates_to=("Object", "Fun")),
        sc("Object"),
        sc("Fun", navigates_to=("Val",)),
        sc("Val"),
    )
)


def big_spec(count=12) -> ProjectSpec:
    names = [f"Step{i}" for i in range(count)]
    out = []
    for i, name in enumerate(names):
        targets = [names[j] for j in range(1, min(count, 9))] if i == 0 else []
        if i != 0 and i + 1 < count:
            targets.append(names[i + 1])
        if i not in (0, count - 1) and i > 1:
            targets.append(names[0])
        out.append(sc(name, f"Step {i}", navigates_to=tuple(dict.fromkeys(targets))))
    return ProjectSpec(screens=tuple(out))


SPECS = {"one": ONE, "three": THREE, "cycle": CYCLE, "keywords": KEYWORDS, "twelve": big_spec()}


def rendered(config=None, spec=None) -> dict[str, str]:
    return {f.path: f.content for f in render_files(config or make(), spec)}


def combined(files) -> str:
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda f: f.path):
        digest.update(f.path.encode() + b"\0" + f.content.encode("utf-8"))
    return digest.hexdigest()


def review_rules(files: dict[str, str]) -> set[str]:
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return {f.rule for f in report.findings}


# --- Phase 5.1 is preserved exactly -------------------------------------------------------------

GOLDEN = [
    (
        {"project_name": "Notes App", "package_name": "com.example.notes"},
        "b7e8bb019d3e4d0038c52a10e6f4d951c8facdc0a6e7e0dec1608b00520d2c7f",
    ),
    (
        {
            "project_name": "R&D Tracker",
            "package_name": "org.acme.deep.pkg",
            "application_id": "com.acme.NotesPro",
            "version_code": 3,
            "version_name": "2.1",
        },
        "f6409eaf9628b165d7e287296432011429c7d29c18b09f5a432dd2a85f4bed00",
    ),
    (
        {"project_name": "नमस्ते", "package_name": "com.example.hello"},
        "0e8261caadca28a4fbebfe203c93be784f1256697a0ca17877fe2107f70b9087",
    ),
]


@pytest.mark.parametrize("kwargs, digest", GOLDEN)
def test_without_a_spec_the_output_is_exactly_what_phase_5_1_produced(kwargs, digest):
    # These hashes were taken from the Phase 5.1 renderer before Phase 5.2 touched it.
    assert combined(render_files(ProjectConfig(**kwargs))) == digest
    assert combined(render_files(ProjectConfig(**kwargs), None)) == digest
    assert combined(render_files(ProjectConfig(**kwargs), spec=None)) == digest


def test_render_patch_without_a_spec_is_unchanged():
    plain = render_patch(make(), **IDS)
    assert plain == render_patch(make(), **IDS, spec=None)
    assert {c.path: c.content for c in plain.changes} == rendered()


# --- which files a spec produces ------------------------------------------------------------------


TEST = "app/src/test/java/com/example/notes/navigation/NavigationTest.kt"
# Phase 5.3 adds the test dependencies to these two files (see test_templates_navtests.py).
TEST_DEPENDENCY_FILES = {"app/build.gradle.kts", "gradle/libs.versions.toml"}


def test_the_spec_replaces_the_sample_screen_navigation_and_strings_and_adds_the_test():
    base, with_spec = rendered(), rendered(spec=THREE)
    removed = set(base) - set(with_spec)
    added = set(with_spec) - set(base)
    changed = {p for p in set(base) & set(with_spec) if base[p] != with_spec[p]}
    assert removed == {f"{ROOT}/ui/home/HomeScreen.kt"}
    assert added == {f"{ROOT}/ui/screens/{n}Screen.kt" for n in ("Home", "Settings", "About")} | {
        TEST
    }
    assert changed == {NAV, STRINGS} | TEST_DEPENDENCY_FILES
    assert len(with_spec) == 19 - 1 + 3 + 1


def test_every_other_file_is_byte_identical_manifest_theme_activity_and_all():
    base, with_spec = rendered(), rendered(spec=THREE)
    untouched = set(base) - {NAV, STRINGS, f"{ROOT}/ui/home/HomeScreen.kt"} - TEST_DEPENDENCY_FILES
    assert {
        "settings.gradle.kts",
        "build.gradle.kts",
        "gradle/wrapper/gradle-wrapper.properties",
        "app/src/main/AndroidManifest.xml",
        f"{ROOT}/MainActivity.kt",
    } <= untouched
    assert all(base[p] == with_spec[p] for p in untouched)


def test_a_single_screen_project_has_the_files_of_phase_5_1_plus_the_navigation_test():
    files = rendered(spec=ONE)
    assert len(files) == 19 + 1
    assert TEST in files
    assert f"{ROOT}/ui/screens/HomeScreen.kt" in files
    assert f"{ROOT}/ui/home/HomeScreen.kt" not in files


def test_screens_follow_the_package_of_the_config():
    files = rendered(make(package_name="org.acme.deep.pkg"), THREE)
    assert "app/src/main/java/org/acme/deep/pkg/ui/screens/SettingsScreen.kt" in files
    assert not [p for p in files if "com/example" in p]
    for path, content in files.items():
        if path.endswith(".kt"):
            assert "com.example" not in content, path
    assert (
        "import org.acme.deep.pkg.ui.screens.SettingsScreen\n"
        in files["app/src/main/java/org/acme/deep/pkg/navigation/AppNavHost.kt"]
    )


# --- the Kotlin that is written -----------------------------------------------------------------


def imports_of(content: str) -> list[str]:
    return [line for line in content.split("\n") if line.startswith("import ")]


@pytest.mark.parametrize("name", SPECS)
def test_every_generated_kotlin_file_is_well_formed(name):
    for path, content in rendered(spec=SPECS[name]).items():
        if not path.endswith(".kt"):
            continue
        directory = path.rsplit("/", 1)[0].removeprefix("app/src/main/java/")
        directory = directory.removeprefix("app/src/test/java/")
        assert re.match(rf"package {re.escape(directory.replace('/', '.'))}\n", content), path
        imports = imports_of(content)
        assert imports == sorted(imports) and len(imports) == len(set(imports)), path
        body = "\n".join(line for line in content.split("\n") if not line.startswith("import "))
        for line in imports:
            assert re.search(rf"\b{re.escape(line.rsplit('.', 1)[-1])}\b", body), f"{path}: {line}"
        assert content.count("{") == content.count("}") and content.count("(") == content.count(")")
        assert "\t" not in content and "$" not in content
        assert all(line == line.rstrip() for line in content.split("\n")), path


def test_a_screen_with_buttons_and_a_back_button():
    files = rendered(spec=THREE)
    settings = files[f"{ROOT}/ui/screens/SettingsScreen.kt"]
    signature = (
        "fun SettingsScreen(\n"
        "    onOpenAbout: () -> Unit,\n"
        "    onBack: () -> Unit,\n"
        "    modifier: Modifier = Modifier,\n"
        ") {"
    )
    assert signature in settings
    assert "Button(onClick = onOpenAbout) {" in settings
    assert "OutlinedButton(onClick = onBack) {" in settings
    assert (
        "stringResource(R.string.screen_about_title)" in settings
    )  # the button shows the target title
    assert "stringResource(R.string.action_back)" in settings
    assert "import androidx.compose.material3.Button\n" in settings
    assert "import androidx.compose.material3.OutlinedButton\n" in settings
    assert "import com.example.notes.R\n" in settings
    assert "import com.example.notes.ui.theme.NotesAppTheme\n" in settings


def test_the_start_screen_has_no_back_button_and_a_leaf_has_no_forward_button():
    files = rendered(spec=THREE)
    home = files[f"{ROOT}/ui/screens/HomeScreen.kt"]
    about = files[f"{ROOT}/ui/screens/AboutScreen.kt"]
    assert "onBack" not in home and "OutlinedButton" not in home
    assert "Button(onClick = onOpenSettings)" in home and "Button(onClick = onOpenAbout)" in home
    assert "Button(onClick" not in about.replace("OutlinedButton(onClick", "")
    assert "import androidx.compose.material3.Button\n" not in about
    assert (
        "fun AboutScreen(\n    onBack: () -> Unit,\n    modifier: Modifier = Modifier,\n) {"
        in about
    )


def test_a_screen_with_nothing_to_wire_keeps_the_simple_signature():
    only = rendered(spec=ONE)[f"{ROOT}/ui/screens/HomeScreen.kt"]
    assert "fun HomeScreen(modifier: Modifier = Modifier) {" in only
    assert "        HomeScreen()\n" in only
    assert "Button" not in only


@pytest.mark.parametrize("name", SPECS)
def test_every_screen_scrolls_vertically_and_keeps_its_content_centred(name):
    # Phase 5.4: a screen with many buttons (a real emulator run: 8 buttons cut off in landscape)
    # has to scroll. The scroll is applied after the system-bar padding and before the content
    # padding, so nothing is clipped under the bars and the centring (min height = screen) stays.
    files = rendered(spec=SPECS[name])
    screens = [p for p in files if "/ui/screens/" in p]
    assert len(screens) == len(SPECS[name].screens)
    for path in screens:
        text = files[path]
        assert (
            "                .fillMaxSize()\n"
            "                .padding(innerPadding)\n"
            "                .verticalScroll(rememberScrollState())\n"
            "                .padding(24.dp),\n"
        ) in text, path
        assert text.count("verticalScroll(") == 1 and text.count("rememberScrollState()") == 1
        assert "import androidx.compose.foundation.rememberScrollState\n" in text
        assert "import androidx.compose.foundation.verticalScroll\n" in text
        assert "Arrangement.spacedBy(16.dp, Alignment.CenterVertically)" in text


def test_the_sample_screen_of_a_project_without_a_spec_is_unchanged_by_the_scroll():
    # Only generated screens scroll; the Phase 5.1 sample screen (no spec) is byte-identical.
    assert "verticalScroll" not in rendered()[f"{ROOT}/ui/home/HomeScreen.kt"]


def test_a_description_becomes_a_second_text():
    files = rendered(spec=THREE)
    assert "stringResource(R.string.screen_home_body)" in files[f"{ROOT}/ui/screens/HomeScreen.kt"]
    assert "screen_settings_body" not in files[f"{ROOT}/ui/screens/SettingsScreen.kt"]


def test_every_screen_has_a_preview_in_the_apps_theme():
    for screen in THREE.screens:
        text = rendered(spec=THREE)[f"{ROOT}/ui/screens/{screen.name}Screen.kt"]
        preview = (
            "@Preview(showBackground = true)\n@Composable\n"
            f"private fun {screen.name}ScreenPreview() {{\n    NotesAppTheme {{"
        )
        assert preview in text


def test_names_that_are_keywords_in_lower_case_are_fine():
    files = rendered(spec=KEYWORDS)
    assert "fun ClassScreen(" in files[f"{ROOT}/ui/screens/ClassScreen.kt"]
    nav = files[NAV]
    assert 'const val CLASS = "class"' in nav and 'const val OBJECT = "object"' in nav
    assert "composable(Routes.FUN) {" in nav and "navController.navigate(Routes.VAL)" in nav
    assert review_rules(files) == set()


# --- navigation: literal or const val routes, every edge wired ----------------------------------


@pytest.mark.parametrize("name", SPECS)
def test_routes_are_const_vals_and_every_edge_is_wired(name):
    spec = SPECS[name]
    nav = rendered(spec=spec)[NAV]
    assert nav.count("object Routes {") == 1
    for screen in spec.screens:
        assert f'    const val {route_constant(screen.name)} = "{route_of(screen.name)}"\n' in nav
        assert nav.count(f"composable(Routes.{route_constant(screen.name)})") == 1
        for target in screen.navigates_to:
            call = f"navController.navigate(Routes.{route_constant(target)})"
            assert f"onOpen{target} = {{ {call} }}," in nav
        assert ("onBack = { navController.popBackStack() }," in nav) or len(spec.screens) == 1
    assert f"startDestination = Routes.{route_constant(spec.start_name)},\n" in nav
    # No route is computed: nothing but literal strings behind the constants, no string template.
    assert 'navigate("' not in nav and "${" not in nav
    assert re.findall(r"navigate\(([^)]*)\)", nav) == [
        f"Routes.{route_constant(t)}" for s in spec.screens for t in s.navigates_to
    ]


@pytest.mark.parametrize("name", SPECS)
def test_the_navigation_rules_see_the_whole_graph(name):
    spec = SPECS[name]
    files = ProjectFiles.from_mapping(rendered(spec=spec))
    nav = ProjectAnalysis(files, ReviewConfig()).navigation.compose
    assert not nav.dynamic and not nav.unsupported and not nav.typed
    assert sorted(r.pattern for r in nav.declared) == sorted(route_of(s.name) for s in spec.screens)
    assert [u.route for u in nav.starts] == [route_of(spec.start_name)]
    assert sorted(u.route for u in nav.navigates) == sorted(
        route_of(t) for s in spec.screens for t in s.navigates_to
    )


def test_a_chosen_start_is_the_start_destination():
    files = rendered(spec=CYCLE)
    nav = files[NAV]
    assert "startDestination = Routes.BETA," in nav
    assert "onBack" in files[f"{ROOT}/ui/screens/AlphaScreen.kt"]
    assert "onBack" not in files[f"{ROOT}/ui/screens/BetaScreen.kt"]


# --- strings ------------------------------------------------------------------------------------


def strings_of(files) -> dict[str, str]:
    return {e.get("name"): e.text for e in ET.fromstring(files[STRINGS])}


@pytest.mark.parametrize("name", SPECS)
def test_strings_cover_what_the_code_uses_and_nothing_else(name):
    files = rendered(spec=SPECS[name])
    strings = strings_of(files)
    used = set()
    for path, content in files.items():
        if path.endswith(".kt"):
            used |= set(re.findall(r"R\.string\.(\w+)", content))
    used |= set(re.findall(r"@string/(\w+)", files["app/src/main/AndroidManifest.xml"]))
    assert used == set(strings), used ^ set(strings)  # no missing string, no unused one (lint)


def test_the_texts_are_escaped_and_parse_back():
    strings = strings_of(rendered(make(project_name="R&D Tracker"), THREE))
    assert strings["app_name"] == "R&D Tracker"
    assert strings["screen_about_title"] == "About & credits"
    assert strings["screen_about_body"] == "Made with Bob\\'s help"  # AAPT unescapes the backslash
    assert strings["screen_home_title"] == "Home"


def test_back_is_only_defined_when_a_screen_uses_it():
    assert "action_back" not in strings_of(rendered(spec=ONE))
    assert strings_of(rendered(spec=THREE))["action_back"] == "Back"


def test_the_xml_is_well_formed_for_awkward_titles():
    spec = ProjectSpec(
        screens=(
            sc(
                "Home",
                "Tom & Jerry's",
                description="C++ (beta) + more!",
                navigates_to=("Next",),
            ),
            sc("Next", "नमस्ते"),
        )
    )
    files = rendered(spec=spec)
    ET.fromstring(files[STRINGS])
    assert strings_of(files)["screen_home_title"] == "Tom & Jerry\\'s"


# --- determinism --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", SPECS)
def test_rendering_is_deterministic(name):
    spec = SPECS[name]
    assert render_files(make(), spec) == render_files(make(), spec)
    assert render_files(make(), spec) == render_files(
        make(), ProjectSpec.model_validate_json(spec.model_dump_json())
    )
    paths = [f.path for f in render_files(make(), spec)]
    assert paths == sorted(paths)


def test_the_order_of_the_screens_decides_the_order_of_routes():
    a, b = sc("A", navigates_to=("B",)), sc("B")
    first = rendered(spec=ProjectSpec(screens=(a, b)))[NAV]
    assert first.index("const val A =") < first.index("const val B =")
    swapped = rendered(spec=ProjectSpec(screens=(b, a), start="A"))[NAV]
    assert swapped.index("const val B =") < swapped.index("const val A =")


def test_the_output_has_no_date_host_or_path():
    blob = "\n".join(rendered(spec=THREE).values())
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", blob)
    for needle in ("/Users/", "C:\\", "/home/", "localhost"):
        assert needle not in blob


# --- limits and errors --------------------------------------------------------------------------


def test_the_largest_project_is_far_inside_the_patch_limits():
    files = render_files(make(), big_spec(12))
    assert len(files) == 19 - 1 + 12 + 1
    assert len(files) <= 500
    assert sum(len(f.content.encode()) for f in files) < 2 * 1024 * 1024
    assert big_spec(12).screens[0].navigates_to  # the big spec really has edges


def test_a_template_that_cannot_take_a_spec_says_so(monkeypatch):
    key = (Language.KOTLIN, UiToolkit.COMPOSE)
    monkeypatch.setitem(renderer._REGISTRY, key, replace(renderer._REGISTRY[key], apply_spec=None))
    with pytest.raises(UnsupportedTemplateError, match="does not support a project spec"):
        render_files(make(), THREE)
    assert render_files(make())  # without a spec it still renders


def test_a_template_that_does_not_exist_is_refused_before_the_spec_is_looked_at():
    with pytest.raises(UnsupportedTemplateError, match="no java\\+compose template yet"):
        render_files(make(language="java"), THREE)


def test_the_spec_layer_refuses_a_template_it_does_not_recognise():
    files = tuple(f for f in render_files(make()) if not f.path.endswith("AppNavHost.kt"))
    with pytest.raises(TemplateRenderError, match="has no .*AppNavHost.kt"):
        screens.apply_spec(files, make(), THREE)


def test_a_screen_cannot_overwrite_an_existing_file():
    files = render_files(make()) + (
        RenderedFile(f"{ROOT}/ui/screens/HomeScreen.kt", "package x\n", "a file already there"),
    )
    with pytest.raises(TemplateRenderError, match="would overwrite"):
        screens.apply_spec(files, make(), ONE)


def test_generated_files_are_held_to_the_same_rules_as_template_files():
    from androai_codegen.templates.render import checked_file

    assert checked_file("a/b.txt", "x\n", "d").path == "a/b.txt"
    for path, content in [
        ("../x.txt", "x\n"),
        ("/abs.txt", "x\n"),
        ("a\\b.txt", "x\n"),
        (".git/config", "x\n"),
        ("a//b.txt", "x\n"),
        ("a/b.txt", "no newline"),
        ("a/b.txt", "crlf\r\n"),
        ("a/b.txt", "nul\x00\n"),
    ]:
        with pytest.raises(TemplateRenderError):
            checked_file(path, content, "d")


# --- PatchSet, PatchEngine, review --------------------------------------------------------------


@pytest.mark.parametrize("name", SPECS)
def test_the_patch_creates_every_file_and_nothing_else(name):
    patch = render_patch(make(), **IDS, spec=SPECS[name])
    assert all(isinstance(c, CreateFile) for c in patch.changes)
    assert {c.path: c.content for c in patch.changes} == rendered(spec=SPECS[name])
    assert all(c.description for c in patch.changes)


def test_the_patch_previews_applies_byte_for_byte_and_rolls_back(engine, ws_root):
    patch = render_patch(make(), **IDS, spec=THREE)
    assert engine.preview(patch).ok
    result = engine.apply(patch)
    assert len(result.records) == 22
    written = {
        p.relative_to(ws_root).as_posix(): p.read_bytes() for p in ws_root.rglob("*") if p.is_file()
    }
    assert written == {path: text.encode() for path, text in rendered(spec=THREE).items()}
    engine.rollback(result.patch_id)
    assert not [p for p in ws_root.rglob("*") if p.is_file()]


def test_a_project_is_not_created_over_an_existing_one(engine):
    patch = render_patch(make(), **IDS, spec=THREE)
    engine.apply(patch)
    with pytest.raises(PatchRejected) as raised:
        engine.apply(patch)
    assert {p.code for p in raised.value.preview.problems} == {ProblemCode.ALREADY_EXISTS}


def test_the_patch_can_be_created_with_a_checkpoint(manager, ws_root):
    tracked = manager.apply(render_patch(make(), **IDS, spec=THREE))
    assert len(tracked.result.records) == 22
    assert (ws_root / f"{ROOT}/ui/screens/AboutScreen.kt").is_file()


def test_review_patch_accepts_the_project_before_it_is_applied(engine, ws_root):
    review = review_patch(engine, render_patch(make(), **IDS, spec=THREE))
    assert review.applicable and review.report is not None and review.report.findings == []
    assert not [p for p in ws_root.rglob("*") if p.is_file()]


@pytest.mark.parametrize("name", SPECS)
@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"package_name": "org.acme.deep.pkg", "application_id": "com.acme.Notes"},
        {"project_name": "R&D Tracker"},
    ],
    ids=["default", "other-package", "special-name"],
)
def test_the_review_finds_nothing_in_any_generated_project(name, overrides):
    files = rendered(make(**overrides), SPECS[name])
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    assert report.findings == [], [(f.rule, f.file) for f in report.findings]
    assert report.files_reviewed >= 14 and not report.files_unparsed


# Sentinels: the rules are alive on these projects. A breakage in one generated file is found.


def break_file(path, old, new, spec=THREE):
    files = rendered(spec=spec)
    assert old in files[path], (path, old)
    files[path] = files[path].replace(old, new, 1)
    return files


SENTINELS = [
    (
        "navigate to a missing route",
        NAV,
        "navController.navigate(Routes.ABOUT)",
        'navController.navigate("nowhere")',
        "navigation.destination_missing",
    ),
    (
        "start destination missing",
        NAV,
        "startDestination = Routes.HOME,",
        'startDestination = "missing",',
        "navigation.start_destination_missing",
    ),
    (
        "destination removed",
        NAV,
        "composable(Routes.SETTINGS) {",
        'composable("elsewhere") {',
        "navigation.destination_missing",
    ),
    (
        "duplicate destination",
        NAV,
        "composable(Routes.ABOUT) {",
        "composable(Routes.HOME) {",
        "navigation.duplicate_destination",
    ),
    (
        "screen import dropped",
        NAV,
        "import com.example.notes.ui.screens.SettingsScreen\n",
        "",
        "import.missing",
    ),
    (
        "string removed",
        STRINGS,
        '    <string name="screen_about_title">About &amp; credits</string>\n',
        "",
        "resource.unresolved",
    ),
    (
        "brace removed",
        f"{ROOT}/ui/screens/AboutScreen.kt",
        "private fun AboutScreenPreview() {",
        "private fun AboutScreenPreview() {{",
        "syntax.unbalanced_brackets",
    ),
]


@pytest.mark.parametrize("label, path, old, new, rule", SENTINELS, ids=[s[0] for s in SENTINELS])
def test_the_review_catches_a_broken_generated_project(label, path, old, new, rule):
    rules = review_rules(break_file(path, old, new))
    assert rule in rules, (label, rules)


def test_removing_a_screen_file_is_caught():
    files = rendered(spec=THREE)
    del files[f"{ROOT}/ui/screens/SettingsScreen.kt"]
    assert "import.unresolved_project" in review_rules(files)
