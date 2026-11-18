# workers/android-test

Android test worker (separately deployable).

- Owner: **Person 4**
- Package: `androai_android_test` (src layout), entry point `python -m androai_android_test`
- Queue: `Queues.ANDROID_TEST` from `androai-contracts`
- Env: `REDIS_URL` (required), `WORKER_CONCURRENCY` (optional)

Foundation only: no tasks are implemented yet. Add tasks under `src/androai_android_test/` and
register them in `celery_app.py`. Exchange data using models from
`packages/contracts`; do not define duplicates here.
