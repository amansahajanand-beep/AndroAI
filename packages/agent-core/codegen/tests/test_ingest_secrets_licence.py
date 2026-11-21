"""Secret detection (kinds, places, never values), the protection it implies, and licences."""

import json
from pathlib import Path

import pytest
from ingest_helpers import import_dir, minimal_project, write_tree

from androai_codegen.editing import ModifyFile, PatchSet
from androai_codegen.editing.errors import ProtectedFileError
from androai_codegen.editing.models import ProblemCode
from androai_codegen.editing.redact import SecretMatch, find_secrets, mask_secrets
from androai_codegen.ingest import IngestLimits, LicenceClass, protection_for, reopen_import
from androai_codegen.ingest.licence import classify_spdx_expression, classify_text

# These are fakes with the shape of real credentials. They are assembled at run time from
# fragments, so that no credential-shaped literal sits in the repository for a secret scanner
# to mistake for a leak.
GOOGLE_KEY = "AIza" + "A" * 35
GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5" * 4
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
SLACK = "xox" + "b-1234567890-abcdefghij"
OPENAI = "sk-" + "Z9y8X7w6V5" * 4
JWT = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0", "abcdefghij1234"])
PEM_BODY = "FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"
PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\n" + PEM_BODY + "\n-----END RSA " + "PRIVATE KEY-----"


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    return root


def project(tmp_path: Path, **extra) -> Path:
    files = minimal_project()
    files.update(extra)
    return write_tree(tmp_path / "src", files)


def scan(tmp_path: Path, data: Path, files: dict, **options):
    source = write_tree(tmp_path / "src", {**minimal_project(), **files})
    return import_dir(source, data, **options)


# --- find_secrets ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"x = {AWS_KEY}", "aws_access_key"),
        (f"token {GITHUB_TOKEN}", "github_token"),
        (f'val k = "{GOOGLE_KEY}"', "google_api_key"),
        (f"hook {SLACK}", "slack_token"),
        (f"key {OPENAI}", "openai_style_key"),
        (f"Bearer {JWT}", "jwt"),
        (PEM, "private_key"),
        ('password = "hunter2hunter2"', "credential_assignment"),
        ("storePassword=hunter2hunter2", "credential_assignment"),
        ("api_key: abcdef123456", "credential_assignment"),
    ],
)
def test_each_kind_of_secret_is_found_with_its_place_and_length(text, kind):
    (match,) = find_secrets(text)
    assert match.kind == kind
    assert 0 <= match.start < match.end <= len(text)
    assert match.length > 0
    assert match.length <= match.end - match.start


def test_a_match_names_a_place_and_a_length_never_the_secret():
    assert SecretMatch._fields == ("kind", "start", "end", "length")


@pytest.mark.parametrize(
    "text",
    [
        'password = System.getenv("PW")',
        "password = [REDACTED]",
        "// no secrets here",
        "val total = items.sum()",
        "class TokenParser",
    ],
)
def test_text_without_a_literal_secret_has_no_finding(text):
    assert find_secrets(text) == []


def test_a_token_assigned_to_a_secret_name_is_reported_once_under_its_specific_kind():
    matches = find_secrets(f'api_key = "{GOOGLE_KEY}"')
    assert [m.kind for m in matches] == ["google_api_key"]


def test_a_private_key_block_is_one_finding_even_though_it_holds_key_like_words():
    assert [m.kind for m in find_secrets(f"private_key = '''{PEM}'''")] == ["private_key"]


@pytest.mark.parametrize(
    "text",
    [
        f"a {AWS_KEY} b",
        f'val k = "{GOOGLE_KEY}"',
        'password = "hunter2hunter2"',
        PEM,
        "nothing",
        "password = [REDACTED]",
        'password = System.getenv("PW")',
        'token_url = "https://example.com/oauth/token"',
        f"{GITHUB_TOKEN} and {OPENAI}",
    ],
)
def test_detection_and_masking_agree_because_they_share_their_patterns(text):
    assert (mask_secrets(text) != text) == bool(find_secrets(text))


# --- what an import finds and reports --------------------------------------------------------


