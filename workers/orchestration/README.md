# workers/orchestration

LangGraph-based agent orchestration worker.

- Owner: **Person 2**
- Package: `androai_orchestration` (src layout), entry point `python -m androai_orchestration`
- Queue: `Queues.ORCHESTRATION` from `androai-contracts`
- Env: `REDIS_URL` (required), `WORKER_CONCURRENCY` (optional)

Thin Celery layer over `packages/agent-core/orchestration`. Tasks: `tasks.py`; wiring: `runtime.py`;
config: `config.py` (env `PROVIDERS_CONFIG_PATH` -> JSON like `providers.example.json`, plus `DATABASE_URL`,
`REDIS_URL`, provider key env vars). `celery beat` is needed for periodic `recover_runs`.
`ProjectWorkspace` is not wired yet (Person 4 dependency): see docs/AI_ORCHESTRATION_PROGRESS.md.
Exchange data using models from `packages/contracts`; do not define duplicates here.
