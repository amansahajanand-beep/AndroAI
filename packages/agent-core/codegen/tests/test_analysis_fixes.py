"""Regression tests for the defect-fix pass on M2A.

B1  import / name / annotation resolution was quadratic (a file with thousands of imports, asked
    about thousands of names, rescanned the import list for every name)
B2  secrets that travel in a URL *path* (Telegram bot tokens, Slack and Discord webhooks, generated
    ids) reached fact ids and attributes
N1  a Kotlin ``where T : Fragment`` constraint was read as a superclass
N2  an annotation imported under another name (``import androidx.room.Dao as RoomDao``) was not
    recognised
N3  source files in a language the analysis does not read were silently ignored
    and: an excerpt of a file whose first line is empty
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from analysis_fixtures import (
    DISCORD_ID,
    DISCORD_TOKEN,
    PATH_SECRETS,
    SLACK_IDS,
    SLACK_SECRET,
    TELEGRAM_SECRET,
    TELEGRAM_TOKEN,
    analyse,
    d,
    edges,
    fact,
    ids,
    mini_app,
    no_errors,
)
from ingest_helpers import write_tree

from androai_codegen.analysis import AnalysisConfig, analyse_workspace
from androai_codegen.analysis.catalog import KNOWN_ANNOTATIONS
from androai_codegen.analysis.members import parse_file
from androai_codegen.analysis.resolve import (
    UNRESOLVED,
    Resolution,
    TypeResolver,
    import_index,
    resolve_known,
)
from androai_codegen.analysis.screens import Composable, ComposeIndex
from androai_codegen.analysis.store import make_id
from androai_codegen.analysis.text import (
    LineText,
    SrcView,
    clip,
    mask_urls,
    redact_path,
    redact_url,
    scrub,
)
from androai_codegen.editing.workspace import Workspace
from androai_codegen.review.source import SourceFile

# ===============================================================================================
# B1 - resolution does not walk the import list per name
# ===============================================================================================


class CountingList(list):
    """A list that counts how often it is iterated: the cost B1 was about."""

    def __init__(self, items=()):
        super().__init__(items)
        self.scans = 0

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


def counted_source(text: str, path: str = "A.kt") -> tuple[SourceFile, CountingList]:
    source = SourceFile(path, text)
    imports = CountingList(source.imports)
    source.__dict__["imports"] = imports  # ``imports`` is a cached_property: this replaces it
    return source, imports


def many_imports(n: int, *, wildcard: bool = False) -> str:
    if wildcard:
        return "package com.x\n" + "".join(f"import com.lib{i}.*\n" for i in range(n))
    return "package com.x\n" + "".join(f"import com.lib.Class{i}\n" for i in range(n))


def test_resolve_known_does_not_walk_the_imports_for_each_name():
    source, imports = counted_source(many_imports(3000))
    for i in range(3000):
        assert resolve_known(source, f"Name{i}", KNOWN_ANNOTATIONS) == UNRESOLVED
    # Index built once (it reads the list a constant number of times); asking about three thousand
    # unresolvable names adds no scans at all.
    assert imports.scans <= 3, imports.scans


def test_resolve_known_with_only_wildcard_imports_does_not_walk_them_per_name():
    source, imports = counted_source(many_imports(3000, wildcard=True))
    for i in range(3000):
        resolve_known(source, "Dao", KNOWN_ANNOTATIONS)
        resolve_known(source, f"Name{i}", KNOWN_ANNOTATIONS)
    assert imports.scans <= 3, imports.scans


def project_types(n: int = 50) -> set[str]:
    return {f"com.p{i}.Type{i}" for i in range(n)} | {"com.x.Own", "com.x.Own.Inner"}


def test_type_resolver_does_not_walk_the_imports_for_each_name():
    source, imports = counted_source(many_imports(3000))
    resolver = TypeResolver(project_types())
    for i in range(3000):
        assert resolver.resolve(source, f"Name{i}", "com.x.Own") == UNRESOLVED
        resolver.resolve(source, f"Name{i}")  # a second owner for the same name
    assert imports.scans <= 3, imports.scans


def test_type_resolver_with_thousands_of_wildcards_asked_about_real_project_types():
    types = project_types(3000)
    wildcard = "package com.x\n" + "".join(f"import com.p{i}.*\n" for i in range(3000))
    source, imports = counted_source(wildcard)
    resolver = TypeResolver(types)
    for i in range(0, 3000, 7):
        resolved = resolver.resolve(source, f"Type{i}")
        assert resolved == Resolution(f"com.p{i}.Type{i}", "wildcard")
    assert imports.scans <= 3, imports.scans


def test_a_repeated_question_is_answered_from_the_memo_and_is_the_same_answer():
    source, imports = counted_source(many_imports(10))
    resolver = TypeResolver(project_types())
    first = resolver.resolve(source, "Own", "com.x")
    scans = imports.scans
    for _ in range(100):
        assert resolver.resolve(source, "Own", "com.x") is first
    assert imports.scans == scans
    # the memo does not mix up owners: the same name means different things in different scopes
    assert resolver.resolve(source, "Inner", "com.x.Own") == Resolution(
        "com.x.Own.Inner", "same_package"
    )
    # from outside ``Own`` the same word is only guessed (one project type has that name)
    assert resolver.resolve(source, "Inner", "com.x") == Resolution("com.x.Own.Inner", "by_name")


def test_the_index_of_one_file_is_not_used_for_another():
    first = SourceFile("A.kt", "package a\nimport com.one.Thing\n")
    second = SourceFile("B.kt", "package b\nimport com.two.Thing\n")
    assert import_index(first).explicit == {"Thing": "com.one.Thing"}
    assert import_index(second).explicit == {"Thing": "com.two.Thing"}
    assert import_index(first) is import_index(first)


def test_import_index_rules_first_explicit_import_wins_static_is_ignored_aliases_are_names():
    source = SourceFile(
        "A.kt",
        d("""
        package p
        import a.First
        import b.First
        import static c.Helper
        import d.Real as Alias
        import e.*
        import f.*
        import e.*
        """),
    )
    index = import_index(source)
    assert index.explicit == {"First": "a.First", "Alias": "d.Real"}
    assert list(index.wildcards) == ["e", "f"]  # a package imported twice counts once
    assert index.wildcards["e"] < index.wildcards["f"]  # ...at its first position
    assert index.imports_from("a.") and index.imports_from("c.Helper")
    assert not index.imports_from("zzz")


def test_a_package_imported_twice_does_not_make_a_name_ambiguous():
    source = SourceFile("A.kt", "package p\nimport com.lib.*\nimport com.lib.*\n")
    resolver = TypeResolver({"com.lib.Thing"})
    assert resolver.resolve(source, "Thing") == Resolution("com.lib.Thing", "wildcard")


def test_two_different_wildcard_packages_with_the_same_name_stay_ambiguous():
    source = SourceFile("A.kt", "package p\nimport one.*\nimport two.*\n")
    resolver = TypeResolver({"one.Thing", "two.Thing"})
    assert resolver.resolve(source, "Thing") == UNRESOLVED


def test_a_nested_type_is_reached_through_a_wildcard_of_its_outer_type():
    source = SourceFile("A.kt", "package p\nimport com.lib.Outer.*\n")
    resolver = TypeResolver({"com.lib.Outer", "com.lib.Outer.Inner"})
    assert resolver.resolve(source, "Inner") == Resolution("com.lib.Outer.Inner", "wildcard")
    # relative to a wildcard of the package, the nested name is written with its outer type
    source2 = SourceFile("B.kt", "package p\nimport com.lib.*\n")
    assert resolver.resolve(source2, "Outer.Inner") == Resolution("com.lib.Outer.Inner", "wildcard")


def test_a_hostile_deeply_nested_type_name_does_not_make_the_resolver_slow():
    deep = ".".join(f"T{i}" for i in range(3000))
    started = time.perf_counter()
    resolver = TypeResolver({f"com.x.{deep}"})
    elapsed = time.perf_counter() - started
    assert elapsed < 5
    source = SourceFile("A.kt", "package com.x\n")
    resolved = resolver.resolve(source, "T2999")
    assert resolved.how == "by_name" and resolved.fqn.endswith(".T2999")  # the only type so named


# -- the new resolvers answer exactly as the old front-to-back scan did -----------------------


def _old_resolve_known(source: SourceFile, written: str, known) -> Resolution:
    """The resolver as it was before B1: a scan of every import for every name."""
    first, _, rest = written.partition(".")
    if rest and first[:1].islower():
        return Resolution(written, "qualified")
    for imp in source.imports:
        if not imp.wildcard and not imp.static and imp.simple_name == first:
            return Resolution(f"{imp.fqn}.{rest}" if rest else imp.fqn, "explicit")
    accepted = set(known.get(written, ())) | set(known.get(first, ()))
    for imp in source.imports:
        if imp.wildcard and not imp.static and f"{imp.fqn}.{written}" in accepted:
            return Resolution(f"{imp.fqn}.{written}", "wildcard")
    if written in known or first in known:
        return Resolution(None, "by_name")
    return UNRESOLVED


def _old_type_resolve(fqns: set[str], source: SourceFile, written: str, owner) -> Resolution:
    by_simple: dict[str, list[str]] = {}
    for fqn in sorted(fqns):
        by_simple.setdefault(fqn.rsplit(".", 1)[-1], []).append(fqn)
    first, _, rest = written.partition(".")
    if rest and first[:1].islower() and written in fqns:
        return Resolution(written, "qualified")
    for imp in source.imports:
        if not imp.wildcard and not imp.static and imp.simple_name == first:
            target = f"{imp.fqn}.{rest}" if rest else imp.fqn
            return Resolution(target, "explicit") if target in fqns else UNRESOLVED
    scope = owner
    while scope:
        candidate = f"{scope}.{written}"
        if candidate in fqns:
            return Resolution(candidate, "same_package")
        scope = scope.rsplit(".", 1)[0] if "." in scope else None
    package = source.package
    candidate = f"{package}.{written}" if package else written
    if candidate in fqns:
        return Resolution(candidate, "same_package")
    hits = [
        f"{imp.fqn}.{written}"
        for imp in source.imports
        if imp.wildcard and not imp.static and f"{imp.fqn}.{written}" in fqns
    ]
    if len(hits) == 1:
        return Resolution(hits[0], "wildcard")
    if not rest:
        options = by_simple.get(first, [])
        if len(options) == 1 and not hits:
            return Resolution(options[0], "by_name")
    return UNRESOLVED


_PACKAGES = ["a.b", "a.c", "d", "e.f.g", "a"]
_NAMES = ["Foo", "Bar", "Baz", "Qux", "Foo2", "Outer", "Dao"]
_KNOWN = {
    "Foo": ("a.b.Foo", "d.Foo"),
    "Bar": ("a.c.Bar",),
    "Dao": ("androidx.room.Dao", "a.b.Dao"),
    "Outer.Inner": ("a.b.Outer.Inner",),
}


def _random_file(rng: random.Random) -> tuple[SourceFile, set[str]]:
    types: set[str] = set()
    for _ in range(rng.randint(0, 14)):
        pkg, name = rng.choice(_PACKAGES), rng.choice(_NAMES)
        types.add(f"{pkg}.{name}")
        if rng.random() < 0.4:
            types.add(f"{pkg}.{name}.Inner")
    lines = [f"package {rng.choice(_PACKAGES)}"]
    for pkg in rng.sample(_PACKAGES, rng.randint(0, 4)):  # wildcard packages: each at most once
        lines.append(f"import {pkg}.*")
    for _ in range(rng.randint(0, 6)):
        pkg, name = rng.choice(_PACKAGES), rng.choice(_NAMES)
        kind = rng.random()
        if kind < 0.15:
            lines.append(f"import static {pkg}.{name}")
        elif kind < 0.35:
            lines.append(f"import {pkg}.{name} as {rng.choice(_NAMES)}X")
        else:
            lines.append(f"import {pkg}.{name}")
    rng.shuffle(lines[1:])
    return SourceFile("A.kt", "\n".join(lines) + "\n"), types


def test_the_indexed_resolvers_agree_with_the_old_scan_on_random_files():
    rng = random.Random(20260501)
    compared = 0
    for _ in range(600):
        source, types = _random_file(rng)
        resolver = TypeResolver(types)
        owners = [None, *sorted(types)[:3]]
        names = [
            *_NAMES,
            *(f"{n}X" for n in _NAMES),
            "Outer.Inner",
            "a.b.Foo",
            "Foo.Inner",
            "Nope",
        ]
        for written in names:
            assert resolve_known(source, written, _KNOWN) == _old_resolve_known(
                source, written, _KNOWN
            ), (source.text, written)
            for owner in owners:
                assert resolver.resolve(source, written, owner) == _old_type_resolve(
                    types, source, written, owner
                ), (source.text, written, owner, sorted(types))
                compared += 1
    assert compared > 20_000


def test_tail_index_walks_the_shorter_side():
    """Many packages hold the name and few wildcards are imported, and the reverse."""
    types = {f"pkg{i}.Item" for i in range(400)}
    resolver = TypeResolver(types)
    few = SourceFile("A.kt", "package p\nimport pkg7.*\nimport other.*\n")
    assert resolver.resolve(few, "Item") == Resolution("pkg7.Item", "wildcard")
    many = SourceFile("B.kt", "package p\n" + "".join(f"import pkg{i}.*\n" for i in range(400)))
    assert resolver.resolve(many, "Item") == UNRESOLVED  # 400 packages: ambiguous
    one = TypeResolver({"pkg5.Item"})
    assert one.resolve(many, "Item") == Resolution("pkg5.Item", "wildcard")


class CountingSet(set):
    """A set that counts membership tests: the work a wildcard lookup does against the types."""

    def __init__(self, items=()):
        super().__init__(items)
        self.lookups = 0

    def __contains__(self, item):
        self.lookups += 1
        return super().__contains__(item)


def wildcard_lookups(types: set[str], imports: str, name: str) -> tuple[list[str], int]:
    counted = CountingSet(types)
    resolver = TypeResolver(counted)
    index = import_index(SourceFile("A.kt", f"package p\n{imports}"))
    counted.lookups = 0
    return resolver._wildcard_hits(index, name), counted.lookups


def test_a_wildcard_lookup_probes_only_the_shorter_side():
    holders = {f"pkg{i}.Item" for i in range(300)}
    # 300 packages hold the name, two wildcards are imported: only the two imports are probed
    hits, lookups = wildcard_lookups(holders, "import pkg7.*\nimport nowhere.*\n", "Item")
    assert hits == ["pkg7.Item"] and lookups == 2
    # two packages hold the name, 300 wildcards are imported: no probe of the types at all
    many = "".join(f"import pkg{i}.*\n" for i in range(300))
    hits, lookups = wildcard_lookups({"pkg1.Item", "pkg2.Item"}, many, "Item")
    assert hits == ["pkg1.Item", "pkg2.Item"] and lookups == 0
    # a tie goes to the packages (the index of the types), which need no probe either
    hits, lookups = wildcard_lookups(
        {"pkg1.Item", "pkg2.Item"}, "import pkg2.*\nimport pkg1.*\n", "Item"
    )
    assert hits == ["pkg2.Item", "pkg1.Item"] and lookups == 0  # in import order


# -- end to end: the probes of the review, with generous bounds -------------------------------


def timed(files: dict[str, str]):
    started = time.perf_counter()
    report = analyse(files)
    return report, time.perf_counter() - started


def test_thousands_of_imports_times_thousands_of_names_is_fast():
    n = 8000  # the review measured 15.7 s here before the fix; it is about 0.3 s now
    imports = "".join(f"import com.lib.Class{i}\n" for i in range(n))
    uses = "".join(f"val v{i} = Name{i}()\n" for i in range(n))
    report, elapsed = timed(mini_app(Big=f"package com.x\n{imports}\n{uses}"))
    no_errors(report)
    assert elapsed < 5, f"{elapsed:.1f}s"
    assert not [lim for lim in report.limitations if lim.code == "time_budget_exceeded"]


def test_thousands_of_imports_times_thousands_of_annotated_classes_is_fast():
    n = 4000  # 7.8 s before the fix
    imports = "".join(f"import com.lib.Class{i}\n" for i in range(n))
    anns = "".join(f"@Ann{i} class C{i}\n" for i in range(n))
    report, elapsed = timed(mini_app(Big=f"package com.x\n{imports}\n{anns}"))
    no_errors(report)
    assert elapsed < 4, f"{elapsed:.1f}s"
    assert report.stats.source_files == 1 and report.stats.facts_by_kind["type"] > 0  # parsed


def test_thousands_of_imports_times_tens_of_thousands_of_stacked_annotations_is_fast():
    imports = "".join(f"import com.lib.Class{i}\n" for i in range(8000))
    report, elapsed = timed(
        mini_app(Big=f"package com.x\n{imports}\n{'@Foo ' * 60000}class C\n")
    )  # 106 s before the fix
    no_errors(report)
    assert elapsed < 8, f"{elapsed:.1f}s"


def test_thousands_of_wildcard_imports_times_thousands_of_names_is_fast():
    wildcard = "".join(f"import com.lib{i}.*\n" for i in range(5000))
    uses = "".join(f"val v{i} = Name{i}()\n@Ann{i} class C{i}\n" for i in range(3000))
    report, elapsed = timed(mini_app(Big=f"package com.x\n{wildcard}\n{uses}"))
    no_errors(report)
    assert elapsed < 5, f"{elapsed:.1f}s"


def composable(name: str, owner: str) -> Composable:
    member = SimpleNamespace(name=name, owner=owner)
    return Composable(member, None, f"composable:{owner}.{name}", False, False, False)  # type: ignore[arg-type]


def test_the_compose_index_resolves_a_call_without_walking_the_imports():
    source, imports = counted_source(
        "package com.x\nimport com.ui.Imported\nimport com.wild.*\n"
        + "".join(f"import com.lib.Class{i}\n" for i in range(3000))
    )
    info = SimpleNamespace(source=source, package="com.x")
    index = ComposeIndex()
    for entry in (
        composable("Imported", "com.ui"),
        composable("Imported", "com.other"),  # same name, not the imported one
        composable("Local", "com.x"),
        composable("Wild", "com.wild"),
        composable("Wild", "com.else"),
        composable("OnlyOne", "com.far"),
        composable("Twice", "com.a"),
        composable("Twice", "com.b"),
    ):
        index.add(entry)

    def answer(name: str):
        return [(e.member.owner, certain) for e, certain in index.resolve(info, name)]

    assert answer("Imported") == [("com.ui", True)]  # named by an explicit import
    assert answer("Local") == [("com.x", True)]  # same package
    assert answer("Wild") == [("com.wild", True)]  # through the wildcard
    assert answer("OnlyOne") == [("com.far", False)]  # the only one so named: a guess
    assert answer("Twice") == []  # two candidates and nothing says which
    assert answer("Missing") == []
    for _ in range(3000):
        for name in ("Imported", "Local", "Wild", "OnlyOne", "Twice", "Missing"):
            answer(name)
    assert imports.scans <= 3, imports.scans


def test_many_imports_do_not_change_what_is_found():
    """The same screen with and without 3000 unrelated imports gives the same facts."""
    body = """
        import androidx.room.Dao
        import androidx.room.Entity
        import androidx.room.PrimaryKey
        @Entity data class Note(@PrimaryKey val id: Int)
        @Dao interface NoteDao
        """
    plain = analyse(mini_app(S="package com.x\n" + d(body)))
    noisy_imports = "".join(f"import com.lib.Class{i}\n" for i in range(3000))
    noisy = analyse(mini_app(S="package com.x\n" + noisy_imports + d(body)))

    def shape(report):
        return {(f.kind, f.subject, f.status) for f in report.facts}

    assert shape(plain) == shape(noisy)
    assert ids(noisy, "room_entity") == ["com.x.Note"]
    assert ids(noisy, "room_dao") == ["com.x.NoteDao"]


# ===============================================================================================
# B2 - secrets in URL paths
# ===============================================================================================


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"/bot{TELEGRAM_TOKEN}/getMe", "/bot[REDACTED]/getMe"),
        (f"/file/bot{TELEGRAM_TOKEN}/photos/a.jpg", "/file/bot[REDACTED]/photos/a.jpg"),
        (f"/services/{SLACK_IDS}/{SLACK_SECRET}", "/services/[REDACTED]"),
        (f"/triggers/{SLACK_IDS}/123456789012/{SLACK_SECRET}", "/triggers/[REDACTED]"),
        (f"/api/webhooks/{DISCORD_ID}/{DISCORD_TOKEN}", "/api/webhooks/[REDACTED]"),
        (
            f"/api/v10/webhooks/{DISCORD_ID}/{DISCORD_TOKEN}/slack",
            "/api/v10/webhooks/[REDACTED]/slack",
        ),
        ("/files/550e8400-e29b-41d4-a716-446655440000/download", "/files/[REDACTED]/download"),
        ("/hook/d41d8cd98f00b204e9800998ecf8427e", "/hook/[REDACTED]"),
        ("/hook/da39a3ee5e6b4b0d3255bfef95601890afd80709/x", "/hook/[REDACTED]/x"),
        (f"/token/{TELEGRAM_SECRET}", "/token/[REDACTED]"),
        ("/k/Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA", "/k/[REDACTED]"),
        ("/auth/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3", "/auth/[REDACTED]"),
        ("/n/1234567890123456789", "/n/[REDACTED]"),
        # relative paths, as Retrofit writes them
        (f"services/{SLACK_IDS}/{SLACK_SECRET}", "services/[REDACTED]"),
        (f"bot{TELEGRAM_TOKEN}/sendMessage", "bot[REDACTED]/sendMessage"),
        (f"webhooks/{DISCORD_ID}/{DISCORD_TOKEN}", "webhooks/[REDACTED]"),
    ],
)
def test_redact_path_hides_the_secret_and_keeps_the_rest(path: str, expected: str):
    assert redact_path(path) == expected
    assert redact_path(redact_path(path)) == expected  # idempotent: scrub may run twice


@pytest.mark.parametrize(
    "path",
    [
        "/v1/users/{id}/notes",
        "/api/v2/oauth2/token",
        "/reference/androidx/compose/material3/ExperimentalMaterial3Api",
        "/swagger/openapi-spec.json",
        "/get-all-notes-for-user",
        "/get_all_notes_for_user",
        "/getAllNotesForCurrentUser",
        "/products/12345/reviews",
        "users/{id}",
        "bot{token}/getMe",
        "/refresh_token",
        "/v1.2.3/items",
        "",
        "/",
        "///",
    ],
)
def test_redact_path_leaves_ordinary_paths_alone(path: str):
    assert redact_path(path) == path


def test_redact_path_survives_hostile_input_quickly():
    started = time.perf_counter()
    for text in (
        "/" * 100_000,
        "/" + "a" * 500_000,
        "/" + "aB1" * 200_000,
        "/" + "-".join(["ab"] * 100_000),
        "/" + "aA" * 100_000 + "!",
        "/bot" + "1" * 200_000 + ":" + "A" * 200_000,
        "/services/T" + "A" * 100_000 + "/" + "B" * 100_000,
    ):
        redact_path(text)
        mask_urls("https://h" + text)
    assert time.perf_counter() - started < 10


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id=1&text=hi",
            "https://api.telegram.org/bot[REDACTED]/sendMessage",
        ),
        (
            f"https://hooks.slack.com/services/{SLACK_IDS}/{SLACK_SECRET}",
            "https://hooks.slack.com/services/[REDACTED]",
        ),
        (
            f"https://discord.com/api/webhooks/{DISCORD_ID}/{DISCORD_TOKEN}",
            "https://discord.com/api/webhooks/[REDACTED]",
        ),
        (
            f"https://user:pw@api.telegram.org:8443/bot{TELEGRAM_TOKEN}/getMe#x",
            "https://api.telegram.org:8443/bot[REDACTED]/getMe",
        ),
        # a template or a relative value is treated the same way
        (f"https://$host/bot{TELEGRAM_TOKEN}/x", "https://$host/bot[REDACTED]/x"),
        (f"bot{TELEGRAM_TOKEN}/getMe", "bot[REDACTED]/getMe"),
        (f"/bot{TELEGRAM_TOKEN}/getMe?x=1", "/bot[REDACTED]/getMe"),
        # the host is not a path: a long generated host name is kept
        (
            "https://abc123def456ghi789jkl.execute-api.us-east-1.amazonaws.com/{stage}/items",
            "https://abc123def456ghi789jkl.execute-api.us-east-1.amazonaws.com/{stage}/items",
        ),
        ("https://api.example.com/v1/users/{id}", "https://api.example.com/v1/users/{id}"),
        ("https://api.example.com:8443/v1/", "https://api.example.com:8443/v1/"),
    ],
)
def test_redact_url_hides_path_secrets_and_keeps_the_host_and_the_route(url: str, expected: str):
    assert redact_url(url) == expected


def test_redact_url_normalises_the_scheme_and_host_of_a_plain_url_and_nothing_else():
    assert (
        redact_url("HTTPS://API.Example.COM:8080/V1/Users?x=1")
        == "https://api.example.com:8080/V1/Users"
    )
    assert redact_url("HTTPS://$HOST/V1/Users") == "HTTPS://$HOST/V1/Users"  # a template as written
    assert redact_url("  https://a.example.com/x \n") == "https://a.example.com/x"  # trimmed


def test_redact_path_judges_segments_from_twelve_to_two_hundred_characters():
    assert redact_path("/aB1cD2eF3gH") == "/aB1cD2eF3gH"  # 11 characters: too short to judge
    assert redact_path("/aB1cD2eF3gHi") == "/[REDACTED]"  # 12
    assert redact_path("/" + "a" * 200) == "/" + "a" * 200  # long, but plain lower-case letters
    assert redact_path("/" + "a" * 201) == "/[REDACTED]"  # beyond any name
    assert redact_path("/" + "a-" * 99 + "aa") == "/" + "a-" * 99 + "aa"  # 200 characters, words
    assert redact_path("/" + "a-" * 100 + "a") == "/[REDACTED]"  # 201: too long for any name


def test_clip_keeps_text_of_exactly_the_limit_and_marks_a_cut():
    assert clip("abcde", 5) == "abcde"
    assert clip("abcdef", 5) == "abcd…"
    assert clip("  a  b ", 5) == "a b"


def test_mask_urls_masks_urls_inside_text_and_a_bare_telegram_token_anywhere():
    line = f'val u = "https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe" // ok'
    masked = mask_urls(line)
    assert TELEGRAM_SECRET not in masked and "api.telegram.org/bot[REDACTED]/getMe" in masked
    assert TELEGRAM_SECRET not in mask_urls(f"token = {TELEGRAM_TOKEN};")
    plain = "see https://developer.android.com/reference/androidx/room/Dao for details"
    assert mask_urls(plain) == plain
    assert (
        mask_urls("androidx.credentials:credentials:1.2.0")
        == "androidx.credentials:credentials:1.2.0"
    )
    assert (
        mask_urls("com.google.android.material:material:1.11.0")
        == "com.google.android.material:material:1.11.0"
    )


def test_scrub_and_make_id_never_let_a_path_secret_into_an_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/"
    assert TELEGRAM_SECRET not in scrub(url)
    assert TELEGRAM_SECRET not in make_id("base_url", url)
    assert make_id("base_url", url) == "base_url:https://api.telegram.org/bot[REDACTED]/"


def path_secret_project() -> dict[str, str]:
    t, ss, di, dt = TELEGRAM_TOKEN, SLACK_SECRET, DISCORD_ID, DISCORD_TOKEN
    return mini_app(
        extra={
            "app/build.gradle.kts": d(f"""
                plugins {{ id("com.android.application") }}
                android {{ namespace = "com.x" }}
                repositories {{
                    maven {{ url = uri("https://hooks.slack.com/services/{SLACK_IDS}/{ss}") }}
                }}
                """),
            "app/src/main/AndroidManifest.xml": d(f"""
                <manifest xmlns:android="http://schemas.android.com/apk/res/android">
                    <application android:name=".App">
                        <meta-data android:name="webhook"
                            android:value="https://hooks.slack.com/services/{SLACK_IDS}/{ss}"/>
                        <activity android:name=".Link" android:exported="true">
                            <intent-filter>
                                <action android:name="android.intent.action.VIEW"/>
                                <category android:name="android.intent.category.DEFAULT"/>
                                <data android:scheme="https" android:host="links.example.com"
                                    android:pathPrefix="/invite/{dt}"/>
                            </intent-filter>
                        </activity>
                    </application>
                </manifest>
                """),
            "app/src/main/res/navigation/nav.xml": d(f"""
                <navigation xmlns:android="http://schemas.android.com/apk/res/android"
                    xmlns:app="http://schemas.android.com/apk/res-auto" android:id="@+id/nav">
                    <fragment android:id="@+id/home" android:name="com.x.HomeFragment">
                        <deepLink app:uri="https://x.example.com/bot{t}/open"/>
                    </fragment>
                </navigation>
                """),
        },
        Net=f"""
            package com.x
            import retrofit2.Retrofit
            import retrofit2.http.GET
            import retrofit2.http.POST

            interface Bot {{
                @POST("bot{t}/sendMessage") fun send(): Int
                @GET("services/{SLACK_IDS}/{ss}") fun slack(): Int
                @POST("api/webhooks/{di}/{dt}") fun discord(): Int
            }}
            fun telegram() = Retrofit.Builder().baseUrl("https://api.telegram.org/bot{t}/").build()
            fun slack() = Retrofit.Builder().baseUrl("https://hooks.slack.com/services/{SLACK_IDS}/{ss}").build()
            fun discord() = Retrofit.Builder().baseUrl("https://discord.com/api/webhooks/{di}/{dt}").build()
            """,
        Nav=f"""
            package com.x
            import androidx.navigation.compose.composable
            import androidx.navigation.NavController
            fun androidx.navigation.NavGraphBuilder.g(nav: NavController) {{
                composable("bot{t}/chat") {{ }}
            }}
            fun go(nav: NavController) {{ nav.navigate("bot{t}/chat") }}
            """,
    )


def strings_in(value):
    """Every string anywhere in a JSON-like structure, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings_in(key)
            yield from strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings_in(item)


