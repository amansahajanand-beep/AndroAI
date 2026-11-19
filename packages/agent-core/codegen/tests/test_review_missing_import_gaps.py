"""``import.missing`` false positives found on real projects (Phase 4a.7).

1. ``items(count = n) { ... }`` in a lazy list or grid is the scope's own *member* function
   (sunflower). Only the extension that takes a list needs ``...lazy.items`` imported.
2. A name the catalog knows only as a Compose/library type, used with a wildcard import of the
   framework package that really provides it (``import android.view.*`` and ``Surface``, on
   android/platform-samples). A wildcard can only excuse a name whose framework class the catalog
   lists, so those classes were missing.

Every test has a twin proving that a genuinely missing import is still reported.
"""

import pytest
from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine


def missing(source: str, name: str = "Uses", language: str = "kotlin") -> list[str]:
    files = dict(good_project())
    files[f"{MAIN}/{name}.{'kt' if language == 'kotlin' else 'java'}"] = source
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    return sorted(f.key for f in report.findings if f.rule == "import.missing")


GRID_IMPORTS = (
    "import androidx.compose.foundation.lazy.grid.GridCells\n"
    "import androidx.compose.foundation.lazy.grid.LazyVerticalGrid\n"
    "import androidx.compose.material3.Text\n"
    "import androidx.compose.runtime.Composable\n"
)


def grid(body: str, imports: str = GRID_IMPORTS) -> str:
    return (
        "package com.example.todo\n\n"
        + imports
        + "\n@Composable\nfun Screen(list: List<String>, total: Int) {\n"
        "    LazyVerticalGrid(columns = GridCells.Fixed(2)) {\n"
        f"        {body}\n"
        "    }\n}\n"
    )


# --- 1. items(count = n): the scope's member ------------------------------------------------------


SUNFLOWER_STYLE = (
    "items(\n"
    "            count = total,\n"
    "            key = { it }\n"
    '        ) { index -> Text("$index") }'
)


@pytest.mark.parametrize(
    "call",
    [
        'items(count = total) { index -> Text("$index") }',
        SUNFLOWER_STYLE,
        'items(5) { index -> Text("$index") }',
        'items(list.size) { index -> Text("$index") }',
        'items(pagingItems.itemCount, key = { it }) { index -> Text("$index") }',
    ],
)
def test_the_member_form_with_a_count_needs_no_import(call):
    assert missing(grid(call)) == []


def test_an_argument_whose_type_cannot_be_known_is_still_judged_as_before():
    """``items(total)`` is the member if ``total`` is an Int and the extension if it is a list.
    Nothing here says which, so the call is not excused (documented limit)."""
    assert missing(grid('items(total) { Text("x") }')) == ["items"]


def test_the_extension_form_with_a_list_still_needs_its_import():
    assert missing(grid("items(list) { Text(it) }")) == ["items"]
    assert missing(grid("items(items = list) { Text(it) }")) == ["items"]


def test_one_member_call_does_not_hide_a_missing_extension_import():
    body = 'items(count = total) { Text("a") }\n        items(list) { Text(it) }'
    assert missing(grid(body)) == ["items"]


def test_the_extension_form_is_fine_once_imported():
    imports = GRID_IMPORTS + "import androidx.compose.foundation.lazy.grid.items\n"
    assert missing(grid("items(list) { Text(it) }", imports)) == []


def test_the_member_form_works_in_a_lazy_column_too():
    source = (
        "package com.example.todo\n\n"
        "import androidx.compose.foundation.lazy.LazyColumn\n"
        "import androidx.compose.material3.Text\n"
        "import androidx.compose.runtime.Composable\n\n"
        "@Composable\nfun Rows(total: Int) {\n"
        '    LazyColumn { items(count = total) { Text("row") } }\n}\n'
    )
    assert missing(source) == []


# --- 2. framework classes behind a wildcard import -----------------------------------------------

COLLISIONS = [
    ("Surface", "android.view", "val s: Surface? = null"),
    ("Color", "android.graphics", "val c: Color? = null"),
    ("Canvas", "android.graphics", "fun draw(canvas: Canvas) {}"),
    ("Path", "android.graphics", "val p: Path? = null"),
    ("Icon", "android.graphics.drawable", "val i: Icon? = null"),
    ("Image", "android.media", "val i: Image? = null"),
    ("RadioButton", "android.widget", "val r: RadioButton? = null"),
    ("Snackbar", "com.google.android.material.snackbar", "val s: Snackbar? = null"),
]


def kotlin_uses(snippet: str, imports: str = "") -> str:
    return f"package com.example.todo\n\n{imports}\nclass Uses {{\n    {snippet}\n}}\n"


@pytest.mark.parametrize(("name", "package", "snippet"), COLLISIONS)
def test_a_wildcard_import_of_the_framework_package_provides_the_class(name, package, snippet):
    assert missing(kotlin_uses(snippet, f"import {package}.*\n")) == []


@pytest.mark.parametrize(("name", "package", "snippet"), COLLISIONS)
def test_the_same_name_with_no_import_is_still_missing(name, package, snippet):
    assert missing(kotlin_uses(snippet)) == [name]


def test_a_wildcard_import_of_an_unrelated_package_does_not_provide_it():
    assert missing(kotlin_uses("fun draw(canvas: Canvas) {}", "import android.view.*\n")) == [
        "Canvas"
    ]
    assert missing(kotlin_uses("val s: Surface? = null", "import android.graphics.*\n")) == [
        "Surface"
    ]


def test_java_files_get_the_same_treatment():
    java = "package com.example.todo;\n\n{imports}\nclass Uses {{ Color c; Surface s; }}\n"
    assert (
        missing(
            java.format(imports="import android.graphics.*;\nimport android.view.*;\n"),
            language="java",
        )
        == []
    )
    assert missing(java.format(imports=""), language="java") == ["Color", "Surface"]


def test_retrofit_path_is_still_suggested_first_for_an_annotation():
    source = (
        "package com.example.todo\n\n"
        "import retrofit2.http.GET\n\n"
        "interface Api {\n"
        '    @GET("a/{id}") suspend fun get(@Path("id") id: String): String\n}\n'
    )
    files = dict(good_project())
    files[f"{MAIN}/Api2.kt"] = source
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    [finding] = [f for f in report.findings if f.rule == "import.missing" and f.key == "Path"]
    assert (finding.suggested_fix or "").startswith("Add `import retrofit2.http.Path`")
