"""M2.2: Kotlin and Java types and their members, read without a compiler."""

from __future__ import annotations

from textwrap import dedent

from androai_codegen.analysis.config import AnalysisConfig
from androai_codegen.analysis.members import FileInfo, TypeInfo, parse_file
from androai_codegen.review.source import SourceFile


def parse(text: str, path: str = "A.kt") -> FileInfo:
    return parse_file(SourceFile(path, dedent(text).lstrip("\n")), AnalysisConfig())


def types(info: FileInfo) -> dict[str, TypeInfo]:
    return {t.fqn: t for t in info.types}


def member_names(decl: TypeInfo) -> list[str]:
    return [m.signature for m in decl.members]


# -- Kotlin: types ------------------------------------------------------------------------------


def test_kotlin_classes_interfaces_objects_enums_and_nesting_get_correct_fqns():
    info = parse("""
        package p

        class Outer {
            class Inner {
                class Deep
            }
            object Registry
            interface Listener
            enum class Mode { A, B }
        }
        interface Top
        object Single
        """)
    assert sorted(types(info)) == [
        "p.Outer",
        "p.Outer.Inner",
        "p.Outer.Inner.Deep",
        "p.Outer.Listener",
        "p.Outer.Mode",
        "p.Outer.Registry",
        "p.Single",
        "p.Top",
    ]
    assert types(info)["p.Outer.Mode"].kind == "enum"
    assert types(info)["p.Outer.Listener"].kind == "interface"


def test_a_class_declared_inside_a_function_is_local_and_not_reported():
    info = parse("""
        package p
        class A {
            fun f() {
                class Hidden { fun nope() {} }
                val o = object : Runnable { override fun run() {} }
            }
        }
        fun top() { class AlsoHidden }
        """)
    assert list(types(info)) == ["p.A"]
    assert member_names(types(info)["p.A"]) == ["f()"]
    assert info.top_level and [m.name for m in info.top_level] == ["top"]


def test_kotlin_supertypes_with_generics_constructor_calls_delegation_and_where():
    info = parse("""
        package p
        class A<T : Any>(val x: Int) : Base<T>(x), Iface<Map<String, Int>>, Other by delegate
        class B : Comparable<B> where B : Any
        class C : a.b.Qualified()
        """)
    found = types(info)
    assert [s.written for s in found["p.A"].supertypes] == ["Base", "Iface", "Other"]
    assert [s.written for s in found["p.B"].supertypes] == ["Comparable"]
    assert [s.written for s in found["p.C"].supertypes] == ["a.b.Qualified"]
    assert found["p.C"].supertypes[0].simple == "Qualified"


def test_kotlin_modifiers_visibility_and_abstractness():
    info = parse("""
        package p
        abstract class A
        private class B
        internal data class C(val a: Int)
        sealed interface D
        annotation class E
        open class F
        """)
    found = types(info)
    assert found["p.A"].is_abstract and "abstract" in found["p.A"].modifiers
    assert found["p.B"].visibility == "private"
    assert found["p.C"].visibility == "internal"
    assert found["p.D"].is_abstract
    assert found["p.E"].kind == "annotation"
    assert found["p.F"].visibility == "public" and not found["p.F"].is_abstract


def test_typealiases_and_fun_interfaces_are_types():
    info = parse("""
        package p
        typealias Names = List<String>
        fun interface Callback { fun call(): Int }
        """)
    found = types(info)
    assert found["p.Names"].kind == "typealias"
    assert found["p.Callback"].kind == "interface"
    assert member_names(found["p.Callback"]) == ["call()"]


# -- Kotlin: constructors and members -----------------------------------------------------------


