import pytest

from androai_codegen.review.source import SourceFile, matching_close

KOTLIN = """package com.example.app.ui

import androidx.compose.material3.Text
import androidx.compose.material3.*
import com.example.app.data.Repo as Repository
import static.fake.Thing

// import com.commented.Out
/* class Hidden */
val greeting = "class NotAClass"

@Composable
fun Greeting(name: String) {
    Text(text = "Hi $name")
}

private fun helper() = 1

data class User(val id: Int)
sealed class Result2 { object Ok : Result2() }
enum class Color { Red, Green }
interface Api
abstract class Base : Api
class MainActivity : AppCompatActivity(), Api by impl {
    companion object Factory { fun make() = 1 }
    class Nested
}
typealias Names = List<String>
const val MAX = 3
val Purple80 = 1
"""

JAVA = """package com.example.app;

import java.util.List;
import static java.lang.Math.max;
import java.util.*;

/** class InJavadoc */
public abstract class Main extends AppCompatActivity implements Runnable, Comparable<Main> {
    public static class Inner {}
    enum Mode { A, B }
    @interface Marker {}
    record Point(int x, int y) {}
    interface Callback extends A, B<String> {}
}
"""


def kotlin() -> SourceFile:
    return SourceFile("app/Main.kt", KOTLIN)


def java() -> SourceFile:
    return SourceFile("app/Main.java", JAVA)


def test_package_and_imports():
    sf = kotlin()
    assert sf.package == "com.example.app.ui"
    imports = {(i.fqn, i.wildcard, i.alias) for i in sf.imports}
    assert ("androidx.compose.material3.Text", False, None) in imports
    assert ("androidx.compose.material3", True, None) in imports
    assert ("com.example.app.data.Repo", False, "Repository") in imports
    assert not any("commented" in i.fqn for i in sf.imports)  # commented out
    assert {i.simple_name for i in sf.imports if not i.wildcard} >= {"Text", "Repository"}
    assert [i.simple_name for i in sf.imports if i.wildcard] == [None]


def test_java_imports_including_static():
    sf = java()
    by_fqn = {i.fqn: i for i in sf.imports}
    assert by_fqn["java.util.List"].static is False
    assert by_fqn["java.lang.Math.max"].static is True
    assert by_fqn["java.util"].wildcard is True


def test_kotlin_type_declarations():
    types = {t.name: t for t in kotlin().types}
    assert set(types) == {
        "User",
        "Result2",
        "Ok",
        "Color",
        "Api",
        "Base",
        "MainActivity",
        "Factory",
        "Nested",
        "Names",
    }
    assert types["Color"].kind == "enum" and types["Api"].kind == "interface"
    assert types["Ok"].kind == "object" and types["Names"].kind == "typealias"
    assert types["User"].fqn == "com.example.app.ui.User" and types["User"].top_level
    assert not types["Nested"].top_level and types["Nested"].fqn.endswith("MainActivity.Nested")
    assert types["Base"].abstract and types["Api"].abstract and types["Result2"].abstract
    assert not types["MainActivity"].abstract and not types["User"].abstract
    assert "Hidden" not in types and "NotAClass" not in types  # comment and string


def test_kotlin_supertypes():
    types = {t.name: t for t in kotlin().types}
    assert types["MainActivity"].supertypes == ("AppCompatActivity", "Api")
    assert types["Base"].supertypes == ("Api",)
    assert types["Ok"].supertypes == ("Result2",)
    assert types["User"].supertypes == ()


def test_java_type_declarations_and_supertypes():
    types = {t.name: t for t in java().types}
    assert set(types) == {"Main", "Inner", "Mode", "Marker", "Point", "Callback"}
    assert types["Mode"].kind == "enum" and types["Marker"].kind == "annotation"
    assert types["Point"].kind == "record" and types["Callback"].kind == "interface"
    assert types["Main"].abstract and types["Main"].top_level and not types["Inner"].top_level
    assert types["Main"].supertypes == ("AppCompatActivity", "Runnable", "Comparable")
    assert types["Callback"].supertypes == ("A", "B")
    assert "InJavadoc" not in types


def test_one_line_nested_declaration_keeps_its_supertype():
    sf = SourceFile("a.kt", "sealed class S { object A : S(); class B(val x: Int) : S() }\n")
    assert {t.name: t.supertypes for t in sf.types} == {"S": (), "A": ("S",), "B": ("S",)}


def test_a_class_without_a_body_does_not_swallow_the_next_declaration():
    sf = SourceFile("a.kt", "class A(val x: Int)\n\nfun f() {}\nclass B : Parent() {\n}\n")
    types = {t.name: t for t in sf.types}
    assert types["A"].supertypes == () and types["B"].supertypes == ("Parent",)


