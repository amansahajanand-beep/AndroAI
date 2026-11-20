"""The AGP 9 ``compileSdk { version = release(N) { minorApiLevel = M } }`` block (API 37.1).

The block usually spans several lines. Before it was read, ``gradle.sdk_order`` and
``change.sdk_changed`` were silent for a module that used it. Each test here has a twin that must
stay quiet, and the forms that cannot be read (``preview(...)``, computed values) are listed
explicitly: they are still not read, by design, and must not crash.
"""

import pytest
from sample_project import good_project

from androai_codegen.review import ProjectFiles, ReviewEngine
from androai_codegen.review.gradle import GradleScript, sdk_label

APP = "app/build.gradle.kts"
KTS_BLOCK = """\
android {
    namespace = "com.example"
    compileSdk {
        version = release(37) {
            minorApiLevel = 1
        }
    }
    defaultConfig {
        minSdk = 24
        targetSdk = 36
    }
}
"""


def script(text: str, path: str = APP) -> GradleScript:
    return GradleScript(path, text)


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def block(release: str, minor: str | None = None, *, oneline: bool = False) -> str:
    if oneline:
        trailing = f" {{ minorApiLevel = {minor} }}" if minor is not None else ""
        return lines(
            "android {", f"    compileSdk {{ version = release({release}){trailing} }}", "}"
        )
    if minor is None:
        call = [f"        version = release({release})"]
    else:
        call = [
            f"        version = release({release}) {{",
            f"            minorApiLevel = {minor}",
            "        }",
        ]
    return lines("android {", "    compileSdk {", *call, "    }", "}")


# --- reading the block ----------------------------------------------------------------------


def test_a_multi_line_block_is_read_with_its_minor_level_and_the_line_of_release():
    s = script(KTS_BLOCK)
    assert s.compile_sdk == (37, 4)  # the line of ``release(37)``, not of ``compileSdk {``
    assert s.compile_sdk_minor == 1
    assert (s.min_sdk, s.target_sdk) == ((24, 9), (36, 10))


@pytest.mark.parametrize(
    "text, expected",
    [
        (block("37", "1"), (37, 1)),
        (block("36", "1", oneline=True), (36, 1)),
        (block("36", "0"), (36, 0)),
        (block("36", "2", oneline=True), (36, 2)),
        (block("37"), (37, 0)),  # no minorApiLevel means minor level 0
        (block("34", oneline=True), (34, 0)),
        ("android {\n    compileSdk = 35\n}\n", (35, 0)),
        ("android {\n    compileSdk 35\n}\n", (35, 0)),
        ("android {\n    compileSdkVersion 34\n}\n", (34, 0)),
        ("android {\n    compileSdkVersion = 33\n}\n", (33, 0)),
    ],
)
def test_every_readable_compile_sdk_form(text, expected):
    s = script(text)
    assert s.compile_sdk is not None
    assert (s.compile_sdk[0], s.compile_sdk_minor) == expected


def test_the_groovy_form_is_read_too():
    groovy = (
        "android {\n    compileSdk {\n        version = release(34) {\n"
        "            minorApiLevel = 1\n        }\n    }\n}\n"
    )
    s = script(groovy, "app/build.gradle")
    assert s.compile_sdk is not None and s.compile_sdk[0] == 34
    assert s.compile_sdk_minor == 1


@pytest.mark.parametrize(
    "text",
    [
        "android { compileSdk { version = release( 37 ) { minorApiLevel=1 } } }\n",
        lines(
            "android {",
            "  compileSdk{",
            "    version=release(37){",
            "      minorApiLevel =  1",
            "    }",
            "  }",
            "}",
        ),
        lines(
            "android {",
            "\tcompileSdk {",
            "\t\tversion = release(37) {",
            "\t\t\tminorApiLevel = 1",
            "\t\t}",
            "\t}",
            "}",
        ),
        lines(
            "android {",
            "    compileSdk {",
            "        version = release(",
            "            37",
            "        ) { minorApiLevel = 1 }",
            "    }",
            "}",
        ),
    ],
    ids=["compact", "tight", "tabs", "wrapped-call"],
)
def test_spacing_and_layout_variants_are_read(text):
    s = script(text)
    assert s.compile_sdk is not None and s.compile_sdk[0] == 37
    assert s.compile_sdk_minor == 1


