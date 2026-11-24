"""Edge cases found by mutation testing: each test pins behaviour that no other test noticed."""

from __future__ import annotations

from pathlib import Path

from analysis_fixtures import (
    ANDROID_NS,
    APP_NS,
    GITHUB_TOKEN,
    analyse,
    d,
    edges,
    fact,
    hilt_project,
    ids,
    java_xml_project,
    mini_app,
)
from ingest_helpers import write_tree

from androai_codegen.analysis import (
    AnalysisConfig,
    AnalysisReport,
    Evidence,
    analyse_mapping,
    read_project,
)
from androai_codegen.analysis.annotations import declaration_anchor, extract_annotations
from androai_codegen.analysis.members import parse_file
from androai_codegen.analysis.model import Fact, Relationship
from androai_codegen.analysis.query import ReportIndex
from androai_codegen.analysis.store import FactStore
from androai_codegen.analysis.text import LineText, SrcView, scrub, split_spans
from androai_codegen.editing.workspace import Workspace
from androai_codegen.review.source import SourceFile


def rel(report: AnalysisReport, kind: str, source: str, target: str) -> Relationship:
    found = [
        r
        for r in report.relationships
        if r.kind == kind and r.source == source and r.target == target
    ]
    assert found, f"no {kind} edge {source} -> {target}; have {sorted(edges(report, kind))[:6]}"
    return found[0]


# -- reading the project ------------------------------------------------------------------------


def test_the_total_size_cap_is_exact_to_the_byte(tmp_path: Path):
    a, b = "package a\nclass A\n", "package b\nclass B\n"
    root = write_tree(tmp_path / "p", {"app/a.kt": a, "app/b.kt": b})
    both, audit = read_project(
        Workspace(root), config=AnalysisConfig(max_total_bytes=len(a) + len(b))
    )
    assert set(both.texts) == {"app/a.kt", "app/b.kt"} and not audit.capped_bytes
    one, audit = read_project(
        Workspace(root), config=AnalysisConfig(max_total_bytes=len(a) + len(b) - 1)
    )
    assert set(one.texts) == {"app/a.kt"} and audit.capped_bytes


def test_a_deadline_that_has_passed_stops_the_work():
    full = analyse(hilt_project())
    stopped = analyse(hilt_project(), config=AnalysisConfig(deadline_seconds=0.0))
    assert len(stopped.facts) < len(full.facts) / 2


def test_a_parser_failure_on_one_file_is_recorded_and_the_others_are_still_read(monkeypatch):
    from androai_codegen.analysis import symbols

    real = symbols.parse_file

    def flaky(source, config):
        if "Bad" in source.path:
            raise ValueError("boom")
        return real(source, config)

    monkeypatch.setattr(symbols, "parse_file", flaky)
    report = analyse_mapping(
        mini_app(Bad="package com.x\nclass Bad\n", Good="package com.x\nclass Good\n")
    )
    errors = [m for m in report.limitations if m.code == "extractor_error"]
    assert [m.scope for m in errors] == ["app/src/main/java/com/x/Bad.kt"]
    assert "ValueError" in errors[0].message and "boom" not in errors[0].message
    assert "type:com.x.Good" in {f.id for f in report.facts} and report.complete is False


# -- model and store ----------------------------------------------------------------------------


def test_one_character_and_nested_evidence_paths_are_valid():
    assert Evidence(path="a").path == "a"
    assert Evidence(path="a/b/c.kt", line=1).line == 1


def test_a_weaker_statement_never_lends_its_note_to_a_stronger_fact():
    s = FactStore(AnalysisConfig())
    ev = Evidence(path="a.kt", line=1)
    s.fact("x", "one", basis="source", evidence=[ev])
    s.fact("x", "one", basis="heuristic", status="inferred", note="a guess")
    frozen = s.freeze(AnalysisReport(complete=True).stats).facts[0]
    assert frozen.status == "confirmed" and frozen.note is None


def test_merged_evidence_keeps_the_smallest_entries_whatever_the_order():
    import random

    lines = list(range(1, 21))
    results = set()
    for seed in range(6):
        order = lines[:]
        random.Random(seed).shuffle(order)
        s = FactStore(AnalysisConfig(max_evidence_per_fact=8))
        for line in order:
            s.fact("x", "one", basis="source", evidence=[Evidence(path="a.kt", line=line)])
        frozen = s.freeze(AnalysisReport(complete=True).stats).facts[0]
        results.add(tuple(e.line for e in frozen.evidence))
    assert results == {tuple(range(1, 9))}


def test_a_path_search_in_a_densely_cyclic_graph_finishes_at_once():
    names = [f"x:n{i}" for i in range(10)]
    ev = (Evidence(path="a.kt"),)
    facts = [
        Fact(id=n, kind="x", subject=n[2:], status="confirmed", basis="source", evidence=ev)
        for n in [*names, "x:target"]
    ]
    rels = [
        Relationship(source=a, target=b, kind="e", status="confirmed", basis="source", evidence=ev)
        for a in names
        for b in names
        if a != b
    ]
    index = ReportIndex(
        AnalysisReport(complete=True, facts=tuple(facts), relationships=tuple(rels))
    )
    assert index.path("x:n0", "x:target", max_depth=12) is None
    assert len(index.path("x:n0", "x:n9")) == 1
    assert len(index.reachable("x:n0", max_depth=50)) == 9


# -- text helpers -------------------------------------------------------------------------------


def test_scrub_keeps_the_text_around_a_credential():
    assert scrub(f"before {GITHUB_TOKEN} after") == "before [REDACTED] after"
    assert scrub(f"{GITHUB_TOKEN}") == "[REDACTED]"


def test_split_spans_starting_at_a_less_than_sign_and_with_comparisons():
    text = "a<b, c"
    assert [text[s:e] for s, e in split_spans(text, 1, 6)] == ["<b", " c"]
    comparison = "x > 1, y"
    assert [comparison[s:e].strip() for s, e in split_spans(comparison, 0, 8)] == ["x > 1", "y"]


def test_line_start_knows_its_first_and_last_line():
    lines = LineText("a\nb", "a\nb")
    assert [lines.line_start(n) for n in (0, 1, 2, 3)] == [None, 0, 2, None]
    assert SrcView(SourceFile("A.kt", "x\n")).lines.line_start(1) == 0


def test_an_annotation_at_the_very_end_of_a_file_is_read():
    [found] = extract_annotations(SrcView(SourceFile("A.kt", "class A\n@Foo")))
    assert found.simple == "Foo" and found.args == ()
    analyse(mini_app(A="package com.x\nclass A\n@Foo"))


def test_the_anchor_stops_at_an_annotation_whose_argument_list_never_closes():
    view = SrcView(SourceFile("A.kt", "@A @B(1, 2\nclass X\n"))
    assert declaration_anchor(view, 0) == 3  # the start of @B: nothing after it can be trusted
    first, second = extract_annotations(view)
    assert first.target == second.target  # a run of annotations shares one anchor


# -- members ------------------------------------------------------------------------------------


def parse(text: str, path: str = "A.kt"):
    return parse_file(SourceFile(path, d(text)), AnalysisConfig())


def test_a_type_alias_is_read_exactly_and_raises_no_unknown():
    info = parse("package p\ntypealias Names = List<String>\n")
    assert info.types[0].exact is True
    assert (
        ids(analyse(mini_app(T="package com.x\ntypealias N = List<String>\n")), "type_members")
        == []
    )


