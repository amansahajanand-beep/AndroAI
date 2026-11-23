"""Task-based model selection, retries, fallback, budgets and structured output."""

from __future__ import annotations

import json
import logging
import random
import re
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMProvider
from .budget import BudgetTracker, UsageRecord, estimate_tokens
from .config import ModelSpec, ProvidersConfig
from .redaction import redact
from .types import (
    BudgetExceeded,
    ChatRequest,
    Message,
    NoEligibleModel,
    ProviderAuthError,
    ProviderError,
    RateLimitError,
    StructuredOutputError,
    TaskKind,
    Usage,
)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def extract_json(text: str) -> object:
    """Parse model output as JSON, tolerating a code fence or surrounding prose."""
    text = text.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        if start == -1:
            raise
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj


class LLMRouter:
    def __init__(
        self,
        config: ProvidersConfig,
        providers: dict[str, LLMProvider],
        usage_sink: Callable[[UsageRecord], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.providers = providers
        self.usage_sink = usage_sink
        self._sleep = sleep

    # ---- selection -------------------------------------------------------------
    def candidates(self, kind: TaskKind, structured: bool = True, est_input_tokens: int = 0) -> list[ModelSpec]:
        route = self.config.routes.get(kind)
        if route is None:
            raise NoEligibleModel(f"no route configured for task {kind.value}")
        out: list[ModelSpec] = []
        for key in route.models:
            spec = self.config.spec(key)
            if spec.provider not in self.providers:
                continue
            if (structured and route.require_json_output) and not (
                spec.supports_json_output or spec.supports_json_schema
            ):
                continue
            if spec.context_window < max(route.min_context_window, est_input_tokens):
                continue
            out.append(spec)
        if not out:
            raise NoEligibleModel(f"no eligible model for task {kind.value}")
        return out

    def health(self) -> dict[str, bool]:
        res = {}
        for name, p in self.providers.items():
            try:
                res[name] = bool(p.health_check())
            except Exception:  # noqa: BLE001
                res[name] = False
        return res

    # ---- calls -----------------------------------------------------------------
    def generate(
        self,
        kind: TaskKind,
        messages: list[Message],
        output: type[T],
        tracker: BudgetTracker,
        max_output_tokens: int = 4096,
    ) -> T:
        """Return a validated `output` instance. Raises BudgetExceeded, NoEligibleModel,
        or StructuredOutputError/ProviderError when every eligible model failed."""
        safe = [Message(role=m.role, content=redact(m.content)) for m in messages]
        est_in = sum(estimate_tokens(m.content) for m in safe)
        last: Exception | None = None
        for spec in self.candidates(kind, True, est_in + max_output_tokens):
            try:
                return self._with_model(spec, kind, safe, output, tracker, max_output_tokens, est_in)
            except BudgetExceeded:
                raise
            except ProviderError as exc:
                log.warning("model %s failed for %s: %s", spec.key, kind.value, type(exc).__name__)
                last = exc
        assert last is not None
        raise last

    def _with_model(
        self, spec: ModelSpec, kind: TaskKind, messages: list[Message], output: type[T],
        tracker: BudgetTracker, max_out: int, est_in: int,
    ) -> T:
        schema = output.model_json_schema()
        msgs = list(messages)
        if not spec.supports_json_schema:
            msgs.insert(
                0,
                Message(
                    role="system",
                    content="Respond with a single JSON object only, no prose, matching this JSON Schema:\n"
                    + json.dumps(schema),
                ),
            )
        request = ChatRequest(
            messages=msgs,
            max_output_tokens=min(max_out, spec.max_output_tokens),
            json_schema=schema if spec.supports_json_schema else None,
        )
        repairs = self.config.retry.schema_repair_attempts
        while True:
            tracker.check_before(spec, est_in, request.max_output_tokens)
            text, usage = self._call_with_retry(spec, request)
            rec = tracker.record(spec, kind.value, usage)
            if self.usage_sink:
                self.usage_sink(rec)
            try:
                return output.model_validate(extract_json(text))
            except (ValueError, ValidationError) as exc:
                if repairs <= 0:
                    raise StructuredOutputError(f"{spec.key}: invalid structured output") from None
                repairs -= 1
                # Give the model its own output and the validation error (no user data added).
                detail = str(exc)[:1500]
                request = request.model_copy(update={"messages": [
                    *request.messages,
                    Message(role="assistant", content=text[:6000]),
                    Message(role="user", content="That output was invalid: " + detail + "\nReturn corrected JSON only."),
                ]})
                est_in = sum(estimate_tokens(m.content) for m in request.messages)

    def _call_with_retry(self, spec: ModelSpec, request: ChatRequest) -> tuple[str, Usage]:
        policy = self.config.retry
        provider = self.providers[spec.provider]
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = provider.complete(spec.model, request, policy.timeout_seconds)
                return resp.text, resp.usage
            except ProviderAuthError:
                raise  # no point retrying; router moves to fallback
            except ProviderError as exc:
                if not exc.retryable or attempt >= policy.max_attempts:
                    raise
                delay = min(policy.max_delay_seconds, policy.base_delay_seconds * 2 ** (attempt - 1))
                if isinstance(exc, RateLimitError) and exc.retry_after:
                    delay = min(policy.max_delay_seconds, max(delay, exc.retry_after))
                self._sleep(delay + random.uniform(0, delay * 0.1))