def test_findings_name_the_file_line_kind_and_length(tmp_path, data):
    code = f'package a\n\nval key = "{GOOGLE_KEY}"\nval ok = 1\n'
    report = scan(tmp_path, data, {"app/src/main/java/a/Api.kt": code}).report
    finding = next(f for f in report.secrets.findings if f.path.endswith("Api.kt"))
    assert (finding.kind, finding.line, finding.length) == ("google_api_key", 3, len(GOOGLE_KEY))
    assert report.secrets.by_kind["google_api_key"] == 1


def test_no_secret_value_appears_anywhere_in_the_report(tmp_path, data):
    files = {
        "app/src/main/java/a/Api.kt": (
            f'val a = "{GOOGLE_KEY}"\nval b = "{GITHUB_TOKEN}"\nval c = "{AWS_KEY}"\n'
        ),
        "app/config.yml": f"api_key: {OPENAI}\npassword: hunter2hunter2\n",
        "gradle.properties": "storePassword=hunter2hunter2\nkeyPassword=correcthorse\n",
        "app/key.kt": f'val pem = """{PEM}"""\n',
        "app/jwt.kt": f'val t = "{JWT}"\n',
        "app/slack.kt": f'val s = "{SLACK}"\n',
    }
    result = scan(tmp_path, data, files)
    text = result.report_path.read_text("utf-8")
    for secret in (
        GOOGLE_KEY,
        GITHUB_TOKEN,
        AWS_KEY,
        OPENAI,
        JWT,
        SLACK,
        "hunter2hunter2",
        "correcthorse",
        PEM_BODY,
    ):
        assert secret not in text, secret
    assert result.report.secrets.total_findings >= 8


def test_an_import_never_alters_the_files_it_scans(tmp_path, data):
    code = f'val a = "{GOOGLE_KEY}"\n'
    result = scan(tmp_path, data, {"app/src/main/java/a/Api.kt": code})
    assert (result.workspace.root / "app/src/main/java/a/Api.kt").read_text("utf-8") == code


def test_binary_oversized_and_non_text_files_are_not_scanned_and_say_so(tmp_path, data):
    files = {
        "app/blob.bin": b"\0\0" + GOOGLE_KEY.encode(),
        "app/latin1.txt": b"caf\xe9 " + GOOGLE_KEY.encode(),
        "app/big.txt": ("x" * 600 + GOOGLE_KEY).encode(),
        "app/small.kt": f'val a = "{GOOGLE_KEY}"\n',
    }
    result = scan(tmp_path, data, files, limits=IngestLimits(secret_scan_max_bytes=500))
    secrets = result.report.secrets
    assert [f.path for f in secrets.findings] == ["app/small.kt"]
    assert secrets.files_not_scanned == 3 and secrets.not_scanned_large == ["app/big.txt"]


def test_a_type_or_a_reference_next_to_a_credential_name_in_code_is_not_a_finding(tmp_path, data):
    code = (
        "package a\n"
        'val password: String = ""\n'  # a type annotation (the redaction pattern would match it)
        "val secret = otherSecret\n"  # a reference
        "fun f(token: String, apiKey: String) {}\n"
        'val apiKey = "hunter2hunter2"\n'  # a quoted literal: reported
        "val dbPassword = 'abcdef123456'\n"
    )
    secrets = scan(tmp_path, data, {"app/src/main/java/a/Login.kt": code}).report.secrets
    assert [(f.kind, f.line) for f in secrets.findings if f.path.endswith("Login.kt")] == [
        ("credential_assignment", 5),
        ("credential_assignment", 6),
    ]


def test_an_unquoted_value_in_a_properties_file_is_a_literal_and_is_reported(tmp_path, data):
    secrets = scan(tmp_path, data, {"app/x.properties": "password: String\n"}).report.secrets
    assert secrets.total_findings == 1 and secrets.protected_paths == ["app/x.properties"]


def test_the_findings_list_is_capped_but_the_totals_are_exact(tmp_path, data):
    lines = "\n".join(f'val k{i} = "{GITHUB_TOKEN}"' for i in range(1010))
    secrets = scan(tmp_path, data, {"app/many.kt": lines}).report.secrets
    assert secrets.total_findings == 1010 and len(secrets.findings) == 1000
    assert secrets.by_kind["github_token"] == 1010


