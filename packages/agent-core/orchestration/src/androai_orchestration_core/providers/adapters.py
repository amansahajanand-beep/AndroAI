"""Vendor adapters. SDKs are imported lazily so the core has no hard vendor dependency.

* AnthropicProvider  - `pip install androai-orchestration-core[anthropic]`
* OpenAICompatibleProvider - OpenAI and any server speaking its chat API
  (set `base_url` for other vendors/gateways).
API keys are passed in by the caller (from the secrets store); never logged.
"""

from __future__ import annotations

from .types import (
    ChatRequest,
    ChatResponse,
    ProviderAuthError,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
    Usage,
)


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def _map_error(exc: Exception) -> ProviderError:
    """Map SDK exceptions by class name (both SDKs share these names)."""
    name = type(exc).__name__
    if name == "RateLimitError":
        return RateLimitError(str(exc), _retry_after(exc))
    if name in ("APITimeoutError", "Timeout", "TimeoutError"):
        return ProviderTimeout(str(exc))
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return ProviderAuthError("provider rejected credentials")
    if name in ("APIConnectionError", "InternalServerError", "ServiceUnavailableError", "OverloadedError"):
        return ProviderUnavailable(str(exc))
    status = getattr(exc, "status_code", None)
    if status in (429,):
        return RateLimitError(str(exc), _retry_after(exc))
    if isinstance(status, int) and status >= 500:
        return ProviderUnavailable(str(exc))
    return ProviderError(str(exc))


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str | None = None, name: str = "anthropic"):
        import anthropic  # lazy

        self.name = name
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, max_retries=0)

    def complete(self, model: str, request: ChatRequest, timeout: float) -> ChatResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        msgs = [{"role": m.role, "content": m.content} for m in request.messages if m.role != "system"]
        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=request.max_output_tokens,
                temperature=request.temperature,
                system=system or None,
                messages=msgs,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - mapped
            raise _map_error(exc) from None
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return ChatResponse(
            text=text,
            usage=Usage(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens),
            model=model,
            provider=self.name,
        )

    def health_check(self) -> bool:
        try:
            self._client.models.list(limit=1)
            return True
        except Exception:  # noqa: BLE001
            return False


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str | None = None, name: str = "openai"):
        import openai  # lazy

        self.name = name
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def complete(self, model: str, request: ChatRequest, timeout: float) -> ChatResponse:
        kwargs: dict = {}
        if request.json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": request.json_schema},
            }
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                max_tokens=request.max_output_tokens,
                temperature=request.temperature,
                timeout=timeout,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            raise _map_error(exc) from None
        usage = resp.usage
        return ChatResponse(
            text=resp.choices[0].message.content or "",
            usage=Usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            ),
            model=model,
            provider=self.name,
        )

    def health_check(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:  # noqa: BLE001
            return False
