"""Users, sessions, RBAC."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..db.types import CreatedMixin, IdType, JsonType, TimestampMixin, UTCDateTime, pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = pk()
    # Tenant = workspace. Today every user owns a personal tenant (tenant_id == id);
    # the column exists on every resource so organisations can be added later.
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # stored lowercased
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    preferences: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)  # UI preferences

    roles: Mapped[list["Role"]] = relationship(secondary="user_roles", lazy="selectin")

    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)


class UserSession(Base, CreatedMixin):
    """One row per issued refresh token. Rotation creates a new row in the same
    `family_id`; presenting an already-rotated token revokes the whole family."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[str] = mapped_column(IdType, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_user_sessions_refresh_token_hash"),
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_family_id", "family_id"),
    )


class UserToken(Base, CreatedMixin):
    """Single-use email-verification / password-reset tokens (hash stored only)."""

    __tablename__ = "user_tokens"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # verify_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_tokens_token_hash"),
        Index("ix_user_tokens_user_id", "user_id"),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", lazy="selectin"
    )
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (UniqueConstraint("name", name="uq_permissions_name"),)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