def test_no_url_path_secret_appears_anywhere_in_the_report_or_its_json():
    report = analyse(path_secret_project())
    no_errors(report)
    text = report.model_dump_json()
    for secret in PATH_SECRETS:
        assert secret not in text, f"leaked {secret[:8]}..."
    leaves = list(strings_in(report.model_dump(mode="json")))
    assert len(leaves) > 100
    for leaf in leaves:
        for secret in PATH_SECRETS:
            assert secret not in leaf, (secret[:8], leaf[:120])
    # the same, one object at a time, so a failure names the field
    for item in (*report.facts, *report.relationships):
        blob = item.model_dump_json()
        for secret in PATH_SECRETS:
            assert secret not in blob, (item.id, secret[:8])
    # and the serialisation that round-trips holds no secret either
    again = json.dumps(json.loads(text))
    for secret in PATH_SECRETS:
        assert secret not in again


def test_the_useful_part_of_a_url_survives_the_masking():
    report = analyse(path_secret_project())
    base = sorted(f.subject for f in report.facts if f.kind == "base_url")
    assert base == [
        "https://api.telegram.org/bot[REDACTED]/",
        "https://discord.com/api/webhooks/[REDACTED]",
        "https://hooks.slack.com/services/[REDACTED]",
    ]
    endpoint = {
        f.attributes["function"]: f.attributes["path"]
        for f in report.facts
        if f.kind == "http_endpoint"
    }
    assert endpoint == {
        "send": "bot[REDACTED]/sendMessage",
        "slack": "services/[REDACTED]",
        "discord": "api/webhooks/[REDACTED]",
    }
    meta = fact(report, "meta_data:webhook")
    assert str(meta.attributes["value"]).startswith("https://hooks.slack.com/services/")
    assert SLACK_SECRET not in str(meta.attributes["value"])
    assert any(
        "links.example.com/invite/[REDACTED]" in str(v)
        for f in report.facts
        for v in f.attributes.values()
    )
    assert ids(report, "deep_link") == ["https://x.example.com/bot[REDACTED]/open"]
    assert ids(report, "compose_route") == ["bot[REDACTED]/chat"]


