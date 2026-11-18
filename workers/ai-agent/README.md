# workers/ai-agent

Code-generation agent worker.

- Owner: **Person 3**
- Package: `androai_agent` (src layout), entry point `python -m androai_agent`
- Queue: `Queues.AI_AGENT` from `androai-contracts`
- Env: `REDIS_URL` (required), `WORKER_CONCURRENCY` (optional)

Foundation only: no tasks are implemented yet. Add tasks under `src/androai_agent/` and
register them in `celery_app.py`. Exchange data using models from
`packages/contracts`; do not define duplicates here.
