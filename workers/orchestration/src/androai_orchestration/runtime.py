"""Builds the OrchestrationService from the environment (once per worker process)."""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine

from androai_orchestration_core.persistence import RedisRunLock, RunStore
from androai_orchestration_core.ports import CeleryCodingEngine, CeleryValidationRunner
from androai_orchestration_core.providers import LLMRouter
from androai_orchestration_core.providers.adapters import AnthropicProvider, OpenAICompatibleProvider
from androai_orchestration_core.workflows import OrchestrationService, WorkflowDeps, make_checkpointer

from .celery_app import app
from .config import WorkerConfig


class _NotConfigured:
    """Placeholder for ports whose real implementation is owned by another team.
    Fails loudly at first use instead of silently skipping work."""

    def __init__(self, what: str):
        self._what = what

    def __getattr__(self, name: str):
        raise NotImplementedError(f"{self._what} is not wired yet (integration dependency, see docs)")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


@lru_cache
def get_service() -> OrchestrationService:
    cfg = WorkerConfig.load()
    db_url = _database_url()
    engine = create_engine(db_url.replace("postgresql://", "postgresql+psycopg://", 1), pool_pre_ping=True)
    store = RunStore(engine)

    providers = {}
    for name, p in cfg.providers.items():
        key = os.environ.get(p.api_key_env)
        if not key:
            continue  # provider unavailable; routes skip providers that are not registered
        providers[name] = (AnthropicProvider(key, p.base_url, name) if p.type == "anthropic"
                           else OpenAICompatibleProvider(key, p.base_url, name))

    def router_for(run_id: str) -> LLMRouter:
        return LLMRouter(cfg.llm, providers, usage_sink=lambda rec: store.record_usage(run_id, rec))

    import redis

    deps = WorkflowDeps(
        store=store, router_factory=router_for,
        workspace=_NotConfigured("ProjectWorkspace (Person 4 storage)"),  # type: ignore[arg-type]
        coding=CeleryCodingEngine(app), validation=CeleryValidationRunner(app), limits=cfg.limits,
    )
    use_pg_checkpoints = os.environ.get("ORCH_CHECKPOINT_BACKEND", "postgres") == "postgres"
    return OrchestrationService(
        deps, make_checkpointer(db_url if use_pg_checkpoints else None),
        lock=RedisRunLock(redis.Redis.from_url(os.environ["REDIS_URL"])),
    )
