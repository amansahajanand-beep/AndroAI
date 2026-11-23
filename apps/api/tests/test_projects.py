import io
import zipfile

from sqlalchemy import select

from androai_api.models import AuditLog, ProjectFile, ProjectFileChange, ProjectFileSnapshot, User, UserRole, Role
from androai_storage import keys

P = "/api/v1/projects"


def make_zip(files: dict[str, bytes | str], root: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(f"{root}/{name}" if root else name, data)
    return buf.getvalue()


def upload(client, h, pid, data: bytes, name="proj.zip"):
    return client.post(f"{P}/{pid}/uploads", headers=h, files={"file": (name, data, "application/zip")})


def new_project(client, h, name="My App"):
    r = client.post(P, headers=h, json={"name": name, "description": "d"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


SAMPLE = {"settings.gradle": "rootProject.name='x'", "app/build.gradle": "apply plugin: 'com.android.application'",
          "app/src/main/AndroidManifest.xml": "<manifest/>"}


def test_project_crud_and_pagination(client, alice):
    _, h = alice
    ids = [new_project(client, h, f"P{i}") for i in range(3)]
    page = client.get(P, headers=h, params={"limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    pid = ids[0]
    assert client.get(f"{P}/{pid}", headers=h).json()["source_type"] == "empty"
    r = client.patch(f"{P}/{pid}", headers=h, json={"name": "Renamed", "status": "archived"})
    assert r.json()["name"] == "Renamed" and r.json()["status"] == "archived"
    assert client.get(P, headers=h).json()["total"] == 2
    assert client.get(P, headers=h, params={"status": "archived"}).json()["total"] == 1
    assert client.patch(f"{P}/{pid}", headers=h, json={"name": "   "}).status_code == 422
    assert client.delete(f"{P}/{pid}", headers=h).status_code == 204
    assert client.get(f"{P}/{pid}", headers=h).status_code == 404


def test_zip_upload_creates_files_and_snapshot(client, alice, storage, db_factory):
    _, h = alice
    pid = new_project(client, h)
    r = upload(client, h, pid, make_zip(SAMPLE, root="my-proj"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_count"] == 3 and body["snapshot_id"] and body["upload"]["status"] == "processed"
    files = client.get(f"{P}/{pid}/files", headers=h).json()
    assert [f["path"] for f in files] == ["app/build.gradle", "app/src/main/AndroidManifest.xml", "settings.gradle"]
    assert client.get(f"{P}/{pid}", headers=h).json()["source_type"] == "zip"
    snaps = client.get(f"{P}/{pid}/snapshots", headers=h).json()
    assert len(snaps) == 1 and snaps[0]["version"] == 1 and snaps[0]["file_count"] == 3
    with db_factory() as db:
        snap = db.scalars(select(ProjectFileSnapshot)).one()
        z = zipfile.ZipFile(io.BytesIO(storage.get_bytes(snap.storage_key)))
        assert sorted(z.namelist()) == sorted(SAMPLE)
        # every object lives under this tenant's prefix
        tenant = db.scalars(select(User)).one().tenant_id
        assert all(o.key.startswith(f"tenants/{tenant}/") for o in storage.list("tenants/"))


def test_reupload_replaces_files_and_records_changes(client, alice, db_factory):
    _, h = alice
    pid = new_project(client, h)
    upload(client, h, pid, make_zip(SAMPLE))
    upload(client, h, pid, make_zip({"settings.gradle": "changed", "new.txt": "n"}))
    files = {f["path"] for f in client.get(f"{P}/{pid}/files", headers=h).json()}
    assert files == {"settings.gradle", "new.txt"}
    with db_factory() as db:
        kinds = sorted((c.path, c.change_type) for c in db.scalars(select(ProjectFileChange)))
        assert ("settings.gradle", "update") in kinds and ("app/build.gradle", "delete") in kinds
    assert len(client.get(f"{P}/{pid}/snapshots", headers=h).json()) == 2


def test_identical_snapshot_is_reused(client, alice):
    _, h = alice
    pid = new_project(client, h)
    upload(client, h, pid, make_zip(SAMPLE))
    r = client.post(f"{P}/{pid}/snapshots", headers=h, json={})
    assert r.status_code == 201 and r.json()["version"] == 1


def test_malicious_archives_rejected_and_nothing_stored(client, alice, storage, db_factory):
    _, h = alice
    pid = new_project(client, h)
    evil = {
        "traversal": make_zip({"ok.txt": "1", "../../evil.txt": "x"}),
        "absolute": make_zip({"/etc/cron.d/x": "x"}),
        "bomb": make_zip({"bomb.bin": b"\0" * (30 * 1024 * 1024)}),
        "garbage": b"PK\x03\x04 definitely not a zip",
    }
    for name, data in evil.items():
        r = upload(client, h, pid, data, f"{name}.zip")
        assert r.status_code == 422, (name, r.text)
        assert r.json()["error"]["code"] == "invalid_archive"
    assert client.get(f"{P}/{pid}/files", headers=h).json() == []
    assert storage.list("tenants/") == []  # no partial blobs left behind
    uploads = client.get(f"{P}/{pid}/uploads", headers=h).json()
    assert len(uploads) == 4 and {u["status"] for u in uploads} == {"rejected"}


def test_upload_type_and_size_limits(client, alice, monkeypatch):
    _, h = alice
    pid = new_project(client, h)
    r = client.post(f"{P}/{pid}/uploads", headers=h, files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    from androai_api.config import get_settings
    monkeypatch.setattr(get_settings(), "upload_max_bytes", 1000)
    r = upload(client, h, pid, make_zip({"a.bin": __import__("os").urandom(5000)}))
    assert r.status_code == 413


def test_apk_upload_is_artifact_only(client, alice, storage):
    _, h = alice
    pid = new_project(client, h)
    apk = make_zip({"AndroidManifest.xml": b"x", "classes.dex": b"d"})
    r = upload(client, h, pid, apk, "app.apk")
    assert r.status_code == 201 and r.json()["artifact_id"] and r.json()["snapshot_id"] is None
    assert client.get(f"{P}/{pid}/files", headers=h).json() == []  # never unpacked
    assert client.get(f"{P}/{pid}", headers=h).json()["source_type"] == "apk"
    arts = client.get(f"{P}/{pid}/artifacts", headers=h).json()
    assert arts[0]["kind"] == "apk"
    assert upload(client, h, pid, make_zip({"x.txt": "y"}), "fake.apk").status_code == 422


def test_editor_read_write_conflict_and_history(client, alice):
    _, h = alice
    pid = new_project(client, h)
    upload(client, h, pid, make_zip(SAMPLE))
    f = "app/build.gradle"
    cur = client.get(f"{P}/{pid}/files/content", headers=h, params={"path": f}).json()
    assert cur["content"].startswith("apply plugin")
    r = client.put(f"{P}/{pid}/files/content", headers=h, params={"path": f},
                   json={"content": "// edited", "base_sha256": cur["sha256"]})
    assert r.status_code == 200 and r.json()["version"] == 2
    # stale base hash => 409, nothing overwritten
    r = client.put(f"{P}/{pid}/files/content", headers=h, params={"path": f},
                   json={"content": "// stale", "base_sha256": cur["sha256"]})
    assert r.status_code == 409
    assert client.get(f"{P}/{pid}/files/content", headers=h, params={"path": f}).json()["content"] == "// edited"
    # create new file: base omitted; existing file without base => conflict
    assert client.put(f"{P}/{pid}/files/content", headers=h, params={"path": "app/New.kt"},
                      json={"content": "class A"}).status_code == 200
    assert client.put(f"{P}/{pid}/files/content", headers=h, params={"path": "app/New.kt"},
                      json={"content": "class B"}).status_code == 409
    hist = client.get(f"{P}/{pid}/files/history", headers=h, params={"path": f}).json()
    assert [c["change_type"] for c in hist][:2] == ["update", "create"] or hist[0]["change_type"] == "update"
    # editing makes a new snapshot on demand
    assert client.post(f"{P}/{pid}/snapshots", headers=h, json={"label": "after edit"}).json()["version"] == 2
    sha = client.get(f"{P}/{pid}/files", headers=h).json()
    assert client.delete(f"{P}/{pid}/files", headers=h, params={"path": "app/New.kt"}).status_code == 204
    assert len(client.get(f"{P}/{pid}/files", headers=h).json()) == len(sha) - 1


def test_editor_rejects_bad_paths(client, alice):
    _, h = alice
    pid = new_project(client, h)
    for bad in ["../x", "/abs", "a/../../b", "a\\b"]:
        r = client.put(f"{P}/{pid}/files/content", headers=h, params={"path": bad}, json={"content": "x"})
        assert r.status_code == 422, bad


def test_tenant_isolation_everywhere(client, alice, bob, db_factory):
    _, ha = alice
    _, hb = bob
    pid = new_project(client, ha)
    upload(client, ha, pid, make_zip(SAMPLE))
    apk_id = upload(client, ha, pid, make_zip({"AndroidManifest.xml": b"x"}), "a.apk").json()["artifact_id"]
    snap = client.get(f"{P}/{pid}/snapshots", headers=ha).json()[0]["id"]
    # every project-scoped route 404s for the other tenant (same as "does not exist")
    for method, url, kw in [
        ("get", f"{P}/{pid}", {}), ("patch", f"{P}/{pid}", {"json": {"name": "x"}}), ("delete", f"{P}/{pid}", {}),
        ("get", f"{P}/{pid}/files", {}), ("get", f"{P}/{pid}/files/content", {"params": {"path": "settings.gradle"}}),
        ("put", f"{P}/{pid}/files/content", {"params": {"path": "z.txt"}, "json": {"content": "x"}}),
        ("delete", f"{P}/{pid}/files", {"params": {"path": "settings.gradle"}}),
        ("get", f"{P}/{pid}/snapshots", {}), ("post", f"{P}/{pid}/snapshots", {"json": {}}),
        ("get", f"{P}/{pid}/activity", {}), ("get", f"{P}/{pid}/artifacts", {}), ("get", f"{P}/{pid}/uploads", {}),
        ("get", f"{P}/{pid}/files/history", {}),
        ("post", f"{P}/{pid}/uploads", {"files": {"file": ("a.zip", make_zip({"a": "b"}), "application/zip")}}),
        ("get", f"/api/v1/artifacts/{apk_id}", {}), ("post", f"/api/v1/artifacts/{apk_id}/download-url", {}),
        ("delete", f"/api/v1/artifacts/{apk_id}", {}),
    ]:
        r = getattr(client, method)(url, headers=hb, **kw)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
    assert client.get(P, headers=hb).json()["total"] == 0
    # nothing changed for the owner
    assert client.get(f"{P}/{pid}", headers=ha).json()["name"] == "My App"
    assert len(client.get(f"{P}/{pid}/files", headers=ha).json()) == 3


def test_cannot_read_other_tenants_object_via_file_row(client, alice, bob, db_factory, storage):
    """Defence in depth: even a corrupted row pointing at another tenant's key is refused."""
    _, ha = alice
    _, hb = bob
    pa, pb = new_project(client, ha), new_project(client, hb, "B")
    upload(client, ha, pa, make_zip({"secret.txt": "alice-secret"}))
    upload(client, hb, pb, make_zip({"x.txt": "x"}))
    with db_factory() as db:
        a_key = db.scalars(select(ProjectFile).where(ProjectFile.project_id == pa)).one().storage_key
        row = db.scalars(select(ProjectFile).where(ProjectFile.project_id == pb)).one()
        row.storage_key = a_key
        db.commit()
    r = client.get(f"{P}/{pb}/files/content", headers=hb, params={"path": "x.txt"})
    assert r.status_code >= 400 and "alice-secret" not in r.text


def test_artifact_signed_download(client, alice):
    _, h = alice
    pid = new_project(client, h)
    apk = make_zip({"AndroidManifest.xml": b"x", "classes.dex": b"d"})
    aid = upload(client, h, pid, apk, "my app.apk").json()["artifact_id"]
    u = client.post(f"/api/v1/artifacts/{aid}/download-url", headers=h).json()
    r = client.get(u["url"])  # no auth header: the signature is the authorisation
    assert r.status_code == 200 and r.content == apk
    assert "attachment" in r.headers["content-disposition"] and r.headers["x-content-type-options"] == "nosniff"
    tampered = u["url"].replace("sig=", "sig=0")
    assert client.get(tampered).status_code == 403
    other = u["url"].replace(aid, "00000000-0000-0000-0000-000000000000")
    assert client.get(other).status_code == 403
    expired = u["url"].split("exp=")[0] + "exp=1&sig=" + u["url"].split("sig=")[1]
    assert client.get(expired).status_code == 403
    assert client.delete(f"/api/v1/artifacts/{aid}", headers=h).status_code == 204
    assert client.get(u["url"]).status_code == 404


def test_delete_project_purges_storage(client, alice, storage):
    _, h = alice
    pid = new_project(client, h)
    upload(client, h, pid, make_zip(SAMPLE))
    assert storage.list("tenants/")
    assert client.delete(f"{P}/{pid}", headers=h).status_code == 204
    assert storage.list("tenants/") == []


def test_unauthenticated_and_validation(client):
    assert client.get(P).status_code == 401
    assert client.post(P, json={"name": "x"}).status_code == 401


# ---- admin
def _make_admin(db_factory, email):
    from androai_api.services import rbac
    with db_factory() as db:
        u = db.scalars(select(User).where(User.email == email)).one()
        db.add(UserRole(user_id=u.id, role_id=rbac.get_role(db, "admin").id))
        db.commit()


def test_admin_requires_role_and_manages_users(client, alice, bob, db_factory):
    ta, ha = alice
    tb, hb = bob
    assert client.get("/api/v1/admin/users", headers=hb).status_code == 403
    _make_admin(db_factory, "alice@example.com")
    ha = {"Authorization": "Bearer " + client.post("/api/v1/auth/refresh", json={"refresh_token": ta["refresh_token"]}).json()["access_token"]}
    users = client.get("/api/v1/admin/users", headers=ha, params={"q": "bob"}).json()
    assert users["total"] == 1
    bid = users["items"][0]["id"]
    r = client.patch(f"/api/v1/admin/users/{bid}", headers=ha, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/v1/users/me", headers=hb).status_code == 401  # sessions revoked
    me = client.get("/api/v1/users/me", headers=ha).json()
    assert client.patch(f"/api/v1/admin/users/{me['id']}", headers=ha, json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/v1/admin/users/{bid}", headers=ha, json={"roles": ["nope"]}).status_code == 422
    logs = client.get("/api/v1/admin/audit-logs", headers=ha, params={"action": "admin.user_update"}).json()
    assert logs["total"] == 1
    # audit rows never contain secrets
    with db_factory() as db:
        for row in db.scalars(select(AuditLog)):
            assert "password" not in str(row.detail).lower()