def test_nested_braces_inside_the_block_do_not_end_it_early():
    text = lines(
        "android {",
        "    compileSdk {",
        "        other { }",
        "        version = release(37) {",
        "            minorApiLevel = 1",
        "        }",
        "    }",
        "}",
    )
    s = script(text)
    assert s.compile_sdk == (37, 4)
    assert s.compile_sdk_minor == 1


def test_a_second_block_is_not_confused_with_the_first():
    text = lines(
        "subprojects {",
        "    compileSdk { version = release(30) }",
        "}",
        "android {",
        "    compileSdk { version = release(36) }",
        "}",
    )
    # The first readable block is the one reported (as for a whole number).
    assert script(text).compile_sdk == (30, 2)


def test_a_whole_number_wins_over_a_block():
    both = "android {\n    compileSdk = 35\n    compileSdk { version = release(37) }\n}\n"
    s = script(both)
    assert s.compile_sdk is not None and s.compile_sdk[0] == 35
    assert s.compile_sdk_minor == 0


def test_the_older_one_line_form_is_still_read():
    s = script("android {\n    compileSdk = release(36)\n}\n")
    assert s.compile_sdk is not None and s.compile_sdk[0] == 36
    assert s.compile_sdk_minor == 0


def test_minor_api_level_is_taken_from_the_compile_sdk_block_only():
    text = (
        "android {\n    compileSdk { version = release(36) }\n"
        "    other { minorApiLevel = 9 }\n}\nminorApiLevel = 7\n"
    )
    assert script(text).compile_sdk_minor == 0


@pytest.mark.parametrize(
    "text",
    [
        'android { compileSdk { version = preview("Baklava") } }\n',
        "android { compileSdk { version = release(libs.versions.compile.get().toInt()) } }\n",
        "android { compileSdk { version = release(sdk) } }\n",
        "android { compileSdk { version = release(36 + 1) } }\n",  # not 36
        "android { compileSdk { } }\n",
        "android { compileSdk {\n  version = release(37)\n",  # never closed
        "android { compileSdk = libs.versions.compile.get().toInt() }\n",
        'android { compileSdkPreview = "Baklava" }\n',
        "android { compileSdkExtension = 7 }\n",
        "",
    ],
    ids=[
        "preview",
        "catalog",
        "variable",
        "arithmetic",
        "empty-block",
        "unclosed",
        "property",
        "preview-property",
        "extension",
        "empty-file",
    ],
)
def test_forms_that_are_not_read_stay_unknown_and_do_not_crash(text):
    s = script(text)
    assert s.compile_sdk is None
    assert s.compile_sdk_minor is None


def test_comments_and_strings_do_not_count():
    text = (
        "// compileSdk { version = release(30) }\n"
        "/* compileSdk { version = release(31) { minorApiLevel = 3 } } */\n"
        'val doc = "compileSdk { version = release(32) }"\n'
        "android {\n    compileSdk = 36\n}\n"
    )
    s = script(text)
    assert s.compile_sdk is not None and s.compile_sdk[0] == 36
    assert s.compile_sdk_minor == 0
    assert script("// compileSdk { version = release(30) }\nandroid { }\n").compile_sdk is None


def test_sdk_label():
    assert sdk_label(37, 1) == "37.1"
    assert sdk_label(37, 0) == "37"
    assert sdk_label(37, None) == "37"


# --- gradle.sdk_order ------------------------------------------------------------------------


def review(files, before=None):
    engine = ReviewEngine()
    after = ProjectFiles.from_mapping(files)
    if before is None:
        report = engine.review(after)
    else:
        report = engine.review(after, before=ProjectFiles.from_mapping(before))
    # a rule that crashes becomes this finding; a test must never mistake it for silence
    assert not [f for f in report.findings if f.rule == "review.internal_error"]
    return report


def project(compile_sdk: str, *, min_sdk=24, target_sdk=35):
    """The known-good project with its ``compileSdk = 35`` line replaced and its levels set."""
    files = good_project()
    text = files[APP]
    assert "    compileSdk = 35\n" in text
    text = text.replace("    compileSdk = 35\n", compile_sdk, 1)
    text = text.replace("minSdk = 24", f"minSdk = {min_sdk}", 1)
    files[APP] = text.replace("targetSdk = 35", f"targetSdk = {target_sdk}", 1)
    return files


def order_findings(files):
    return [(f.key, f.description) for f in review(files).findings if f.rule == "gradle.sdk_order"]


BLOCK_36_1 = lines(
    "    compileSdk {",
    "        version = release(36) {",
    "            minorApiLevel = 1",
    "        }",
    "    }",
)
BLOCK_37_1 = BLOCK_36_1.replace("36", "37")
BLOCK_37_0 = BLOCK_37_1.replace("= 1", "= 0")


