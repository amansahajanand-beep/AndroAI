"""Public API schemas (request/response bodies). Responses never include password hashes,
token hashes, storage keys or other internal fields."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class TokenOut(BaseModel):
    token_type: str = "bearer"
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class EmailTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class MessageOut(BaseModel):
    message: str


# ---- users
class UserOut(_Out):
    id: str
    email: str
    display_name: str | None
    is_active: bool
    email_verified: bool
    roles: list[str]
    permissions: list[str]
    created_at: datetime


class UserPatchIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


class AuthOut(BaseModel):
    user: UserOut
    tokens: TokenOut


# ---- projects
class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ProjectPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectOut(_Out):
    id: str
    name: str
    description: str | None
    source_type: str
    status: str
    current_snapshot_id: str | None
    created_at: datetime
    updated_at: datetime


class UploadOut(_Out):
    id: str
    kind: str
    filename: str
    size: int
    sha256: str
    status: str
    file_count: int | None
    created_at: datetime


class UploadResultOut(BaseModel):
    upload: UploadOut
    file_count: int
    snapshot_id: str | None
    artifact_id: str | None


class FileOut(_Out):
    path: str
    size: int
    sha256: str
    is_binary: bool
    version: int
    updated_at: datetime


class FileContentOut(FileOut):
    content: str


class FilePutIn(BaseModel):
    content: str
    base_sha256: str | None = Field(
        default=None, pattern="^[0-9a-f]{64}$",
        description="sha256 of the version you edited; omit only when creating a new file",
    )
    editor_session_id: str | None = None


class SnapshotOut(_Out):
    id: str
    version: int
    size: int
    sha256: str
    file_count: int
    label: str | None
    created_at: datetime


class SnapshotCreateIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)


class ActivityOut(_Out):
    id: str
    action: str
    actor_id: str | None
    detail: dict
    created_at: datetime


class ArtifactOut(_Out):
    id: str
    project_id: str
    kind: str
    name: str
    size: int
    sha256: str
    build_job_id: str | None
    created_at: datetime
    expires_at: datetime | None


class DownloadUrlOut(BaseModel):
    url: str
    expires_in: int


# ---- admin
class AdminUserOut(UserOut):
    last_login_at: datetime | None


class AdminUserPatchIn(BaseModel):
    is_active: bool | None = None
    roles: list[str] | None = None


class AuditLogOut(_Out):
    id: str
    actor_id: str | None
    tenant_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    detail: dict
    created_at: datetime