def test_supertypes_on_continuation_lines_and_function_types_in_generics():
    info = parse("""
        package p
        class A :
            Base(),
            Other
        class B
            : Base2()
        class H : Handler<(Int) -> Unit>(), Plain
        """)
    found = {t.name: [s.written for s in t.supertypes] for t in info.types}
    assert found == {"A": ["Base", "Other"], "B": ["Base2"], "H": ["Handler", "Plain"]}


def test_an_untyped_delegated_property_is_read_and_a_plain_one_is_not_delegated():
    info = parse("""
        package p
        class A {
            val x by lazy { 1 }
            val y = 2
        }
        """)
    members = {m.name: m for m in info.types[0].members}
    assert members["x"].delegated and members["x"].init_name == "lazy"
    assert not members["y"].delegated


def test_a_java_method_named_like_its_class_but_with_a_return_type_is_a_method():
    info = parse("package p;\nclass A { A() {} int A() { return 1; } }\n", "A.java")
    assert [(m.kind, m.name) for m in info.types[0].members] == [
        ("constructor", "A"),
        ("function", "A"),
    ]


# -- build --------------------------------------------------------------------------------------


def test_compose_in_a_build_features_block_is_a_feature_without_the_compiler_plugin():
    files = mini_app(
        extra={
            "app/build.gradle.kts": d("""
                plugins { id("com.android.application") }
                android {
                    buildFeatures {
                        compose = true
                    }
                }
                """)
        }
    )
    assert "app|compose" in ids(analyse(files), "build_feature")


def test_a_dependency_records_its_group_artifact_and_the_catalog_it_came_from():
    report = analyse(hilt_project())
    dep = fact(report, "dependency:app|implementation|com.squareup.okhttp3:okhttp")
    assert dep.attributes["group"] == "com.squareup.okhttp3"
    assert dep.attributes["artifact"] == "okhttp" and dep.attributes["via"] == "literal"
    via_catalog = fact(report, "dependency:app|implementation|com.google.dagger:hilt-android")
    assert any(e.path == "gradle/libs.versions.toml" for e in via_catalog.evidence)


def test_an_unresolved_dependency_says_which_kind_of_reference_failed():
    files = mini_app(
        extra={
            "app/build.gradle.kts": d("""
                plugins { id("com.android.application") }
                dependencies {
                    implementation(libs.nothing.here)
                    implementation(Libs.NOPE)
                }
                """)
        }
    )
    report = analyse(files)
    alias = fact(report, "dependency:app|implementation|libs.nothing.here")
    constant = fact(report, "dependency:app|implementation|Libs.NOPE")
    assert "catalog" in alias.reason and "constant" in constant.reason


# -- manifest and roles -------------------------------------------------------------------------


def manifest(body: str) -> dict[str, str]:
    return {"app/src/main/AndroidManifest.xml": f"<manifest {ANDROID_NS}>{body}</manifest>"}


def test_defined_permissions_and_required_features_are_facts():
    report = analyse(
        mini_app(
            manifest(
                '<permission android:name="com.x.PERM" android:protectionLevel="signature"/>'
                '<uses-feature android:name="android.hardware.camera" android:required="false"/>'
                "<application/>"
            )
        )
    )
    assert (
        fact(report, "permission_defined:com.x.PERM").attributes["protection_level"] == "signature"
    )
    assert fact(report, "uses_feature:android.hardware.camera").attributes["required"] == "false"


def test_a_short_secret_in_a_secret_named_meta_data_is_hidden_from_the_excerpt_too():
    report = analyse(
        mini_app(
            manifest(
                '<application>\n<meta-data android:name="api.token" android:value="hunter2"/>\n</application>'
            )
        )
    )
    found = fact(report, "meta_data:api.token")
    assert found.attributes["value"] == "[REDACTED]"
    assert "hunter2" not in found.evidence[0].excerpt and "[REDACTED]" in found.evidence[0].excerpt


def test_a_role_is_inferred_when_the_parent_is_exact_but_its_own_role_is_a_guess():
    report = analyse(
        mini_app(
            Base="package com.x\nopen class BaseFragment : Fragment()\n",
            Leaf="package com.x\nclass Leaf : BaseFragment()\n",
        )
    )
    assert fact(report, "fragment:com.x.BaseFragment").status == "inferred"
    assert fact(report, "fragment:com.x.Leaf").status == "inferred"


def test_the_stronger_of_two_supertype_matches_wins_in_either_order():
    report = analyse(
        mini_app(
            M="""
            package com.x
            import androidx.fragment.app.DialogFragment
            class A : Fragment(), DialogFragment()
            class B : DialogFragment(), Fragment()
            """
        )
    )
    assert fact(report, "fragment:com.x.A").status == "confirmed"
    assert fact(report, "fragment:com.x.B").status == "confirmed"


def test_an_activity_found_only_in_source_has_no_manifest_link():
    report = analyse(
        mini_app(
            A="package com.x\nimport androidx.appcompat.app.AppCompatActivity\nclass A : AppCompatActivity()\n"
        )
    )
    assert ids(report, "activity") == ["com.x.A"]
    assert edges(report, "implemented_by") == set()


def test_a_supertype_written_with_its_package_and_one_nested_in_a_sibling_resolve():
    qualified = analyse(
        {
            **mini_app(Leaf="package com.x\nclass Leaf : com.x.base.BaseFragment()\n"),
            "app/src/main/java/com/x/base/BaseFragment.kt": (
                "package com.x.base\nimport androidx.fragment.app.Fragment\nopen class BaseFragment : Fragment()\n"
            ),
        }
    )
    assert fact(qualified, "fragment:com.x.Leaf").status == "confirmed"
    nested = analyse(
        mini_app(
            N="""
            package com.x
            class Outer {
                open class A : androidx.fragment.app.Fragment()
                class Mid { class Leaf : A() }
            }
            """
        )
    )
    leaf = fact(nested, "fragment:com.x.Outer.Mid.Leaf")
    assert leaf.status == "confirmed" and leaf.attributes["inherited_via"] == ("com.x.Outer.A",)


# -- Room, Retrofit, DI -------------------------------------------------------------------------

ROOM = "import androidx.room.Dao\nimport androidx.room.Entity\nimport androidx.room.Insert\nimport androidx.room.PrimaryKey\nimport androidx.room.Query\n"


def test_a_dao_reaches_its_entity_by_parameter_type_with_confirmation():
    report = analyse(hilt_project())
    dao, entity = (
        "room_dao:com.example.notes.data.NoteDao",
        "room_entity:com.example.notes.data.Note",
    )
    assert rel(report, "accesses", dao, entity).status == "confirmed"


def test_a_dao_that_only_names_a_table_reaches_the_entity_as_an_inference():
    files = mini_app(
        D=f"""
        package com.x
        {ROOM}
        @Entity(tableName = "notes") data class N(@PrimaryKey val id: Int)
        @Dao interface D {{ @Query("SELECT * FROM notes") fun all(): List<N> }}
        """
    )
    found = rel(analyse(files), "accesses", "room_dao:com.x.D", "room_entity:com.x.N")
    assert found.status == "inferred" and "table name" in found.note


def test_an_entity_matched_by_name_only_is_an_inferred_dao_target():
    files = mini_app(
        D=f"package com.x\n{ROOM}\n@Dao interface D {{ @Insert fun add(n: N) }}\n",
        N=f"package com.y\n{ROOM}\n@Entity class N(@PrimaryKey val id: Int)\n",
    )
    found = rel(analyse(files), "accesses", "room_dao:com.x.D", "room_entity:com.y.N")
    assert found.status == "inferred" and "name only" in found.note