# --- which files become protected ------------------------------------------------------------


def test_google_services_json_is_always_protected(tmp_path, data):
    result = scan(tmp_path, data, {"app/google-services.json": '{"client": []}'})
    assert "app/google-services.json" in result.report.secrets.protected_paths
    assert result.protection.is_protected("app/google-services.json")
    with pytest.raises(ProtectedFileError):
        result.open_engine().read_for_llm("app/google-services.json")


def test_a_properties_file_with_a_credential_is_protected_one_without_is_not(tmp_path, data):
    files = {
        "gradle.properties": "storePassword=hunter2hunter2\n",
        "app/other.properties": "org.gradle.jvmargs=-Xmx2g\n",
    }
    result = scan(tmp_path, data, files)
    assert result.report.secrets.protected_paths == ["gradle.properties"]
    assert result.protection.is_protected("gradle.properties")
    assert not result.protection.is_protected("app/other.properties")


@pytest.mark.parametrize(
    "name",
    ["app/config.yml", "app/config.yaml", "app/c.json", "app/x.ini", "app/x.env", "app/x.conf"],
)
def test_any_configuration_file_holding_a_secret_is_protected(tmp_path, data, name):
    result = scan(tmp_path, data, {name: f'api_key: "{OPENAI}"\n'})
    assert name in result.report.secrets.protected_paths


def test_a_file_holding_a_private_key_is_protected_whatever_it_is_called(tmp_path, data):
    result = scan(tmp_path, data, {"app/src/main/java/a/Keys.kt": f'val k = """{PEM}"""\n'})
    assert "app/src/main/java/a/Keys.kt" in result.report.secrets.protected_paths


def test_source_and_resource_files_with_a_secret_stay_editable_and_are_masked_for_an_llm(
    tmp_path, data
):
    manifest = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <meta-data android:name="com.google.android.geo.API_KEY" '
        f'android:value="{GOOGLE_KEY}"/>\n'
        "</manifest>\n"
    )
    kotlin = f'package a\n\nval key = "{GOOGLE_KEY}"\n'
    result = scan(
        tmp_path,
        data,
        {"app/src/main/AndroidManifest.xml": manifest, "app/src/main/java/a/Api.kt": kotlin},
    )
    assert result.report.secrets.protected_paths == []
    engine = result.open_engine()
    for path in ("app/src/main/AndroidManifest.xml", "app/src/main/java/a/Api.kt"):
        assert not result.protection.is_protected(path)
        shown = engine.read_for_llm(path).content
        assert GOOGLE_KEY not in shown and "[REDACTED]" in shown


def test_a_protected_file_cannot_be_changed_through_the_engine(tmp_path, data):
    result = scan(tmp_path, data, {"gradle.properties": "storePassword=hunter2hunter2\n"})
    engine = result.open_engine()
    patch = PatchSet(
        project_id="proj1",
        run_id="r",
        task_id="t",
        description="touch a secret file",
        changes=[
            ModifyFile(
                path="gradle.properties",
                expected_checksum=engine.workspace.checksum("gradle.properties"),
                content="x=1\n",
                description="x",
            )
        ],
    )
    preview = engine.preview(patch)
    assert not preview.ok
    assert ProblemCode.PROTECTED_FILE in {p.code for p in preview.problems}


def test_the_default_protected_files_are_listed_but_need_no_extra_protection(tmp_path, data):
    result = scan(tmp_path, data, {"app/release.jks": b"\x00\x01binary", ".env": "A=1\n"})
    kinds = {(f.path, f.kind) for f in result.report.secrets.findings if f.kind == "protected_file"}
    assert ("app/release.jks", "protected_file") in kinds and (".env", "protected_file") in kinds
    assert result.protection.is_protected("app/release.jks") and result.protection.is_protected(
        ".env"
    )
    assert "app/release.jks" not in result.report.secrets.protected_paths


def test_protection_is_case_insensitive_like_the_engines_own(tmp_path, data):
    result = scan(tmp_path, data, {"app/Local.Properties.json": f'{{"api_key": "{OPENAI}"}}'})
    assert result.protection.is_protected("APP/LOCAL.PROPERTIES.JSON")