def test_primary_constructor_parameters_with_annotations_and_the_inject_marker():
    info = parse("""
        package p
        class VM @Inject constructor(
            private val repo: Repo,
            @Named("io") val dispatcher: CoroutineDispatcher,
            plain: Map<String, Int> = emptyMap(),
            vararg rest: String,
            content: @Composable () -> Unit,
        ) : ViewModel()
        """)
    vm = types(info)["p.VM"]
    assert [a.simple for a in vm.constructor_annotations] == ["Inject"]
    params = {p.name: p for p in vm.constructor_params}
    assert list(params) == ["repo", "dispatcher", "plain", "rest", "content"]
    assert params["repo"].kind == "val" and params["repo"].type_text == "Repo"
    assert [a.simple for a in params["dispatcher"].annotations] == ["Named"]
    assert params["plain"].kind is None and params["plain"].type_simple == "Map"
    assert params["plain"].default_call == "emptyMap"
    assert params["rest"].vararg
    assert "@Composable" in params["content"].type_text
    assert (
        params["content"].annotations == ()
    )  # an annotation inside the type is not the parameter's


def test_kotlin_member_kinds_types_modifiers_and_initialisers():
    info = parse("""
        package p
        class A {
            val a: Int = 1
            private var b = 0
            lateinit var c: Foo
            val d: Foo by lazy { Foo() }
            val e: Bar by viewModels<Bar>()
            val f = mutableListOf<String>()
            const val G = "g"
            override fun toString(): String = "x"
            suspend fun load(id: Int, vararg tags: String): List<Item> { return emptyList() }
            fun <T> List<T>.second(): T? = getOrNull(1)
            abstract fun later()
            constructor(x: Int) : this()
        }
        """)
    a = types(info)["p.A"]
    by_name = {m.name: m for m in a.members if m.kind != "constructor"}
    assert by_name["a"].type_text == "Int" and "val" in by_name["a"].modifiers
    assert by_name["b"].visibility == "private" and "var" in by_name["b"].modifiers
    assert by_name["c"].type_text == "Foo" and "lateinit" in by_name["c"].modifiers
    assert by_name["d"].delegated and by_name["d"].init_name == "lazy"
    assert by_name["e"].delegated and by_name["e"].init_name == "viewModels"
    assert by_name["e"].init_generic == "Bar"
    assert by_name["f"].init_name == "mutableListOf" and by_name["f"].init_generic == "String"
    assert "const" in by_name["G"].modifiers
    assert by_name["toString"].type_text == "String" and "override" in by_name["toString"].modifiers
    load = by_name["load"]
    assert "suspend" in load.modifiers and load.type_text == "List<Item>"
    assert [p.name for p in load.params] == ["id", "tags"] and load.params[1].vararg
    assert load.body is not None
    assert by_name["second"].type_text == "T?"
    assert "abstract" in by_name["later"].modifiers and by_name["later"].body is None
    assert [m.signature for m in a.members if m.kind == "constructor"] == ["A(Int)"]


def test_declarations_inside_bodies_lambdas_and_initialisers_are_not_members():
    info = parse("""
        package p
        class A {
            val cb = Callback(object : Listener { override fun onEvent() {} })
            val f = run { val inner = 1; inner }
            init { val z = 2; fun helper() {} }
            fun real() { val local = 3; fun nested() {} }
        }
        """)
    assert sorted(m.name for m in types(info)["p.A"].members) == ["cb", "f", "real"]


def test_companion_object_members_belong_to_the_enclosing_class_and_are_flagged():
    info = parse("""
        package p
        abstract class M {
            @Binds abstract fun bind(i: Impl): Api
            companion object {
                @Provides fun provide(): Db = TODO()
                const val TAG = "m"
            }
            companion object Named2 { fun not() {} }
        }
        """)
    m = types(info)["p.M"]
    assert [x.name for x in m.members if x.companion] == ["provide", "TAG", "not"]
    assert [x.name for x in m.members if not x.companion] == ["bind"]
    assert "p.M.Named2" not in types(info)  # a companion is not a separate type


