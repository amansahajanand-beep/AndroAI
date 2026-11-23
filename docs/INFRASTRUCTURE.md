# Infrastructure

## Local stack (`docker-compose.yml`)

| Service | Image | Port |
|---|---|---|
| postgres | postgres:16-alpine | 5432 |
| redis | redis:7-alpine | 6379 |
| api | `apps/api/Dockerfile` (python:3.12-slim, context = repo root) | 8000 |
| web | `apps/web/Dockerfile` (node:22-alpine, standalone output, context = `apps/web`) | 3000 |

```bash
cp .env.example .env
docker compose config
docker compose up --build
docker compose exec api alembic upgrade head   # api WORKDIR is apps/api
```

## Backend runtime notes

- `docker compose exec api alembic upgrade head`, then `docker compose exec -e ADMIN_PASSWORD=... api python -m androai_api.cli create-admin you@example.com`.
- Local dev stores objects on disk (`STORAGE_BACKEND=local`, volume `apidata`). Production must use `STORAGE_BACKEND=s3` with a **private** bucket (the app refuses to start otherwise); any S3-compatible service works (AWS S3, MinIO, R2, Spaces) via `S3_ENDPOINT_URL`.
- Nginx must cap request bodies (`client_max_body_size`, sample in `infrastructure/nginx/nginx.conf`) at or above `UPLOAD_MAX_BYTES`, and set `X-Forwarded-For`; then set `TRUST_PROXY_HEADERS=true`.
- Email: `EMAIL_BACKEND=smtp` + `SMTP_*` before enabling `REQUIRE_EMAIL_VERIFICATION`.
- Dependencies: PostgreSQL (state), Redis (rate limits now; queues later), S3-compatible storage. Build/test workers, scheduler, backups and monitoring are not implemented yet (see BACKEND_PROGRESS.md).

## Rules

- API image contains **no** JDK/Android SDK/Gradle.
- Each worker has its own Dockerfile (`workers/*/Dockerfile`, context = repo root) and is deployed independently. `android-build`/`android-test` Dockerfiles carry a TODO for the SDK, owned by Person 4.
- Workers are not in the compose file yet; add them when they have behaviour.

## Reserved directories

`infrastructure/nginx` (sample reverse-proxy config), `docker`, `scripts`, `monitoring`, `deployment`: placeholders; no cloud resources are provisioned.

## Status

Compose file and Dockerfiles were written but **not built or validated** in the bootstrap environment (Docker unavailable). Run `docker compose config` and `docker compose build` first.
