"""Provider/model configuration. No vendor is a built-in default; deployments
supply a ProvidersConfig (from env/YAML/DB)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .types import TaskKind


class ModelSpec(BaseModel):
    """A concrete model offered by a provider and what it can do."""

    provider: str  # key into the provider registry
    model: str
    supports_json_schema: bool = False  # native structured output
    supports_json_output: bool = True  # can be prompted to emit JSON
    context_window: int = Field(default=100_000, gt=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    # USD per 1M tokens. None = unpriced: cost cannot be estimated, so cost
    # budgets fail closed for this model.
    input_price_per_mtok: float | None = Field(default=None, ge=0)
    output_price_per_mtok: float | None = Field(default=None, ge=0)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def priced(self) -> bool:
        return self.input_price_per_mtok is not None and self.output_price_per_mtok is not None


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=1.0, ge=0)
    max_delay_seconds: float = Field(default=30.0, ge=0)
    timeout_seconds: float = Field(default=120.0, gt=0)
    schema_repair_attempts: int = Field(default=1, ge=0, le=3)


class TaskRoute(BaseModel):
    """Ordered candidates for a task kind: first = primary, rest = fallbacks.
    Entries are ModelSpec.key values. Fallbacks are only used if they satisfy the
    route requirements (re-checked at call time, never assumed from config)."""

    models: list[str] = Field(min_length=1)
    require_json_output: bool = True
    min_context_window: int = Field(default=0, ge=0)


class ProvidersConfig(BaseModel):
    models: list[ModelSpec]
    routes: dict[TaskKind, TaskRoute]
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @model_validator(mode="after")
    def _routes_reference_known_models(self) -> "ProvidersConfig":
        keys = {m.key for m in self.models}
        if len(keys) != len(self.models):
            raise ValueError("duplicate model keys")
        for kind, route in self.routes.items():
            missing = [k for k in route.models if k not in keys]
            if missing:
                raise ValueError(f"route {kind.value} references unknown models: {missing}")
        return self

    def spec(self, key: str) -> ModelSpec:
        for m in self.models:
            if m.key == key:
                return m
        raise KeyError(key)
