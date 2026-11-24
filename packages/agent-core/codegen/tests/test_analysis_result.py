"""M2.10: the inventory, the result wrapper, its JSON, and the freshness check.

What is pinned here:

* two fingerprints, never confused: ``report.fingerprint`` hashes the analysis output and
  ``provenance.input_fingerprint`` hashes the project input;
* an unattested or absent import can be analysed, and the result says it is not eligible; nothing
  creates an attestation;
* ``loads`` refuses what is too large, too deep, malformed, mistyped, repeated, of another version
  or inconsistent with itself, and cannot detect an edit that also rewrote the hashes (nothing is
  signed);
* ``check_freshness`` finds added, deleted and changed files, never opens a protected file, and says
  ``unknown`` when it cannot tell.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from analysis_fixtures import (
    ANDROID_NS,
    convention_project,
    hilt_project,
    java_xml_project,
    koin_project,
    mini_app,
)
from ingest_helpers import import_dir, minimal_project, write_tree

from androai_codegen.analysis import (
    ANALYSIS_VERSION,
    AnalysisConfig,
    AnalysisResult,
    Eligibility,
    InputFile,
    InvalidAnalysisResult,
    InventoryItem,
    analyse_import_result,
    analyse_mapping_result,
    analyse_workspace_result,
    build_inventory,
    check_freshness,
    dumps_result,
    loads_result,
)
from androai_codegen.analysis.freshness import MAX_CHANGED_PATHS, hash_text
from androai_codegen.analysis.inventory import MAX_ITEMS_PER_SECTION
from androai_codegen.analysis.store import report_fingerprint
from androai_codegen.editing.workspace import Workspace

PROJECTS = {
    "hilt": hilt_project,
    "java_xml": java_xml_project,
    "koin": koin_project,
    "convention": convention_project,
}


def result_of(files=None, **kwargs) -> AnalysisResult:
    result = analyse_mapping_result(files if files is not None else hilt_project(), **kwargs)
    assert [m for m in result.report.limitations if m.code == "extractor_error"] == []
    return result


def imported_project(tmp_path: Path, files: dict | None = None):
    """A project imported from disk (with the attestation the helpers record)."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return import_dir(write_tree(tmp_path / "src", files or minimal_project()), data)


def edited(result: AnalysisResult, change) -> str:
    """The JSON of ``result`` after ``change(dict)`` has modified it."""
    data = json.loads(dumps_result(result))
    change(data)
    return json.dumps(data)


# -- 1. the inventory ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROJECTS)
def test_every_inventory_entry_points_at_facts_and_has_evidence_or_a_reason(name: str):
    result = result_of(PROJECTS[name]())
    known = {f.id for f in result.report.facts}
    assert result.inventory.fact_ids() <= known
    seen = 0
    for section in result.inventory.sections().values():
        for item in section.items:
            seen += 1
            assert item.fact_ids and set(item.fact_ids) <= known
            assert item.evidence or item.reason
            fact = next(f for f in result.report.facts if f.id == item.fact_ids[0])
            assert (item.status, item.kind, item.name) == (fact.status, fact.kind, fact.subject)
            if item.status == "unknown":
                assert item.reason
    assert seen > 20


def test_an_inventory_entry_without_a_fact_or_without_evidence_or_reason_cannot_exist():
    with pytest.raises(ValueError):
        InventoryItem(kind="x", name="n", status="unknown", fact_ids=())
    with pytest.raises(ValueError, match="evidence or a reason"):
        InventoryItem(kind="x", name="n", status="confirmed", fact_ids=("x:n",))


def test_the_sections_group_the_facts_of_the_project():
    inv = result_of().inventory
    assert {i.name for i in inv.identity.items} == {"app", "core/data"}
    app = next(i for i in inv.identity.items if i.name == "app")
    assert app.attributes["namespace"] and app.kind == "module"
    assert {"gradle_plugin", "sdk_level"} <= set(inv.build.counts)
    assert "entry_point" in inv.components.counts and "application" in inv.components.counts
    assert "app_flow" in inv.screens_and_navigation.counts
    assert "compose_route" in inv.screens_and_navigation.counts
    assert {"room_database", "room_dao", "retrofit_service"} <= set(inv.data_and_network.counts)
    assert "permission" in inv.permissions.counts
    assert "technology" in inv.integrations.counts


