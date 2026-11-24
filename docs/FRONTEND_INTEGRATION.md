# Frontend <-> Backend Integration

How `apps/web` talks to the FastAPI backend, what is connected, and what still answers "waiting for backend".

## Architecture

```
Browser ──cookies──► Next.js (:3000) ──/api/v1/* rewrite──► FastAPI (:8000)      (dev)
Browser ──cookies──► Nginx ──/api/ ► FastAPI,  / ► Next.js                       (production)
```

- **Contract package**: `packages/shared-types` (`@apppilot/contracts`): `ENDPOINTS` registry + TypeScript types. It was **reconstructed from how the frontend uses it** because the original package was not in the repository. Person 1 should review it; treat it as the source of truth from now on and keep it in step with `docs/API.md`.
- **Transport**: `apps/web/src/lib/api/live/` implements the frontend's `Transport` interface. Every endpoint key maps to one or more backend calls and the response is converted from the backend's snake_case shapes to the contract types (`mappers.ts`, unit-tested). Keys with no handler answer `501 not_implemented`, which every screen already renders as its "waiting for backend" state. `NEXT_PUBLIC_API_MODE=mock` still selects the old mock transport for pure-UI work.
- **Auth**: httpOnly cookies (`ap_access` 30 min, `ap_refresh` 30 days, path `/api/v1/auth`), `SameSite=Lax`, `Secure` in production. JavaScript never sees a token. State-changing cookie requests must carry a trusted `Origin` (CSRF); the browser adds it automatically. A `401` triggers one shared refresh and a retry; if that fails the app redirects to login.
- **Uploads**: the wizard's "signed URL" flow is bridged (`live/uploads.ts`): the file is POSTed as multipart to a freshly created project; if the archive is rejected the project is deleted again so no empty projects pile up.

## Endpoint status

| Area | Status | Notes |
|---|---|---|
| Auth: session, login, register, logout, forgot/reset password | **Live** | register creates the account then signs in |
| Users: profile, change password, preferences | **Live** | changing the password signs out other devices, not this one |
| Users: API keys | Planned | no backend |
| Projects: list/get/create/update/delete | **Live** | "create from prompt" creates an **empty** project (no AI agent connected); the wizard then opens the IDE instead of an agent task |
| Projects: uploads (ZIP / APK) | **Live** | ZIP analysis from detected build files; APK is validated and stored only (no manifest/permission extraction) |
| Projects: activity feed | **Live** | project created, uploads, build and test results |
| Projects: env vars, git log, terminal, live events | Planned | env vars need encrypted storage (vault exists); terminal needs the sandbox |
| Files: tree, read, save (optimistic concurrency), create, move, delete, search | **Live** | directories are `.keep` markers; binary files open as binary |
| Diagnostics | **Live** (derived) | errors of the latest finished build |
| Builds: list/get/start/retry/cancel/logs/log stream (SSE) | **Live** | queues until a worker exists (shows why); **no real build worker yet** |
| Artifacts: list, signed download | **Live** | |
| Tests: list/get/start | **Live** | test cases, screenshots and logs are Planned; "could not run" is shown as **blocked**, never passed |
| Admin: overview, users, workers, audit | **Live** | plan column shows "—" (billing not connected) |
| Agent: tasks, messages, change sets | Planned | needs the orchestration API surface (Person 2) |
| Usage, billing | Planned | tables exist, services not built |
| Preview (emulator), visual UI editor | Planned | needs emulator infrastructure / codegen source mapping |

## Local development without Postgres, Redis or Docker

```bash
make dev-api                       # API on SQLite + local files, seeds admin@example.com (password printed once)
make dev-web                       # Next.js on :3000, proxies /api to :8000
# optional: exercise the build pipeline with a FAKE worker (runs no Gradle; artifact is a placeholder)
#   create a worker as admin, then:  WORKER_TOKEN=wk_... make dev-worker
make smoke                         # end-to-end check through the proxy (set DEV_ADMIN_PASSWORD for the worker steps)
```

`scripts/dev/*` are development tools only; never deploy them.

## Things worth knowing

- The Next.js dev proxy buffers request bodies and truncates at 10 MB by default; `next.config.ts` raises it to 210 MB to match the upload cap (found by the smoke test). In production Nginx sends `/api` directly to the API.
- Build log lines stream over SSE (`/builds/{id}/logs/stream`); the stream continues the line numbering of the full-log fetch (trailing newlines trimmed) so the UI never duplicates lines. Lines written between the full-log fetch and the stream connecting could be missed until the next refresh.
- The `web` Docker image needs the repo root as build context (see `apps/web/Dockerfile`, unverified: no Docker in the authoring environment). `BACKEND_URL` is baked in at build time.
- `package-lock.json` for the web app is now committed and references the contracts package by path, so `npm install` can never resolve `@apppilot/contracts` from the public registry.

## Verified

37 frontend unit tests (mappers, transport, token refresh, error translation, request shapes, "every live endpoint has a handler / every planned one answers 501"); typecheck, lint and a production `next build` pass; `scripts/dev/smoke_web_api.py` passes end to end through the real Next.js proxy (cookie login, CSRF refusal, upload incl. a 30 MB file, analysis, search, move, build submission, admin worker creation, logout). **Not verified:** actual browser rendering of the screens (no browser available to the author), Docker builds, anything against PostgreSQL/Redis/S3.