def test_kotlin_enum_entries_and_members_after_the_semicolon():
    info = parse("""
        package p
        enum class Mode(val label: String) {
            A("a"), B("b") { override fun f() = 1 }, @Deprecated C("c");
            open fun f() = 0
        }
        enum class Plain { ONE, TWO }
        """)
    found = types(info)
    assert found["p.Mode"].entries == ("A", "B", "C")
    assert member_names(found["p.Mode"]) == ["f()"]
    assert found["p.Plain"].entries == ("ONE", "TWO")
    assert found["p.Plain"].members == ()


def test_kotlin_top_level_members_and_file_annotations():
    info = parse("""
        @file:JvmName("Util")
        package p
        val TAG = "x"
        fun helper(a: Int): Int = a
        @Composable fun Screen() {}
        private fun hidden() {}
        class A { fun inClass() {} }
        """)
    assert [m.signature for m in info.top_level] == ["TAG", "helper(Int)", "Screen()", "hidden()"]
    assert info.top_level[3].visibility == "private"
    assert [a.simple for a in info.top_level[2].annotations] == ["Composable"]
    assert [a.simple for a in info.file_annotations] == ["JvmName"]


def test_backtick_names_are_skipped_not_misread():
    info = parse("""
        package p
        class T {
            fun `does something odd`() {}
            fun ok() {}
        }
        """)
    assert member_names(types(info)["p.T"]) == ["ok()"]


def test_a_string_or_comment_that_looks_like_a_declaration_is_ignored():
    info = parse('''
        package p
        // class Fake { fun nope() }
        val text = """
            class Ghost { fun boo() {} }
        """
        /* object Phantom */
        class Real
        ''')
    assert list(types(info)) == ["p.Real"]
    assert [m.name for m in info.top_level] == ["text"]


# -- Kotlin: malformed input --------------------------------------------------------------------


def test_an_unclosed_class_body_is_marked_inexact_and_never_raises():
    info = parse("package p\nclass A {\n    fun f() {\n")
    a = types(info)["p.A"]
    assert a.exact is False
    assert "brackets" in info.issues


def test_an_unclosed_constructor_or_generic_is_marked_inexact():
    info = parse("package p\nclass A(val x: Int\nclass B<T\nclass C\n")
    found = types(info)
    assert found["p.A"].exact is False
    assert found["p.B"].exact is False
    assert "p.C" in found


def test_a_hostile_file_does_not_raise():
    for text in ("", "{{{{", "}}}}", "class", "class {", "@", "fun (", "val", "(((((", "@A(" * 50):
        parse(text)
        parse(text, "A.java")


# -- Java ---------------------------------------------------------------------------------------


def test_java_types_nesting_supertypes_and_modifiers():
    info = parse(
        """
        package p;
        public class A<T extends Number> extends Base<T> implements I, J<String> {
            static class Inner {}
            interface Cb { void done(); }
            enum Kind { ONE, TWO(2); private int v; Kind() {} }
        }
        abstract class B {}
        """,
        "A.java",
    )
    found = types(info)
    assert sorted(found) == ["p.A", "p.A.Cb", "p.A.Inner", "p.A.Kind", "p.B"]
    assert [s.written for s in found["p.A"].supertypes] == ["Base", "I", "J"]
    assert found["p.A.Cb"].kind == "interface" and found["p.A.Kind"].kind == "enum"
    assert found["p.B"].is_abstract
    assert found["p.A"].visibility == "public" and found["p.B"].visibility == "package"
    assert found["p.A.Kind"].entries == ("ONE", "TWO")
    assert member_names(found["p.A.Kind"]) == ["v", "Kind()"]