def test_a_module_whose_identity_cannot_be_read_is_a_module_but_not_an_identity():
    files = mini_app()
    files["settings.gradle.kts"] = 'include(":app", ":lib")\n'
    files["lib/build.gradle.kts"] = 'plugins { id("com.example.convention.library") }\n'
    inv = result_of(files).inventory
    assert {i.name for i in inv.identity.items} == {"app"}
    assert {i.name for i in inv.modules.items if i.kind == "module"} == {"app", "lib"}


def test_conventions_are_split_across_sections_by_their_dimension():
    inv = result_of().inventory
    languages = {i.attributes["dimension"] for i in inv.languages_and_ui.items}
    assert languages == {"language", "ui_toolkit"}
    architecture = {
        i.attributes["dimension"] for i in inv.architecture.items if i.kind == "convention"
    }
    assert "language" not in architecture and "testing" not in architecture
    assert {i.attributes["dimension"] for i in inv.tests.items} == {"testing"}


def test_unreadable_things_are_unknown_entries_not_empty_sections():
    inv = result_of(convention_project()).inventory
    unknown = [
        item
        for section in inv.sections().values()
        for item in section.items
        if item.status == "unknown"
    ]
    assert unknown and all(item.reason for item in unknown)
    assert inv.complete is False or any(m.affects_completeness for m in inv.limitations) is False


def test_the_architecture_section_holds_the_viewmodels_as_well_as_the_conventions():
    inv = result_of().inventory
    kinds = {item.kind for item in inv.architecture.items}
    assert "convention" in kinds and kinds & {"viewmodel", "hilt_viewmodel"}
    assert all(not section.truncated for section in inv.sections().values())


def test_a_section_with_exactly_the_limit_is_not_truncated():
    permissions = "".join(
        f'<uses-permission android:name="com.x.permission.P{i}"/>'
        for i in range(MAX_ITEMS_PER_SECTION)
    )
    manifest = f"<manifest {ANDROID_NS}>{permissions}<application/></manifest>"
    section = result_of(
        mini_app(extra={"app/src/main/AndroidManifest.xml": manifest})
    ).inventory.permissions
    assert section.total == len(section.items) == MAX_ITEMS_PER_SECTION
    assert section.truncated is False


def test_a_section_is_cut_at_its_limit_but_counts_everything():
    permissions = "".join(
        f'<uses-permission android:name="com.x.permission.P{i}"/>'
        for i in range(MAX_ITEMS_PER_SECTION + 50)
    )
    manifest = f"<manifest {ANDROID_NS}>{permissions}<application/></manifest>"
    inv = result_of(mini_app(extra={"app/src/main/AndroidManifest.xml": manifest})).inventory
    section = inv.permissions
    assert section.total == MAX_ITEMS_PER_SECTION + 50
    assert section.truncated is True and len(section.items) == MAX_ITEMS_PER_SECTION
    assert section.counts["permission"] == MAX_ITEMS_PER_SECTION + 50


def test_the_counts_of_an_untruncated_section_match_its_items():
    for section in result_of().inventory.sections().values():
        if not section.truncated:
            assert section.total == len(section.items) == sum(section.counts.values())
            assert sum(section.by_status.values()) == section.total


def test_the_inventory_depends_only_on_the_report():
    result = result_of()
    assert build_inventory(result.report) == build_inventory(result.report)
    assert build_inventory(result.report).report_fingerprint == result.report.fingerprint
    again = result_of(dict(reversed(list(hilt_project().items()))))
    assert again.inventory == result.inventory


def test_the_protection_summary_counts_what_was_not_read_and_what_an_import_found(tmp_path: Path):
    files = minimal_project(**{"app__src__main__res__raw__big.bin": b"\x00" * 10})
    files[".env"] = "API_KEY=abcd1234efgh5678ijkl9012mnop3456\n"
    imported = imported_project(tmp_path, files)
    result = analyse_import_result(imported)
    protection = result.inventory.protection
    assert protection.files_not_read.get("protected", 0) >= 1
    assert protection.secret_findings is not None and protection.secret_findings >= 1
    assert protection.secret_kinds
    assert "abcd1234efgh5678ijkl9012mnop3456" not in dumps_result(result)  # counts, never values


