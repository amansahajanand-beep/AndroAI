"""F1: a member list cut off at the limit is never reported as if it were complete.

Before the correction a class with 400 methods gave ``complete=True``, 300 members and no hint that
100 were dropped, and ``observation("member", ...)`` answered ``not_observed`` for a method that was
dropped. ``TypeInfo.truncated`` was set but nothing read it.
"""

from __future__ import annotations

import time

import pytest
from analysis_fixtures import ANDROID_NS, analyse, edges, fact, ids, mini_app, no_errors

from androai_codegen.analysis import AnalysisConfig, AnalysisReport
from androai_codegen.analysis.members import parse_file
from androai_codegen.review.source import SourceFile

CAP = AnalysisConfig().max_members_per_type  # 300
CLASS_PATH = "app/src/main/java/com/x/Cls.kt"
TOP_PATH = "app/src/main/java/com/x/Top.kt"


def kt_class(n: int, name: str = "Big") -> str:
    funs = "".join(f"    fun g{i}() {{}}\n" for i in range(n))
    return f"package com.x\nclass {name} {{\n{funs}}}\n"


def kt_top(n: int) -> str:
    return "package com.x\n" + "".join(f"fun f{i}() {{}}\n" for i in range(n))


def java_class(n: int) -> str:
    methods = "".join(f"    void g{i}() {{}}\n" for i in range(n))
    return f"package com.x;\npublic class Big {{\n{methods}}}\n"


def parse(text: str, path: str = "A.kt", **config):
    return parse_file(SourceFile(path, text), AnalysisConfig(**config))


def limitations(report: AnalysisReport, code: str = "member_cap_reached"):
    return [lim for lim in report.limitations if lim.code == code]


# -- the parser: exactly when a member was dropped ----------------------------------------------


@pytest.mark.parametrize("n", [1, 299, 300, 301, 400, 1000])
def test_a_kotlin_class_is_truncated_only_when_a_member_beyond_the_limit_exists(n: int):
    (decl,) = parse(kt_class(n)).types
    assert len(decl.members) == min(n, CAP)
    assert decl.truncated is (n > CAP)


@pytest.mark.parametrize("n", [299, 300, 301, 400])
def test_a_java_class_is_truncated_only_when_a_member_beyond_the_limit_exists(n: int):
    (decl,) = parse(java_class(n), "Big.java").types
    assert len(decl.members) == min(n, CAP)
    assert decl.truncated is (n > CAP)


@pytest.mark.parametrize("n", [299, 300, 301, 400])
def test_the_top_level_of_a_kotlin_file_is_truncated_only_when_a_member_beyond_the_limit_exists(
    n: int,
):
    info = parse(kt_top(n))
    assert len(info.top_level) == min(n, CAP)
    assert info.top_level_truncated is (n > CAP)
    assert info.types == []


def test_the_members_kept_are_the_first_ones_in_source_order():
    (decl,) = parse(kt_class(400)).types
    assert [m.name for m in decl.members] == [f"g{i}" for i in range(CAP)]
    info = parse(kt_top(400))
    assert [m.name for m in info.top_level] == [f"f{i}" for i in range(CAP)]


def test_properties_functions_and_constructors_all_count():
    body = (
        "".join(f"    val p{i} = {i}\n" for i in range(100))
        + "".join(f"    fun g{i}() {{}}\n" for i in range(100))
        + "".join(f"    constructor(a{i}: Int) : this()\n" for i in range(100))
    )
    exactly = f"package com.x\nclass Big() {{\n{body}}}\n"
    (decl,) = parse(exactly).types
    assert len(decl.members) == CAP and not decl.truncated
    one_more = f"package com.x\nclass Big() {{\n{body}    val extra = 1\n}}\n"
    (decl,) = parse(one_more).types
    assert len(decl.members) == CAP and decl.truncated


@pytest.mark.parametrize(("companion", "truncated"), [(100, False), (101, True)])
def test_companion_members_count_towards_the_limit_of_their_class(companion: int, truncated: bool):
    own = "".join(f"    fun g{i}() {{}}\n" for i in range(200))
    inside = "".join(f"        fun c{i}() {{}}\n" for i in range(companion))
    text = f"package com.x\nclass Big {{\n{own}    companion object {{\n{inside}    }}\n}}\n"
    (decl,) = parse(text).types
    assert len(decl.members) == CAP
    assert decl.truncated is truncated
    assert sum(1 for m in decl.members if m.companion) == min(companion, 100)


def test_nested_types_have_limits_of_their_own():
    outer = "".join(f"    fun o{i}() {{}}\n" for i in range(CAP))
    inner = "".join(f"        fun i{i}() {{}}\n" for i in range(CAP + 1))
    text = f"package com.x\nclass Outer {{\n{outer}    class Inner {{\n{inner}    }}\n}}\n"
    by_name = {t.name: t for t in parse(text).types}
    assert len(by_name["Outer"].members) == CAP and not by_name["Outer"].truncated
    assert len(by_name["Inner"].members) == CAP and by_name["Inner"].truncated


