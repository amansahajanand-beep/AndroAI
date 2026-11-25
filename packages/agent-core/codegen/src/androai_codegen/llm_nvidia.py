"""An ``LlmClient`` for NVIDIA's hosted, OpenAI-compatible chat API (build.nvidia.com / NIM).

Standard library only. The key is read from the environment (``NVIDIA_API_KEY``) when the client is
created, is only ever sent in the Authorization header, and never appears in an exception message
or a log line. The project's code leaves the machine when this client is used: that is the point of
using a hosted model, so only point it at projects the user agreed to send.

``transport`` is injectable so tests (and a future proxy or SDK) need no network.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

# (url, headers, body bytes, timeout) -> (status, response bytes)
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class LlmError(Exception):
    """A model call failed. The message never contains the key or the response body."""


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read(8_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(64_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LlmError(f"network error: {type(exc).__name__}") from None


class NvidiaClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_attempts: int = 3,
        temperature: float = 0.1,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get("NVIDIA_API_KEY")
        if not key:
            raise LlmError("NVIDIA_API_KEY is not set")
        self._key = key
        self.model = model or os.environ.get("NVIDIA_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.environ.get("NVIDIA_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.temperature = temperature
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def __repr__(self) -> str:  # never show the key
        return f"NvidiaClient(model={self.model!r})"

    def complete_json(
        self, system: str, user: str, output: type[T], *, max_output_tokens: int
    ) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        schema_hint = json.dumps(output.model_json_schema())[:6000]
        messages[0]["content"] += f"\n\nThe JSON must satisfy this JSON Schema:\n{schema_hint}"
        last_problem = ""
        for _attempt in (1, 2):  # one repair attempt if the reply is not valid
            text = self._chat(messages, max_output_tokens)
            try:
                return output.model_validate(_extract_json(text))
            except (ValueError, ValidationError) as exc:
                last_problem = type(exc).__name__
                messages = [
                    *messages,
                    {"role": "assistant", "content": text[:20000]},
                    {
                        "role": "user",
                        "content": "That reply was not valid JSON for the required schema "
                        f"({_short_error(exc)}). Reply again with the JSON object only.",
                    },
                ]
        raise LlmError(f"the model did not return valid JSON ({last_problem})")

    # -- one chat call, with retries on rate limits and server errors ---------------------

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": self.temperature,
                "stream": False,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "androai-codegen",
        }
        status = 0
        for attempt in range(1, self.max_attempts + 1):
            try:
                status, raw = self._transport(
                    f"{self.base_url}/chat/completions", headers, body, self.timeout
                )
            except LlmError:
                if attempt == self.max_attempts:
                    raise
                self._sleep(min(2.0 * attempt, 10.0))
                continue
            if status == 200:
                return self._read(raw)
            if status in (408, 429, 500, 502, 503, 504) and attempt < self.max_attempts:
                self._sleep(min(2.0 * attempt, 10.0))
                continue
            break
        if status in (401, 403):
            raise LlmError(f"the API rejected the key or model access (HTTP {status})")
        raise LlmError(f"the API call failed (HTTP {status})")

    def _read(self, raw: bytes) -> str:
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmError("the API reply had an unexpected shape") from None
        if not isinstance(text, str) or not text.strip():
            raise LlmError("the model returned an empty reply")
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["output_tokens"] += int(usage.get("completion_tokens") or 0)
        return text


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> object:
    """The JSON object in a model reply: bare, in a code fence, or surrounded by prose."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise ValueError("no JSON object found")


def _short_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:300]