# -- 2. the result, provenance and eligibility ---------------------------------------------------


def test_an_analysis_with_no_import_record_is_not_eligible_and_says_why():
    result = result_of()
    assert result.eligibility.eligible_for_modification is False
    assert "no import record" in result.eligibility.reason
    assert result.provenance.imported is None
    assert result.analysis_version == ANALYSIS_VERSION == result.report.analysis_version


def test_an_import_with_an_attestation_gives_an_eligible_result_that_names_the_import(
    tmp_path: Path,
):
    imported = imported_project(tmp_path)
    result = analyse_import_result(imported)
    assert result.eligibility.eligible_for_modification is True
    assert result.eligibility.import_id == imported.report.import_id
    assert "ownership attestation (own)" in result.eligibility.reason
    link = result.provenance.imported
    assert link is not None
    assert (link.import_id, link.content_fingerprint, link.basis) == (
        imported.report.import_id,
        imported.report.content_fingerprint,
        "own",
    )
    assert "I wrote this application" not in dumps_result(result)  # the statement is not copied


def test_an_import_that_is_not_marked_eligible_is_analysed_and_recorded_as_not_eligible(
    tmp_path: Path,
):
    imported = imported_project(tmp_path)
    report = imported.report.model_copy(update={"eligible_for_modification": False})
    result = analyse_workspace_result(
        imported.workspace, protection=imported.protection, import_report=report
    )
    assert result.eligibility.eligible_for_modification is False
    assert result.eligibility.import_id == report.import_id
    assert result.report.facts  # it was still analysed


def test_analysing_a_workspace_without_its_import_record_never_upgrades_it(tmp_path: Path):
    imported = imported_project(tmp_path)
    result = analyse_workspace_result(imported.workspace, protection=imported.protection)
    assert result.eligibility.eligible_for_modification is False


def test_a_result_cannot_claim_eligibility_without_an_import_record():
    result = result_of()
    with pytest.raises(ValueError, match="only through an import record"):
        AnalysisResult.model_validate(
            {
                **result.model_dump(),
                "eligibility": Eligibility(eligible_for_modification=True, reason="x").model_dump(),
            }
        )


def test_the_two_fingerprints_are_different_things_and_move_independently():
    base = result_of(mini_app(K="package com.x\nclass K\n"))
    assert base.report.fingerprint != base.provenance.input_fingerprint
    # a binary file the analysis cannot use changes the input but not the output
    files = mini_app(K="package com.x\nclass K\n")
    files["app/src/main/assets/blob.bin"] = b"\x00\x01"
    more = result_of(files)
    assert more.provenance.input_fingerprint != base.provenance.input_fingerprint
    assert more.report.fingerprint == base.report.fingerprint
    # a changed text file changes both
    changed = result_of(mini_app(K="package com.x\nclass K2\n"))
    assert changed.provenance.input_fingerprint != base.provenance.input_fingerprint
    assert changed.report.fingerprint != base.report.fingerprint


def test_the_input_manifest_lists_read_files_by_hash_and_other_files_by_path_only():
    files = mini_app(K="package com.x\nclass K\n")
    files["app/src/main/assets/blob.bin"] = b"\x00"
    manifest = {f.path: f.sha256 for f in result_of(files).provenance.input_files}
    kt = "app/src/main/java/com/x/K.kt"
    assert manifest[kt] == hash_text("package com.x\nclass K\n")
    assert manifest["app/src/main/assets/blob.bin"] is None
    assert list(manifest) == sorted(manifest)


def test_the_recorded_configuration_is_the_one_the_analysis_used():
    result = result_of(config=AnalysisConfig(max_flow_screens=7))
    assert result.provenance.config["max_flow_screens"] == 7
    assert result.provenance.config["deadline_seconds"] is None