def test_class_literals_and_member_classes_are_not_declarations():
    sf = SourceFile("a.kt", "val a = Foo::class.java\nval b = this::class\nclass Real\n")
    assert [t.name for t in sf.types] == ["Real"]
    assert [n for n, _ in sf.class_literals] == ["Foo"]
    jf = SourceFile("A.java", "class A { Class<?> c = Foo.class; Object o = a.b.Bar.class; }")
    assert [t.name for t in jf.types] == ["A"]
    assert [n for n, _ in jf.class_literals] == ["Foo"]  # qualified Bar is skipped


def test_kotlin_functions():
    funcs = {f.name: f for f in kotlin().functions}
    assert set(funcs) == {"Greeting", "helper", "make"}
    assert funcs["Greeting"].composable and funcs["Greeting"].top_level
    assert not funcs["helper"].composable and funcs["helper"].private
    assert not funcs["make"].top_level
    start, end = funcs["Greeting"].body
    assert kotlin().text[start] == "{" and kotlin().text[end] == "}"
    assert funcs["helper"].body is None  # expression body


def test_function_names_with_receivers_generics_and_default_lambdas():
    sf = SourceFile(
        "a.kt",
        "fun <T> List<T>.second(): T = this[1]\n"
        "fun String.shout(times: Int = 2, f: () -> Unit = { }): String { return this }\n"
        "fun interface Handler { fun handle() }\n",
    )
    assert [f.name for f in sf.functions] == ["second", "shout", "handle"]
    assert sf.functions[1].body is not None


def test_composable_annotation_does_not_leak_to_the_next_function():
    sf = SourceFile(
        "a.kt",
        '@Composable fun A() = Text("x")\n\nfun B() {}\n\n@Composable\nfun C() {}\n',
    )
    assert {f.name: f.composable for f in sf.functions} == {"A": True, "B": False, "C": True}


def test_top_level_values_include_properties_but_not_locals_or_members():
    sf = SourceFile(
        "Color.kt",
        "val Purple80 = 1\nconst val MAX = 3\nprivate val hidden = 2\n"
        "class K { val member = 1 }\nfun f() { val local = 2 }\n",
    )
    assert sf.top_level_values == ["Purple80", "MAX", "hidden"]


def test_used_names_skip_qualified_constants_generics_labels_and_headers():
    sf = SourceFile(
        "a.kt",
        "package com.x\n\nimport androidx.compose.ui.Modifier\n\n"
        "@Composable\nfun Screen(vm: ViewModel) {\n"
        "    val m = Modifier.padding(1)\n"
        "    val n = androidx.compose.ui.Alignment.Center\n"
        "    val c = MAX_SIZE + TAG\n"
        "    val g: List<T> = emptyList()\n"
        "    scope.launch { return@launch }\n"
        "    this@MainActivity.finish()\n"
        '    val s = "Text in a string" // Text in a comment\n'
        "}\n",
    )
    assert set(sf.used_names) == {"Composable", "Screen", "ViewModel", "Modifier", "List"}


def test_used_names_record_the_first_use_offset():
    sf = SourceFile("a.kt", "val a = Foo()\nval b = Foo()\n")
    assert sf.used_names["Foo"] == 8


def test_crlf_and_cr_line_endings_are_normalised_without_moving_lines_or_columns():
    lf = SourceFile("a.kt", "package p\n\nimport a.B\n\nclass C : D()\n")
    crlf = SourceFile("a.kt", "package p\r\n\r\nimport a.B\r\n\r\nclass C : D()\r\n")
    old_mac = SourceFile("a.kt", "package p\r\rimport a.B\r\rclass C : D()\r")
    for source in (crlf, old_mac):
        assert "\r" not in source.text and source.text == lf.text
        assert [i.fqn for i in source.imports] == ["a.B"]
        assert [(t.name, t.line, t.supertypes) for t in source.types] == [("C", 5, ("D",))]
        offset = source.text.index("class")
        assert (source.line(offset), source.column(offset)) == (lf.line(offset), lf.column(offset))


def test_gradle_scripts_are_normalised_too():
    from androai_codegen.review.gradle import GradleScript

    script = GradleScript("app/build.gradle.kts", 'dependencies {\r\n    api("a:b:1")\r\n}\r\n')
    assert "\r" not in script.text
    assert [(d.config, d.coordinate, d.line) for d in script.dependencies] == [("api", "a:b", 2)]


def test_positions():
    sf = kotlin()
    assert sf.line(sf.text.index("fun Greeting")) == 13  # line 12 is the @Composable annotation


@pytest.mark.parametrize(
    ("text", "open_index", "expected"),
    [("{ a { b } c }", 0, 12), ("{ a { b } c }", 4, 8), ("{ unclosed", 0, None)],
)
def test_matching_close(text, open_index, expected):
    assert matching_close(text, open_index) == expected


def test_large_file_is_analysed_quickly():
    import time

    body = "".join(f'class Cls{i} : Base()\nfun f{i}() {{ val x = "s" }}\n' for i in range(5000))
    sf = SourceFile("big.kt", "package p\n" + body)
    started = time.perf_counter()
    assert len(sf.types) == 5000 and len(sf.functions) == 5000
    assert len(sf.used_names) > 5000
    assert time.perf_counter() - started < 10