def test_an_endpoint_service_and_base_urls_stay_distinct_after_masking():
    report = analyse(path_secret_project())
    assert len({f.id for f in report.facts if f.kind == "http_endpoint"}) == 3
    assert len({f.id for f in report.facts if f.kind == "base_url"}) == 3


# ===============================================================================================
# N1 - a Kotlin ``where`` constraint is not a superclass
# ===============================================================================================


def parse(text: str, path: str = "A.kt"):
    return parse_file(SourceFile(path, d(text)), AnalysisConfig())


def supers(info) -> dict[str, list[str]]:
    return {t.fqn: [s.written for s in t.supertypes] for t in info.types}


def test_a_where_bound_is_not_a_supertype():
    info = parse("""
        package p
        class Box<T> where T : Fragment
        class Holder<T>(val x: T) where T : Fragment, T : Parcelable
        class Multi<T, R>
            where T : Fragment,
                  R : Activity
        interface Source<T> where T : Fragment
        """)
    assert supers(info) == {"p.Box": [], "p.Holder": [], "p.Multi": [], "p.Source": []}


def test_a_real_supertype_before_a_where_clause_is_kept_and_the_bound_is_not():
    info = parse("""
        package p
        class A<T> : Base<T>() where T : Fragment
        class B<T> : Iface, Other where T : Activity
        abstract class C<T : Fragment> : Base()
        class D<T : Fragment>(val x: Int) : Base(), I where T : Any
        """)
    assert supers(info) == {
        "p.A": ["Base"],
        "p.B": ["Iface", "Other"],
        "p.C": ["Base"],
        "p.D": ["Base", "I"],
    }