def test_auto_migrations_and_the_absence_of_a_schema_location():
    files = mini_app(
        Db="""
        package com.x
        import androidx.room.Database
        import androidx.room.RoomDatabase
        @Database(entities = [], version = 2, autoMigrations = [AutoMigration(from = 1, to = 2)])
        abstract class Db : RoomDatabase()
        """,
        extra={
            "app/build.gradle.kts": d("""
                plugins { id("com.android.application") }
                ksp { arg("some.other.option", "x") }
                """)
        },
    )
    report = analyse(files)
    assert fact(report, "room_database:com.x.Db").attributes["has_auto_migrations"] is True
    assert ids(report, "room_policy") == []  # a string literal that is not room.schemaLocation


def test_a_retrofit_http_annotation_with_an_explicit_method():
    files = mini_app(
        Api="""
        package com.x
        import retrofit2.http.HTTP
        interface Api {
            @HTTP(method = "PATCH", path = "things", hasBody = true) fun patch(): Int
        }
        """
    )
    endpoint = fact(analyse(files), "http_endpoint:com.x.Api#PATCH things patch")
    assert endpoint.attributes["http_method"] == "PATCH" and endpoint.attributes["path"] == "things"


def test_a_class_with_an_unrelated_scope_annotation_is_not_a_hilt_class():
    files = mini_app(A="package com.x\n@Singleton class A\n@Inject class B\n")
    report = analyse(files)
    for kind in (
        "hilt_application",
        "hilt_android_entry",
        "hilt_viewmodel",
        "di_module",
        "hilt_worker",
    ):
        assert ids(report, kind) == [], kind


def test_a_hilt_view_model_is_marked_on_its_role_fact():
    assert (
        fact(
            analyse(hilt_project()), "viewmodel:com.example.notes.ui.NoteListViewModel"
        ).attributes["hilt"]
        is True
    )


def test_the_framework_of_a_dagger_module_is_not_confused_by_an_unrelated_koin_import():
    files = mini_app(
        M="package com.x\nimport dagger.Module\nimport org.koin.core.qualifier.named\n@Module object M\n"
    )
    report = analyse(files)
    assert fact(report, "di_module:com.x.M").attributes["framework"] == "dagger"
    assert ids(report, "koin_module") == []


def test_an_unimported_module_annotation_is_an_inferred_dagger_module():
    report = analyse(mini_app(M="package com.x\n@Module object M\n"))
    module = fact(report, "di_module:com.x.M")
    assert module.status == "inferred" and module.attributes["framework"] == "dagger"


def test_a_provided_type_is_confirmed_only_when_both_the_annotation_and_the_type_are():
    base = "package com.x\n{imports}\n@Module object M {{ @Provides fun a(): {type} = TODO() }}\n"
    imports = "import dagger.Module\nimport dagger.Provides\n"
    cases = {
        "exact": (imports, "Local", "confirmed"),  # annotation imported, type in the same package
        "type_by_name": (
            imports,
            "Foo",
            "inferred",
        ),  # annotation imported, type only matched by name
        "annotation_by_name": ("", "Local", "inferred"),  # type exact, annotation not imported
    }
    for name, (header, type_name, expected) in cases.items():
        files = mini_app(
            M=base.format(imports=header, type=type_name),
            Local="package com.x\nclass Local\n",
            Foo="package com.y\nclass Foo\n",
        )
        report = analyse(files)
        found = rel(
            report,
            "provides",
            "di_binding:com.x.M#a()",
            f"type:{'com.x' if type_name == 'Local' else 'com.y'}.{type_name}",
        )
        assert found.status == expected, name


def test_only_a_property_built_by_module_is_a_koin_module():
    files = mini_app(
        K="""
        package com.x
        import org.koin.dsl.module
        val first = listOf(1)
        val appModule = module { single { Repo() } }
        class Repo
        """
    )
    assert ids(analyse(files), "koin_module") == ["com.x#appModule"]


def test_a_koin_importing_class_gets_no_injection_edge_from_a_plain_property():
    files = mini_app(
        K="""
        package com.x
        import org.koin.core.qualifier.named
        class Repo
        class Screen { val repo: Repo = Repo() }
        """
    )
    assert edges(analyse(files), "injects") == set()


def test_a_koin_binding_matched_by_name_is_an_inferred_binding():
    files = mini_app(
        K="""
        package com.x
        import org.koin.dsl.module
        val m = module { single<Repo> { RepoImpl() } }
        """,
        R="package com.y\ninterface Repo\n",
        I="package com.z\nclass RepoImpl : com.y.Repo\n",
    )
    found = rel(analyse(files), "bound_to", "type:com.y.Repo", "type:com.z.RepoImpl")
    assert found.status == "inferred" and found.note


# -- layouts and navigation ---------------------------------------------------------------------


def res(path: str, text: str) -> dict[str, str]:
    return {f"app/src/main/res/{path}": text}


def test_a_layouts_root_is_the_tag_of_each_variant():
    extra = {
        **res("layout/a.xml", f"<LinearLayout {ANDROID_NS}/>"),
        **res("layout-land/a.xml", f"<FrameLayout {ANDROID_NS}/>"),
        **res("layout/b.xml", f"<ScrollView {ANDROID_NS}/>"),
    }
    report = analyse(mini_app(extra=extra))
    assert fact(report, "layout:app|a").attributes["root"] == "FrameLayout,LinearLayout"
    assert fact(report, "layout:app|b").attributes["root"] == "ScrollView"


def test_layout_attributes_are_recorded_only_where_the_xml_has_them():
    extra = res(
        "layout/plain.xml",
        f'<FrameLayout {ANDROID_NS}><TextView android:name="com.x.NotAFragment"/>'
        f'<foo name="bar"/><variable type="x.Y"/></FrameLayout>',
    )
    extra.update(
        res(
            "layout/host.xml",
            f'<FrameLayout {ANDROID_NS}><androidx.fragment.app.FragmentContainerView android:name="com.x.F"/>'
            "<androidx.compose.ui.platform.ComposeView/></FrameLayout>",
        )
    )
    report = analyse(mini_app(extra=extra))
    plain, host = fact(report, "layout:app|plain"), fact(report, "layout:app|host")
    assert "fragments" not in plain.attributes and "binding_variables" not in plain.attributes
    assert plain.attributes["compose_view"] is False
    assert host.attributes["fragments"] == ("com.x.F",) and host.attributes["compose_view"] is True


def test_a_widget_tag_is_not_a_custom_view_even_when_the_project_has_a_class_of_that_name():
    files = mini_app(
        Button="package com.x\nclass Button\n",
        extra=res("layout/a.xml", f"<LinearLayout {ANDROID_NS}><Button/></LinearLayout>"),
    )
    assert edges(analyse(files), "uses_view") == set()


def test_a_layout_used_from_a_top_level_function_is_credited_to_its_file():
    files = mini_app(
        Top="package com.x\nfun show() { setContentView(R.layout.a) }\n",
        extra=res("layout/a.xml", f"<FrameLayout {ANDROID_NS}/>"),
    )
    assert ("file:app/src/main/java/com/x/Top.kt", "layout:app|a") in edges(
        analyse(files), "uses_layout"
    )


def test_a_binding_imported_from_another_package_is_only_inferred():
    files = mini_app(
        U="""
        package com.x
        import com.other.databinding.ABinding
        class U { fun f() = ABinding.inflate(null) }
        """,
        extra=res("layout/a.xml", f"<FrameLayout {ANDROID_NS}/>"),
    )
    binding = fact(analyse(files), "binding:app|ABinding")
    assert binding.status == "inferred" and "another package" in binding.note