def test_an_input_file_rejects_a_bad_path_or_digest():
    for bad in ("/abs", "a\\b", "../up", ""):
        with pytest.raises(ValueError):
            InputFile(path=bad)
    with pytest.raises(ValueError):
        InputFile(path="a.kt", sha256="xyz")
    assert InputFile(path="a.kt", sha256="0" * 64).sha256 == "0" * 64


# -- 3. JSON -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROJECTS)
def test_a_result_survives_a_round_trip_exactly(name: str):
    result = result_of(PROJECTS[name]())
    text = dumps_result(result)
    assert loads_result(text) == result
    assert loads_result(text.encode("utf-8")) == result
    assert dumps_result(loads_result(text)) == text


def test_the_json_is_canonical_ascii_with_sorted_keys_and_one_trailing_newline():
    text = dumps_result(result_of())
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text.isascii()
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n" == text


def test_the_json_holds_no_timestamp_and_no_host_path(tmp_path: Path):
    imported = imported_project(tmp_path)
    text = dumps_result(analyse_import_result(imported))
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    assert imported.report.created_at.isoformat() not in text
    assert "created_at" not in text


def test_the_json_does_not_depend_on_the_order_the_files_were_given():
    files = hilt_project()
    assert dumps_result(result_of(dict(files))) == dumps_result(
        result_of(dict(reversed(list(files.items()))))
    )


def test_the_json_is_identical_under_hash_randomisation():
    script = (
        "import hashlib\n"
        "from analysis_fixtures import hilt_project\n"
        "from androai_codegen.analysis import analyse_mapping_result, dumps_result\n"
        "print(hashlib.sha256(dumps_result(analyse_mapping_result(hilt_project())).encode()).hexdigest())\n"
    )
    outputs = set()
    for seed in ("0", "1", "31337"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join(sys.path))
        done = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True
        )
        outputs.add(done.stdout.strip())
    assert len(outputs) == 1


@pytest.mark.parametrize(
    ("label", "payload", "message"),
    [
        ("not json", "this is not json", "not valid JSON"),
        ("empty", "", "not valid JSON"),
        ("a list", "[]", "schema"),
        ("nan", '{"schema_version": NaN}', "NaN"),
        ("infinity", '{"x": Infinity}', "Infinity"),
        ("repeated key", '{"schema_version": 1, "schema_version": 1}', "repeats a key"),
    ],
)
def test_loads_refuses_what_is_not_a_result(label, payload, message):
    with pytest.raises(InvalidAnalysisResult, match=message):
        loads_result(payload)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(schema_version="1"),
        lambda d: d["report"].update(complete="true"),
        lambda d: d["provenance"].update(capped="false"),
        lambda d: d["provenance"]["config"].update(max_files=5.0),
    ],
    ids=[
        "a string for the version",
        "a string for a bool",
        "a string for the cap flag",
        "a float for an int",
    ],
)
def test_loads_does_not_coerce_one_type_into_another(change):
    with pytest.raises(InvalidAnalysisResult):
        loads_result(edited(result_of(), change))


def test_loads_refuses_what_is_too_large_before_parsing_it():
    text = dumps_result(result_of())
    with pytest.raises(InvalidAnalysisResult, match="the limit is"):
        loads_result(text, max_bytes=len(text) - 1)
    assert loads_result(text, max_bytes=len(text.encode()))  # exactly at the limit is fine


def test_loads_refuses_deep_nesting_without_recursing():
    for depth in (65, 1_000, 200_000):
        with pytest.raises(InvalidAnalysisResult, match="nested deeper"):
            loads_result("[" * depth + "]" * depth)
        with pytest.raises(InvalidAnalysisResult, match="nested deeper"):
            loads_result('{"a":' * depth + "1" + "}" * depth)
    with pytest.raises(InvalidAnalysisResult, match="nested deeper"):
        loads_result(dumps_result(result_of()), max_depth=3)


def test_brackets_inside_strings_do_not_count_as_nesting():
    from androai_codegen.analysis.result import _depth_of

    assert _depth_of('{"a": "[[[[[[[[[[[[", "b": "\\"[["}', 10) == 1
    assert _depth_of("[[[]]]", 10) == 3


def test_loads_refuses_invalid_utf8():
    with pytest.raises(InvalidAnalysisResult, match="UTF-8"):
        loads_result(b"\xff\xfe{")


