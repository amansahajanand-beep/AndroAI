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

## Rules

- API image contains **no** JDK/Android SDK/Gradle.
- Each worker has its own Dockerfile (`workers/*/Dockerfile`, context = repo root) and is deployed independently. `android-build`/`android-test` Dockerfiles carry a TODO for the SDK, owned by Person 4.
- Workers are not in the compose file yet; add them when they have behaviour.

## Reserved directories

`infrastructure/nginx` (sample reverse-proxy config), `docker`, `scripts`, `monitoring`, `deployment`: placeholders; no cloud resources are provisioned.

## Status

Compose file and Dockerfiles were written but **not built or validated** in the bootstrap environment (Docker unavailable). Run `docker compose config` and `docker compose build` first.
