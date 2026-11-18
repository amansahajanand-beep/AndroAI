# workers/android-build

Android Gradle build worker (separately deployable).

- Owner: **Person 4**
- Package: `androai_android_build` (src layout), entry point `python -m androai_android_build`
- Queue: `Queues.ANDROID_BUILD` from `androai-contracts`
- Env: `REDIS_URL` (required), `WORKER_CONCURRENCY` (optional)

Foundation only: no tasks are implemented yet. Add tasks under `src/androai_android_build/` and
register them in `celery_app.py`. Exchange data using models from
`packages/contracts`; do not define duplicates here.
