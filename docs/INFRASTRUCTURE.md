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

## Live preview (emulator in the browser)

The Preview tab (`EmulatorStreamSession` in `packages/shared-types`) expects a `viewerUrl` it can
embed in an iframe. Two implementations exist behind the same contract:

* **Dev stand-in (built, `AGENT_DEV_BRIDGE=1`):** `apps/api/.../services/emulator_dev.py` and
  `api/v1/preview_dev.py`. On the developer's own machine it builds the debug APK with the project's
  Gradle wrapper, uses a connected device or boots an AVD from the local Android SDK, installs and
  launches the app, and serves a small viewer page that streams the screen as PNG frames and sends
  taps, swipes, keys and text back through `adb`. One preview at a time, 30-minute sessions. The
  viewer URL carries an unguessable token (an iframe cannot carry the login). **It runs the project's
  Gradle build on the host, so use it only for projects you trust on a dev machine.**
* **Production (not built, Person 4):** the same flow in isolated, network-restricted worker images
  (JDK + Android SDK + KVM emulator, one container per session), reached through the existing
  `kind: emulator` worker registration and a streaming proxy. The API contract does not change.

Setup for the dev stand-in: Android SDK (`ANDROID_HOME`, or the Android Studio default location) with
platform-tools, build-tools and, for no connected device, the emulator plus one AVD whose system image
is installed. `PREVIEW_AVD` picks the AVD, `PREVIEW_EMULATOR_WINDOW=1` shows the emulator window.

## Checking the agent's result before delivery

After the agent finishes, the project is checked and any problems go back to the agent to fix (two
rounds by default) before the user sees the change set.

1. **Quick static checks** (`androai_codegen.agent.checks`, always on): the Firebase config knows the
   application id, imports of `R`/`BuildConfig` point at a package that exists, manifest components
   exist, Java files sit in their package folder, edited XML/JSON still parses.
2. **A real Gradle build** (dev bridge only, `BuildChecker` in `services/emulator_dev.py`): runs only
   when the quick checks are clean. On by default when an Android SDK is found; set
   `AGENT_VERIFY_BUILD=0` to turn it off. It runs the project's own Gradle build, so it is for
   development machines and trusted projects. Production needs the isolated build worker (Person 4).

Whatever the agent cannot fix is reported in its summary ("NOTE: the project checks still report ...").
