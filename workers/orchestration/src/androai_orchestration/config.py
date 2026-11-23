"""Worker configuration, loaded from the environment.

Secrets (provider API keys, DATABASE_URL) come from env vars only. Model/route/limit
configuration comes from a JSON file at PROVIDERS_CONFIG_PATH so that no vendor is
hardcoded. Example in docs/AI_ORCHESTRATION_PROGRESS.md."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from androai_orchestration_core.providers import ProvidersConfig
from androai_orchestration_core.workflows import Limits


class ProviderEntry(BaseModel):
    type: str = Field(pattern="^(anthropic|openai_compatible)$")
    api_key_env: str  # NAME of the env var holding the key (never the key itself)
    base_url: str | None = None


class WorkerConfig(BaseModel):
    providers: dict[str, ProviderEntry]
    llm: ProvidersConfig
    limits: Limits = Field(default_factory=Limits)

    @classmethod
    def load(cls, path: str | None = None) -> "WorkerConfig":
        path = path or os.environ.get("PROVIDERS_CONFIG_PATH")
        if not path:
            raise RuntimeError("PROVIDERS_CONFIG_PATH is required")
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