def test_a_synthetic_import_of_an_ambiguous_layout_is_inferred_for_each_candidate():
    files = {
        "settings.gradle.kts": 'include(":app", ":a", ":b")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "a/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.a" }\n',
        "b/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.b" }\n',
        "a/src/main/res/layout/shared.xml": f"<FrameLayout {ANDROID_NS}/>",
        "b/src/main/res/layout/shared.xml": f"<FrameLayout {ANDROID_NS}/>",
        "app/src/main/java/com/x/S.kt": "package com.x\nimport kotlinx.android.synthetic.main.shared.*\nclass S\n",
    }
    found = [r for r in analyse(files).relationships if r.kind == "uses_layout"]
    assert {r.target for r in found} == {"layout:a|shared", "layout:b|shared"}
    assert all(r.status == "inferred" and "several modules" in r.note for r in found)


def test_a_typed_route_is_marked_typed_and_names_its_type():
    files = mini_app(
        N="""
        package com.x
        import androidx.compose.runtime.Composable
        import androidx.navigation.compose.composable
        class Detail
        class UI
        fun androidx.navigation.NavGraphBuilder.graph() {
            composable<Detail> { }
            composable<UI> { }
        }
        """
    )
    report = analyse(files)
    assert fact(report, "compose_route:typed:Detail").attributes["route_type"] == "com.x.Detail"
    assert (
        fact(report, "compose_route:typed:UI").attributes["typed"] is True
    )  # not mistaken for a type parameter
    literal = analyse(hilt_project())
    assert fact(literal, "compose_route:add").attributes["typed"] is False


def screens_in(*names: str, package: str = "com.x.ui") -> dict[str, str]:
    body = "".join(f"@Composable fun {n}() {{}}\n" for n in names)
    return {
        "app/src/main/java/com/x/ui/Screens.kt": (
            f"package {package}\nimport androidx.compose.runtime.Composable\n{body}"
        )
    }


def test_a_destination_may_give_its_content_as_an_argument():
    files = mini_app(
        N="""
        package com.x
        import androidx.navigation.compose.composable
        fun androidx.navigation.NavGraphBuilder.graph() {
            composable("x", content = { HomeScreen() })
        }
        """,
        extra=screens_in("HomeScreen", package="com.x"),
    )
    assert ("compose_route:x", "composable:com.x#HomeScreen()") in edges(analyse(files), "renders")


def test_a_destination_showing_a_composable_matched_by_name_is_an_inferred_edge():
    files = mini_app(
        N="""
        package com.x
        import androidx.navigation.compose.composable
        fun androidx.navigation.NavGraphBuilder.graph() {
            composable("x") { Landing() }
        }
        """,
        extra=screens_in("Landing"),  # not named like a screen: only the destination makes it one
    )
    report = analyse(files)
    found = rel(report, "renders", "compose_route:x", "composable:com.x.ui#Landing()")
    assert found.status == "inferred" and "name only" in found.note
    screen = fact(report, "compose_screen:com.x.ui#Landing()")
    assert screen.status == "inferred" and "name only" in screen.note


def test_a_destination_records_at_most_three_of_the_composables_it_calls():
    files = mini_app(
        N="""
        package com.x
        import androidx.navigation.compose.composable
        fun androidx.navigation.NavGraphBuilder.graph() {
            composable("x") { A(); B(); C(); D() }
        }
        """,
        extra=screens_in("A", "B", "C", "D", package="com.x"),
    )
    assert len([r for r in analyse(files).relationships if r.kind == "renders"]) == 3


def nav_xml(name: str, body: str, graph_id: str) -> dict[str, str]:
    return res(
        f"navigation/{name}.xml",
        f'<navigation {ANDROID_NS} {APP_NS} android:id="@+id/{graph_id}">{body}</navigation>',
    )


def test_an_action_to_an_id_that_two_graphs_define_is_not_guessed():
    extra = {
        **nav_xml("g1", '<fragment android:id="@+id/home" android:name="com.x.A"/>', "g1"),
        **nav_xml("g2", '<fragment android:id="@+id/home" android:name="com.x.B"/>', "g2"),
        **nav_xml(
            "g3",
            '<fragment android:id="@+id/other" android:name="com.x.C">'
            '<action android:id="@+id/go" app:destination="@id/home"/></fragment>',
            "g3",
        ),
    }
    assert edges(analyse(mini_app(extra=extra)), "navigates_to") == set()


def test_graph_edges_contain_destinations_and_nested_graphs_start_where_they_say():
    extra = nav_xml(
        "main",
        '<fragment android:id="@+id/a" android:name="com.x.A"/>'
        '<navigation android:id="@+id/inner" app:startDestination="@id/b">'
        '<fragment android:id="@+id/b" android:name="com.x.B"/></navigation>',
        "main",
    )
    report = analyse(mini_app(extra=extra))
    contains = edges(report, "contains")
    assert ("nav_graph:app|main", "nav_destination:app|main|a") in contains
    assert ("nav_nested_graph:app|main|inner", "nav_destination:app|main|b") in contains
    assert ("nav_nested_graph:app|main|inner", "nav_destination:app|main|b") in edges(
        report, "starts_at"
    )


def test_composables_found_by_wildcard_import_preview_variants_and_setcontent_arguments():
    files = mini_app(
        A="""
        package com.x
        import androidx.activity.ComponentActivity
        import androidx.activity.compose.setContent
        import com.x.ui.*
        class A : ComponentActivity() {
            fun f() { setContent(null) { Home() } }
        }
        """,
        extra={
            "app/src/main/java/com/x/ui/Home.kt": d("""
                package com.x.ui
                import androidx.compose.runtime.Composable
                @Composable fun Home() {}
                @PreviewLightDark @Composable fun HomeScreen() {}
                """)
        },
    )
    report = analyse(files)
    assert (
        rel(report, "hosts_content", "type:com.x.A", "composable:com.x.ui#Home()").status
        == "confirmed"
    )
    preview = fact(report, "composable:com.x.ui#HomeScreen()")
    assert preview.attributes["preview"] is True
    assert ids(report, "compose_screen") == ["com.x.ui#Home()"]  # the preview is not a screen


def test_content_shown_by_setcontent_and_matched_by_name_is_inferred():
    files = mini_app(
        A="""
        package com.x
        import androidx.activity.ComponentActivity
        class A : ComponentActivity() { fun f() { setContent { Home() } } }
        """,
        extra=screens_in("Home"),
    )
    found = rel(analyse(files), "hosts_content", "type:com.x.A", "composable:com.x.ui#Home()")
    assert found.status == "inferred" and "name only" in found.note


# -- symbols ------------------------------------------------------------------------------------


def test_file_facts_say_what_kind_of_file_they_are_and_members_list_their_annotations():
    files = mini_app(
        A="package com.x\nclass A { @Foo fun f() {}\n fun g() {} }\n",
        B_java="package com.x;\npublic class B {}\n",
    )
    report = analyse(files)
    assert fact(report, "file:app/src/main/java/com/x/A.kt").attributes["file_kind"] == "kotlin"
    assert fact(report, "file:app/src/main/java/com/x/B.java").attributes["file_kind"] == "java"
    assert fact(report, "member:com.x.A#f()").attributes["annotations"] == ("Foo",)
    assert "annotations" not in fact(report, "member:com.x.A#g()").attributes


