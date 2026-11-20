"""Screens, routes and navigation of a ``ProjectSpec`` for the Kotlin + Compose template.

``apply_spec`` takes the files of the Phase 5.1 template and turns them into those of a project
with the screens of a spec:

* the sample ``HomeScreen.kt`` is removed,
* ``navigation/AppNavHost.kt`` and ``res/values/strings.xml`` are replaced,
* one ``ui/screens/<Name>Screen.kt`` is added per screen.

Everything else is untouched. Only validated identifiers reach Kotlin code (screen names, their
snake-case routes and upper-case constants). Routes are ``const val`` strings in ``Routes`` and
every ``navigate`` call names one of them, so the static navigation review can follow the graph
(it stays silent when a route is computed). Titles and descriptions only reach ``strings.xml``,
escaped, and a string is written only if something uses it, so lint finds no unused resource.
"""

from __future__ import annotations

from .config import ProjectConfig
from .errors import TemplateRenderError
from .render import RenderedFile, android_string, checked_file
from .spec import ProjectSpec, ScreenSpec, route_constant, route_of

STRINGS_PATH = "app/src/main/res/values/strings.xml"
BACK_STRING = "action_back"


def _java_root(config: ProjectConfig) -> str:
    return f"app/src/main/java/{config.package_path}"


def screen_path(config: ProjectConfig, screen: ScreenSpec) -> str:
    return f"{_java_root(config)}/ui/screens/{screen.name}Screen.kt"


def title_resource(screen: ScreenSpec) -> str:
    return f"screen_{route_of(screen.name)}_title"


def body_resource(screen: ScreenSpec) -> str:
    return f"screen_{route_of(screen.name)}_body"


def _is_start(spec: ProjectSpec, screen: ScreenSpec) -> bool:
    return screen.name == spec.start_name


def _callback(target: str) -> str:
    return f"onOpen{target}"


def strings_xml(config: ProjectConfig, spec: ProjectSpec) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<resources>",
        f'    <string name="app_name">{android_string(config.project_name)}</string>',
    ]
    for screen in spec.screens:
        lines.append(
            f'    <string name="{title_resource(screen)}">{android_string(screen.title)}</string>'
        )
        if screen.description:
            lines.append(
                f'    <string name="{body_resource(screen)}">'
                f"{android_string(screen.description)}</string>"
            )
    if any(not _is_start(spec, screen) for screen in spec.screens):
        lines.append(f'    <string name="{BACK_STRING}">Back</string>')
    lines.append("</resources>")
    return "\n".join(lines) + "\n"


def screen_source(config: ProjectConfig, spec: ProjectSpec, screen: ScreenSpec) -> str:
    start = _is_start(spec, screen)
    callbacks = [_callback(target) for target in screen.navigates_to]
    if not start:
        callbacks.append("onBack")

    imports = {
        "androidx.compose.foundation.layout.Arrangement",
        "androidx.compose.foundation.layout.Column",
        "androidx.compose.foundation.layout.fillMaxSize",
        "androidx.compose.foundation.layout.padding",
        "androidx.compose.material3.MaterialTheme",
        "androidx.compose.material3.Scaffold",
        "androidx.compose.material3.Text",
        "androidx.compose.runtime.Composable",
        "androidx.compose.ui.Alignment",
        "androidx.compose.ui.Modifier",
        "androidx.compose.ui.res.stringResource",
        "androidx.compose.ui.tooling.preview.Preview",
        "androidx.compose.ui.unit.dp",
        f"{config.package_name}.R",
        f"{config.package_name}.ui.theme.{config.theme_function}",
    }
    if screen.navigates_to:
        imports.add("androidx.compose.material3.Button")
    if not start:
        imports.add("androidx.compose.material3.OutlinedButton")

    name = f"{screen.name}Screen"
    out = [f"package {config.package_name}.ui.screens", ""]
    out += [f"import {item}" for item in sorted(imports)]
    out += ["", "@Composable"]
    if callbacks:
        out.append(f"fun {name}(")
        out += [f"    {callback}: () -> Unit," for callback in callbacks]
        out += ["    modifier: Modifier = Modifier,", ") {"]
    else:
        out.append(f"fun {name}(modifier: Modifier = Modifier) {{")
    out += [
        "    Scaffold(modifier = modifier.fillMaxSize()) { innerPadding ->",
        "        Column(",
        "            modifier = Modifier",
        "                .fillMaxSize()",
        "                .padding(innerPadding)",
        "                .padding(24.dp),",
        "            verticalArrangement =",
        "                Arrangement.spacedBy(16.dp, Alignment.CenterVertically),",
        "            horizontalAlignment = Alignment.CenterHorizontally,",
        "        ) {",
        "            Text(",
        f"                text = stringResource(R.string.{title_resource(screen)}),",
        "                style = MaterialTheme.typography.headlineMedium,",
        "            )",
    ]
    if screen.description:
        out += [
            "            Text(",
            f"                text = stringResource(R.string.{body_resource(screen)}),",
            "                style = MaterialTheme.typography.bodyLarge,",
            "            )",
        ]
    for target in screen.navigates_to:
        target_title = title_resource(spec.screen(target))
        out += [
            f"            Button(onClick = {_callback(target)}) {{",
            f"                Text(text = stringResource(R.string.{target_title}))",
            "            }",
        ]
    if not start:
        out += [
            "            OutlinedButton(onClick = onBack) {",
            f"                Text(text = stringResource(R.string.{BACK_STRING}))",
            "            }",
        ]
    out += ["        }", "    }", "}", "", "@Preview(showBackground = true)", "@Composable"]
    out += [f"private fun {name}Preview() {{", f"    {config.theme_function} {{"]
    if callbacks:
        out.append(f"        {name}(")
        out += [f"            {callback} = {{}}," for callback in callbacks]
        out.append("        )")
    else:
        out.append(f"        {name}()")
    out += ["    }", "}"]
    return "\n".join(out) + "\n"


