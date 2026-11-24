# API

Base: `http://localhost:8000`. Interactive docs: `/docs`.

## Versioning

Feature endpoints live under `/api/v1`. Breaking changes â†’ new `api/v2` package; v1 stays stable. Operational endpoints (`/health`) are unversioned.

## Endpoints

### `GET /health` (liveness)
Does not touch dependencies.
```json
{"status":"ok","service":"androai-api","version":"0.1.0","environment":"development","time":"2026-01-01T00:00:00+00:00"}
```

### `GET /api/v1/health/ready` (readiness)
Checks PostgreSQL and Redis. `200` when both reachable, otherwise `503`:
```json
{"status":"degraded","checks":{"database":false,"redis":true}}
```

## Authentication

Two ways to authenticate; both end up as the same revocable session:

- **Bearer token** (API clients, workers' admin tooling): `Authorization: Bearer <access_token>` from `/auth/login`. Not subject to CSRF checks.
- **Cookies** (the web app): `/auth/login` also sets httpOnly cookies `ap_access` (path `/`) and `ap_refresh` (path `/api/v1/auth`), `SameSite=Lax`, `Secure` in production. Cookie-authenticated **unsafe** requests (POST/PUT/PATCH/DELETE) must carry an `Origin` (or `Referer`) from `APP_URL`/`ALLOWED_ORIGINS`, else `403 csrf`. `/auth/refresh` and `/auth/logout` accept the refresh cookie when no body is sent. `GET /auth/session` returns `{user, expires_at}`.

Access tokens live 30 min (`JWT_ACCESS_TTL_MINUTES`) and are bound to a server-side session, so logout, password reset, deactivation and refresh-token reuse revoke them immediately. Refresh tokens are opaque, single-use (rotated on every refresh), 30 days. Changing your password signs out your *other* sessions but keeps the current one.

Client flow: `login` -> on `401 invalid_token` call `refresh` once -> retry; if refresh fails, sign in again.

## v1 endpoints (implemented)

OpenAPI: `/openapi.json`, UI at `/docs`. Pagination: `?limit=&offset=` returning `{items,total,limit,offset}`.

### Auth (`/api/v1/auth`) â€” all *public* unless noted; IP rate-limited (`429 rate_limited`)
| Method | Path | Body -> Response |
|---|---|---|
| POST | `/register` | `{email,password,display_name?}` -> `201 User`. Password >= 10 chars. `409 email_taken`, `422 weak_password`. Sends a verification email |
| GET | `/session` | *auth required* -> `{user, expires_at}` |
| POST | `/login` | `{email,password,remember?}` -> `{user, tokens:{access_token,access_expires_at,refresh_token,refresh_expires_at}}`. `401 invalid_credentials` (same for unknown email), `403 email_not_verified` when enforced |
| POST | `/refresh` | `{refresh_token}` or the refresh cookie -> new `tokens` (and cookies) |
| POST | `/logout` | `{refresh_token}` or the refresh cookie -> `204` (revokes the whole login session, clears cookies) |
| POST | `/verify-email` | `{token}` |
| POST | `/resend-verification` | *auth required* |
| POST | `/forgot-password` | `{email}` -> `202` always |
| POST | `/reset-password` | `{token,new_password}`; revokes all sessions |
| POST | `/change-password` | *auth required* `{current_password,new_password}`; revokes all sessions |

### Users (`/api/v1/users`)
`GET /me`, `PATCH /me {display_name}`, `POST /me/logout-all`, `GET|PUT /me/preferences` (`theme`, `default_language`, `default_ui_toolkit`, `email_*` flags). `User` = `{id,email,display_name,is_active,email_verified,roles,permissions,created_at}`.

### Projects (`/api/v1/projects`) â€” permission `projects:manage`; other tenants' ids return `404`
| Method | Path | Notes |
|---|---|---|
| POST / GET | `` | create `{name,description?,metadata?}` (`metadata`: `language, ui_toolkit, package_name, min_sdk, target_sdk, requirements, config`, all validated); list `?status=active|archived` (items include `storage_bytes`, `active_jobs`, `last_build`) |
| GET | `/activity/recent?limit=` | newest activity across your projects |
| GET / PATCH / DELETE | `/{id}` | PATCH `{name?,description?,status?}`; DELETE purges stored files, `409 project_busy` if jobs are running |
| POST | `/{id}/uploads` | multipart `file` (`.zip` source or `.apk`). `Content-Length` required, max 200 MB. ZIP replaces the file set and creates a snapshot; APK is stored as an artifact only. `413`, `415`, `422 invalid_archive|invalid_apk` |
| GET | `/{id}/uploads` | upload history incl. rejected |
| GET | `/{id}/files` | current file index |
| GET | `/{id}/files/search?q=` | text search (max 200 hits) |
| POST | `/{id}/files/move` | `{from, to}` rename a file or directory atomically (`409 exists`) |
| GET | `/{id}/analysis` | detected Gradle/AGP/Kotlin/SDK settings, modules, whether it can be built |
| GET / PUT | `/{id}/files/content?path=` | PUT `{content, base_sha256}`; `409 conflict` if the file changed since `base_sha256` (omit it only when creating) |
| DELETE | `/{id}/files?path=&base_sha256=&recursive=` | `recursive=true` deletes a directory tree |
| GET | `/{id}/files/history?path=` | change history (source: upload/editor/agent/ui_editor) |
| GET / POST | `/{id}/snapshots` | immutable ZIP of the tree; identical content reuses the latest version |
| GET | `/{id}/activity`, `/{id}/artifacts` | |

### Artifacts (`/api/v1/artifacts`)
`GET /?build_id=&project_id=` (list), `GET /{id}`, `POST /{id}/download-url` -> `{url, expires_in}` (HMAC-signed, 5 min), `GET /{id}/content?exp=&sig=` (*public*; authorised by the signature), `DELETE /{id}`.

### Admin (`/api/v1/admin`) â€” role `admin`
`GET /users?q=`, `GET /users/{id}`, `PATCH /users/{id} {is_active?, roles?}`, `GET /audit-logs?action=&actor_id=`.

### Builds (`/api/v1/builds`) and tests (`/api/v1/tests`) — permission `builds:run`; tenant-scoped (`404` across tenants)
| Method | Path | Notes |
|---|---|---|
| POST | `/builds` | `{project_id, variant: debug|release, output_type: apk|aab, gradle_tasks?, priority 50-200, timeout_seconds}`. Snapshots the project's current files, detects the toolchain, queues the job. `422 unsupported_project` (no wrapper / unknown AGP / compileSdk), `422 invalid_gradle_tasks` (plain task names only), `429 queue_limit`, `503 queue_full`. **Release builds are unsigned.** Returns the job in state `queued`, or `blocked` with `blocked_reason` when no live worker can run it |
| GET | `/builds`, `/builds/{id}` | list (`?project_id=&state=`), detail incl. `toolchain.{detected,required,jdk}` |
| POST | `/builds/{id}/cancel` | queued/blocked: cancelled at once; running: `cancel_requested` and the worker aborts. `409` if finished |
| GET | `/builds/{id}/logs?after_seq=` | poll to tail |
| GET | `/builds/{id}/logs/stream` | SSE: `log` `{seq,line}` then `end` `{status}` |
| GET | `/builds/{id}/result` | `{state, artifact_id, duration_seconds, errors:[{file,line,message}]}`; download the artifact via `/artifacts/{id}/download-url` |
| POST | `/tests` | `{project_id, kind: static|compile|unit|instrumented|emulator, build_job_id?, emulator_profile?, ...}`. `instrumented`/`emulator` need a finished `build_job_id` and a KVM-capable worker, otherwise the job is `blocked` |
| GET / POST | `/tests`, `/tests/{id}`, `/tests/{id}/cancel`, `/tests/{id}/result`, `/tests/{id}/reports` | `result.outcome` is `passed|failed|not_run|error`; `not_run` carries `not_run_reason` |

Build items include `number` (per project), `commit_sha`, `artifact_ids`, `errors`, `duration_seconds`; test items embed `result`. Job states: `queued, starting, running, completed, failed, cancelled, blocked`. Retries: infrastructure failures and lost workers are retried (`max_attempts` 2, backoff) and every attempt is metered.

### Worker protocol (`/api/v1/worker`) — bearer token `wk_...` issued by an admin; for worker implementers
`POST /register {toolchain:{jdks,platforms}, capabilities:{kvm,emulator}}` -> `POST /heartbeat` every ~30 s (returns `cancel: [job ids]`) -> `POST /claim` (`{job: null}` when idle) -> `GET /jobs/{build|test}/{id}/source` (immutable ZIP; hostile content) -> `POST .../start` -> `POST .../logs {stream, content}` (returns `cancel`) -> `POST .../files` (multipart `role=artifact|report`) -> `POST .../complete {outcome, error_code?, retryable?, errors?, artifact_id?, test_outcome?, passed/failed/skipped?, not_run_reason?}`. Instrumented tests fetch the APK from `GET /jobs/test/{id}/apk`. A claim is a lease (default 120 s) extended by heartbeats and log posts; silence lets the scheduler retry the job elsewhere.

### Admin additions — permission `admin:workers`
`POST /admin/workers {name, kind: build|test|emulator, provider, capacity}` (returns the token **once**), `GET /admin/workers`, `PATCH /admin/workers/{id} {capacity?, draining?}`, `POST /admin/workers/{id}/rotate-token`, `DELETE /admin/workers/{id}`, `GET /admin/queues` (depth per queue/state, live vs offline workers). `GET /admin/overview` (needs `admin:system`): users, active users, projects, builds today, failure rate, queue depth, AI cost today. `GET /admin/users` includes `project_count`; `GET /admin/audit-logs` includes `actor_email`.

### Not yet implemented
`/agent/*`, `/usage/*`, `/billing/*` (see BACKEND_PROGRESS.md). They will be added under `/api/v1` without changing the endpoints above.

## Error envelope

All errors:
```json
{"error":{"code":"validation_error","message":"Invalid request","details":[]}}
```
Raise `androai_api.errors.AppError(status, code, message)` for domain errors. Codes: `http_<status>`, `validation_error`, `internal_error`.

## Adding an endpoint

1. Create a module/router under `androai_api/` (e.g. `projects/router.py`).
2. Include it in `api/v1/router.py` with a prefix.
3. Use `get_db` from `androai_api.db` for sessions and contracts from `androai_contracts` for worker payloads.

## Orchestration worker interface (Celery, queue `orchestration`)

Not HTTP. The API service enqueues these tasks by name; payloads are JSON (contract models). Tasks are idempotent. Full detail in [AI_ORCHESTRATION_PROGRESS.md](AI_ORCHESTRATION_PROGRESS.md).

| Task | Arguments | Notes |
|---|---|---|
| `androai_orchestration.start_run` | `agent_task` (`AgentTask`), `tenant_id`, `workflow` (`new_app`, `modify` or `repair`), `failure`, `source_key` | Idempotent on `AgentTask.id`. `repair` requires `failure` `{log, error_code, retryable}` and `source_key`. |
| `androai_orchestration.respond` | `tenant_id`, `project_id`, `run_id`, `reply` | Clarification: `{"answers": {...}}`. Approval: `{"approved": true}` or `{"approved": false, "feedback": "..."}`. |
| `androai_orchestration.cancel_run` | `tenant_id`, `project_id`, `run_id` | |
| `androai_orchestration.handle_coding_result` | `CodingResult` | Sent by the ai-agent worker. |
| `androai_orchestration.handle_build_result` / `handle_test_result` | `BuildResult` / `TestResult` | Sent by the build/test workers. |
| `androai_orchestration.recover_runs` | `stale_seconds` | Scheduled (beat). |

Each start/respond/result task returns a run snapshot: `{run_id, status, workflow, pending, result, error}`. `pending` is what the run waits for (`clarification` questions, `plan_approval` plan, or an awaited job). Run statuses: `running`, `waiting_clarification`, `waiting_approval`, `waiting_coding`, `waiting_validation`, `succeeded`, `failed`, `cancelled`. Error codes include `budget_exceeded`, `revision_limit`, `plan_rejected`, `coding_failed`, `unsafe_output`, `out_of_scope_change`, `repair_exhausted`, `infrastructure_failure`, `step_limit`, `empty_project`, `planning_failed`, `provider_failed`.
