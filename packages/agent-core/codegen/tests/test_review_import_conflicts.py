"""``import.conflicting`` (Phase 4a): only two *classifiers* of one name clash.

Found on android/platform-samples: ``android.provider.Settings`` (a class) next to the Material icon
``androidx.compose.material.icons.rounded.Settings`` (an extension property) is valid Kotlin. Each
test has a twin showing that a real clash between two classes is still reported.
"""

from sample_project import MAIN, good_project

from androai_codegen.review import ProjectFiles, ReviewEngine

ICON = "androidx.compose.material.icons.rounded.Settings"
OTHER_ICON = "androidx.compose.material.icons.outlined.Settings"
CLASS = "android.provider.Settings"


def conflicts(*imports: str, language: str = "kotlin", extra: dict | None = None):
    files = dict(good_project())
    if language == "kotlin":
        files[f"{MAIN}/Uses.kt"] = (
            "package com.example.todo\n\n"
            + "".join(f"import {i}\n" for i in imports)
            + "\nclass Uses\n"
        )
    else:
        files[f"{MAIN}/Uses.java"] = (
            "package com.example.todo;\n\n"
            + "".join(f"import {i};\n" for i in imports)
            + "\nclass Uses {}\n"
        )
    files.update(extra or {})
    report = ReviewEngine().review(ProjectFiles.from_mapping(files))
    return sorted(f.key for f in report.findings if f.rule == "import.conflicting")


def test_a_class_and_an_icon_property_of_the_same_name_coexist_in_either_order():
    assert conflicts(CLASS, ICON) == []
    assert conflicts(ICON, CLASS) == []


def test_icons_from_different_styles_still_coexist():
    assert conflicts(ICON, OTHER_ICON) == []


def test_an_icon_and_a_project_class_of_the_same_name_coexist():
    project_class = {f"{MAIN}/ui/Settings.kt": "package com.example.todo.ui\n\nclass Settings\n"}
    assert conflicts("com.example.todo.ui.Settings", ICON, extra=project_class) == []


def test_two_classes_of_the_same_name_still_conflict():
    assert conflicts(CLASS, "com.example.other.Settings") == ["Settings"]
    assert conflicts("java.util.Date", "java.sql.Date") == ["Date"]


def test_two_classes_still_conflict_when_an_unrelated_icon_is_imported_too():
    # the icon excuses the pair it is in, not a clash between two other classes
    assert conflicts(
        CLASS, "com.example.other.Settings", "androidx.compose.material.icons.filled.Add"
    ) == ["Settings"]


def test_java_imports_are_all_types_so_a_clash_is_a_clash():
    assert conflicts("java.util.Date", "java.sql.Date", language="java") == ["Date"]