def test_a_generic_class_with_a_where_bound_gets_no_fragment_role():
    report = analyse(
        mini_app(
            Box="""
            package com.x
            import androidx.fragment.app.Fragment
            class Box<T> where T : Fragment
            class Page : Fragment()
            """
        )
    )
    assert ids(report, "fragment") == ["com.x.Page"]
    assert ("type:com.x.Box", "type:com.x.Fragment") not in edges(report, "extends")


def test_a_where_clause_does_not_hide_the_primary_constructor_or_the_body():
    info = parse("""
        package p
        class A<T>(val x: Int, val y: String) where T : Comparable<T> {
            fun f() {}
        }
        """)
    decl = info.types[0]
    assert [p.name for p in decl.constructor_params] == ["x", "y"]
    assert [m.signature for m in decl.members] == ["f()"]
    assert decl.body is not None and decl.supertypes == ()


def test_modifiers_and_annotations_before_the_supertype_colon_do_not_hide_it():
    info = parse("""
        package p
        class A private constructor(val x: Int) : Base(), I
        class B internal constructor() : Base()
        class C @Inject constructor(val x: Int) : Base()
        open class D<T> private constructor() : Base<T>() where T : Any
        """)
    assert supers(info) == {
        "p.A": ["Base", "I"],
        "p.B": ["Base"],
        "p.C": ["Base"],
        "p.D": ["Base"],
    }


