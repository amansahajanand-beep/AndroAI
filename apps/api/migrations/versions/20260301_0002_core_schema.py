"""core platform schema: identity, projects, jobs, workers, usage, billing, audit

Revision ID: 0002
Revises: 0001

Generated from the SQLAlchemy models and reviewed by hand. Agent-run tables (`orch_*`)
are owned by the orchestration package and are intentionally not part of this revision.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('actor_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=32), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_actor_id_created_at', 'audit_logs', ['actor_id', 'created_at'], unique=False)
    op.create_index('ix_audit_logs_tenant_id_created_at', 'audit_logs', ['tenant_id', 'created_at'], unique=False)
    op.create_table('permissions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=96), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions')),
    sa.UniqueConstraint('name', name='uq_permissions_name')
    )
    op.create_table('roles',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('name', name='uq_roles_name')
    )
    op.create_table('subscription_plans',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('code', sa.String(length=48), nullable=False),
    sa.Column('name', sa.String(length=96), nullable=False),
    sa.Column('billing_interval', sa.String(length=8), nullable=False),
    sa.Column('price_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('limits', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("billing_interval IN ('month','year','none')", name=op.f('ck_subscription_plans_billing_interval')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscription_plans')),
    sa.UniqueConstraint('code', name='uq_subscription_plans_code')
    )
    op.create_table('system_logs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_system_logs'))
    )
    op.create_index('ix_system_logs_created_at', 'system_logs', ['created_at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name='uq_users_email')
    )
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_table('worker_registry',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('toolchain', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('capabilities', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('draining', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('build','test','emulator')", name=op.f('ck_worker_registry_kind')),
    sa.CheckConstraint("status IN ('idle','busy','unhealthy','offline','draining')", name=op.f('ck_worker_registry_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_worker_registry')),
    sa.UniqueConstraint('name', name='uq_worker_registry_name'),
    sa.UniqueConstraint('token_hash', name='uq_worker_registry_token_hash')
    )
    op.create_index('ix_worker_registry_kind_status', 'worker_registry', ['kind', 'status'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('owner_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('current_snapshot_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source_type IN ('empty','zip','apk','generated')", name=op.f('ck_projects_source_type')),
    sa.CheckConstraint("status IN ('active','archived','deleted')", name=op.f('ck_projects_status')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_projects_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'], unique=False)
    op.create_index('ix_projects_tenant_id_status', 'projects', ['tenant_id', 'status'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('permission_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permissions'))
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('role_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_roles_role_id_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id', name=op.f('pk_user_roles'))
    )
    op.create_table('user_sessions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('family_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('refresh_token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
    sa.UniqueConstraint('refresh_token_hash', name='uq_user_sessions_refresh_token_hash')
    )
    op.create_index('ix_user_sessions_family_id', 'user_sessions', ['family_id'], unique=False)
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'], unique=False)
    op.create_table('user_subscriptions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('plan_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('pending_plan_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('provider', sa.String(length=24), nullable=True),
    sa.Column('provider_subscription_id', sa.String(length=128), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('trialing','active','past_due','cancelled','expired')", name=op.f('ck_user_subscriptions_status')),
    sa.ForeignKeyConstraint(['pending_plan_id'], ['subscription_plans.id'], name=op.f('fk_user_subscriptions_pending_plan_id_subscription_plans'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], name=op.f('fk_user_subscriptions_plan_id_subscription_plans'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_subscriptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_subscriptions'))
    )
    op.create_index('ix_user_subscriptions_user_id_status', 'user_subscriptions', ['user_id', 'status'], unique=False)
    op.create_table('user_tokens',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_tokens')),
    sa.UniqueConstraint('token_hash', name='uq_user_tokens_token_hash')
    )
    op.create_index('ix_user_tokens_user_id', 'user_tokens', ['user_id'], unique=False)
    op.create_table('worker_heartbeats',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('worker_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('active_jobs', sa.Integer(), nullable=False),
    sa.Column('load', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['worker_id'], ['worker_registry.id'], name=op.f('fk_worker_heartbeats_worker_id_worker_registry'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_worker_heartbeats'))
    )
    op.create_index('ix_worker_heartbeats_worker_id_created_at', 'worker_heartbeats', ['worker_id', 'created_at'], unique=False)
    op.create_table('ai_usage',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('agent_run_id', sa.String(length=64), nullable=True),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=96), nullable=False),
    sa.Column('input_tokens', sa.BigInteger(), nullable=False),
    sa.Column('output_tokens', sa.BigInteger(), nullable=False),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_ai_usage_project_id_projects'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_usage_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_usage'))
    )
    op.create_index('ix_ai_usage_tenant_id_created_at', 'ai_usage', ['tenant_id', 'created_at'], unique=False)
    op.create_table('billing_records',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('subscription_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['subscription_id'], ['user_subscriptions.id'], name=op.f('fk_billing_records_subscription_id_user_subscriptions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_billing_records_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_records'))
    )
    op.create_index('ix_billing_records_user_id_created_at', 'billing_records', ['user_id', 'created_at'], unique=False)
    op.create_table('build_usage',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('job_kind', sa.String(length=16), nullable=False),
    sa.Column('job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('runtime_seconds', sa.Float(), nullable=False),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_build_usage_project_id_projects'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_build_usage_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_build_usage')),
    sa.UniqueConstraint('job_kind', 'job_id', 'attempt', name='uq_build_usage_job_kind_job_id_attempt')
    )
    op.create_index('ix_build_usage_tenant_id_created_at', 'build_usage', ['tenant_id', 'created_at'], unique=False)
    op.create_table('project_activity',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('actor_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_project_activity_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_activity_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_activity'))
    )
    op.create_index('ix_project_activity_project_id_created_at', 'project_activity', ['project_id', 'created_at'], unique=False)
    op.create_table('project_artifacts',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('build_job_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_artifacts_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_artifacts'))
    )
    op.create_index('ix_project_artifacts_expires_at', 'project_artifacts', ['expires_at'], unique=False)
    op.create_index('ix_project_artifacts_project_id', 'project_artifacts', ['project_id'], unique=False)
    op.create_index('ix_project_artifacts_tenant_id', 'project_artifacts', ['tenant_id'], unique=False)
    op.create_table('project_editor_sessions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_editor_sessions_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_project_editor_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_editor_sessions'))
    )
    op.create_index('ix_project_editor_sessions_project_id', 'project_editor_sessions', ['project_id'], unique=False)
    op.create_table('project_file_snapshots',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('created_by', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_project_file_snapshots_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_file_snapshots_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_file_snapshots')),
    sa.UniqueConstraint('project_id', 'version', name='uq_project_file_snapshots_project_id_version')
    )
    op.create_index('ix_project_file_snapshots_tenant_id', 'project_file_snapshots', ['tenant_id'], unique=False)
    op.create_table('project_files',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('is_binary', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_files_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_files')),
    sa.UniqueConstraint('project_id', 'path', name='uq_project_files_project_id_path')
    )
    op.create_index('ix_project_files_tenant_id', 'project_files', ['tenant_id'], unique=False)
    op.create_table('project_uploads',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('zip','apk')", name=op.f('ck_project_uploads_kind')),
    sa.CheckConstraint("status IN ('received','processed','rejected')", name=op.f('ck_project_uploads_status')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_uploads_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_project_uploads_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_uploads'))
    )
    op.create_index('ix_project_uploads_project_id', 'project_uploads', ['project_id'], unique=False)
    op.create_index('ix_project_uploads_tenant_id', 'project_uploads', ['tenant_id'], unique=False)
    op.create_table('storage_usage',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('source_bytes', sa.BigInteger(), nullable=False),
    sa.Column('artifact_bytes', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_storage_usage_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_storage_usage'))
    )
    op.create_index('ix_storage_usage_tenant_id_created_at', 'storage_usage', ['tenant_id', 'created_at'], unique=False)
    op.create_table('build_jobs',
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('snapshot_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('variant', sa.String(length=16), nullable=False),
    sa.Column('output_type', sa.String(length=8), nullable=False),
    sa.Column('gradle_tasks', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('worker_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blocked_reason', sa.String(length=255), nullable=True),
    sa.Column('agent_run_id', sa.String(length=64), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('toolchain', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("output_type IN ('apk','aab')", name=op.f('ck_build_jobs_output_type')),
    sa.CheckConstraint("state IN ('queued','starting','running','completed','failed','cancelled','blocked')", name=op.f('ck_build_jobs_state')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_build_jobs_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['project_file_snapshots.id'], name=op.f('fk_build_jobs_snapshot_id_project_file_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_build_jobs_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_build_jobs'))
    )
    op.create_index('ix_build_jobs_project_id', 'build_jobs', ['project_id'], unique=False)
    op.create_index('ix_build_jobs_state_priority', 'build_jobs', ['state', 'priority', 'queued_at'], unique=False)
    op.create_index('ix_build_jobs_tenant_id_state', 'build_jobs', ['tenant_id', 'state'], unique=False)
    op.create_table('payment_records',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('billing_record_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('provider', sa.String(length=24), nullable=False),
    sa.Column('provider_payment_id', sa.String(length=128), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['billing_record_id'], ['billing_records.id'], name=op.f('fk_payment_records_billing_record_id_billing_records'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payment_records_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_records')),
    sa.UniqueConstraint('provider', 'provider_payment_id', name='uq_payment_records_provider_provider_payment_id')
    )
    op.create_index('ix_payment_records_user_id_created_at', 'payment_records', ['user_id', 'created_at'], unique=False)
    op.create_table('project_file_changes',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('change_type', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('editor_session_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('before_sha256', sa.String(length=64), nullable=True),
    sa.Column('after_sha256', sa.String(length=64), nullable=True),
    sa.Column('before_key', sa.String(length=1024), nullable=True),
    sa.Column('after_key', sa.String(length=1024), nullable=True),
    sa.Column('agent_run_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("change_type IN ('create','update','delete')", name=op.f('ck_project_file_changes_change_type')),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_project_file_changes_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['editor_session_id'], ['project_editor_sessions.id'], name=op.f('fk_project_file_changes_editor_session_id_project_editor_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_file_changes_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_file_changes'))
    )
    op.create_index('ix_project_file_changes_project_id_created_at', 'project_file_changes', ['project_id', 'created_at'], unique=False)
    op.create_table('build_logs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('build_job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('stream', sa.String(length=8), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['build_job_id'], ['build_jobs.id'], name=op.f('fk_build_logs_build_job_id_build_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_build_logs')),
    sa.UniqueConstraint('build_job_id', 'seq', name='uq_build_logs_build_job_id_seq')
    )
    op.create_table('build_results',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('build_job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('artifact_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('log_key', sa.String(length=1024), nullable=True),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('errors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['project_artifacts.id'], name=op.f('fk_build_results_artifact_id_project_artifacts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['build_job_id'], ['build_jobs.id'], name=op.f('fk_build_results_build_job_id_build_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_build_results')),
    sa.UniqueConstraint('build_job_id', name='uq_build_results_build_job_id')
    )
    op.create_table('test_jobs',
    sa.Column('project_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('snapshot_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('build_job_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('emulator_profile', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('worker_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blocked_reason', sa.String(length=255), nullable=True),
    sa.Column('agent_run_id', sa.String(length=64), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('toolchain', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('static','compile','unit','instrumented','emulator')", name=op.f('ck_test_jobs_kind')),
    sa.CheckConstraint("state IN ('queued','starting','running','completed','failed','cancelled','blocked')", name=op.f('ck_test_jobs_state')),
    sa.ForeignKeyConstraint(['build_job_id'], ['build_jobs.id'], name=op.f('fk_test_jobs_build_job_id_build_jobs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_test_jobs_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['project_file_snapshots.id'], name=op.f('fk_test_jobs_snapshot_id_project_file_snapshots')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_test_jobs_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_jobs'))
    )
    op.create_index('ix_test_jobs_project_id', 'test_jobs', ['project_id'], unique=False)
    op.create_index('ix_test_jobs_state_priority', 'test_jobs', ['state', 'priority', 'queued_at'], unique=False)
    op.create_index('ix_test_jobs_tenant_id_state', 'test_jobs', ['tenant_id', 'state'], unique=False)
    op.create_table('test_reports',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('test_job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('format', sa.String(length=16), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['test_job_id'], ['test_jobs.id'], name=op.f('fk_test_reports_test_job_id_test_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_reports'))
    )
    op.create_index('ix_test_reports_test_job_id', 'test_reports', ['test_job_id'], unique=False)
    op.create_table('test_results',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('test_job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('not_run_reason', sa.String(length=255), nullable=True),
    sa.Column('passed', sa.Integer(), nullable=False),
    sa.Column('failed', sa.Integer(), nullable=False),
    sa.Column('skipped', sa.Integer(), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome IN ('passed','failed','not_run','error')", name=op.f('ck_test_results_outcome')),
    sa.ForeignKeyConstraint(['test_job_id'], ['test_jobs.id'], name=op.f('fk_test_results_test_job_id_test_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_results')),
    sa.UniqueConstraint('test_job_id', name='uq_test_results_test_job_id')
    )


def downgrade() -> None:

    op.drop_table('test_results')
    op.drop_index('ix_test_reports_test_job_id', table_name='test_reports')
    op.drop_table('test_reports')
    op.drop_index('ix_test_jobs_tenant_id_state', table_name='test_jobs')
    op.drop_index('ix_test_jobs_state_priority', table_name='test_jobs')
    op.drop_index('ix_test_jobs_project_id', table_name='test_jobs')
    op.drop_table('test_jobs')
    op.drop_table('build_results')
    op.drop_table('build_logs')
    op.drop_index('ix_project_file_changes_project_id_created_at', table_name='project_file_changes')
    op.drop_table('project_file_changes')
    op.drop_index('ix_payment_records_user_id_created_at', table_name='payment_records')
    op.drop_table('payment_records')
    op.drop_index('ix_build_jobs_tenant_id_state', table_name='build_jobs')
    op.drop_index('ix_build_jobs_state_priority', table_name='build_jobs')
    op.drop_index('ix_build_jobs_project_id', table_name='build_jobs')
    op.drop_table('build_jobs')
    op.drop_index('ix_storage_usage_tenant_id_created_at', table_name='storage_usage')
    op.drop_table('storage_usage')
    op.drop_index('ix_project_uploads_tenant_id', table_name='project_uploads')
    op.drop_index('ix_project_uploads_project_id', table_name='project_uploads')
    op.drop_table('project_uploads')
    op.drop_index('ix_project_files_tenant_id', table_name='project_files')
    op.drop_table('project_files')
    op.drop_index('ix_project_file_snapshots_tenant_id', table_name='project_file_snapshots')
    op.drop_table('project_file_snapshots')
    op.drop_index('ix_project_editor_sessions_project_id', table_name='project_editor_sessions')
    op.drop_table('project_editor_sessions')
    op.drop_index('ix_project_artifacts_tenant_id', table_name='project_artifacts')
    op.drop_index('ix_project_artifacts_project_id', table_name='project_artifacts')
    op.drop_index('ix_project_artifacts_expires_at', table_name='project_artifacts')
    op.drop_table('project_artifacts')
    op.drop_index('ix_project_activity_project_id_created_at', table_name='project_activity')
    op.drop_table('project_activity')
    op.drop_index('ix_build_usage_tenant_id_created_at', table_name='build_usage')
    op.drop_table('build_usage')
    op.drop_index('ix_billing_records_user_id_created_at', table_name='billing_records')
    op.drop_table('billing_records')
    op.drop_index('ix_ai_usage_tenant_id_created_at', table_name='ai_usage')
    op.drop_table('ai_usage')
    op.drop_index('ix_worker_heartbeats_worker_id_created_at', table_name='worker_heartbeats')
    op.drop_table('worker_heartbeats')
    op.drop_index('ix_user_tokens_user_id', table_name='user_tokens')
    op.drop_table('user_tokens')
    op.drop_index('ix_user_subscriptions_user_id_status', table_name='user_subscriptions')
    op.drop_table('user_subscriptions')
    op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')
    op.drop_index('ix_user_sessions_family_id', table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_index('ix_projects_tenant_id_status', table_name='projects')
    op.drop_index('ix_projects_owner_id', table_name='projects')
    op.drop_table('projects')
    op.drop_index('ix_worker_registry_kind_status', table_name='worker_registry')
    op.drop_table('worker_registry')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_table('users')
    op.drop_index('ix_system_logs_created_at', table_name='system_logs')
    op.drop_table('system_logs')
    op.drop_table('subscription_plans')
    op.drop_table('roles')
    op.drop_table('permissions')
    op.drop_index('ix_audit_logs_tenant_id_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_id_created_at', table_name='audit_logs')
    op.drop_table('audit_logs')