def test_the_known_good_project_with_the_block_form_is_clean():
    report = review(project(BLOCK_37_1, target_sdk=36))
    assert report.findings == []


def test_a_target_above_a_multi_line_compile_sdk_block_is_reported_not_skipped():
    ((key, description),) = order_findings(project(BLOCK_36_1, target_sdk=37))
    assert key == "target>compile"
    assert description == "targetSdk (37) is higher than compileSdk (36.1)."


def test_the_same_report_with_a_whole_number_keeps_its_old_message():
    ((key, description),) = order_findings(project("    compileSdk = 35\n", target_sdk=36))
    assert (key, description) == (
        "target>compile",
        "targetSdk (36) is higher than compileSdk (35).",
    )


def test_a_one_line_block_is_reported_too():
    one_line = "    compileSdk { version = release(35) }\n"
    ((key, description),) = order_findings(project(one_line, target_sdk=36))
    assert (key, description) == (
        "target>compile",
        "targetSdk (36) is higher than compileSdk (35).",
    )


def test_a_minor_level_does_not_make_an_equal_target_wrong():
    # targetSdk 37 under compile SDK 37.1 (and 37.0) is in order: only the API level is compared.
    assert order_findings(project(BLOCK_37_1, target_sdk=37)) == []
    assert order_findings(project(BLOCK_37_0, target_sdk=37)) == []
    assert order_findings(project(BLOCK_36_1, target_sdk=36)) == []


def test_min_above_target_is_still_found_next_to_the_block():
    ((key, _),) = order_findings(project(BLOCK_37_1, min_sdk=37, target_sdk=36))
    assert key == "min>target"


def test_both_orderings_can_be_wrong_at_once_with_the_block():
    keys = [k for k, _ in order_findings(project(BLOCK_36_1, min_sdk=38, target_sdk=37))]
    assert sorted(keys) == ["min>target", "target>compile"]


def test_a_block_that_cannot_be_read_is_silent_and_does_not_crash():
    preview = '    compileSdk {\n        version = preview("Baklava")\n    }\n'
    assert order_findings(project(preview, target_sdk=37)) == []


def test_the_findings_are_warnings_that_do_not_block_and_point_at_the_target_line():
    report = review(project(BLOCK_36_1, target_sdk=37))
    (found,) = [f for f in report.findings if f.rule == "gradle.sdk_order"]
    assert not found.blocking
    assert found.line is not None


# --- change.sdk_changed ----------------------------------------------------------------------


def changed(before, after):
    findings = review(after, before=before).findings
    return sorted(f.description for f in findings if f.rule == "change.sdk_changed")


def test_lowering_the_api_level_through_the_block_is_reported():
    before = project(BLOCK_37_1, target_sdk=35)
    after = project(BLOCK_36_1, target_sdk=35)
    assert changed(before, after) == ["compileSdk is lowered from 37.1 to 36.1."]


def test_going_from_a_whole_number_to_a_lower_block_is_reported():
    before = project("    compileSdk = 35\n")
    after = project("    compileSdk { version = release(34) }\n")
    assert changed(before, after) == ["compileSdk is lowered from 35 to 34."]


def test_dropping_the_minor_level_is_a_downgrade():
    # 37.1 -> 37.0 is what Compose 1.13.0 rejects in a real build, so it must not pass silently.
    before = project(BLOCK_37_1, target_sdk=35)
    for lowered in (
        BLOCK_37_0,
        "    compileSdk { version = release(37) }\n",
        "    compileSdk = 37\n",
    ):
        assert changed(before, project(lowered, target_sdk=35)) == [
            "compileSdk is lowered from 37.1 to 37."
        ], lowered


def test_raising_or_keeping_the_compile_sdk_is_quiet():
    low = project("    compileSdk { version = release(36) }\n", target_sdk=35)
    high = project(BLOCK_37_1, target_sdk=35)
    assert changed(low, high) == []
    assert changed(high, high) == []
    assert changed(project(BLOCK_37_0, target_sdk=35), high) == []  # 37.0 -> 37.1 is a raise


def test_whole_number_changes_keep_their_old_messages():
    before = project("    compileSdk = 35\n", target_sdk=35)
    after = project("    compileSdk = 34\n", target_sdk=34)
    assert changed(before, after) == [
        "compileSdk is lowered from 35 to 34.",
        "targetSdk is lowered from 35 to 34.",
    ]
