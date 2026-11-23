import time

import pytest

from androai_codegen.editing import (
    DEFAULT_PROTECTED_PATTERNS,
    REDACTION_MARKER,
    PathValidationError,
    ProtectionPolicy,
    mask_secrets,
    normalize_relative_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("app/src/main/Main.kt", "app/src/main/Main.kt"),
        ("a//b/./c.kt", "a/b/c.kt"),
        ("./x.kt", "x.kt"),
        (".gitignore", ".gitignore"),
        ("app/build.gradle.kts", "app/build.gradle.kts"),
        ("console.kt", "console.kt"),  # starts with 'con' but is not the device name
        ("app/github~notes.md", "app/github~notes.md"),  # only an exact GIT~<n> segment is blocked
        ("digit.kt", "digit.kt"),
        ("app/aux_utils.kt", "app/aux_utils.kt"),
        ("app/\u043a\u043b\u044e\u0447.kt", "app/\u043a\u043b\u044e\u0447.kt"),
    ],
)
def test_valid_paths_are_normalized(raw, expected):
    assert normalize_relative_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/etc/passwd",
        "../x",
        "a/../../x",
        "a/b/..",
        "a\\b",
        "..\\x",
        "C:/x",
        "C:\\x",
        "a/b:stream",
        "a\0b",
        "a\nb",
        "a/",
        ".git/config",
        "a/.GIT/x",
        "GIT~1/config",
        "a/git~12/hooks/pre-commit",
        "con",
        "CON.txt",
        "a/nul.kt",
        "a/COM1",
        "a/b.",
        "a/ b",
        "a/b ",
        "./",
        "a/" + "x" * 300,
        "x" * 2000,
        123,
        None,
        b"bytes",
    ],
)
def test_unsafe_paths_are_rejected(raw):
    with pytest.raises(PathValidationError):
        normalize_relative_path(raw)


@pytest.mark.parametrize(
    "path",
    [
        "app/release.jks",
        "app/RELEASE.KEYSTORE",
        "keystore.properties",
        "app/local.properties",
        ".env",
        "backend/.env.production",
        "certs/server.pem",
        "config/my-service-account-prod.json",
    ],
)
def test_protected_paths(path):
    assert ProtectionPolicy().is_protected(path)


@pytest.mark.parametrize(
    "path", ["app/src/Main.kt", "gradle.properties", "app/google-services.json", "environment.kt"]
)
def test_ordinary_paths_are_not_protected(path):
    assert not ProtectionPolicy().is_protected(path)


def test_custom_policy_replaces_defaults():
    policy = ProtectionPolicy(patterns=("secrets/*",))
    assert policy.is_protected("secrets/a.txt")
    assert not policy.is_protected("keystore.properties")
    assert DEFAULT_PROTECTED_PATTERNS  # defaults stay available for callers to extend


@pytest.mark.parametrize(
    ("source", "must_not_contain"),
    [
        ("storePassword=hunter2", "hunter2"),
        ('val apiKey = "abc123XYZ789"', "abc123XYZ789"),
        ('"client_secret": "s3cr3t-value"', "s3cr3t-value"),
        ("api_key: sk_live_abcdefghijkl", "sk_live_abcdefghijkl"),
        ("aws = AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("t = ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ghp_abcdefghij"),
        ("k = sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345", "sk-ant-api03"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAbCd\n-----END RSA PRIVATE KEY-----",
            "MIIEow",
        ),
        ("jwt = eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "eyJhbGci"),
    ],
)
def test_secrets_are_masked(source, must_not_contain):
    masked = mask_secrets(source)
    assert must_not_contain not in masked
    assert REDACTION_MARKER in masked


def test_masking_keeps_structure_of_assignments():
    assert mask_secrets('val apiKey = "abc123"') == f'val apiKey = "{REDACTION_MARKER}"'
    assert mask_secrets("storePassword=hunter2") == f"storePassword={REDACTION_MARKER}"
    assert mask_secrets('"password": "pw1"') == f'"password": "{REDACTION_MARKER}"'


@pytest.mark.parametrize(
    "source",
    [
        'val greeting = "hello"',
        'password = System.getenv("DB_PW")',
        "class TokenParser { fun parse() = 1 }",
        "val task-name = 3",
    ],
)
def test_non_secrets_are_untouched(source):
    assert mask_secrets(source) == source


def test_masking_is_idempotent():
    once = mask_secrets('val apiKey = "abc123"\nstorePassword=hunter2')
    assert mask_secrets(once) == once


@pytest.mark.parametrize(
    "blob",
    ["a" * 2_000_000, "a-" * 1_000_000, ("password" * 50 + " ") * 20_000, "=" * 2_000_000],
)
def test_masking_is_not_vulnerable_to_pathological_input(blob):
    started = time.perf_counter()
    mask_secrets(blob)
    assert time.perf_counter() - started < 5
