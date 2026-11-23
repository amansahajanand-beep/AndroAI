"""Object key construction and validation.

Every key starts with `tenants/<tenant_id>/`. Services build keys only through these
helpers and `assert_key_in_tenant` guards every read/delete, so a bug elsewhere cannot
address another tenant's objects.
"""

from __future__ import annotations

import re

_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class InvalidKey(ValueError):
    pass


def _check_id(value: str, what: str) -> str:
    if not _ID.match(value):
        raise InvalidKey(f"invalid {what}")
    return value


def safe_name(name: str, default: str = "file") -> str:
    """Reduce a user-supplied filename to a harmless single path component."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _SAFE_NAME.sub("_", base).strip("._") or default
    return base[:120]


def tenant_prefix(tenant_id: str) -> str:
    return f"tenants/{_check_id(tenant_id, 'tenant_id')}/"


def project_prefix(tenant_id: str, project_id: str) -> str:
    return f"{tenant_prefix(tenant_id)}projects/{_check_id(project_id, 'project_id')}/"


def upload_key(tenant_id: str, project_id: str, upload_id: str, filename: str) -> str:
    return f"{project_prefix(tenant_id, project_id)}uploads/{_check_id(upload_id, 'upload_id')}/{safe_name(filename)}"


def file_key(tenant_id: str, project_id: str, sha256: str) -> str:
    """Source files are content-addressed within a project (dedupe + immutable objects)."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise InvalidKey("invalid sha256")
    return f"{project_prefix(tenant_id, project_id)}blobs/{sha256}"


def snapshot_key(tenant_id: str, project_id: str, version: int) -> str:
    return f"{project_prefix(tenant_id, project_id)}snapshots/{int(version):06d}.zip"


def artifact_key(tenant_id: str, project_id: str, artifact_id: str, filename: str) -> str:
    return f"{project_prefix(tenant_id, project_id)}artifacts/{_check_id(artifact_id, 'artifact_id')}/{safe_name(filename)}"


def log_key(tenant_id: str, project_id: str, job_id: str) -> str:
    return f"{project_prefix(tenant_id, project_id)}logs/{_check_id(job_id, 'job_id')}.log"


def report_key(tenant_id: str, project_id: str, job_id: str, filename: str) -> str:
    return f"{project_prefix(tenant_id, project_id)}reports/{_check_id(job_id, 'job_id')}/{safe_name(filename)}"


def assert_key_in_tenant(key: str, tenant_id: str) -> str:
    prefix = tenant_prefix(tenant_id)
    if not key.startswith(prefix) or ".." in key.split("/") or "\x00" in key or key.startswith("/"):
        raise InvalidKey("key outside tenant scope")
    return key