@pytest.mark.parametrize(
    ("label", "change", "message"),
    [
        ("an unknown field", lambda d: d.update(extra=1), "extra"),
        ("a version that is not supported", lambda d: d.update(schema_version=2), "unsupported"),
        (
            "a string where a number is required",
            lambda d: d["provenance"]["config"].update(max_files="5"),
            "schema",
        ),
        (
            "an analysis version that disagrees with the report",
            lambda d: d.update(analysis_version="m2a-1"),
            "different analysis versions",
        ),
        (
            "a report that does not match its fingerprint",
            lambda d: d["report"]["facts"][0]["attributes"].update(zzz=1),
            "fingerprint",
        ),
        (
            "a report whose fingerprint was changed",
            lambda d: d["report"].update(fingerprint="0" * 64),
            "fingerprint",
        ),
        (
            "an inventory built from another report",
            lambda d: d["inventory"].update(report_fingerprint="0" * 64),
            "not built from this report",
        ),
        (
            "an input manifest that does not match its fingerprint",
            lambda d: d["provenance"]["input_files"][0].update(sha256="1" * 64),
            "input manifest",
        ),
        (
            "a configuration that does not match its digest",
            lambda d: d["provenance"]["config"].update(max_files=1),
            "digest",
        ),
        (
            "a boolean where a string is required",
            lambda d: d["eligibility"].update(reason=True),
            "schema",
        ),
        ("a bad hash", lambda d: d["provenance"].update(config_digest="xyz"), "schema"),
    ],
)
def test_loads_refuses_a_result_that_is_wrong_or_inconsistent(label, change, message):
    result = result_of()
    with pytest.raises(InvalidAnalysisResult, match=message):
        loads_result(edited(result, change))


def test_loads_refuses_an_inventory_that_points_at_a_fact_the_report_lacks():
    result = result_of()

    def change(data):
        data["inventory"]["identity"]["items"][0]["fact_ids"] = ["module:does-not-exist"]

    with pytest.raises(InvalidAnalysisResult, match="facts the report does not have"):
        loads_result(edited(result, change))


def test_loads_refuses_a_claim_of_eligibility_without_an_import():
    def change(data):
        data["eligibility"]["eligible_for_modification"] = True

    with pytest.raises(InvalidAnalysisResult, match="only through an import record"):
        loads_result(edited(result_of(), change))


def test_an_edit_that_also_rewrites_the_hashes_is_accepted_because_nothing_is_signed():
    """``loads`` checks that a result agrees with itself. It cannot tell a genuine result from one
    that was edited together with its fingerprints: that would need a signature, and there is none."""
    result = result_of(mini_app(K="package com.x\nclass K\n"))
    data = json.loads(dumps_result(result))
    data["report"]["facts"][0]["subject"] = "edited-by-hand"
    data["report"]["facts"][0]["id"] = f"{data['report']['facts'][0]['kind']}:edited-by-hand"
    forged = loads_result.__globals__["AnalysisReport"].model_validate(
        {**data["report"], "fingerprint": ""}
    )
    fingerprint = report_fingerprint(forged)
    data["report"]["fingerprint"] = fingerprint
    data["inventory"]["report_fingerprint"] = fingerprint
    data["inventory"] = json.loads(
        json.dumps(data["inventory"])
    )  # (its entries may now name a fact that was renamed)
    for section in data["inventory"].values():
        if isinstance(section, dict) and "items" in section:
            section["items"] = []
    loaded = loads_result(json.dumps(data))
    assert loaded.report.facts[0].subject == "edited-by-hand"


# -- 4. freshness --------------------------------------------------------------------------------


def project() -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = dict(
        mini_app(
            A="package com.x\nclass A\n",
            B="package com.x\nclass B\n",
        )
    )
    files["app/src/main/assets/blob.bin"] = b"\x00\x01"
    return files


A = "app/src/main/java/com/x/A.kt"
B = "app/src/main/java/com/x/B.kt"
BLOB = "app/src/main/assets/blob.bin"