def test_the_java_xml_fixture_still_has_no_unexplained_unknowns():
    report = analyse(java_xml_project())
    # nothing is unreadable; a ``convention`` can still be unknown because there is too little to
    # describe (M2.8): that is a different reason, and it always says how little
    unknown = [f for f in report.facts if f.status == "unknown"]
    assert {f.kind for f in unknown} <= {"convention"}
    assert all("at least" in (f.reason or "") for f in unknown)


# -- survivors of the second mutation round -------------------------------------------------------


def test_the_anchor_is_the_end_of_the_file_when_nothing_follows_an_annotation():
    text = "class A\n@Foo"
    view = SrcView(SourceFile("A.kt", text))
    assert declaration_anchor(view, len(text)) == len(text)
    [found] = extract_annotations(view)
    assert found.target == len(text)
    assert declaration_anchor(SrcView(SourceFile("A.kt", "@ class X")), 0) == 0


def test_the_manifest_is_a_file_fact_and_a_broken_source_file_is_a_limitation():
    manifest_fact = fact(analyse(hilt_project()), "file:app/src/main/AndroidManifest.xml")
    assert manifest_fact.attributes["file_kind"] == "manifest"
    broken = analyse(mini_app(Broken="package com.x\nclass Broken {\n    fun f() {\n"))
    limits = [m for m in broken.limitations if m.code == "malformed_source"]
    assert [m.scope for m in limits] == ["app/src/main/java/com/x/Broken.kt"]
    assert limits[0].affects_completeness and broken.complete is False


def test_every_role_fact_is_tied_to_its_type_and_containers_to_what_they_hold():
    report = analyse(hilt_project())
    roles = edges(report, "role_of")
    data = "com.example.notes.data"
    for kind, fqn in (
        ("room_dao", f"{data}.NoteDao"),
        ("room_entity", f"{data}.Note"),
        ("room_database", f"{data}.NotesDatabase"),
        ("retrofit_service", f"{data}.NotesApi"),
        ("di_injectable", f"{data}.NoteRepositoryImpl"),
        ("di_module", "com.example.notes.di.RepositoryModule"),
        ("viewmodel", "com.example.notes.ui.NoteListViewModel"),
    ):
        assert (f"{kind}:{fqn}", f"type:{fqn}") in roles, kind
    assert (
        f"retrofit_service:{data}.NotesApi",
        f"http_endpoint:{data}.NotesApi#GET notes notes",
    ) in edges(report, "declares_endpoint")
    module = "di_module:com.example.notes.di.RepositoryModule"
    binding = "di_binding:com.example.notes.di.RepositoryModule#bindRepository(NoteRepositoryImpl)"
    assert (module, binding) in edges(report, "declares_binding")


def test_a_database_reaches_entities_and_daos_matched_only_by_name_as_inferences():
    files = mini_app(
        Db="""
        package com.x
        import androidx.room.Database
        import androidx.room.RoomDatabase
        @Database(entities = [N::class], version = 1)
        abstract class Db : RoomDatabase() { abstract fun dao(): D }
        """,
        N="package com.y\nimport androidx.room.Entity\nimport androidx.room.PrimaryKey\n@Entity class N(@PrimaryKey val id: Int)\n",
        D="package com.z\nimport androidx.room.Dao\n@Dao interface D\n",
    )
    report = analyse(files)
    entity = rel(report, "contains_entity", "room_database:com.x.Db", "room_entity:com.y.N")
    dao = rel(report, "exposes_dao", "room_database:com.x.Db", "room_dao:com.z.D")
    assert entity.status == dao.status == "inferred"
    assert "name only" in entity.note and "name only" in dao.note


def test_a_retrofit_model_matched_only_by_name_is_an_inferred_edge():
    files = mini_app(
        Api='package com.x\nimport retrofit2.http.GET\ninterface Api { @GET("i") fun item(): Item }\n',
        Item="package com.y\nclass Item\n",
    )
    report = analyse(files)
    found = rel(report, "uses_model", "http_endpoint:com.x.Api#GET i item", "type:com.y.Item")
    assert found.status == "inferred" and "name only" in found.note


def test_a_view_model_matched_only_by_name_is_an_inferred_edge_from_properties_and_bodies():
    files = mini_app(
        Vm="package com.y\nimport androidx.lifecycle.ViewModel\nclass HomeVm : ViewModel()\n",
        U="""
        package com.x
        import androidx.compose.runtime.Composable
        import androidx.fragment.app.Fragment
        import androidx.fragment.app.viewModels
        class F : Fragment() { private val vm: HomeVm by viewModels() }
        @Composable fun Screen() { val vm = hiltViewModel<HomeVm>() }
        """,
    )
    report = analyse(files)
    for source in ("type:com.x.F", "composable:com.x#Screen()"):
        found = rel(report, "uses_viewmodel", source, "viewmodel:com.y.HomeVm")
        assert found.status == "inferred" and "name only" in found.note, source


def test_an_include_of_a_layout_that_exists_in_several_modules_is_inferred():
    files = {
        "settings.gradle.kts": 'include(":app", ":a", ":b")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "a/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.a" }\n',
        "b/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.b" }\n',
        "a/src/main/res/layout/part.xml": f"<FrameLayout {ANDROID_NS}/>",
        "b/src/main/res/layout/part.xml": f"<FrameLayout {ANDROID_NS}/>",
        "app/src/main/res/layout/page.xml": (
            f'<LinearLayout {ANDROID_NS}><include layout="@layout/part"/></LinearLayout>'
        ),
    }
    found = [r for r in analyse(files).relationships if r.kind == "includes"]
    assert {r.target for r in found} == {"layout:a|part", "layout:b|part"}
    assert all(r.status == "inferred" and "several modules" in r.note for r in found)


def test_merged_relationships_follow_the_same_rules_as_merged_facts():
    s = FactStore(AnalysisConfig())
    ev = Evidence(path="a.kt", line=1)
    a = s.fact("x", "a", basis="source", evidence=[ev])
    b = s.fact("x", "b", basis="source", evidence=[ev])
    s.relate(a, "uses", b, basis="source", evidence=[ev])
    s.relate(a, "uses", b, basis="heuristic", status="inferred", note="a guess")
    edge = s.freeze(AnalysisReport(complete=True).stats).relationships[0]
    assert edge.status == "confirmed" and edge.note is None


# -- survivors of the third mutation round --------------------------------------------------------


def test_the_value_objects_of_the_analysis_stay_immutable():
    from androai_codegen.analysis.annotations import Annotation, Arg
    from androai_codegen.analysis.components import RoleHit
    from androai_codegen.analysis.members import Member, Param, SuperRef, TypeInfo
    from androai_codegen.analysis.resolve import Resolution
    from androai_codegen.analysis.screens import Composable

    for cls in (
        Annotation,
        Arg,
        RoleHit,
        Member,
        Param,
        SuperRef,
        TypeInfo,
        Resolution,
        Composable,
    ):
        assert cls.__dataclass_params__.frozen, cls.__name__  # type: ignore[attr-defined]


def test_equal_strength_statements_merge_to_the_same_fact_whatever_the_order():
    ev = Evidence(path="a.kt", line=1)
    pieces = [
        {"basis": "source", "status": "inferred", "note": "zeta guess"},
        {"basis": "gradle", "status": "inferred", "note": "alpha guess"},
        {"basis": "manifest", "status": "inferred", "note": "mid guess"},
    ]
    outcomes = set()
    for order in ([0, 1, 2], [2, 1, 0], [1, 2, 0], [1, 0, 2]):
        s = FactStore(AnalysisConfig())
        for i in order:
            s.fact("x", "one", evidence=[ev], **pieces[i])
        frozen = s.freeze(AnalysisReport(complete=True).stats).facts[0]
        outcomes.add((frozen.basis, frozen.note))
    assert outcomes == {("gradle", "alpha guess")}


