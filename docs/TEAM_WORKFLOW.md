# Team Workflow

## Ownership

| Person | Role | Owns |
|---|---|---|
| 1 | Frontend | `apps/web`, `docs/DESIGN_SYSTEM.md`, `packages/shared-types` (TS types from contract JSON Schema) |
| 2 | AI orchestration | `workers/orchestration`, `packages/agent-core/orchestration` |
| 3 | Code generation | `workers/ai-agent`, `packages/agent-core/codegen` |
| 4 | Backend & infra | `apps/api`, `workers/android-build`, `workers/android-test`, DB/migrations, `infrastructure/`, `packages/storage`, `packages/android-tools`, root Docker/CI files, `packages/contracts` (maintainer) |

Each path has exactly one owner. Touching another person's path requires their review.

## Shared interfaces

`packages/contracts` is shared. A change needs approval from the **producer and consumer owners** of the affected model (listed in each model's docstring). Process:

1. Open a PR touching only contracts (+ `make schemas` output).
2. Tag both owners; merge after both approve.
3. Bump `SCHEMA_VERSION` for breaking changes; consumers update in follow-up PRs.

`agent-core/orchestration` and `agent-core/codegen` must not import each other; shared code goes through contracts.

## Git

- `main` is protected: PRs + CI green + one review (enable in GitHub settings).
- Branches: `p1/<topic>`, `p2/<topic>`, `p3/<topic>`, `p4/<topic>`.
- Small PRs; rebase on `main` before merge.
- Alembic: one head only (see DATABASE.md).
- Stack changes (frameworks, DBs, queues) need team approval.

## Getting started per developer

- **Person 1**: `cd apps/web && npm install && npm run dev`. API URL via `NEXT_PUBLIC_API_URL`. Types: `make schemas` then generate from `packages/contracts/schemas/*.json`.
- **Person 2**: `pip install -e workers/orchestration` (after contracts). Entry `python -m androai_orchestration` (needs `REDIS_URL`). Add LangGraph when you start the workflow.
- **Person 3**: same pattern with `workers/ai-agent`, package `androai_agent`. Consume `CodingTask`, return `CodingResult`.
- **Person 4**: everything else; first tasks: validate Docker, add DB tables via migrations, object storage package, SDK images.