def test_an_unchanged_project_is_fresh():
    files = project()
    verdict = check_freshness(result_of(files), files)
    assert verdict.state == "fresh" and verdict.changed == verdict.added == verdict.deleted == ()
    assert verdict.files_checked == len(files)


def test_a_changed_text_file_makes_the_result_stale_and_is_named():
    files = project()
    result = result_of(files)
    files[A] = "package com.x\nclass A { val x = 1 }\n"
    verdict = check_freshness(result, files)
    assert verdict.state == "stale"
    assert (verdict.changed, verdict.added, verdict.deleted) == ((A,), (), ())
    assert verdict.changed_count == 1 and "1 changed" in verdict.reason


def test_an_added_and_a_deleted_file_are_found():
    files = project()
    result = result_of(files)
    del files[B]
    files["app/src/main/java/com/x/C.kt"] = "package com.x\nclass C\n"
    verdict = check_freshness(result, files)
    assert verdict.state == "stale"
    assert verdict.deleted == (B,) and verdict.added == ("app/src/main/java/com/x/C.kt",)
    assert verdict.changed == ()


def test_a_binary_file_appearing_or_disappearing_matters_but_its_content_does_not():
    files = project()
    result = result_of(files)
    files[BLOB] = b"\x09\x09\x09\x09"  # same file, other bytes: the analysis never used them
    assert check_freshness(result, files).state == "fresh"
    del files[BLOB]
    verdict = check_freshness(result, files)
    assert verdict.state == "stale" and verdict.deleted == (BLOB,)
    files[BLOB] = b""
    files["app/src/main/assets/new.bin"] = b"\x00"
    assert check_freshness(result, files).added == ("app/src/main/assets/new.bin",)


def test_a_whitespace_change_in_a_text_file_counts_as_a_change():
    files = project()
    result = result_of(files)
    files[A] = str(files[A]) + "\n"
    assert check_freshness(result, files).changed == (A,)


def test_a_byte_order_mark_alone_does_not_change_what_the_analysis_saw():
    files = project()
    result = result_of(files)
    files[A] = "﻿" + str(files[A])
    assert check_freshness(result, files).state == "fresh"


def test_an_old_analysis_version_is_incompatible_and_stale_whatever_the_files_say():
    files = project()
    old = result_of(files).model_copy(update={"analysis_version": "m2a-1"})
    verdict = check_freshness(old, files)
    assert verdict.state == "stale" and "incompatible analysis version" in verdict.reason


def test_a_different_configuration_is_stale_and_the_recorded_one_is_used_otherwise():
    files = project()
    result = result_of(files, config=AnalysisConfig(max_file_bytes=20))
    # the same configuration, or none: fresh (A.kt is longer than 20 bytes and was not read)
    assert check_freshness(result, files).state == "fresh"
    assert check_freshness(result, files, config=AnalysisConfig(max_file_bytes=20)).state == "fresh"
    other = check_freshness(result, files, config=AnalysisConfig())
    assert other.state == "stale" and "configuration differs" in other.reason


def test_a_result_with_settings_this_code_lacks_is_incompatible():
    files = project()
    result = result_of(files)
    provenance = result.provenance.model_copy(
        update={"config": {**result.provenance.config, "setting_from_the_future": 1}}
    )
    verdict = check_freshness(result.model_copy(update={"provenance": provenance}), files)
    assert verdict.state == "unknown" or "incompatible configuration" in verdict.reason


def test_a_file_that_becomes_too_large_to_read_is_a_change():
    files = project()
    result = result_of(files, config=AnalysisConfig(max_file_bytes=200))
    files[A] = "package com.x\nclass A\n" + "// padding\n" * 50
    verdict = check_freshness(result, files)
    assert verdict.state == "stale" and verdict.changed == (A,)


def test_a_tracked_change_is_stale_and_an_unchanged_capped_analysis_is_unknown(tmp_path: Path):
    imported = imported_project(tmp_path)
    result = analyse_import_result(imported, config=AnalysisConfig(max_files=2))
    assert result.provenance.capped is True and len(result.provenance.input_files) == 2
    unchanged = check_freshness(result, imported.workspace, protection=imported.protection)
    assert unchanged.state == "unknown" and "file limit" in unchanged.reason
    tracked = next(f.path for f in result.provenance.input_files if f.sha256)
    imported.workspace.write_bytes(tracked, b"<manifest>changed</manifest>\n")
    changed = check_freshness(result, imported.workspace, protection=imported.protection)
    assert changed.state == "stale" and tracked in changed.changed


