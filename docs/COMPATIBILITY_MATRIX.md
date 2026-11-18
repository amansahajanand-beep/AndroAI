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

## Android (to be pinned by Person 4 when build workers are implemented)

| Item | Proposed |
|---|---|
| JDK | 17 (or 21 if AGP requires) |
| Gradle / AGP | Pin one tested pair |
| Kotlin / Compose BOM | Pin per generated-project template |
| compileSdk / targetSdk / minSdk | 35 / 35 / 24 (defaults in `AndroidTarget`) |