def test_java_generics_with_bounds_are_unaffected():
    info = parse(
        """
        package p;
        class A<T extends Fragment> extends Base<T> implements I {}
        """,
        "A.java",
    )
    assert supers(info) == {"p.A": ["Base", "I"]}


# ===============================================================================================
# N2 - annotations imported under another name
# ===============================================================================================


ROOM = """
    package com.x
    import androidx.room.{Dao}
    import androidx.room.{Database}
    import androidx.room.{Entity}
    import androidx.room.{PrimaryKey}
    import androidx.room.{Query}
    import androidx.room.RoomDatabase

    @{Entity_}(tableName = "notes") data class Note(@{PrimaryKey_} val id: Int, val title: String)
    @{Dao_} interface NoteDao {{ @{Query_}("SELECT * FROM notes") fun all(): List<Note> }}
    @{Database_}(entities = [Note::class], version = 1)
    abstract class AppDb : RoomDatabase() {{ abstract fun notes(): NoteDao }}
    """


def room_source(*, alias: bool) -> str:
    names = ("Dao", "Database", "Entity", "PrimaryKey", "Query")
    aliases = {
        "Dao": "RoomDao",
        "Database": "Db",
        "Entity": "Table",
        "PrimaryKey": "Pk",
        "Query": "Q",
    }
    values: dict[str, str] = {}
    for name in names:
        used = aliases[name] if alias else name
        values[name] = f"{name} as {used}" if alias else name
        values[f"{name}_"] = used
    return d(ROOM.format(**values))


