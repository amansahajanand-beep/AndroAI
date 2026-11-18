"""Structured project understanding. All facts come from static analysis of the
uploaded files; nothing here is inferred by an LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Symbol(BaseModel):
    name: str
    kind: str  # class | object | interface | function | composable | activity | fragment | viewmodel | entity | dao
    path: str
    line: int
    detail: str | None = None  # e.g. superclass, route, signature


class FileInfo(BaseModel):
    path: str
    sha256: str
    size: int
    language: str  # kotlin | java | xml | gradle | other
    imports: list[str] = Field(default_factory=list)
    package: str | None = None
    tags: list[str] = Field(default_factory=list)  # e.g. auth, payment, network, database, navigation, ui
    symbols: list[Symbol] = Field(default_factory=list)
    skipped_reason: str | None = None  # set if content is not indexed (sensitive/too large/binary)


class GradleInfo(BaseModel):
    path: str
    namespace: str | None = None
    application_id: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    compile_sdk: int | None = None
    plugins: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ManifestInfo(BaseModel):
    path: str
    package: str | None = None
    permissions: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    receivers: list[str] = Field(default_factory=list)
    launcher_activity: str | None = None
    application_class: str | None = None


class ApiEndpoint(BaseModel):
    method: str
    path: str
    file: str
    function: str | None = None


class ProjectProfile(BaseModel):
    """Summary used for planning (small enough to put in a prompt)."""

    root_modules: list[str] = Field(default_factory=list)
    namespace: str | None = None
    application_id: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    compile_sdk: int | None = None
    ui_toolkits: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    gradle: list[GradleInfo] = Field(default_factory=list)
    manifests: list[ManifestInfo] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    fragments: list[str] = Field(default_factory=list)
    composables: list[str] = Field(default_factory=list)
    layouts: list[str] = Field(default_factory=list)
    navigation_graphs: list[str] = Field(default_factory=list)
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    database_files: list[str] = Field(default_factory=list)
    auth_files: list[str] = Field(default_factory=list)
    payment_files: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    file_count: int = 0
    skipped: dict[str, str] = Field(default_factory=dict)  # path -> reason


class ProjectScope(BaseModel):
    """Isolation key. Every index/store operation requires one."""

    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.tenant_id}/{self.project_id}"


class RetrievedChunk(BaseModel):
    path: str
    score: float
    reason: str  # why it was selected: match | symbol | dependency | manifest
    content: str  # redacted, line-bounded excerpt
    start_line: int
    end_line: int