def test_annotate_adds_evidence_without_changing_status():
    s = FactStore(AnalysisConfig())
    s.fact("x", "one", basis="source", evidence=[Evidence(path="a.kt", line=1)])
    s.annotate("x:one", evidence=[Evidence(path="b.kt", line=2)])
    frozen = s.freeze(AnalysisReport(complete=True).stats).facts[0]
    assert [e.path for e in frozen.evidence] == ["a.kt", "b.kt"] and frozen.status == "confirmed"


def test_xml_evidence_reads_the_first_line_and_ignores_missing_ones():
    from androai_codegen.analysis.text import xml_evidence

    assert xml_evidence("<a/>\n<b/>", "x.xml", 1).excerpt == "<a/>"
    assert xml_evidence("<a/>\n<b/>", "x.xml", 2).excerpt == "<b/>"
    assert xml_evidence("<a/>", "x.xml", 0).excerpt == ""
    assert xml_evidence("<a/>", "x.xml", 3).excerpt == ""
    assert xml_evidence("<a/>", "x.xml", None).excerpt == ""


def test_limitations_for_a_fact_include_its_modules_and_files_but_not_other_modules():
    from analysis_fixtures import convention_project

    from androai_codegen.analysis import analyse_mapping

    index = analyse_mapping(convention_project()).index()
    app = index.explain("sdk_level:app|minSdk")["limitations"]
    assert {m.scope for m in app if m.code == "convention_plugin_dependencies_unknown"} == {"app"}
    home = index.explain("sdk_level:feature/home|minSdk")["limitations"]
    assert {m.scope for m in home if m.code == "convention_plugin_dependencies_unknown"} == {
        "feature/home"
    }


def test_agp_nine_compile_sdk_records_its_minor_level_and_only_for_compile_sdk():
    files = mini_app(
        extra={
            "app/build.gradle.kts": d("""
                plugins { id("com.android.application") }
                android {
                    compileSdk {
                        version = release(37) { minorApiLevel = 1 }
                    }
                    defaultConfig { minSdk = 24 }
                }
                """)
        }
    )
    report = analyse(files)
    compile_sdk = fact(report, "sdk_level:app|compileSdk")
    assert compile_sdk.attributes["value"] == 37 and compile_sdk.attributes["minor"] == 1
    assert "minor" not in fact(report, "sdk_level:app|minSdk").attributes


def test_gradle_evidence_quotes_the_line_it_came_from():
    report = analyse(hilt_project())
    dep = fact(report, "dependency:app|implementation|com.squareup.okhttp3:okhttp")
    assert dep.evidence[0].excerpt == 'implementation("com.squareup.okhttp3:okhttp:4.12.0")'
    assert dep.evidence[0].line is not None


def test_manifest_details_categories_nameless_meta_data_and_tools_context():
    report = analyse(hilt_project())
    categories = fact(report, "activity:com.example.notes.MainActivity").attributes["categories"]
    assert categories == ("android.intent.category.LAUNCHER",)
    nameless = analyse(
        mini_app(manifest('<application><meta-data android:value="x"/></application>'))
    )
    assert ids(nameless, "meta_data") == []
    layout = fact(analyse(java_xml_project()), "layout:app|activity_main")
    assert layout.attributes["tools_context"] == ".MainActivity"


def test_room_entities_record_foreign_keys_and_indices_only_when_declared():
    files = mini_app(
        E="""
        package com.x
        import androidx.room.Entity
        import androidx.room.ForeignKey
        import androidx.room.Index
        import androidx.room.PrimaryKey
        @Entity(
            foreignKeys = [ForeignKey(entity = Parent::class, parentColumns = ["id"], childColumns = ["p"])],
            indices = [Index("p")],
        )
        class Child(@PrimaryKey val id: Int, val p: Int)
        @Entity class Parent(@PrimaryKey val id: Int)
        """
    )
    report = analyse(files)
    child = fact(report, "room_entity:com.x.Child").attributes
    assert child["has_foreign_keys"] is True and child["has_indices"] is True
    parent = fact(report, "room_entity:com.x.Parent").attributes
    assert "has_foreign_keys" not in parent and "has_indices" not in parent


def test_a_shared_preferences_call_without_arguments_is_the_default_file():
    found = analyse(mini_app(P="package com.x\nfun f() = getSharedPreferences()\n"))
    assert ids(found, "shared_preferences") == ["(default)"]


def test_module_framework_follows_the_imports_when_the_annotation_does_not_say():
    files = mini_app(
        K="package com.x\nimport org.koin.android.ext.koin.androidContext\n@Module class K\n"
    )
    module = fact(analyse(files), "koin_module:com.x.K")
    assert module.status == "inferred"


def test_a_binding_is_confirmed_only_when_both_ends_of_it_are():
    files = mini_app(
        M="""
        package com.x
        import dagger.Binds
        import dagger.Module
        interface Api
        @Module abstract class M { @Binds abstract fun b(i: Impl): Api }
        """,
        Impl="package com.y\nclass Impl : com.x.Api\n",
    )
    found = rel(analyse(files), "bound_to", "type:com.x.Api", "type:com.y.Impl")
    assert found.status == "inferred" and found.note


def test_a_koin_definition_is_confirmed_only_when_both_ends_of_it_are():
    files = mini_app(
        K="""
        package com.x
        import org.koin.dsl.module
        interface Repo
        val m = module { single<Repo> { RepoImpl() } }
        """,
        I="package com.y\nclass RepoImpl : com.x.Repo\n",
    )
    found = rel(analyse(files), "bound_to", "type:com.x.Repo", "type:com.y.RepoImpl")
    assert found.status == "inferred"


def test_a_layouts_navigation_graph_comes_from_that_modules_layout_only():
    files = {
        "settings.gradle.kts": 'include(":app", ":a", ":b")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "a/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.a" }\n',
        "b/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.b" }\n',
        "app/src/main/res/navigation/g.xml": (
            f'<navigation {ANDROID_NS} {APP_NS} android:id="@+id/g"/>'
        ),
        "a/src/main/res/layout/main.xml": (
            f"<FrameLayout {ANDROID_NS} {APP_NS}>"
            '<androidx.fragment.app.FragmentContainerView app:navGraph="@navigation/g"/></FrameLayout>'
        ),
        "b/src/main/res/layout/main.xml": f"<FrameLayout {ANDROID_NS}/>",
    }
    found = edges(analyse(files), "uses_nav_graph")
    assert ("layout:a|main", "nav_graph:app|g") in found
    assert ("layout:b|main", "nav_graph:app|g") not in found


def test_a_view_tag_with_a_class_attribute_is_a_custom_view():
    files = mini_app(
        extra={
            "app/src/main/res/layout/a.xml": f'<FrameLayout {ANDROID_NS}><view class="com.x.MyView"/></FrameLayout>'
        }
    )
    assert fact(analyse(files), "layout:app|a").attributes["custom_views"] == ("com.x.MyView",)


def test_an_action_may_target_the_navigation_graph_itself():
    extra = nav_xml(
        "main",
        '<fragment android:id="@+id/a" android:name="com.x.A">'
        '<action android:id="@+id/up" app:destination="@id/main"/></fragment>',
        "main",
    )
    found = edges(analyse(mini_app(extra=extra)), "navigates_to")
    assert ("nav_destination:app|main|a", "nav_graph:app|main") in found