DI = """
    package com.x
    import androidx.lifecycle.ViewModel
    import dagger.{Module}
    import dagger.{Provides}
    import dagger.hilt.{InstallIn}
    import dagger.hilt.android.lifecycle.{HiltViewModel}
    import dagger.hilt.components.SingletonComponent
    import javax.inject.{Inject}
    import javax.inject.{Singleton}

    class Api
    @{Module_} @{InstallIn_}(SingletonComponent::class)
    object NetModule {{ @{Provides_} @{Singleton_} fun api(): Api = Api() }}
    class Repo @{Inject_} constructor(val api: Api)
    @{HiltViewModel_} class Vm @{Inject_} constructor(val repo: Repo) : ViewModel()
    """


def di_source(*, alias: bool) -> str:
    aliases = {
        "Module": "DaggerModule",
        "Provides": "Prov",
        "InstallIn": "Install",
        "HiltViewModel": "HVM",
        "Inject": "Inj",
        "Singleton": "Single",
    }
    values: dict[str, str] = {}
    for name, short in aliases.items():
        used = short if alias else name
        values[name] = f"{name} as {used}" if alias else name
        values[f"{name}_"] = used
    return d(DI.format(**values))


def shape(report):
    return (
        {(f.kind, f.subject, f.status) for f in report.facts},
        {(r.kind, r.source, r.target, r.status) for r in report.relationships},
    )


def test_aliased_room_annotations_give_the_same_facts_as_the_plain_ones():
    plain = analyse(mini_app(Db=room_source(alias=False)))
    aliased = analyse(mini_app(Db=room_source(alias=True)))
    assert ids(plain, "room_entity") == ["com.x.Note"]
    assert ids(plain, "room_dao") == ["com.x.NoteDao"]
    assert ids(plain, "room_database") == ["com.x.AppDb"]
    assert shape(aliased) == shape(plain)
    assert fact(aliased, "room_entity:com.x.Note").status == "confirmed"
    assert fact(aliased, "room_dao:com.x.NoteDao").status == "confirmed"
    assert fact(aliased, "room_database:com.x.AppDb").status == "confirmed"


def test_aliased_dagger_and_hilt_annotations_give_the_same_facts_as_the_plain_ones():
    plain = analyse(mini_app(Di=di_source(alias=False)))
    aliased = analyse(mini_app(Di=di_source(alias=True)))
    assert ids(plain, "di_module") == ["com.x.NetModule"]
    assert ids(plain, "hilt_viewmodel") == ["com.x.Vm"]
    assert shape(aliased) == shape(plain)
    assert fact(aliased, "di_module:com.x.NetModule").status == "confirmed"
    assert fact(aliased, "hilt_viewmodel:com.x.Vm").status == "confirmed"


