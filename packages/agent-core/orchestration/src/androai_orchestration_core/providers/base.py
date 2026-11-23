"""Provider protocol and a scriptable fake for tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .types import ChatRequest, ChatResponse, Usage


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, model: str, request: ChatRequest, timeout: float) -> ChatResponse:
        """Blocking completion. Must raise the ProviderError subclasses in `types`
        (map vendor exceptions in the adapter) and honour `timeout`."""
        ...

    def health_check(self) -> bool: ...


class FakeProvider:
    """Deterministic provider for tests. `script` is a list of str | Exception | callable,
    consumed in order (last item repeats)."""

    def __init__(self, name: str = "fake", script: list | None = None):
        self.name = name
        self.script = list(script or [])
        self.calls: list[tuple[str, ChatRequest]] = []
        self.healthy = True

    def complete(self, model: str, request: ChatRequest, timeout: float) -> ChatResponse:
        self.calls.append((model, request))
        idx = min(len(self.calls) - 1, len(self.script) - 1)
        item = self.script[idx]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Callable):
            item = item(request)
        words = sum(len(m.content.split()) for m in request.messages)
        return ChatResponse(
            text=item,
            usage=Usage(input_tokens=words, output_tokens=max(1, len(item.split()))),
            model=model,
            provider=self.name,
        )

    def health_check(self) -> bool:
        return self.healthy