def test_the_lists_of_changed_files_are_bounded_but_the_counts_are_exact():
    files = {**project()}
    for i in range(120):
        files[f"app/src/main/java/com/x/G{i}.kt"] = f"package com.x\nclass G{i}\n"
    result = result_of(files)
    for i in range(120):
        files[f"app/src/main/java/com/x/G{i}.kt"] = f"package com.x\nclass G{i}X\n"
    verdict = check_freshness(result, files)
    assert verdict.changed_count == 120 and len(verdict.changed) == MAX_CHANGED_PATHS
    assert verdict.truncated is True
    assert list(verdict.changed) == sorted(verdict.changed)


def test_an_input_manifest_that_disagrees_with_its_fingerprint_is_unknown():
    files = project()
    result = result_of(files)
    provenance = result.provenance.model_copy(update={"input_fingerprint": "0" * 64})
    verdict = check_freshness(result.model_copy(update={"provenance": provenance}), files)
    assert verdict.state == "unknown" and "does not match its fingerprint" in verdict.reason


def test_a_project_that_cannot_be_read_now_is_unknown_not_stale():
    result = result_of(project())
    verdict = check_freshness(result, {"../outside.kt": "x"})
    assert verdict.state == "unknown" and "could not be read" in verdict.reason


def test_a_workspace_is_checked_with_the_same_rules_and_a_protected_file_is_never_opened(
    tmp_path: Path, monkeypatch
):
    files = minimal_project()
    files[".env"] = "API_KEY=abcd1234efgh5678ijkl9012mnop3456\n"
    imported = imported_project(tmp_path, files)
    opened: list[str] = []
    real_bytes = Workspace.read_bytes

    def spy(self, rel_path):
        opened.append(rel_path)
        return real_bytes(self, rel_path)

    monkeypatch.setattr(Workspace, "read_bytes", spy)
    result = analyse_import_result(imported)
    verdict = check_freshness(result, imported.workspace, protection=imported.protection)
    assert verdict.state == "fresh"
    assert ".env" not in opened and opened  # (and something else was)
    assert any(f.path == ".env" and f.sha256 is None for f in result.provenance.input_files)

    # the protected file's content may change without the result going stale: it was never used
    real_write = imported.workspace.write_bytes
    real_write(".env", b"API_KEY=zzzz1234efgh5678ijkl9012mnop3456\n")
    assert (
        check_freshness(result, imported.workspace, protection=imported.protection).state == "fresh"
    )
    assert ".env" not in opened
    # a source file that changes does
    main = "app/src/main/java/com/example/demo/Main.kt"
    real_write(main, b"package com.example.demo\n\nclass Main2\n")
    stale = check_freshness(result, imported.workspace, protection=imported.protection)
    assert stale.state == "stale" and stale.changed == (main,)
    # and a protected file that is removed is a deleted path
    imported.workspace.delete(".env")
    assert (
        ".env"
        in check_freshness(result, imported.workspace, protection=imported.protection).deleted
    )


def test_a_workspace_that_is_removed_afterwards_reads_as_every_file_deleted(tmp_path: Path):
    imported = imported_project(tmp_path)
    result = analyse_import_result(imported)
    shutil.rmtree(imported.workspace.root)
    verdict = check_freshness(result, imported.workspace, protection=imported.protection)
    assert verdict.state == "stale" and verdict.deleted_count == len(result.provenance.input_files)


def test_freshness_after_the_json_round_trip_gives_the_same_answer():
    files = project()
    result = result_of(files)
    again = loads_result(dumps_result(result))
    files[A] = "package com.x\nclass A { }\n"
    assert check_freshness(again, files) == check_freshness(result, files)


# -- 5. size and speed ---------------------------------------------------------------------------