def test_the_protection_is_rebuilt_exactly_when_a_project_is_reopened(tmp_path, data):
    original = scan(
        tmp_path,
        data,
        {"gradle.properties": "storePassword=hunter2hunter2\n", "app/google-services.json": "{}"},
    )
    reopened = reopen_import(original.project_dir)
    assert reopened.protection == original.protection
    assert protection_for(original.report.secrets.protected_paths) == original.protection
    assert reopened.protection.is_protected("gradle.properties")


def test_the_default_policy_still_applies_to_the_imported_project(tmp_path, data):
    result = scan(tmp_path, data, {})
    assert result.protection.is_protected("keystore.properties")
    assert not result.protection.is_protected("app/src/main/AndroidManifest.xml")


# --- licence ---------------------------------------------------------------------------------

MIT = (
    "MIT License\n\nCopyright (c) 2024 Someone\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy of this "
    'software and associated documentation files (the "Software"), to deal in the Software'
)
APACHE = (
    "                                 Apache License\n"
    "                           Version 2.0, January 2004\n"
    "                        http://www.apache.org/licenses/"
)
GPL3 = (
    "                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007"
)
GPL2 = "                    GNU GENERAL PUBLIC LICENSE\n                       Version 2, June 1991"
LGPL21 = (
    "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n"
    "Use the GNU General Public License for the rest"
)
LGPL3 = (
    "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
    "the GNU General Public License, version 3"
)
AGPL3 = "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007"
BSD2 = (
    "Redistribution and use in source and binary forms, with or without modification, "
    "are permitted provided that the following conditions are met"
)
BSD3 = (
    BSD2
    + "\n3. Neither the name of the copyright holder nor the names of its contributors may be used"
)
MPL = "Mozilla Public License Version 2.0\n=================================="
ISC = (
    "Permission to use, copy, modify, and/or distribute this software for any purpose "
    "with or without fee is hereby granted"
)
UNLICENSE = "This is free and unencumbered software released into the public domain."
CC0 = "CC0 1.0 Universal\n\nStatement of Purpose"


@pytest.mark.parametrize(
    ("text", "spdx", "klass"),
    [
        (MIT, "MIT", LicenceClass.PERMISSIVE),
        (APACHE, "Apache-2.0", LicenceClass.PERMISSIVE),
        (BSD2, "BSD-2-Clause", LicenceClass.PERMISSIVE),
        (BSD3, "BSD-3-Clause", LicenceClass.PERMISSIVE),
        (ISC, "ISC", LicenceClass.PERMISSIVE),
        (UNLICENSE, "Unlicense", LicenceClass.PERMISSIVE),
        (CC0, "CC0-1.0", LicenceClass.PERMISSIVE),
        (MPL, "MPL-2.0", LicenceClass.WEAK_COPYLEFT),
        (LGPL21, "LGPL-2.1", LicenceClass.WEAK_COPYLEFT),
        (LGPL3, "LGPL-3.0", LicenceClass.WEAK_COPYLEFT),
        (GPL2, "GPL-2.0", LicenceClass.STRONG_COPYLEFT),
        (GPL3, "GPL-3.0", LicenceClass.STRONG_COPYLEFT),
        (AGPL3, "AGPL-3.0", LicenceClass.STRONG_COPYLEFT),
        ("Proprietary. All rights reserved.", None, LicenceClass.UNKNOWN),
    ],
)
def test_well_known_licence_texts_are_recognised(text, spdx, klass):
    assert classify_text(text) == (spdx, klass)


def test_a_lesser_gpl_text_that_mentions_the_gpl_is_not_taken_for_the_gpl():
    assert classify_text(LGPL3)[0] == "LGPL-3.0"


@pytest.mark.parametrize(
    "name",
    [
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "licence.txt",
        "COPYING",
        "UNLICENSE",
        "License-APACHE",
    ],
)
def test_licence_files_are_found_under_their_usual_names(tmp_path, data, name):
    report = scan(tmp_path, data, {name: MIT}).report
    assert report.licence.classification is LicenceClass.PERMISSIVE
    assert report.licence.spdx_ids == ["MIT"] and report.licence.files[0].path == name


