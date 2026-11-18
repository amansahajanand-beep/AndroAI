# AndroAI

AI-powered Android application development SaaS platform. Monorepo.

> Status: **repository foundation only.** No product features, AI workflows or Android builds exist yet. See [docs/IMPLEMENTATION_PROGRESS.md](docs/IMPLEMENTATION_PROGRESS.md).

## Layout and ownership

| Path | Purpose | Owner |
|---|---|---|
| `apps/web` | Next.js frontend | Person 1 |
| `workers/orchestration` | LangGraph orchestration worker | Person 2 |
| `workers/ai-agent` | Code-generation worker | Person 3 |
| `apps/api`, `workers/android-build`, `workers/android-test`, `infrastructure/`, `docker-compose.yml`, DB/migrations, CI | Backend, infra, integration | Person 4 |
| `packages/contracts` | Shared service contracts (single source of truth) | Person 4 maintains; changes need producer + consumer owner approval |
| `packages/agent-core/orchestration` | Orchestration-only library code | Person 2 |
| `packages/agent-core/codegen` | Codegen-only library code | Person 3 |
| `packages/storage`, `packages/android-tools`, `packages/shared-types` | Reserved (empty) | Person 4 (`shared-types`: Person 1 consumes) |

Details: [docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start (local, no Docker)

Prereqs: Python 3.11+ (3.12 used in images), Node 20+ (22 used in images), PostgreSQL and Redis for readiness checks.

```bash
cp .env.example .env          # then edit; required: DATABASE_URL, REDIS_URL, JWT_SECRET
make install                  # or see Makefile for the underlying commands
make api                      # http://localhost:8000/health
make web                      # http://localhost:3000
make test
```

Windows without `make`: use the commands inside the Makefile (venv at `.venv/Scripts/python`).

## Docker

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, JWT_SECRET
docker compose config         # validate
docker compose up --build     # web :3000, api :8000, postgres :5432, redis :6379
```

Android build/test workers are separate images and are not in the compose file yet. The API image never contains the Android SDK.

## Contracts

`packages/contracts` (`androai_contracts`) defines every cross-service message. Import it; never redefine its models. Export JSON Schema for non-Python consumers with `make schemas`.
