# Backend Progress (Person 4)

Branch: `p4/backend-foundation`. Status key: **Done** = implemented and covered by automated tests; **Not started** = nothing exists yet.

## Verification status (read this first)

All tests run against **SQLite and a local-filesystem / moto-mocked S3**. The following have **not** been exercised against real services in this environment (no Docker, PostgreSQL, Redis or S3 available): PostgreSQL execution of the migration (its DDL *does* render with `alembic upgrade head --sql`), Redis-backed rate limiting (in-memory fallback is tested), SMTP sending, a real S3/MinIO bucket, `docker compose build`. Run the compose stack and `alembic upgrade head` on PostgreSQL before relying on any of this.

## Phase 1: foundation (this branch)

| Module | State | Notes |
|---|---|---|
| Database schema + Alembic `0002` | Done | 32 tables; migration is checked to match the models and to downgrade (`tests/test_migrations.py`) |
| Authentication | Done | register, login, logout, refresh rotation with reuse detection, email verification, password reset, change password; argon2id; JWT access tokens bound to a revocable session |
| RBAC | Done | roles `user`, `admin`; permission checked per route; `python -m androai_api.cli create-admin` |
| User management | Done | `/users/me`, admin list/activate/roles |
| Project management | Done | CRUD, tenant-scoped, delete purges object storage |
| Object storage (`packages/storage`) | Done | S3-compatible + local backends, tenant-prefixed key builders, presigned URLs |
| Secure ZIP / APK intake | Done | see SECURITY.md; adversarial tests included |
| File index, editor API, change history, snapshots | Done | optimistic concurrency (`base_sha256`), append-only `project_file_changes`, deterministic snapshot ZIPs |
| Artifact access | Done | signed short-lived download URLs |
| Audit log | Done | auth, uploads, admin actions, artifact access |
| Rate limiting | Done (partial) | auth endpoints only; Redis + in-process fallback |
| Encrypted secret storage | Done (library) | `secrets_vault.py`; nothing stores secrets yet |

## Phase 2: scheduler, worker registry, toolchain detection (this branch)

| Module | State | Notes |
|---|---|---|
| Toolchain detection + compatibility (`packages/android-tools`) | Done | Gradle/AGP/Kotlin/SDK/JDK detection; JDK selection; AGP table **needs verification** (see COMPATIBILITY_MATRIX.md) |
| Job submission, limits, backpressure | Done | per-user pending cap, global queue cap, snapshot at submit |
| Persistent scheduler (claim, leases, priority, fairness, retry, timeout, cancel, blocked) | Done | `services/scheduler.py`, `services/dispatch.py`; 17 end-to-end tests |
| Worker registry + protocol | Done | `/worker/*`, `/admin/workers`, `/admin/queues` |
| Maintenance | Done | `python -m androai_api.cli sweep --loop 15` must run as its own process (not yet in compose) |
| Result delivery to orchestration | Done (untested against Celery) | `BuildResult`/`TestResult` contracts via `send_task`; off unless `NOTIFY_ORCHESTRATION=true`; best effort, relies on orchestration `recover_runs` for lost messages |
| Build usage rows | Done | runtime per attempt, retries included; no plan enforcement yet |

Scheduler concurrency has been tested single-threaded on SQLite. Claim safety on PostgreSQL relies on `FOR UPDATE SKIP LOCKED` and has **not** been exercised with concurrent workers.

## Phase 3: web integration (this branch)

See [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md). Backend additions made for the web app: cookie sessions + CSRF checks, `/auth/session`, project metadata and enriched project/build/test responses, per-project build numbers (migration `0003`), file move / recursive delete / search, project analysis, activity feed, preferences, artifact listing, SSE build log stream, admin overview/audit extras. `@apppilot/contracts` was missing from the repo and has been reconstructed in `packages/shared-types`: **Person 1 must review it**.

## Not started (in planned order)

1. **Android build worker**: the process that claims jobs, unpacks the source, runs Gradle in a sandbox, extracts errors, uploads artifacts; SDK/JDK images; sandbox network policy. `workers/android-build` is still the skeleton.
2. **Test worker + emulator provider** (`workers/android-test`): static/compile/unit runners, KVM/virtualization preflight, external provider adapter.
3. Usage limits, budgets and alerts (tables exist; build usage is recorded, nothing enforces plans).
4. Billing and payment-provider abstraction (tables exist; no logic).
5. Observability (structured logs, metrics, request ids), backups, retention sweeper, blob GC.
6. `/agent` API (needs Person 2's run API shape), visual-editor backend endpoints beyond file history.

## Decisions and open items for the team

- **Agent tables.** Person 2 already owns `orch_agent_*` tables on their own `MetaData`. I did **not** create `agent_runs/steps/messages/checkpoints/memory` to avoid two sources of truth. Person 2 to confirm; if they want those tables in the main Alembic chain, their `OrchBase.metadata` must be added to `migrations/env.py` `target_metadata` (the orchestration package is not an API dependency today).
- **Tenancy.** One tenant per user (`tenant_id == user.id`). `tenant_id` is on every resource table so organisations can be added without a data migration.
- **Source layout.** Project files are stored as content-addressed blobs (`tenants/<t>/projects/<p>/blobs/<sha256>`) indexed in `project_files`; builds consume an immutable ZIP **snapshot** (`BuildJob.source_key` in `packages/contracts` = a snapshot's `storage_key`). Unreferenced blobs are not yet garbage-collected.
- **Contracts.** `packages/contracts` `BuildJob`/`TestJob` have no `tenant_id`, toolchain or output-type fields; I will propose additions (with Person 2 sign-off) when the scheduler lands. No contract was changed in this phase.
- **Registration** reveals whether an email exists (409); login and password reset do not.
- **Rate limits** apply to auth routes only so far.