def test_an_alias_of_a_different_library_class_is_still_not_the_known_annotation():
    report = analyse(
        mini_app(
            A="""
            package com.x
            import com.other.Dao as RoomDao
            import com.other.Dao
            @RoomDao interface One
            @Dao interface Two
            """
        )
    )
    assert ids(report, "room_dao") == []


def test_an_alias_named_like_another_known_annotation_means_what_it_was_imported_as():
    report = analyse(
        mini_app(
            A="""
            package com.x
            import androidx.room.Entity as Dao
            import androidx.room.PrimaryKey
            @Dao data class Row(@PrimaryKey val id: Int)
            """
        )
    )
    assert ids(report, "room_entity") == ["com.x.Row"]
    assert ids(report, "room_dao") == []


def test_the_annotation_keeps_the_name_as_written_and_gains_the_catalogue_name():
    from androai_codegen.analysis.annotations import extract_annotations

    source = SourceFile("A.kt", "import androidx.room.Dao as RoomDao\n@RoomDao interface X\n")
    (annotation,) = extract_annotations(SrcView(source))
    assert annotation.name == "RoomDao"
    assert annotation.simple == "Dao"
    assert annotation.resolution == Resolution("androidx.room.Dao", "explicit")
    assert annotation.level(KNOWN_ANNOTATIONS["Dao"]) == "confirmed"


def test_a_wildcard_import_and_a_qualified_name_are_unchanged():
    report = analyse(
        mini_app(
            A="""
            package com.x
            import androidx.room.*
            @Dao interface One
            @androidx.room.Dao interface Two
            """
        )
    )
    assert ids(report, "room_dao") == ["com.x.One", "com.x.Two"]


def test_an_alias_keeps_its_own_name_unless_it_renames_a_catalogued_annotation():
    from androai_codegen.analysis.annotations import extract_annotations

    source = SourceFile(
        "A.kt",
        "import com.other.Dao as RoomDao\n"
        "import androidx.room.Query as Dao\n"
        "import com.other.Thing as Foo\n"
        "@RoomDao interface X\n@Dao fun f()\n@Foo class Y\n@Plain class Z\n",
    )
    found = {a.name: (a.simple, a.resolution.how) for a in extract_annotations(SrcView(source))}
    assert found == {
        "RoomDao": ("RoomDao", "explicit"),  # renames a class of another library: stays RoomDao
        "Dao": ("Query", "explicit"),  # renames a catalogued annotation: its catalogue name
        "Foo": ("Foo", "explicit"),
        "Plain": ("Plain", "unresolved"),
    }


# ===============================================================================================
# N3 - source in a language the analysis does not read
# ===============================================================================================


def unsupported(report):
    return [lim for lim in report.limitations if lim.code == "unsupported_source"]


def test_a_project_without_unsupported_sources_is_complete_and_says_nothing():
    report = analyse(mini_app())
    assert report.complete is True
    assert unsupported(report) == []
    assert "unsupported_source" not in report.stats.files_not_read


@pytest.mark.parametrize(
    "path", ["app/src/main/groovy/com/x/Util.groovy", "app/src/main/scala/com/x/Util.scala"]
)
def test_unread_jvm_source_is_reported_and_makes_the_report_incomplete(path: str):
    report = analyse(mini_app(extra={path: "class Util { }\n"}))
    (limitation,) = unsupported(report)
    assert limitation.scope == path
    assert limitation.affects_completeness is True
    assert report.complete is False
    assert report.stats.files_not_read["unsupported_source"] == 1


def test_nothing_is_concluded_from_the_absence_of_facts_when_jvm_source_was_not_read():
    report = analyse(mini_app(extra={"app/src/main/groovy/com/x/Boot.groovy": "class Boot {}\n"}))
    index = report.index()
    assert index.observation("activity") == "unknown"
    assert index.observation("room_dao") == "unknown"
    assert index.observation("activity", module="app") == "unknown"


@pytest.mark.parametrize(
    "path",
    [
        "app/src/main/cpp/native-lib.cpp",
        "app/src/main/cpp/native-lib.h",
        "lib/app.dart",
        "scripts/tool.py",
        "web/index.ts",
        "app/src/main/aidl/com/x/IFoo.aidl",
        "app/src/main/cpp/UPPER.CPP",
    ],
)
def test_unread_native_and_cross_platform_source_is_reported_but_does_not_make_it_incomplete(
    path: str,
):
    report = analyse(mini_app(extra={path: "// not analysed\n"}))
    (limitation,) = unsupported(report)
    assert limitation.scope == path
    assert limitation.affects_completeness is False
    assert report.complete is True
    assert report.index().observation("activity") == "not_observed"
    assert report.stats.files_not_read["unsupported_source"] == 1


def test_the_message_names_the_language():
    report = analyse(
        mini_app(extra={"a/B.groovy": "x", "a/c.cpp": "y", "a/d.scala": "z", "a/e.swift": "w"})
    )
    messages = {lim.scope: lim.message for lim in unsupported(report)}
    assert "Groovy" in messages["a/B.groovy"] and "missing" in messages["a/B.groovy"]
    assert "Scala" in messages["a/d.scala"]
    assert "C++" in messages["a/c.cpp"] and "outside" in messages["a/c.cpp"]
    assert "Swift" in messages["a/e.swift"]


def test_supported_and_unrelated_files_are_not_reported():
    report = analyse(
        mini_app(
            extra={
                "app/src/main/res/drawable/logo.png": "png",
                "README.md": "# hi",
                "gradle.properties": "a=b",
                "app/src/main/java/com/x/Own.java": "package com.x; class Own {}",
                "app/proguard-rules.pro": "-keep class x",
            }
        )
    )
    assert unsupported(report) == []
    assert report.complete is True


def test_many_unsupported_files_are_capped_and_the_rest_is_summarised():
    extra = {f"src/g/G{i}.groovy": "class G {}" for i in range(150)}
    extra.update({f"src/n/N{i}.cpp": "int x;" for i in range(130)})
    report = analyse(mini_app(extra=extra))
    found = unsupported(report)
    assert sum(1 for lim in found if lim.scope != "project") == 200  # 100 per group
    (summary,) = [lim for lim in found if lim.scope == "project"]
    assert "80 more" in summary.message
    assert summary.affects_completeness is True  # some of the omitted ones were Groovy
    assert report.stats.files_not_read["unsupported_source"] == 280
    assert report.complete is False


def test_overflow_of_only_native_files_does_not_make_the_report_incomplete():
    report = analyse(mini_app(extra={f"n/N{i}.c": "int x;" for i in range(130)}))
    (summary,) = [lim for lim in unsupported(report) if lim.scope == "project"]
    assert summary.affects_completeness is False
    assert report.complete is True