def nav_host_source(config: ProjectConfig, spec: ProjectSpec) -> str:
    imports = {
        "androidx.compose.runtime.Composable",
        "androidx.compose.ui.Modifier",
        "androidx.navigation.compose.NavHost",
        "androidx.navigation.compose.composable",
        "androidx.navigation.compose.rememberNavController",
    }
    imports |= {f"{config.package_name}.ui.screens.{s.name}Screen" for s in spec.screens}

    out = [f"package {config.package_name}.navigation", ""]
    out += [f"import {item}" for item in sorted(imports)]
    out += ["", "object Routes {"]
    out += [f'    const val {route_constant(s.name)} = "{route_of(s.name)}"' for s in spec.screens]
    out += [
        "}",
        "",
        "@Composable",
        "fun AppNavHost(modifier: Modifier = Modifier) {",
        "    val navController = rememberNavController()",
        "",
        "    NavHost(",
        "        navController = navController,",
        f"        startDestination = Routes.{route_constant(spec.start_name)},",
        "        modifier = modifier,",
        "    ) {",
    ]
    for screen in spec.screens:
        wiring = [
            f"                {_callback(target)} = "
            f"{{ navController.navigate(Routes.{route_constant(target)}) }},"
            for target in screen.navigates_to
        ]
        if not _is_start(spec, screen):
            wiring.append("                onBack = { navController.popBackStack() },")
        out.append(f"        composable(Routes.{route_constant(screen.name)}) {{")
        if wiring:
            out.append(f"            {screen.name}Screen(")
            out += wiring
            out.append("            )")
        else:
            out.append(f"            {screen.name}Screen()")
        out.append("        }")
    out += ["    }", "}"]
    return "\n".join(out) + "\n"


def apply_spec(
    files: tuple[RenderedFile, ...], config: ProjectConfig, spec: ProjectSpec
) -> tuple[RenderedFile, ...]:
    """The files of the Phase 5.1 project with the screens and navigation of ``spec``."""
    root = _java_root(config)
    nav_path = f"{root}/navigation/AppNavHost.kt"
    sample_path = f"{root}/ui/home/HomeScreen.kt"
    base = {file.path: file for file in files}
    for path in (nav_path, sample_path, STRINGS_PATH):
        if path not in base:
            raise TemplateRenderError(f"the template has no {path} for the spec to replace")

    result = {path: file for path, file in base.items() if path != sample_path}
    result[nav_path] = checked_file(
        nav_path, nav_host_source(config, spec), "Navigation host and routes of the screens"
    )
    result[STRINGS_PATH] = checked_file(
        STRINGS_PATH, strings_xml(config, spec), "String resources: app name and screen texts"
    )
    for screen in spec.screens:
        path = screen_path(config, screen)
        if path in result:
            raise TemplateRenderError(f"screen {screen.name} would overwrite {path}")
        result[path] = checked_file(
            path, screen_source(config, spec, screen), f"{screen.name} screen"
        )
    return tuple(result[path] for path in sorted(result))
