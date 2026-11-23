"""Usage metering, subscriptions, billing, and operational/audit logs.

Money is stored as integer minor units (paise/cents) with an ISO currency code.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.types import CreatedMixin, IdType, JsonType, TimestampMixin, UTCDateTime, pk


class AiUsage(Base, CreatedMixin):
    """Reported by the orchestration layer (Person 2)."""

    __tablename__ = "ai_usage"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    agent_run_id: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(96), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)  # 1e-6 USD
    __table_args__ = (Index("ix_ai_usage_tenant_id_created_at", "tenant_id", "created_at"),)


class BuildUsage(Base, CreatedMixin):
    __tablename__ = "build_usage"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    job_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # build|test|emulator
    job_id: Mapped[str] = mapped_column(IdType, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # >1 => retry cost
    runtime_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    __table_args__ = (
        UniqueConstraint("job_kind", "job_id", "attempt", name="uq_build_usage_job_kind_job_id_attempt"),
        Index("ix_build_usage_tenant_id_created_at", "tenant_id", "created_at"),
    )


class StorageUsage(Base, CreatedMixin):
    """Point-in-time measurements; the latest row per tenant/project is current."""

    __tablename__ = "storage_usage"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    __table_args__ = (Index("ix_storage_usage_tenant_id_created_at", "tenant_id", "created_at"),)


class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = pk()
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(8), nullable=False)  # month|year|none
    price_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    # Enforced by backend services: projects, build_minutes, concurrent_builds,
    # storage_bytes, ai_cost_micros, emulator_minutes, queue_depth, upload_bytes ...
    limits: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (
        UniqueConstraint("code", name="uq_subscription_plans_code"),
        CheckConstraint("billing_interval IN ('month','year','none')", name="billing_interval"),
    )


class UserSubscription(Base, TimestampMixin):
    __tablename__ = "user_subscriptions"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_plan_id: Mapped[str | None] = mapped_column(ForeignKey("subscription_plans.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(24))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint("status IN ('trialing','active','past_due','cancelled','expired')", name="status"),
        Index("ix_user_subscriptions_user_id_status", "user_id", "status"),
    )


class BillingRecord(Base, CreatedMixin):
    __tablename__ = "billing_records"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("user_subscriptions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # subscription|usage|adjustment|refund
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)  # open|paid|void|failed
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (Index("ix_billing_records_user_id_created_at", "user_id", "created_at"),)


class PaymentRecord(Base, CreatedMixin):
    __tablename__ = "payment_records"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = mapped_column(IdType, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    billing_record_id: Mapped[str | None] = mapped_column(ForeignKey("billing_records.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128))
    method: Mapped[str | None] = mapped_column(String(16))  # card|upi|netbanking|wallet
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pending|succeeded|failed|refunded
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_payment_id", name="uq_payment_records_provider_provider_payment_id"
        ),
        Index("ix_payment_records_user_id_created_at", "user_id", "created_at"),
    )


class SystemLog(Base, CreatedMixin):
    __tablename__ = "system_logs"

    id: Mapped[str] = pk()
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    __table_args__ = (Index("ix_system_logs_created_at", "created_at"),)


class AuditLog(Base, CreatedMixin):
    """Security-relevant actions. Append-only; never stores secrets."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = pk()
    tenant_id: Mapped[str | None] = mapped_column(IdType)
    actor_id: Mapped[str | None] = mapped_column(IdType)  # no FK: survives user deletion
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    __table_args__ = (
        Index("ix_audit_logs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_audit_logs_actor_id_created_at", "actor_id", "created_at"),
    )