def test_composables_declared_inside_an_object_are_found():
    files = mini_app(
        S="""
        package com.x
        import androidx.compose.runtime.Composable
        object Screens {
            @Composable fun Inner() {}
        }
        """
    )
    assert ids(analyse(files), "composable") == ["com.x.Screens#Inner()"]


def test_member_and_type_attributes_record_params_companions_delegates_and_enum_entries():
    files = mini_app(
        S="""
        package com.x
        enum class Mode { ON, OFF }
        class A {
            val lazyOne by lazy { 1 }
            val plain = 2
            fun f(x: Int, y: String) {}
            companion object { fun make() = 1 }
        }
        """
    )
    report = analyse(files)
    assert fact(report, "type:com.x.Mode").attributes["enum_entries"] == ("ON", "OFF")
    assert fact(report, "member:com.x.A#f(Int,String)").attributes["params"] == (
        "x: Int",
        "y: String",
    )
    assert fact(report, "member:com.x.A#lazyOne").attributes["delegated"] is True
    assert "delegated" not in fact(report, "member:com.x.A#plain").attributes
    assert "params" not in fact(report, "member:com.x.A#plain").attributes
    assert fact(report, "member:com.x.A#make()").attributes["companion"] is True
    assert "companion" not in fact(report, "member:com.x.A#f(Int,String)").attributes


def test_caps_and_defaults_hold_at_their_exact_boundaries(tmp_path: Path):
    root = write_tree(
        tmp_path / "p", {f"app/f{n}.kt": f"package p\nclass C{n}\n" for n in range(4)}
    )
    files, audit = read_project(Workspace(root), config=AnalysisConfig(max_files=2))
    assert sorted(files.texts) == ["app/f0.kt", "app/f1.kt"] and audit.capped_files
    ten = "package p\n" + "".join(f"class C{i}\n" for i in range(10))
    exact = parse_file(SourceFile("A.kt", ten), AnalysisConfig(max_types_per_file=10))
    assert len(exact.types) == 10 and "too_many_types" not in exact.issues
    Fact(  # a 400-character attribute is the longest allowed
        id="x:a",
        kind="x",
        subject="a",
        status="confirmed",
        basis="source",
        evidence=(Evidence(path="a.kt"),),
        attributes={"k": "y" * 400},
    )
    from androai_codegen.analysis import Limitation

    assert Limitation(code="file_too_large", scope="a.kt", message="m").affects_completeness is True


def test_a_byte_order_mark_is_ignored_for_in_memory_projects_too():
    report = analyse(mini_app(A="﻿package com.x\nclass A\n"))
    assert "type:com.x.A" in {f.id for f in report.facts}


def test_the_last_line_without_a_newline_and_the_first_line_have_excerpts():
    lines = LineText("a\nb", "a\nb")
    assert lines.excerpt_at_offset(2) == "b" and lines.excerpt_at_line(1) == "a"
    assert lines.excerpt_at_line(2) == "b" and lines.excerpt_at_line(3) == ""


def test_a_provides_method_with_a_parameter_is_not_a_binds():
    files = mini_app(
        M="""
        package com.x
        import dagger.Module
        import dagger.Provides
        interface Api
        class Impl : Api
        @Module object M { @Provides fun api(impl: Impl): Api = impl }
        """
    )
    assert edges(analyse(files), "bound_to") == set()


def test_a_layout_that_exists_in_one_other_module_is_the_one_a_reference_means():
    files = {
        "settings.gradle.kts": 'include(":app", ":lib")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "lib/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.lib" }\n',
        "lib/src/main/res/layout/only_here.xml": f"<FrameLayout {ANDROID_NS}/>",
        "app/src/main/java/com/x/U.kt": "package com.x\nclass U { fun f() { setContentView(R.layout.only_here) } }\n",
    }
    found = rel(analyse(files), "uses_layout", "type:com.x.U", "layout:lib|only_here")
    assert found.status == "confirmed"


def test_a_binding_used_from_a_top_level_function_is_credited_to_its_file():
    files = mini_app(
        U="package com.x\nimport com.x.databinding.ABinding\nfun f() = ABinding.inflate(null)\n",
        extra=res("layout/a.xml", f"<FrameLayout {ANDROID_NS}/>"),
    )
    uses = edges(analyse(files), "uses_binding")
    assert ("file:app/src/main/java/com/x/U.kt", "binding:app|ABinding") in uses


def test_reachability_follows_edges_to_the_depth_asked_for():
    index = analyse(hilt_project()).index()
    target = "composable:com.example.notes.ui#AddNoteScreen()"
    assert target not in index.reachable(
        "compose_route:list", ["navigates_to", "renders"], max_depth=1
    )
    assert target in index.reachable("compose_route:list", ["navigates_to", "renders"], max_depth=2)


def test_an_activity_that_sets_compose_content_says_so():
    activity = fact(analyse(hilt_project()), "activity:com.example.notes.MainActivity")
    assert activity.attributes["ui"] == "compose" and "ui:compose" in activity.tags


def test_merged_edges_of_equal_strength_do_not_depend_on_the_order():
    ev = Evidence(path="a.kt", line=1)
    outcomes = set()
    for order in ((0, 1), (1, 0)):
        s = FactStore(AnalysisConfig())
        a = s.fact("x", "a", basis="source", evidence=[ev])
        b = s.fact("x", "b", basis="source", evidence=[ev])
        pieces = [("source", "zeta"), ("gradle", "alpha")]
        for i in order:
            basis, note = pieces[i]
            s.relate(a, "uses", b, basis=basis, status="inferred", note=note, evidence=[ev])
        edge = s.freeze(AnalysisReport(complete=True).stats).relationships[0]
        outcomes.add((edge.basis, edge.note))
    assert outcomes == {("gradle", "alpha")}


def test_type_and_member_facts_record_constructor_parameters_and_declared_types():
    files = mini_app(
        S='package com.x\nclass A(val id: Int, name: String) { val label: String = "" }\n'
    )
    report = analyse(files)
    assert fact(report, "type:com.x.A").attributes["constructor_params"] == (
        "id: Int",
        "name: String",
    )
    assert fact(report, "member:com.x.A#label").attributes["type"] == "String"


def test_a_deadline_that_has_passed_leaves_no_facts_at_all():
    stopped = analyse(hilt_project(), config=AnalysisConfig(deadline_seconds=0.0))
    assert stopped.facts == () and stopped.complete is False  # every step saw the budget spent


def test_a_valid_version_catalog_is_a_fact_with_its_counts():
    catalog = fact(analyse(hilt_project()), "version_catalog:gradle/libs.versions.toml")
    assert catalog.status == "confirmed"
    assert (catalog.attributes["libraries"], catalog.attributes["plugins"]) == (12, 6)


def test_a_library_is_recognised_from_a_wildcard_import_when_the_build_does_not_say():
    files = mini_app(R="package com.x\nimport androidx.room.*\nclass R\n")
    room = fact(analyse(files), "technology:room")
    assert room.basis == "source" and room.attributes["category"] == "storage"


def test_an_activity_is_a_launcher_only_with_both_the_main_action_and_the_launcher_category():
    split = analyse(
        mini_app(
            manifest(
                '<application><activity android:name=".A">'
                '<intent-filter><action android:name="android.intent.action.MAIN"/></intent-filter>'
                '<intent-filter><category android:name="android.intent.category.LAUNCHER"/></intent-filter>'
                "</activity></application>"
            )
        )
    )
    assert fact(split, "activity:com.x.A").attributes["launcher"] is False
    assert "launcher" not in fact(split, "activity:com.x.A").tags


