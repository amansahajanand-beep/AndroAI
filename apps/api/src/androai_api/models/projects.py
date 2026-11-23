"""Projects and their stored files. Bytes live in object storage; rows hold metadata only."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.types import CreatedMixin, IdType, JsonType, TimestampMixin, UTCDateTime, pk


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(16), default="empty", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, default=dict, nullable=False)
    current_snapshot_id: Mapped[str | None] = mapped_column(IdType)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint("source_type IN ('empty','zip','apk','generated')", name="source_type"),
        CheckConstraint("status IN ('active','archived','deleted')", name="status"),
        Index("ix_projects_tenant_id_status", "tenant_id", "status"),
        Index("ix_projects_owner_id", "owner_id"),
    )


class ProjectFile(Base, TimestampMixin):
    """Current-version index of a project's files (path -> object key)."""

    __tablename__ = "project_files"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_binary: Mapped[bool] = mapped_column(default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_project_files_project_id_path"),
        Index("ix_project_files_tenant_id", "tenant_id"),
    )


class ProjectUpload(Base, CreatedMixin):
    __tablename__ = "project_uploads"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # zip | apk
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="received", nullable=False)
    file_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("kind IN ('zip','apk')", name="kind"),
        CheckConstraint("status IN ('received','processed','rejected')", name="status"),
        Index("ix_project_uploads_project_id", "project_id"),
        Index("ix_project_uploads_tenant_id", "tenant_id"),
    )


class ProjectArtifact(Base, CreatedMixin):
    __tablename__ = "project_artifacts"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # apk|aab|log|report|upload
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    build_job_id: Mapped[str | None] = mapped_column(IdType)  # logical ref (build_jobs defined elsewhere)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index("ix_project_artifacts_project_id", "project_id"),
        Index("ix_project_artifacts_tenant_id", "tenant_id"),
        Index("ix_project_artifacts_expires_at", "expires_at"),
    )


class ProjectActivity(Base, CreatedMixin):
    __tablename__ = "project_activity"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)

    __table_args__ = (Index("ix_project_activity_project_id_created_at", "project_id", "created_at"),)


class ProjectEditorSession(Base, CreatedMixin):
    __tablename__ = "project_editor_sessions"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_project_editor_sessions_project_id", "project_id"),)


class ProjectFileChange(Base, CreatedMixin):
    """Append-only history of file edits (editor, AI patch, upload)."""

    __tablename__ = "project_file_changes"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)  # create|update|delete
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # upload|editor|agent|ui_editor
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    editor_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_editor_sessions.id", ondelete="SET NULL")
    )
    before_sha256: Mapped[str | None] = mapped_column(String(64))
    after_sha256: Mapped[str | None] = mapped_column(String(64))
    before_key: Mapped[str | None] = mapped_column(String(1024))
    after_key: Mapped[str | None] = mapped_column(String(1024))
    agent_run_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("change_type IN ('create','update','delete')", name="change_type"),
        Index("ix_project_file_changes_project_id_created_at", "project_id", "created_at"),
    )


class ProjectFileSnapshot(Base, CreatedMixin):
    """Immutable ZIP of the full project tree at a version (build input / restore point)."""

    __tablename__ = "project_file_snapshots"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_project_file_snapshots_project_id_version"),
        Index("ix_project_file_snapshots_tenant_id", "tenant_id"),
    )
