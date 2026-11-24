"""M2.0: the fact model, its invariants, the store that merges facts, and determinism."""

from __future__ import annotations

import json

import pytest
from analysis_fixtures import analyse, fact, hilt_project, no_errors
from pydantic import ValidationError

from androai_codegen.analysis import (
    AnalysisConfig,
    Evidence,
    Fact,
    Limitation,
    Relationship,
)
from androai_codegen.analysis.model import AnalysisStats
from androai_codegen.analysis.store import FactStore, make_id

EV = Evidence(path="app/Main.kt", line=3, excerpt="class Main")


def make_fact(**overrides) -> Fact:
    base = {
        "id": "type:a.B",
        "kind": "type",
        "subject": "a.B",
        "status": "confirmed",
        "basis": "source",
        "evidence": (EV,),
    }
    base.update(overrides)
    return Fact(**base)


# -- evidence -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "C:/Users/x/a.kt", "a\\b.kt", "../outside.kt", "a/../../b.kt", ""],
)
def test_evidence_rejects_paths_that_are_not_relative_project_paths(path):
    with pytest.raises(ValidationError):
        Evidence(path=path)


def test_evidence_excerpt_is_limited_to_80_characters():
    Evidence(path="a.kt", excerpt="x" * 80)
    with pytest.raises(ValidationError):
        Evidence(path="a.kt", excerpt="x" * 81)


def test_evidence_line_must_be_positive():
    with pytest.raises(ValidationError):
        Evidence(path="a.kt", line=0)


# -- fact status rules --------------------------------------------------------------------------


def test_a_confirmed_fact_needs_evidence():
    make_fact()
    with pytest.raises(ValidationError, match="evidence"):
        make_fact(evidence=())


def test_an_inferred_fact_needs_a_note_saying_what_was_assumed():
    make_fact(status="inferred", note="matched by name only")
    with pytest.raises(ValidationError, match="note"):
        make_fact(status="inferred", evidence=())


def test_an_unknown_fact_needs_a_reason_and_may_have_no_evidence():
    make_fact(status="unknown", evidence=(), reason="computed at build time")
    with pytest.raises(ValidationError, match="reason"):
        make_fact(status="unknown", evidence=())


@pytest.mark.parametrize("status", ["confirmed", "inferred"])
def test_only_an_unknown_fact_may_carry_a_reason(status):
    with pytest.raises(ValidationError, match="reason"):
        make_fact(status=status, note="n", reason="because")


def test_the_id_must_be_kind_and_subject():
    with pytest.raises(ValidationError, match="id"):
        make_fact(id="type:other")


@pytest.mark.parametrize("kind", ["Type", "1type", "a-b", "", "x" * 41])
def test_kinds_are_lower_snake_case(kind):
    with pytest.raises(ValidationError):
        make_fact(kind=kind, id=f"{kind}:a.B")


def test_attribute_names_must_be_lower_snake_case_and_values_bounded():
    with pytest.raises(ValidationError):
        make_fact(attributes={"Bad-Name": "x"})
    with pytest.raises(ValidationError):
        make_fact(attributes={"ok": "x" * 401})
    with pytest.raises(ValidationError):
        make_fact(attributes={"ok": tuple("x" for _ in range(201))})
    with pytest.raises(ValidationError):
        make_fact(attributes={"ok": ("y" * 201,)})


def test_attributes_are_stored_sorted_and_round_trip_through_json():
    made = make_fact(attributes={"b": 1, "a": ("x", "y"), "c": True})
    assert list(made.attributes) == ["a", "b", "c"]
    again = Fact.model_validate_json(made.model_dump_json())
    assert again == made
    assert isinstance(again.attributes["a"], tuple)
    assert again.attributes["c"] is True


def test_facts_are_frozen_and_reject_unknown_fields():
    made = make_fact()
    with pytest.raises(ValidationError):
        made.status = "inferred"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Fact(**{**made.model_dump(), "surprise": 1})


def test_relationship_follows_the_same_status_rules():
    Relationship(
        source="a:1", target="b:2", kind="uses", status="confirmed", basis="source", evidence=(EV,)
    )
    with pytest.raises(ValidationError):
        Relationship(source="a:1", target="b:2", kind="uses", status="confirmed", basis="source")
    with pytest.raises(ValidationError):
        Relationship(source="a:1", target="b:2", kind="uses", status="inferred", basis="source")
    with pytest.raises(ValidationError):
        Relationship(source="a:1", target="b:2", kind="uses", status="unknown", basis="source")
    rel = Relationship(
        source="a:1", target="b:2", kind="uses", status="unknown", basis="source", reason="r"
    )
    assert rel.id == "a:1>uses>b:2"


