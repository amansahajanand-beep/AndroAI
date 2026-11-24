"""build numbers per project, user preferences

Revision ID: 0003
Revises: 0002

* build_jobs.number: per-project sequence shown as "build #14" in the UI. Added nullable,
  backfilled in creation order, then made NOT NULL + unique (backward compatible for rows
  that already exist).
* users.preferences: UI preferences (theme, defaults, notifications) as JSON.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("build_jobs", sa.Column("number", sa.Integer(), nullable=True))
    # Single portable statement (also valid in offline --sql mode): number = rank by creation order per project.
    op.execute(
        "UPDATE build_jobs SET number = ("
        "SELECT COUNT(*) FROM build_jobs b2 WHERE b2.project_id = build_jobs.project_id AND "
        "(b2.created_at < build_jobs.created_at OR (b2.created_at = build_jobs.created_at AND b2.id <= build_jobs.id)))"
    )
    with op.batch_alter_table("build_jobs") as batch:
        batch.alter_column("number", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_build_jobs_project_id_number", ["project_id", "number"])

    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.add_column("users", sa.Column("preferences", json_type, nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("preferences", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("preferences")
    with op.batch_alter_table("build_jobs") as batch:
        batch.drop_constraint("uq_build_jobs_project_id_number", type_="unique")
        batch.drop_column("number")