def summaries(report):
    return [lim for lim in unsupported(report) if lim.scope == "project"]


@pytest.mark.parametrize("suffix", [".groovy", ".cpp"])
def test_exactly_one_hundred_files_of_a_group_need_no_summary(suffix: str):
    report = analyse(mini_app(extra={f"s/F{i}{suffix}": "x" for i in range(100)}))
    assert summaries(report) == []
    assert len(unsupported(report)) == 100


def test_the_hundred_and_first_file_is_summarised_with_the_weight_of_its_group():
    jvm = analyse(mini_app(extra={f"s/F{i}.groovy": "x" for i in range(101)}))
    (summary,) = summaries(jvm)
    assert "1 more" in summary.message and summary.affects_completeness is True
    native = analyse(mini_app(extra={f"s/F{i}.cpp": "x" for i in range(101)}))
    (summary,) = summaries(native)
    assert "1 more" in summary.message and summary.affects_completeness is False
    assert native.complete is True


def test_groovy_under_the_cap_does_not_make_an_overflow_of_native_files_matter():
    extra = {f"j/F{i}.groovy": "x" for i in range(50)}
    extra.update({f"n/F{i}.cpp": "x" for i in range(101)})
    report = analyse(mini_app(extra=extra))
    (summary,) = summaries(report)
    assert "1 more" in summary.message
    assert summary.affects_completeness is False  # the overflow holds only native files
    assert report.complete is False  # the 50 listed Groovy files already did
    both = analyse(
        mini_app(
            extra={
                **{f"j/F{i}.groovy": "x" for i in range(101)},
                **{f"n/F{i}.cpp": "x" for i in range(101)},
            }
        )
    )
    (summary,) = summaries(both)
    assert "2 more" in summary.message and summary.affects_completeness is True
    # exactly a hundred Groovy files fill their group without overflowing it
    full = analyse(
        mini_app(
            extra={
                **{f"j/F{i}.groovy": "x" for i in range(100)},
                **{f"n/F{i}.cpp": "x" for i in range(101)},
            }
        )
    )
    (summary,) = summaries(full)
    assert "1 more" in summary.message and summary.affects_completeness is False


EXPECTED_UNSUPPORTED = {
    ".groovy": ("Groovy", True),
    ".gvy": ("Groovy", True),
    ".scala": ("Scala", True),
    ".aidl": ("AIDL", False),
    ".c": ("C", False),
    ".cc": ("C++", False),
    ".cpp": ("C++", False),
    ".cxx": ("C++", False),
    ".h": ("C/C++", False),
    ".hh": ("C++", False),
    ".hpp": ("C++", False),
    ".hxx": ("C++", False),
    ".dart": ("Dart", False),
    ".swift": ("Swift", False),
    ".js": ("JavaScript", False),
    ".jsx": ("JavaScript", False),
    ".mjs": ("JavaScript", False),
    ".ts": ("TypeScript", False),
    ".tsx": ("TypeScript", False),
    ".py": ("Python", False),
    ".rs": ("Rust", False),
    ".go": ("Go", False),
}


@pytest.mark.parametrize(("suffix", "expected"), sorted(EXPECTED_UNSUPPORTED.items()))
def test_every_unsupported_suffix_is_reported_with_its_language_and_its_weight(
    suffix: str, expected: tuple[str, bool]
):
    language, affects = expected
    path = f"src/thing{suffix}"
    report = analyse(mini_app(extra={path: "x"}))
    (limitation,) = unsupported(report)
    assert limitation.scope == path
    assert language in limitation.message
    assert limitation.affects_completeness is affects
    assert report.complete is (not affects)


def test_the_table_of_unsupported_suffixes_is_exactly_the_documented_one():
    from androai_codegen.analysis.analyser import UNSUPPORTED_SOURCE

    assert UNSUPPORTED_SOURCE == EXPECTED_UNSUPPORTED


def test_unsupported_sources_are_found_in_a_project_on_disk(tmp_path: Path):
    root = write_tree(
        tmp_path / "proj",
        mini_app(extra={"app/src/main/groovy/Util.groovy": "class Util {}\n", "n/a.cpp": "int a;"}),
    )
    report = analyse_workspace(Workspace(root))
    no_errors(report)
    scopes = {lim.scope: lim.affects_completeness for lim in unsupported(report)}
    assert scopes == {"app/src/main/groovy/Util.groovy": True, "n/a.cpp": False}
    assert report.complete is False


def test_the_report_with_unsupported_sources_is_deterministic():
    files = mini_app(extra={"x/A.groovy": "a", "x/B.scala": "b", "y/c.cpp": "c", "y/d.dart": "d"})
    first, second = analyse(dict(files)), analyse(dict(reversed(list(files.items()))))
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()


# ===============================================================================================
# an excerpt of a file whose first line is empty
# ===============================================================================================


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_an_empty_first_line_has_an_empty_excerpt_not_the_whole_file(newline: str):
    text = f"{newline}class A{newline}fun f() {{}}{newline}"
    lines = LineText(text, text)
    assert lines.excerpt_at_offset(0) == ""
    assert lines.excerpt_at_line(1) == ""
    assert lines.excerpt_at_line(2) == "class A"
    assert lines.excerpt_at_line(3) == "fun f() {}"
    assert lines.excerpt_at_offset(len(newline)) == "class A"


def test_a_blank_first_line_with_spaces_and_a_file_that_is_one_newline():
    text = "   \nclass A\n"
    lines = LineText(text, text)
    assert lines.excerpt_at_offset(0) == ""
    assert lines.excerpt_at_offset(1) == ""
    assert lines.excerpt_at_offset(3) == ""  # the newline that ends the blank first line
    assert lines.excerpt_at_offset(4) == "class A"  # the first character of line 2
    only = LineText("\n", "\n")
    assert only.excerpt_at_offset(0) == "" and only.excerpt_at_line(1) == ""
    empty = LineText("", "")
    assert empty.excerpt_at_offset(0) == "" and empty.excerpt_at_line(1) == ""


def test_the_evidence_of_a_declaration_below_an_empty_first_line_quotes_that_line():
    text = "\npackage com.x\n\nclass Own\n"
    report = analyse(mini_app(extra={"app/src/main/java/com/x/Own.kt": text}))
    evidence = fact(report, "type:com.x.Own").evidence[0]
    assert evidence.line == 4
    assert evidence.excerpt == "class Own"
    view = SrcView(SourceFile("Own.kt", text))
    assert view.evidence(0).excerpt == ""
    assert view.evidence(0).line == 1
