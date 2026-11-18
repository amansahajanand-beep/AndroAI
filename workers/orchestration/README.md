# workers/orchestration

LangGraph-based agent orchestration worker.

- Owner: **Person 2**
- Package: `androai_orchestration` (src layout), entry point `python -m androai_orchestration`
- Queue: `Queues.ORCHESTRATION` from `androai-contracts`
- Env: `REDIS_URL` (required), `WORKER_CONCURRENCY` (optional)

Foundation only: no tasks are implemented yet. Add tasks under `src/androai_orchestration/` and
register them in `celery_app.py`. Exchange data using models from
`packages/contracts`; do not define duplicates here.
