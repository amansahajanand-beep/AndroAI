# Compatibility Matrix

Versions used in this foundation. Change only with team approval.

| Component | Version | Notes |
|---|---|---|
| Python | 3.12 (images); 3.11+ supported; verified locally on 3.14 | |
| Node.js | 22 (images); 20+ | |
| Next.js / React | 16.x / 19.x | as scaffolded by create-next-app |
| Tailwind CSS | 4.x | |
| shadcn/ui | initialised (style `base-nova`) | components added on demand |
| FastAPI / Pydantic | ≥0.115 / 2.x | |
| SQLAlchemy / Alembic / psycopg | 2.x / ≥1.13 / 3.x | |
| PostgreSQL / Redis | 16 / 7 | |
| Celery | ≥5.4 (Redis broker) | |

## Android build compatibility (implemented in `packages/android-tools`)

The scheduler detects each project's requirements from its build files and only assigns it to a worker whose advertised environment satisfies them. **The project's toolchain is never modified**; unsatisfiable projects are rejected (`422 unsupported_project`) or stay `blocked` with the reason.

Detected (best effort, regex based; anything not found is reported, never guessed): Gradle (from the wrapper), Android Gradle Plugin, Kotlin, compileSdk / targetSdk / minSdk, requested Java level, notable plugins (kapt, ksp, hilt, google-services, compose, NDK).

Required for a build: a Gradle wrapper, a `settings.gradle(.kts)`, a determinable AGP version and compileSdk.

Worker environment = `{jdks: [..], platforms: [..]}` (reported by the worker at registration). A job fits when some installed JDK is >= the minimum for its AGP (and >= its requested Java level) and <= the maximum its Gradle supports, and its compileSdk platform is installed.

| AGP | Min JDK | Min Gradle |
|---|---|---|
| 4.0 - 4.2 | 8 | 6.1.1 - 6.7.1 |
| 7.0 - 7.4 | 11 | 7.0.2 - 7.5 |
| 8.0 - 8.1 | 17 | 8.0 |
| 8.2 / 8.3 / 8.4 | 17 | 8.2 / 8.4 / 8.6 |
| 8.5 / 8.6 | 17 | 8.7 |
| 8.7 / 8.8 / 8.9 / 8.10 | 17 | 8.9 / 8.10.2 / 8.11.1 / 8.11.1 |
| newer than the table | 17 (flagged `unverified`) | not checked |

Gradle JDK ceiling: Gradle < 7.3 cannot run JDK 17; Gradle < 8.5 cannot run JDK 21.

**Verify this table against the Android Gradle Plugin release notes before pinning production images**; it was transcribed without network access to those pages. A Gradle version below the AGP minimum produces a warning (the project's own wrapper decides), not an error.

Build images (not yet created; see BACKEND_PROGRESS.md): planned `jdk17-android34/35` first, `jdk11` for AGP 7.x projects. SDK/Gradle versions are pinned per image, not per job.
