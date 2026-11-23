# Database

PostgreSQL 16, SQLAlchemy 2.x (sync, psycopg 3), Alembic. Current head: `0002` (core schema). Models: `apps/api/src/androai_api/models/`.

## Connection

`DATABASE_URL=postgresql://user:pass@host:5432/db` (rewritten to `postgresql+psycopg://`). Engine is lazy: `androai_api.db.get_engine()`. Sessions via the `get_db` dependency; services commit explicitly.

## Conventions

- Ids: UUID (strings in Python, native `uuid` in PostgreSQL). Timestamps: timezone-aware UTC (`UTCDateTime`). JSON: `JSONB` on PostgreSQL.
- Money: integer minor units + ISO currency code.
- Every tenant-owned table has `tenant_id` and an index starting with it (or on `project_id`). Queries must filter by it; routes load projects only through `deps.get_owned_project`.
- Constraint names come from the naming convention in `db/base.py`; enumerations are `CHECK` constraints on `String` columns (adding a value is a cheap migration).
- No large binaries in the database; rows hold object-storage keys.

## Tables

| Area | Tables |
|---|---|
| Identity | `users`, `user_sessions` (refresh-token rows, rotation families), `user_tokens` (verify/reset), `roles`, `permissions`, `role_permissions`, `user_roles` |
| Projects | `projects`, `project_files` (current path -> blob index), `project_uploads`, `project_artifacts`, `project_activity`, `project_file_changes` (append-only history), `project_editor_sessions`, `project_file_snapshots` (immutable ZIPs, build input) |
| Execution | `build_jobs`, `build_results`, `build_logs`, `test_jobs`, `test_results`, `test_reports`, `worker_registry`, `worker_heartbeats` |
| Usage | `ai_usage`, `build_usage`, `storage_usage` |
| Billing | `subscription_plans`, `user_subscriptions`, `billing_records`, `payment_records` |
| Operations | `system_logs`, `audit_logs` |

Not in this schema: `agent_runs`, `agent_steps`, `agent_messages`, `agent_checkpoints`, `agent_memory`. Person 2's `orch_agent_*` tables (own `MetaData`, `OrchBase`) already cover runs/steps; see BACKEND_PROGRESS.md for the open decision.

Notes:
- Job tables (`build_jobs`, `test_jobs`) share scheduler columns (incl. `toolchain` JSON = detected / required / selected JDK): `state` (`queued, starting, running, completed, failed, cancelled, blocked`), `priority` (lower first), `attempts/max_attempts`, `timeout_seconds`, `cancel_requested`, `worker_id`, `lease_expires_at`, `not_before`. Index `(state, priority, queued_at)` serves "next job" queries.
- `test_results.outcome` includes `not_run` + `not_run_reason`: an unavailable runtime (no KVM, no emulator) is recorded as not run, never as passed.
- `audit_logs.actor_id` has no foreign key so history survives user deletion.
- Deleting a project cascades its files, uploads, artifacts, jobs and snapshots; usage rows keep history (`project_id` set null) and audit rows remain.

## Migrations

Run from `apps/api`:

```bash
alembic upgrade head
alembic revision --autogenerate -m "add x"     # then edit by hand; SQLite autogenerate renders portable types
alembic upgrade head --sql                       # render PostgreSQL DDL without a database (also run in CI)
```

Rules: never edit a merged migration; one linear history (`tests/test_migrations.py` fails on multiple heads); the migration test fails if models and migrations diverge; prefer additive, backward-compatible changes (add nullable column -> backfill -> constrain) so old and new API versions can run during a deploy. Person 4 reviews all migrations.

## Adding tables

1. Define the model in `models/`, export it from `models/__init__.py`.
2. `alembic revision --autogenerate`, review, replace `androai_api.db.types.UTCDateTime(...)` with `sa.DateTime(timezone=True)`, commit.
3. Run `pytest apps/api/tests/test_migrations.py`.
