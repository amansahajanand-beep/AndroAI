"""Token and cost accounting with hard budgets (per run)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .config import ModelSpec
from .types import BudgetExceeded, Usage


class Budget(BaseModel):
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_llm_calls: int | None = Field(default=None, gt=0)


class UsageRecord(BaseModel):
    provider: str
    model: str
    task_kind: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # None when the model is unpriced


def estimate_cost(spec: ModelSpec, usage: Usage) -> float | None:
    if not spec.priced:
        return None
    return (
        usage.input_tokens * spec.input_price_per_mtok  # type: ignore[operator]
        + usage.output_tokens * spec.output_price_per_mtok  # type: ignore[operator]
    ) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Cheap upper-biased estimate (~3.5 chars/token); used only for pre-flight checks."""
    return int(len(text) / 3.5) + 1


@dataclass
class BudgetTracker:
    """Thread-safe. `check_before` is a pre-flight guard; `record` books actuals."""

    budget: Budget
    records: list[UsageRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd or 0.0 for r in self.records)

    def check_before(self, spec: ModelSpec, est_input: int, max_output: int) -> None:
        b = self.budget
        with self._lock:
            if b.max_llm_calls is not None and len(self.records) >= b.max_llm_calls:
                raise BudgetExceeded(f"LLM call budget exhausted ({b.max_llm_calls})")
            if b.max_total_tokens is not None and (
                self.total_tokens + est_input + max_output > b.max_total_tokens
            ):
                raise BudgetExceeded("token budget would be exceeded")
            if b.max_cost_usd is not None:
                if not spec.priced:
                    raise BudgetExceeded(
                        f"model {spec.key} has no price configured; cannot enforce cost budget"
                    )
                worst = estimate_cost(spec, Usage(input_tokens=est_input, output_tokens=max_output))
                if self.total_cost + (worst or 0.0) > b.max_cost_usd:
                    raise BudgetExceeded("cost budget would be exceeded")

    def record(self, spec: ModelSpec, task_kind: str, usage: Usage) -> UsageRecord:
        rec = UsageRecord(
            provider=spec.provider,
            model=spec.model,
            task_kind=task_kind,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=estimate_cost(spec, usage),
        )
        with self._lock:
            self.records.append(rec)
        return rec
