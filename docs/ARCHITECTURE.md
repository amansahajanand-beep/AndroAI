# Architecture

## Overview

```
Browser (apps/web, Next.js)
   │ HTTPS/JSON
   ▼
apps/api (FastAPI) ──── PostgreSQL (state, via SQLAlchemy/Alembic)
   │  enqueue (Celery over Redis, contracts as payloads)
   ▼
workers/orchestration ──► workers/ai-agent        (control plane, Python only)
   │
   ▼
workers/android-build ─► workers/android-test     (JDK + Android SDK + Gradle; isolated images)
```

Object storage (S3-compatible) holds project snapshots, APKs, logs and reports. Services exchange *keys*, not blobs.

## Principles

- **Contracts first.** All cross-service payloads are models in `packages/contracts`. Producers and consumers import them; no copies.
- **Control plane vs. build plane.** The API and orchestration/agent workers never run Gradle and never ship the Android SDK. Only `android-build` and `android-test` do, in separately deployable images.
- **Queues.** One Celery queue per worker, names in `androai_contracts.Queues`.
- **Config via environment**, validated at startup (API: `androai_api/config.py`).

## Modules

| Module | Responsibility | Status |
|---|---|---|
| apps/web | UI | Placeholder page + API status check |
| apps/api | HTTP API, auth, persistence, task dispatch | `/health`, `/api/v1/health/ready`, error envelope, DB/Redis abstractions |
| workers/orchestration | Agent workflow (LangGraph planned) | Celery skeleton |
| workers/ai-agent | Code generation | Celery skeleton |
| workers/android-build | Gradle builds | Celery skeleton |
| workers/android-test | Android tests | Celery skeleton |
| packages/contracts | Shared schemas | 8 models |

## Shared interfaces

| Flow | Contract | Producer → Consumer |
|---|---|---|
| User request | `AgentTask`, `AgentTaskStatus` | API → orchestration (status back) |
| Code generation | `CodingTask`, `CodingResult` | orchestration → ai-agent (result back) |
| Build | `BuildJob`, `BuildResult` | API/orchestration → android-build |
| Test | `TestJob`, `TestResult` | API/orchestration → android-test |

Schemas are versioned via `schema_version` (`ContractModel`); unknown fields are rejected.

## Not yet decided / deferred

LangGraph checkpoint storage, LLM provider abstraction design, auth flows, object-storage client (`packages/storage`), sandboxing model for builds (see SECURITY.md).