# -- the store ----------------------------------------------------------------------------------


def store() -> FactStore:
    return FactStore(AnalysisConfig())


def test_the_stronger_status_wins_and_a_stale_reason_is_dropped():
    s = store()
    s.fact("x", "one", basis="gradle", status="unknown", reason="not readable")
    s.fact("x", "one", basis="source", status="confirmed", evidence=[EV])
    frozen = s.freeze(AnalysisStats()).facts[0]
    assert frozen.status == "confirmed"
    assert frozen.reason is None
    assert frozen.basis == "source"


def test_a_weaker_statement_never_downgrades_a_fact():
    s = store()
    s.fact("x", "one", basis="source", status="confirmed", evidence=[EV])
    s.fact("x", "one", basis="heuristic", status="inferred", note="guess")
    s.fact("x", "one", basis="gradle", status="unknown", reason="r")
    frozen = s.freeze(AnalysisStats()).facts[0]
    assert frozen.status == "confirmed"
    assert frozen.basis == "source"


def test_evidence_and_tags_are_unioned_and_sorted():
    s = store()
    s.fact("x", "one", basis="source", evidence=[Evidence(path="b.kt", line=2)], tags=["t2"])
    s.fact("x", "one", basis="source", evidence=[Evidence(path="a.kt", line=9)], tags=["t1"])
    frozen = s.freeze(AnalysisStats()).facts[0]
    assert [e.path for e in frozen.evidence] == ["a.kt", "b.kt"]
    assert frozen.tags == ("t1", "t2")


def test_tuple_attributes_union_and_scalar_conflicts_pick_the_smaller_value():
    s = store()
    s.fact("x", "one", basis="source", evidence=[EV], attrs={"files": ("b",), "n": 5, "s": "zeta"})
    s.fact("x", "one", basis="source", evidence=[EV], attrs={"files": ("a",), "n": 3, "s": "alpha"})
    attrs = s.freeze(AnalysisStats()).facts[0].attributes
    assert attrs["files"] == ("a", "b")
    assert attrs["n"] == 3
    assert attrs["s"] == "alpha"


def test_merging_is_independent_of_the_order_facts_are_added():
    pieces = [
        dict(status="unknown", reason="r", basis="gradle", attrs={"v": 2}, tags=["a"]),
        dict(status="confirmed", evidence=[EV], basis="source", attrs={"v": 1}, tags=["b"]),
        dict(status="inferred", note="n", basis="heuristic", attrs={"v": 3}, tags=["c"]),
    ]
    results = set()
    for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2], [1, 2, 0]):
        s = store()
        for i in order:
            s.fact("x", "one", **pieces[i])
        results.add(s.freeze(AnalysisStats()).facts[0].model_dump_json())
    assert len(results) == 1


def test_annotate_adds_detail_without_changing_the_status():
    s = store()
    s.fact("x", "one", basis="source", status="inferred", note="by name", evidence=[EV])
    assert s.annotate(make_id("x", "one"), attrs={"ui": "compose"}, tags=["ui:compose"])
    assert not s.annotate(make_id("x", "missing"), attrs={"a": 1})
    frozen = s.freeze(AnalysisStats()).facts[0]
    assert frozen.status == "inferred"
    assert frozen.attributes["ui"] == "compose"
    assert "ui:compose" in frozen.tags


def test_relationships_merge_and_edges_to_missing_facts_are_dropped():
    s = store()
    a = s.fact("x", "a", basis="source", evidence=[EV])
    b = s.fact("x", "b", basis="source", evidence=[EV])
    s.relate(a, "uses", b, basis="source", status="inferred", note="n")
    s.relate(a, "uses", b, basis="source", status="confirmed", evidence=[EV])
    s.relate(a, "uses", "x:ghost", basis="source", evidence=[EV])
    report = s.freeze(AnalysisStats())
    assert len(report.relationships) == 1
    assert report.relationships[0].status == "confirmed"