def test_a_database_version_written_as_a_constant_is_not_read_as_a_number():
    files = mini_app(
        Db="""
        package com.x
        import androidx.room.Database
        import androidx.room.RoomDatabase
        const val DB_VERSION = 3
        @Database(entities = [], version = DB_VERSION)
        abstract class Db : RoomDatabase()
        """
    )
    assert "version" not in fact(analyse(files), "room_database:com.x.Db").attributes


def test_injectables_record_their_scopes_only_when_they_have_them():
    files = mini_app(
        R="""
        package com.x
        import dagger.hilt.android.scopes.ViewModelScoped
        import javax.inject.Inject
        import javax.inject.Singleton
        @Singleton class Scoped @Inject constructor()
        class Plain @Inject constructor()
        """
    )
    report = analyse(files)
    assert fact(report, "di_injectable:com.x.Scoped").attributes["scopes"] == ("Singleton",)
    assert "scopes" not in fact(report, "di_injectable:com.x.Plain").attributes


def test_a_binding_between_exact_types_is_still_only_inferred_when_its_annotations_are():
    files = mini_app(
        M="""
        package com.x
        interface Api
        class Impl : Api
        @Module abstract class M { @Binds abstract fun b(i: Impl): Api }
        """
    )
    found = rel(analyse(files), "bound_to", "type:com.x.Api", "type:com.x.Impl")
    assert found.status == "inferred"


def test_a_binding_class_is_tied_to_the_layout_of_the_module_that_uses_it():
    files = {
        "settings.gradle.kts": 'include(":app", ":lib")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "lib/build.gradle.kts": 'plugins { id("com.android.library") }\nandroid { namespace = "com.lib" }\n',
        "app/src/main/res/layout/a.xml": f"<FrameLayout {ANDROID_NS}/>",
        "lib/src/main/res/layout/a.xml": f"<FrameLayout {ANDROID_NS}/>",
        "app/src/main/java/com/x/U.kt": (
            "package com.x\nimport com.x.databinding.ABinding\nclass U { fun f() = ABinding.inflate(null) }\n"
        ),
    }
    assert ids(analyse(files), "binding") == ["app|ABinding"]


def test_constructors_and_functions_carry_no_property_flags():
    files = mini_app(S="package com.x\nclass A { constructor(x: Int)\n fun f() {} }\n")
    report = analyse(files)
    for member in ("member:com.x.A#A(Int)", "member:com.x.A#f()"):
        attrs = fact(report, member).attributes
        assert "delegated" not in attrs and "companion" not in attrs, member


def test_the_innermost_type_around_an_offset_is_found():
    text = "package p\nclass A {\n    class B {\n        val x = 1\n    }\n}\n"
    info = parse_file(SourceFile("A.kt", text), AnalysisConfig())
    assert info.type_at(text.index("val x")).fqn == "p.A.B"
    assert info.type_at(text.index("class B")).fqn == "p.A"


def test_a_navigate_call_in_a_plain_function_is_credited_to_that_function():
    files = mini_app(
        N="""
        package com.x
        import androidx.navigation.NavController
        import androidx.navigation.compose.composable
        fun androidx.navigation.NavGraphBuilder.graph() { composable("add") { } }
        class Flow { fun go(c: NavController) { c.navigate("add") } }
        """
    )
    found = edges(analyse(files), "navigates_to")
    assert ("member:com.x.Flow#go(NavController)", "compose_route:add") in found


def test_a_type_that_could_not_be_read_is_described_by_its_unknown_members_fact():
    broken = analyse(mini_app(B="package com.x\nclass B {\n    fun f() {\n"))
    assert ("type_members:com.x.B", "type:com.x.B") in edges(broken, "describes")
    assert fact(broken, "type_members:com.x.B").status == "unknown"


def test_a_type_written_with_an_unclosed_parenthesis_is_survived():
    info = parse_file(SourceFile("A.kt", "package p\nval x: (Int\nval y = 1\n"), AnalysisConfig())
    # past an unbalanced bracket nothing can be trusted, so the scan stops there: and says why
    assert [m.name for m in info.top_level] == ["x"]
    assert "brackets" in info.issues


def test_a_type_without_a_body_does_not_swallow_the_declarations_after_it():
    """``interface Repo`` followed by a newline once read the next lines as part of its header, so
    members after it were lost and it could adopt the next class's body."""
    config = AnalysisConfig()
    text = (
        "package p\n"
        "interface Repo\n"
        "val first = 1\n"
        "class Plain\n"
        "object Single\n"
        "class Real {\n"
        "    fun kept() {}\n"
        "}\n"
        "val last = 2\n"
    )
    info = parse_file(SourceFile("A.kt", text), config)
    by_name = {t.name: t for t in info.types}
    assert [m.name for m in info.top_level] == ["first", "last"]
    for name in ("Repo", "Plain", "Single"):
        assert by_name[name].members == () and by_name[name].body is None, name
    assert [m.name for m in by_name["Real"].members] == ["kept"]


def test_a_module_property_after_a_body_less_interface_is_still_a_koin_module():
    files = mini_app(
        K="""
        package com.x
        import org.koin.dsl.module
        interface Repo
        val m = module { single<Repo> { Local() } }
        class Local : Repo
        """
    )
    assert ids(analyse(files), "koin_module") == ["com.x#m"]


def test_a_property_mentioning_by_after_its_name_with_a_type_and_a_class_body_after_a_type_alias():
    info = parse_file(
        SourceFile("A.kt", "package p\ntypealias N = Int\nfun f() {}\nval after = 1\n"),
        AnalysisConfig(),
    )
    assert [m.name for m in info.top_level] == ["f", "after"]


def test_unterminated_headers_and_types_at_the_end_of_a_file_are_survived():
    config = AnalysisConfig()
    eof = parse_file(SourceFile("A.kt", "package p\nclass A @Foo"), config)
    assert [t.name for t in eof.types] == ["A"]
    open_args = parse_file(SourceFile("A.kt", "package p\nclass A @Foo(1, 2 {\n}\n"), config)
    assert open_args.types[0].exact is False
    tail = parse_file(SourceFile("A.kt", "package p\nval x: Int"), config)
    assert [(m.name, m.type_text) for m in tail.top_level] == [("x", "Int")]
    open_generic = parse_file(SourceFile("A.kt", "package p\nval x: Foo<Bar\nval y = 1\n"), config)
    assert [(m.name, m.type_text) for m in open_generic.top_level] == [("x", "Foo"), ("y", "")]
    one_line = parse_file(SourceFile("A.kt", "package p\nclass A { fun f(): List<Int> }\n"), config)
    assert one_line.types[0].members[0].type_text == "List<Int>"


def test_java_initialisers_with_bodies_and_broken_brackets_do_not_invent_members():
    config = AnalysisConfig()
    anonymous = parse_file(
        SourceFile(
            "A.java",
            "package p;\nclass A { Runnable r = new Runnable() { public void run() { int hidden; } }; int after; }\n",
        ),
        config,
    )
    assert [m.name for m in anonymous.types[0].members] == ["r", "after"]
    parse_file(
        SourceFile("A.java", "package p;\nclass A { int x = (1; int y; }\n"), config
    )  # no error
    plain = parse_file(
        SourceFile("A.java", "package p;\nclass A { Map<String, Integer> m; private int n; }\n"),
        config,
    )
    assert [(m.name, m.visibility) for m in plain.types[0].members] == [
        ("m", "package"),
        ("n", "private"),
    ]