@pytest.mark.parametrize(("n", "truncated"), [(4, False), (5, False), (6, True), (50, True)])
def test_the_limit_is_the_configured_one(n: int, truncated: bool):
    (decl,) = parse(kt_class(n), max_members_per_type=5).types
    assert len(decl.members) == min(n, 5)
    assert decl.truncated is truncated
    info = parse(kt_top(n), max_members_per_type=5)
    assert info.top_level_truncated is truncated


def test_a_java_enum_and_interface_report_truncation_too():
    methods = "".join(f"    void g{i}();\n" for i in range(CAP + 1))
    (decl,) = parse(f"package com.x;\ninterface Api {{\n{methods}}}\n", "Api.java").types
    assert decl.kind == "interface" and decl.truncated and len(decl.members) == CAP
    bodies = "".join(f"    void g{i}() {{}}\n" for i in range(CAP + 1))
    (decl,) = parse(f"package com.x;\nenum E {{\n    A, B;\n{bodies}}}\n", "E.java").types
    assert decl.kind == "enum" and decl.truncated and decl.entries == ("A", "B")


def test_a_huge_member_list_is_still_cut_quickly():
    started = time.perf_counter()
    (decl,) = parse(kt_class(30_000)).types
    info = parse(kt_top(30_000))
    assert time.perf_counter() - started < 10
    assert decl.truncated and info.top_level_truncated


# -- the report: an explicit, honest signal -----------------------------------------------------


@pytest.mark.parametrize("n", [299, 300])
def test_a_class_within_the_limit_looks_exactly_as_before(n: int):
    report = analyse(mini_app(Cls=kt_class(n)))
    assert report.complete is True
    assert limitations(report) == []
    assert ids(report, "type_members") == []
    big = fact(report, "type:com.x.Big")
    assert big.attributes["members"] == n and "members_truncated" not in big.attributes


@pytest.mark.parametrize("n", [301, 400])
def test_a_truncated_class_is_marked_everywhere_the_report_can_say_so(n: int):
    report = analyse(mini_app(Cls=kt_class(n)))
    no_errors(report)
    # 1. the type fact says its member list is cut
    big = fact(report, "type:com.x.Big")
    assert big.attributes["members_truncated"] is True and big.attributes["members"] == CAP
    # 2. an unknown fact with the reason, tied to the type
    unknown = fact(report, "type_members:com.x.Big")
    assert unknown.status == "unknown" and str(CAP) in (unknown.reason or "")
    assert ("type_members:com.x.Big", "type:com.x.Big") in edges(report, "describes")
    # 3. a limitation for the file that blocks completeness
    (limitation,) = limitations(report)
    assert limitation.scope == CLASS_PATH and limitation.affects_completeness is True
    assert str(CAP) in limitation.message
    assert report.complete is False
    # 4. only the first CAP members are facts
    members = [
        f for f in report.facts if f.kind == "member" and f.attributes["owner"] == "com.x.Big"
    ]
    assert len(members) == CAP


def test_the_limitation_bears_on_the_facts_read_from_the_truncated_file():
    report = analyse(mini_app(Cls=kt_class(301)))
    index = report.index()
    for fact_id in ("type:com.x.Big", "member:com.x.Big#g0()"):
        explained = index.explain(fact_id)
        assert [lim.code for lim in explained["limitations"]] == ["member_cap_reached"]


@pytest.mark.parametrize("n", [299, 300])
def test_a_top_level_list_within_the_limit_looks_exactly_as_before(n: int):
    report = analyse(mini_app(Top=kt_top(n)))
    assert report.complete is True and limitations(report) == []
    assert ids(report, "type_members") == []


@pytest.mark.parametrize("n", [301, 400])
def test_a_truncated_top_level_list_is_marked_too(n: int):
    report = analyse(mini_app(Top=kt_top(n)))
    no_errors(report)
    unknown = fact(report, f"type_members:{TOP_PATH}")
    assert unknown.status == "unknown" and unknown.attributes["scope"] == "top_level"
    assert unknown.attributes["limit"] == CAP
    assert (f"type_members:{TOP_PATH}", f"file:{TOP_PATH}") in edges(report, "describes")
    (limitation,) = limitations(report)
    assert limitation.scope == TOP_PATH and limitation.affects_completeness is True
    assert report.complete is False
    assert sum(1 for f in report.facts if f.kind == "member") == CAP


def test_a_class_and_a_top_level_list_truncated_in_one_file_give_one_limitation():
    text = (
        kt_top(CAP + 5)
        + "class Big {\n"
        + "".join(f"  fun g{i}() {{}}\n" for i in range(CAP + 5))
        + "}\n"
    )
    report = analyse(mini_app(Both=text))
    assert len(limitations(report)) == 1
    assert fact(report, "type_members:com.x.Big").status == "unknown"
    assert any(
        f.kind == "type_members" and f.attributes.get("scope") == "top_level" for f in report.facts
    )


def test_a_java_class_is_reported_as_truncated_too():
    report = analyse(mini_app(Big_java=java_class(301)))
    assert fact(report, "type:com.x.Big").attributes["members_truncated"] is True
    assert fact(report, "type_members:com.x.Big").status == "unknown"
    assert report.complete is False


