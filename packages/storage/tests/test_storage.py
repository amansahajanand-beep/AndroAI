import io
import tempfile

import pytest

from androai_storage import InvalidKey, LocalStorage, ObjectNotFound, S3Storage, StorageError
from androai_storage import keys

T = "11111111-1111-1111-1111-111111111111"
P = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"


def backends(tmp_path):
    import boto3
    from moto import mock_aws

    # short root: Windows MAX_PATH is 260 and keys are long
    yield "local", LocalStorage(tempfile.mkdtemp(prefix="s"))
    with mock_aws():
        from botocore.config import Config
        c = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))
        c.create_bucket(Bucket="test-bucket")
        yield "s3", S3Storage("test-bucket", client=c)


def test_roundtrip_on_all_backends(tmp_path):
    for name, s in backends(tmp_path):
        k = keys.file_key(T, P, "a" * 64)
        s.put_bytes(k, b"hello")
        s.put_file(k + "2", io.BytesIO(b"world"))
        assert s.exists(k) and s.get_bytes(k) == b"hello", name
        assert s.get_bytes(k, max_bytes=2) == b"he", name
        assert s.open_read(k + "2").read() == b"world", name
        assert sorted(o.key for o in s.list(keys.project_prefix(T, P))) == [k, k + "2"], name
        s.delete(k)
        assert not s.exists(k), name
        with pytest.raises(ObjectNotFound):
            s.get_bytes(k)
        assert s.delete_prefix(keys.project_prefix(T, P)) == 1, name
        assert s.list(keys.tenant_prefix(T)) == [], name


def test_local_rejects_escaping_keys(tmp_path):
    s = LocalStorage(tmp_path / "s")
    for bad in ["../x", "a/../../x", "/abs", "a\\b", ""]:
        with pytest.raises(StorageError):
            s.put_bytes(bad, b"x")


def test_presigned_url_s3_only(tmp_path):
    for name, s in backends(tmp_path):
        url = s.presigned_get_url(keys.file_key(T, P, "b" * 64), 60, "app debug.apk")
        assert (url is None) == (name == "local")
        if url:
            assert "X-Amz-Signature" in url and "X-Amz-Expires=60" in url


def test_keys_are_tenant_scoped_and_validated():
    assert keys.file_key(T, P, "a" * 64).startswith(f"tenants/{T}/projects/{P}/")
    with pytest.raises(InvalidKey):
        keys.tenant_prefix("../../etc")
    with pytest.raises(InvalidKey):
        keys.file_key(T, P, "../x")
    assert keys.safe_name("../../etc/passwd") == "passwd"
    assert keys.safe_name("a b\\c d.apk") == "c_d.apk"
    k = keys.snapshot_key(T, P, 3)
    assert keys.assert_key_in_tenant(k, T) == k
    with pytest.raises(InvalidKey):
        keys.assert_key_in_tenant(k, OTHER)
    with pytest.raises(InvalidKey):
        keys.assert_key_in_tenant(f"tenants/{T}/../{OTHER}/x", T)