def test_java_fields_methods_and_constructors():
    info = parse(
        """
        package p;
        public class A {
            @PrimaryKey public int id;
            private final String name = "x";
            private static final Runnable R = () -> { int y = 1; };
            int[] arr = {1, 2, 3};
            Map<String, List<Integer>> map;
            @Inject
            public A(Repo repo, @Named("a") String b) {}
            @Override public String toString() { return ""; }
            public static <T extends Number> Map<String, T> make(List<T> items, int... rest) throws IOException { return null; }
            abstract void later();
            static { int z = 1; }
            { int w = 2; }
        }
        """,
        "A.java",
    )
    a = types(info)["p.A"]
    names = [(m.kind, m.name) for m in a.members]
    assert names == [
        ("field", "id"),
        ("field", "name"),
        ("field", "R"),
        ("field", "arr"),
        ("field", "map"),
        ("constructor", "A"),
        ("function", "toString"),
        ("function", "make"),
        ("function", "later"),
    ]
    by = {m.name: m for m in a.members}
    assert [x.simple for x in by["id"].annotations] == ["PrimaryKey"]
    assert by["name"].type_text == "String" and "final" in by["name"].modifiers
    assert by["map"].type_text == "Map<String, List<Integer>>"
    ctor = by["A"]
    assert [a_.simple for a_ in ctor.annotations] == ["Inject"]
    assert [(p.name, p.type_text) for p in ctor.params] == [("repo", "Repo"), ("b", "String")]
    assert [x.simple for x in ctor.params[1].annotations] == ["Named"]
    make = by["make"]
    assert make.type_text == "Map<String, T>"
    assert [p.name for p in make.params] == ["items", "rest"] and make.params[1].vararg
    assert "static" in make.modifiers
    assert by["toString"].annotations[0].simple == "Override"


def test_java_interface_members_are_public_and_annotation_elements_are_methods():
    info = parse(
        """
        package p;
        public interface Api {
            @GET("x") Call<List<Item>> items();
            int LIMIT = 5;
        }
        @interface Marker { String value() default "x"; }
        """,
        "Api.java",
    )
    api = types(info)["p.Api"]
    assert [(m.kind, m.name, m.visibility) for m in api.members] == [
        ("function", "items", "public"),
        ("field", "LIMIT", "public"),
    ]
    assert api.members[0].type_text == "Call<List<Item>>"
    marker = types(info)["p.Marker"]
    assert marker.kind == "annotation"
    assert [m.name for m in marker.members] == ["value"]


def test_java_nested_generic_and_array_declarations_do_not_split_wrongly():
    info = parse(
        """
        package p;
        class A {
            Map<String, Map<String, int[]>> deep = new HashMap<>();
            List<String>[] arrays;
            <K, V extends Comparable<V>> void generic(Map<K, V> m, Function<K, V> f) {}
        }
        """,
        "A.java",
    )
    a = types(info)["p.A"]
    assert [m.name for m in a.members] == ["deep", "arrays", "generic"]
    assert [p.name for p in a.members[2].params] == ["m", "f"]


def test_java_comment_and_string_lookalikes_are_ignored():
    info = parse(
        'package p;\n// class Fake {}\nclass A { String s = "class Ghost { void boo() {} }"; /* int hidden; */ }\n',
        "A.java",
    )
    assert list(types(info)) == ["p.A"]
    assert [m.name for m in types(info)["p.A"].members] == ["s"]


def test_member_count_is_capped_and_the_type_says_so():
    body = "".join(f"    fun f{i}() {{}}\n" for i in range(50))
    info = parse_file(
        SourceFile("A.kt", f"package p\nclass A {{\n{body}}}\n"),
        AnalysisConfig(max_members_per_type=10),
    )
    a = types(info)["p.A"]
    assert len(a.members) == 10 and a.truncated


def test_the_type_count_per_file_is_capped():
    text = "package p\n" + "".join(f"class C{i}\n" for i in range(30))
    info = parse_file(SourceFile("A.kt", text), AnalysisConfig(max_types_per_file=10))
    assert len(info.types) == 10
    assert "too_many_types" in info.issues


def test_type_at_and_function_at_find_the_innermost_declaration():
    text = "package p\nclass A {\n    fun f(x: Int = 1) {\n        val y = 2\n    }\n}\n"
    info = parse(text)
    inside_body = text.index("val y")
    assert info.type_at(inside_body).fqn == "p.A"
    assert info.function_at(inside_body).name == "f"
    assert info.function_at(text.index("x: Int")).name == "f"  # the parameter list counts
    assert info.function_at(text.index("class A")) is None
