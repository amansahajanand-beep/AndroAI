"""Public API schemas (request/response bodies). Responses never include password hashes,
token hashes, storage keys or other internal fields."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

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
    remember: bool = True  # persistent refresh cookie (browser sessions only)


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


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime


# ---- projects
class ProjectMeta(BaseModel):
    """Optional descriptive settings a client stores with a project (all validated and bounded)."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["kotlin", "java"] | None = None
    ui_toolkit: Literal["compose", "xml"] | None = None
    package_name: str | None = Field(default=None, max_length=255,
                                     pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
    min_sdk: int | None = Field(default=None, ge=1, le=40)
    target_sdk: int | None = Field(default=None, ge=1, le=40)
    requirements: list[Annotated[str, Field(max_length=500)]] | None = Field(default=None, max_length=50)
    config: dict[Annotated[str, Field(max_length=100)], Annotated[str, Field(max_length=1000)]] | None = Field(
        default=None, max_length=50)


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    metadata: ProjectMeta | None = None

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
    metadata: ProjectMeta | None = Field(default=None, description="merged into the existing metadata")


class LastBuildOut(BaseModel):
    id: str
    number: int
    state: str
    finished_at: datetime | None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    source_type: str
    status: str
    metadata: dict
    current_snapshot_id: str | None
    storage_bytes: int = 0
    active_jobs: int = 0
    last_build: LastBuildOut | None = None
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


class FileMoveIn(BaseModel):
    src: str = Field(min_length=1, max_length=1024, alias="from")
    dst: str = Field(min_length=1, max_length=1024, alias="to")

    model_config = ConfigDict(populate_by_name=True)


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
    project_count: int = 0


class AdminUserPatchIn(BaseModel):
    is_active: bool | None = None
    roles: list[str] | None = None


class AuditLogOut(_Out):
    id: str
    actor_id: str | None
    actor_email: str | None = None
    tenant_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    detail: dict
    created_at: datetime


# ---- extras used by the web app
class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["light", "dark", "system"] = "system"
    default_language: Literal["kotlin", "java"] = "kotlin"
    default_ui_toolkit: Literal["compose", "xml"] = "compose"
    email_build_failed: bool = True
    email_agent_task_completed: bool = True
    email_usage_threshold: bool = False


class ActivityRecentOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    action: str
    detail: dict
    created_at: datetime


class AnalysisOut(BaseModel):
    detected: dict
    required: dict
    file_count: int
    modules: list[str]
    build_system: Literal["gradle-kts", "gradle-groovy", "unknown"]


class SearchHitOut(BaseModel):
    path: str
    line: int
    column: int
    preview: str


class OverviewOut(BaseModel):
    users: int
    active_users_7d: int
    projects: int
    builds_today: int
    build_failure_rate_24h: float
    queue_depth: dict[str, int]
    ai_cost_today_usd: float