# -- queries: absent is not the same as possibly dropped ----------------------------------------


def test_a_member_beyond_the_limit_is_unknown_not_absent():
    report = analyse(mini_app(Cls=kt_class(301)))
    index = report.index()
    assert index.observation("member", "com.x.Big#g0()") == "observed"
    assert index.observation("member", f"com.x.Big#g{CAP - 1}()") == "observed"
    assert index.observation("member", f"com.x.Big#g{CAP}()") == "unknown"  # the 301st: dropped
    assert index.observation("member", "com.x.Big#neverWritten()") == "unknown"


def test_a_member_of_a_class_within_the_limit_is_genuinely_absent():
    report = analyse(mini_app(Cls=kt_class(300)))
    index = report.index()
    assert index.observation("member", f"com.x.Big#g{CAP - 1}()") == "observed"
    assert index.observation("member", f"com.x.Big#g{CAP}()") == "not_observed"
    assert index.observation("member", "com.x.Big#neverWritten()") == "not_observed"
    assert index.observation("room_dao") == "not_observed"


def test_a_top_level_member_beyond_the_limit_is_unknown_not_absent():
    over = analyse(mini_app(Top=kt_top(301))).index()
    assert over.observation("member", f"com.x#f{CAP - 1}()") == "observed"
    assert over.observation("member", f"com.x#f{CAP}()") == "unknown"
    exact = analyse(mini_app(Top=kt_top(300))).index()
    assert exact.observation("member", f"com.x#f{CAP}()") == "not_observed"


def test_kinds_built_from_members_are_unknown_too_when_a_list_was_cut():
    """A dropped member could have been a DAO query, an endpoint or an injected binding."""
    text = (
        "package com.x\nimport androidx.room.Dao\n@Dao interface NoteDao {\n"
        + "".join(f"    fun q{i}(): Int\n" for i in range(CAP + 1))
        + "}\n"
    )
    cut = analyse(mini_app(Dao=text)).index()
    assert cut.observation("http_endpoint") == "unknown"
    whole = analyse(mini_app(Dao=text.replace("fun q300(): Int\n", ""))).index()
    assert whole.observation("http_endpoint") == "not_observed"


TWO_MODULES = {
    "settings.gradle.kts": 'include(":app", ":lib")\n',
    "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
    "lib/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.y" }\n',
    "app/src/main/AndroidManifest.xml": f"<manifest {ANDROID_NS}><application/></manifest>",
    "lib/src/main/AndroidManifest.xml": f"<manifest {ANDROID_NS}/>",
    "app/src/main/java/com/x/Small.kt": "package com.x\nclass Small { fun f() {} }\n",
}


def test_truncation_blocks_only_the_module_that_holds_the_truncated_file():
    files = {
        **TWO_MODULES,
        "lib/src/main/java/com/y/Big.kt": kt_class(301).replace("com.x", "com.y"),
    }
    index = analyse(files).index()
    assert index.observation("member", "com.y.Big#g300()", module="lib") == "unknown"
    assert index.observation("member", "com.y.Big#g300()") == "unknown"  # the whole project
    assert index.observation("member", "com.x.Small#nope()", module="app") == "not_observed"
    assert index.observation("member", "com.x.Small#nope()", module="lib") == "unknown"


# -- scope: members are reported for application code only --------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "app/src/test/java/com/x/BigTest.kt",
        "app/src/androidTest/java/com/x/BigTest.kt",
        "buildSrc/src/main/kotlin/Big.kt",
    ],
)
def test_a_truncated_class_in_tests_or_build_logic_is_flagged_but_does_not_block_the_report(path):
    report = analyse(mini_app(extra={path: kt_class(301).replace("class Big", "class BigTest")}))
    assert fact(report, "type:com.x.BigTest").attributes["members_truncated"] is True
    assert [f for f in report.facts if f.kind == "member"] == []  # never reported for these
    assert limitations(report) == [] and ids(report, "type_members") == []
    assert report.complete is True


# -- determinism and serialisation --------------------------------------------------------------


def test_the_truncation_signals_are_deterministic_and_serialise():
    files = mini_app(Cls=kt_class(350), Top=kt_top(320))
    first = analyse(dict(files))
    second = analyse(dict(reversed(list(files.items()))))
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()
    assert AnalysisReport.model_validate_json(first.model_dump_json()) == first
    assert [lim.scope for lim in limitations(first)] == sorted(
        lim.scope for lim in limitations(first)
    )


def test_a_smaller_configured_limit_gives_the_same_signals():
    report = analyse(mini_app(Cls=kt_class(8)), config=AnalysisConfig(max_members_per_type=7))
    assert fact(report, "type:com.x.Big").attributes["members_truncated"] is True
    assert "7" in limitations(report)[0].message and report.complete is False
    exact = analyse(mini_app(Cls=kt_class(7)), config=AnalysisConfig(max_members_per_type=7))
    assert limitations(exact) == [] and exact.complete is True