def test_a_large_project_makes_a_result_quickly_and_it_survives_the_round_trip():
    started = time.perf_counter()
    files = mini_app()
    for i in range(1_500):
        files[f"app/src/main/java/com/x/Big{i}.kt"] = f"package com.x\nclass Big{i}\n"
    result = result_of(files)
    text = dumps_result(result)
    assert loads_result(text) == result
    assert check_freshness(result, files).state == "fresh"
    assert time.perf_counter() - started < 60


def test_hostile_json_of_every_shape_is_refused_quickly():
    started = time.perf_counter()
    shapes = [
        "[" * 500_000,
        "{" * 500_000,
        '"' * 100_000,
        "a" * 1_000_000,
        '{"a":' * 60 + "1" + "}" * 60,
        "[" * 63 + "]" * 63,
        "\\" * 100_000,
        '{"report": {"facts": [' + "{},".join(["{}"] * 50_000) + "]}}",
    ]
    for text in shapes:
        with pytest.raises(InvalidAnalysisResult):
            loads_result(text)
    assert time.perf_counter() - started < 20


def test_the_configuration_digest_does_not_depend_on_the_order_of_the_settings():
    from androai_codegen.analysis.freshness import config_digest

    assert config_digest({"b": 1, "a": 2}) == config_digest({"a": 2, "b": 1})
    assert config_digest({"a": 1}) != config_digest({"a": 2})


def test_an_input_digest_must_be_exactly_sixty_four_lower_case_hex_digits():
    for bad in ("abc", "g" * 64, "A" * 64, "a" * 63, "a" * 65, ""):
        with pytest.raises(ValueError):
            InputFile(path="a.kt", sha256=bad)
    assert InputFile(path="a.kt", sha256="a" * 64).sha256 == "a" * 64


def test_the_nesting_check_counts_depth_exactly_and_ignores_strings():
    from androai_codegen.analysis.result import _depth_of

    assert (
        _depth_of('{"a": "", "b": [[[[1]]]]}', 100) == 5
    )  # an empty string does not hide brackets
    assert _depth_of('{"a": "\\\\", "b": [[1]]}', 100) == 3
    assert _depth_of("1", 100) == 0
    assert _depth_of("[[[[[[", 3) == 4  # it stops as soon as the limit is passed


def test_loads_accepts_nesting_up_to_the_limit_and_refuses_one_level_more():
    from androai_codegen.analysis.result import _depth_of

    text = dumps_result(result_of())
    depth = _depth_of(text, 1000)
    assert loads_result(text, max_depth=depth)
    with pytest.raises(InvalidAnalysisResult, match="nested deeper"):
        loads_result(text, max_depth=depth - 1)


def reason_after(change) -> str:
    files = project()
    result = result_of(files)
    change(files)
    verdict = check_freshness(result, files)
    assert verdict.state == "stale" and verdict.truncated is False
    return verdict.reason


def test_the_reason_for_a_stale_result_names_only_what_happened():
    prefix = "files differ from the analysed input: "
    assert (
        reason_after(lambda f: f.update({A: "package com.x\nclass A2\n"})) == prefix + "1 changed"
    )
    assert reason_after(
        lambda f: f.update({"app/src/main/java/com/x/C.kt": "package com.x\n"})
    ) == (prefix + "1 added")
    assert reason_after(lambda f: f.pop(B)) == prefix + "1 deleted"

    def everything(files):
        files[A] = "package com.x\nclass A3\n"
        files["app/src/main/java/com/x/C.kt"] = "package com.x\n"
        del files[B]

    assert reason_after(everything) == prefix + "1 changed, 1 added, 1 deleted"


def test_a_fresh_result_and_a_small_stale_one_are_not_truncated():
    files = project()
    result = result_of(files)
    fresh = check_freshness(result, files)
    assert fresh.truncated is False and fresh.changed_count == 0
    files[A] = "package com.x\nclass A4\n"
    assert check_freshness(result, files).truncated is False


def test_the_package_writes_and_executes_nothing():
    for name in ("result", "inventory", "freshness"):
        source = (
            Path(__file__).parent.parent / "src" / "androai_codegen" / "analysis" / f"{name}.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "open(",
            "subprocess",
            "os.system",
            "write_text",
            "write_bytes",
            "pickle",
        ):
            assert forbidden not in source, (name, forbidden)