def test_secrets_in_a_subject_or_attribute_are_scrubbed():
    s = store()
    token = "ghp_" + "a1B2c3D4" * 5
    s.fact("x", f"name {token}", basis="source", evidence=[EV], attrs={"v": f"t={token}"})
    frozen = s.freeze(AnalysisStats()).facts[0]
    assert token not in frozen.model_dump_json()


def test_the_fact_cap_drops_bulk_kinds_first_and_says_so():
    s = FactStore(AnalysisConfig(max_facts=5))
    keep = [s.fact("module", f"m{i}", basis="gradle", evidence=[EV]) for i in range(3)]
    for i in range(10):
        s.fact("member", f"c#f{i}", basis="source", evidence=[EV])
    s.relate(keep[0], "uses", make_id("member", "c#f9"), basis="source", evidence=[EV])
    report = s.freeze(AnalysisStats())
    assert len(report.facts) == 5
    assert {f.kind for f in report.facts} >= {"module"}
    assert any(m.code == "fact_cap_reached" and m.affects_completeness for m in report.limitations)
    assert report.complete is False
    assert report.relationships == ()  # its target was dropped, so the edge went with it


def test_completeness_depends_only_on_limitations_that_affect_it():
    s = store()
    s.fact("x", "a", basis="source", evidence=[EV])
    s.limit("groovy_dsl_partial", "build.gradle", "info", affects_completeness=False)
    assert s.freeze(AnalysisStats()).complete is True
    s.limit("malformed_source", "A.kt", "broken")
    assert s.freeze(AnalysisStats()).complete is False


def test_limitation_is_recorded_once_per_code_and_scope():
    s = store()
    s.limit("file_too_large", "a.kt", "first")
    s.limit("file_too_large", "a.kt", "second")
    s.limit("file_too_large", "b.kt", "third")
    assert [(m.scope, m.message) for m in s.limitations] == [("a.kt", "first"), ("b.kt", "third")]


def test_limitation_model_is_bounded():
    with pytest.raises(ValidationError):
        Limitation(code="file_too_large", scope="x", message="m" * 301)
    with pytest.raises(ValidationError):
        Limitation(code="made_up", scope="x", message="m")  # type: ignore[arg-type]


# -- determinism of a whole report --------------------------------------------------------------


def test_the_same_project_gives_the_same_report_every_time():
    files = hilt_project()
    first, second = analyse(files), analyse(files)
    assert first.fingerprint == second.fingerprint
    assert first.model_dump_json() == second.model_dump_json()


def test_the_order_files_are_listed_in_does_not_change_the_report():
    files = hilt_project()
    reversed_files = dict(reversed(list(files.items())))
    assert analyse(files).model_dump_json() == analyse(reversed_files).model_dump_json()


def test_the_fingerprint_changes_when_a_fact_changes():
    files = hilt_project()
    changed = dict(files)
    path = "core/data/src/main/java/com/example/notes/data/NotesDatabase.kt"
    changed[path] = changed[path].replace("version = 3", "version = 4")
    assert analyse(files).fingerprint != analyse(changed).fingerprint


def test_a_report_contains_no_timestamps_hostnames_or_absolute_paths():
    text = analyse(hilt_project()).model_dump_json()
    assert "\\\\" not in text
    for needle in ("C:\\", "/home/", "/tmp/", "/Users/"):
        assert needle not in text


def test_every_fact_of_a_real_project_satisfies_the_status_rules():
    report = analyse(hilt_project())
    no_errors(report)
    assert report.facts
    for item in report.facts:
        if item.status == "confirmed":
            assert item.evidence
        if item.status == "inferred":
            assert item.note
        if item.status == "unknown":
            assert item.reason
    for rel in report.relationships:
        if rel.status == "confirmed":
            assert rel.evidence


def test_the_report_carries_an_untrusted_content_notice():
    report = analyse(hilt_project())
    assert "untrusted" in report.notice
    assert report.analysis_version


def test_report_json_round_trips():
    report = analyse(hilt_project())
    again = type(report).model_validate(json.loads(report.model_dump_json()))
    assert again.fingerprint == report.fingerprint
    assert again.model_dump_json() == report.model_dump_json()


def test_a_fact_can_be_looked_up_by_its_id():
    report = analyse(hilt_project())
    found = fact(report, "room_database:com.example.notes.data.NotesDatabase")
    assert found.attributes["version"] == 3