def test_a_project_without_any_licence_says_so(tmp_path, data):
    licence = scan(tmp_path, data, {}).report.licence
    assert licence.classification is LicenceClass.NONE and licence.files == []
    assert any("all rights reserved" in note for note in licence.notes)


def test_the_most_restrictive_licence_among_several_is_reported(tmp_path, data):
    files = {"LICENSE": MIT, "app/LICENSE": GPL3, "lib/COPYING": APACHE}
    licence = scan(tmp_path, data, files).report.licence
    assert licence.classification is LicenceClass.STRONG_COPYLEFT
    assert licence.spdx_ids == ["Apache-2.0", "GPL-3.0", "MIT"]
    assert any("copyleft" in note for note in licence.notes)


def test_a_licence_file_deep_inside_the_tree_is_ignored(tmp_path, data):
    licence = scan(tmp_path, data, {"app/src/third_party/LICENSE": GPL3}).report.licence
    assert licence.classification is LicenceClass.NONE


def test_an_unrecognised_licence_file_is_unknown_not_ignored(tmp_path, data):
    licence = scan(tmp_path, data, {"LICENSE": "Do what you like, mostly."}).report.licence
    assert licence.classification is LicenceClass.UNKNOWN
    assert licence.files[0].spdx is None


def test_spdx_headers_in_source_files_are_read(tmp_path, data):
    code = "// SPDX-License-Identifier: Apache-2.0\npackage a\n"
    licence = scan(tmp_path, data, {"app/src/main/java/a/A.kt": code}).report.licence
    assert licence.source_headers == 1 and licence.spdx_ids == ["Apache-2.0"]
    assert licence.classification is LicenceClass.PERMISSIVE


@pytest.mark.parametrize(
    ("expression", "ids", "klass"),
    [
        ("MIT", ["MIT"], LicenceClass.PERMISSIVE),
        ("MIT OR Apache-2.0", ["MIT", "Apache-2.0"], LicenceClass.PERMISSIVE),
        ("GPL-3.0-or-later", ["GPL-3.0-or-later"], LicenceClass.STRONG_COPYLEFT),
        ("GPL-2.0+", ["GPL-2.0+"], LicenceClass.STRONG_COPYLEFT),
        ("(MIT AND LGPL-2.1-only)", ["MIT", "LGPL-2.1-only"], LicenceClass.WEAK_COPYLEFT),
        (
            "GPL-2.0 WITH Classpath-exception-2.0",
            ["GPL-2.0", "Classpath-exception-2.0"],
            LicenceClass.STRONG_COPYLEFT,
        ),
        ("Made-Up-1.0", ["Made-Up-1.0"], LicenceClass.UNKNOWN),
    ],
)
def test_spdx_expressions_are_split_and_the_strictest_class_wins(expression, ids, klass):
    assert classify_spdx_expression(expression) == (ids, klass)


def test_a_header_far_down_a_file_is_not_searched_for(tmp_path, data):
    code = "// filler\n" * 400 + "// SPDX-License-Identifier: GPL-3.0\n"
    licence = scan(tmp_path, data, {"app/src/main/java/a/A.kt": code}).report.licence
    assert licence.source_headers == 0


@pytest.mark.parametrize("text", [GPL3, AGPL3, "no licence at all", "Proprietary"])
def test_a_licence_is_recorded_but_never_blocks_a_confirmed_import(tmp_path, data, text):
    result = scan(tmp_path, data, {"LICENSE": text} if text != "no licence at all" else {})
    assert result.eligible_for_modification
    assert "not legal advice" in result.report.licence.notes[0]


def test_the_report_json_round_trips_with_its_licence_and_secret_sections(tmp_path, data):
    result = scan(
        tmp_path, data, {"LICENSE": MIT, "gradle.properties": "storePassword=hunter2hunter2\n"}
    )
    document = json.loads(result.report_path.read_text("utf-8"))
    assert document["licence"]["classification"] == "permissive"
    assert document["secrets"]["protected_paths"] == ["gradle.properties"]
