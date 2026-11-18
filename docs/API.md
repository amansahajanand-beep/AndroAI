# API

Base: `http://localhost:8000`. Interactive docs: `/docs`.

## Versioning

Feature endpoints live under `/api/v1`. Breaking changes → new `api/v2` package; v1 stays stable. Operational endpoints (`/health`) are unversioned.

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
