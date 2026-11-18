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
