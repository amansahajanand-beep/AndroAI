from androai_orchestration_core.intelligence import ProjectIndex, ProjectScope
from androai_orchestration_core.providers import redact

from fixtures import AUTH_REPO, FILES

SCOPE = ProjectScope(tenant_id="t1", project_id="p1")


def build():
    return ProjectIndex.build(SCOPE, FILES)


def test_profile_facts():
    p = build().profile
    assert p.namespace == "com.example.shop" and p.application_id == "com.example.shop"
    assert (p.min_sdk, p.target_sdk, p.compile_sdk) == (24, 35, 35)
    assert "android.permission.INTERNET" in p.permissions
    assert p.manifests[0].launcher_activity == ".LoginActivity"
    assert p.activities == ["LoginActivity"]
    assert {(e.method, e.path) for e in p.api_endpoints} == {("GET", "products"), ("POST", "orders")}
    assert "app/src/main/java/com/example/shop/auth/AuthRepository.kt" in p.auth_files
    assert "com.squareup.retrofit2:retrofit:2.11.0" in p.gradle[0].dependencies


def test_unsafe_sensitive_and_build_outputs_skipped():
    idx = build()
    assert idx.profile.skipped["../escape.kt"] == "unsafe_path"
    assert idx.profile.skipped["local.properties"] == "sensitive"
    assert "app/build/generated/Junk.kt" not in idx.files
    assert "hunter2" not in " ".join(idx._texts.values())


def test_search_and_dependencies():
    idx = build()
    top = idx.search("add google login to authentication")[0][0]
    assert top.endswith(("AuthRepository.kt", "LoginActivity.kt"))
    login = "app/src/main/java/com/example/shop/LoginActivity.kt"
    assert idx.dependencies_of(login) == ["app/src/main/java/com/example/shop/auth/AuthRepository.kt"]
    assert idx.dependents_of("app/src/main/java/com/example/shop/auth/AuthRepository.kt") == [login]


def test_retrieve_respects_budget_and_is_partial():
    idx = build()
    chunks = idx.retrieve("login", token_budget=40)
    assert chunks and sum(len(c.content) for c in chunks) < 400
    assert len(idx.retrieve("login", token_budget=10_000, k=1, include_deps=False)) == 1


def test_incremental_update():
    idx = build()
    r = idx.update({"app/src/main/java/com/example/shop/auth/AuthRepository.kt": AUTH_REPO})
    assert r["unchanged"] and not r["modified"]
    new = AUTH_REPO + b"\nclass GoogleSignInHelper\n"
    r = idx.update({"app/src/main/java/com/example/shop/auth/AuthRepository.kt": new})
    assert r["modified"]
    assert idx.symbols_named("GoogleSignInHelper")
    idx.update({}, deleted=["app/src/main/java/com/example/shop/auth/AuthRepository.kt"])
    assert not idx.symbols_named("GoogleSignInHelper") and "app/src/main/java/com/example/shop/auth/AuthRepository.kt" not in idx.profile.auth_files


def test_redaction():
    out = redact('val k = "AIza' + "a" * 35 + '"\nstorePassword = "hunter2hunter2"\nplain = 1')
    assert "AIza" not in out and "hunter2" not in out and "plain = 1" in out
