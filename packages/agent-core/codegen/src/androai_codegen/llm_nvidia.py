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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

# (url, headers, body bytes, timeout) -> (status, response bytes)
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class LlmError(Exception):
    """A model call failed. The message never contains the key or the response body, so it is safe
    to show to a user (``safe_message``)."""

    @property
    def safe_message(self) -> str:
        return str(self)[:300]


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


StreamTransport = Callable[[str, dict[str, str], bytes, float], Iterator[bytes]]


def _urllib_stream(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> Iterator[bytes]:
    """The reply body line by line, as it arrives."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status != 200:
                raise LlmError(f"the API call failed (HTTP {response.status})")
            yield from response
    except urllib.error.HTTPError as exc:
        raise LlmError(f"the API call failed (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LlmError(f"network error: {type(exc).__name__}") from None


class _ThinkFilter:
    """Drops a reasoning model's <think>...</think> text from a stream of pieces."""

    def __init__(self) -> None:
        self._pending = ""
        self._inside = False

    def feed(self, piece: str) -> str:
        self._pending += piece
        out = ""
        while True:
            if self._inside:
                end = self._pending.lower().find("</think>")
                if end < 0:
                    self._pending = self._pending[-8:]  # keep a possible partial closing tag
                    return out
                self._pending = self._pending[end + 8 :]
                self._inside = False
                continue
            start = self._pending.lower().find("<think>")
            if start >= 0:
                out += self._pending[:start]
                self._pending = self._pending[start + 7 :]
                self._inside = True
                continue
            keep = 0  # hold back a possible partial "<think>" at the end
            for n in range(min(6, len(self._pending)), 0, -1):
                if "<think>".startswith(self._pending[-n:].lower()):
                    keep = n
                    break
            out += self._pending[: len(self._pending) - keep]
            self._pending = self._pending[len(self._pending) - keep :]
            return out

    def flush(self) -> str:
        rest, self._pending = ("" if self._inside else self._pending), ""
        return rest


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
        stream_transport: StreamTransport | None = None,
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
        self._stream_transport = stream_transport or _urllib_stream
        self._sleep = sleep
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        # Optional override of the per-call reply limit (NVIDIA_MAX_OUTPUT_TOKENS in .env).
        raw_limit = os.environ.get("NVIDIA_MAX_OUTPUT_TOKENS", "")
        self.max_output_override = (
            int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else None
        )

    def __repr__(self) -> str:  # never show the key
        return f"NvidiaClient(model={self.model!r})"

    def complete_json(
        self, system: str, user: str, output: type[T], *, max_output_tokens: int
    ) -> T:
        return self._complete(system, user, output, max_output_tokens, 1)[0]

    def complete_json_many(
        self, system: str, user: str, output: type[T], *, max_output_tokens: int, limit: int = 5
    ) -> list[T]:
        """Like ``complete_json`` but returns every valid object in the reply (up to ``limit``).

        Some models answer a "next step" prompt with several steps in a row; this keeps them instead
        of throwing all but the first away. Pieces that do not validate are skipped."""
        return self._complete(system, user, output, max_output_tokens, max(1, limit))

    def stream_text(
        self, system: str, user: str, *, max_output_tokens: int = 600
    ) -> Iterator[str]:
        """Plain text from the model, piece by piece as it is generated (no JSON, no retries)."""
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_output_tokens,
                "temperature": 0.3,
                "stream": True,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "androai-codegen",
        }
        think = _ThinkFilter()
        for raw in self._stream_transport(
            f"{self.base_url}/chat/completions", headers, body, self.timeout
        ):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                choice = json.loads(payload)["choices"][0]
                piece = (choice.get("delta") or {}).get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            shown = think.feed(piece) if piece else ""
            if shown:
                yield shown
        tail = think.flush()
        if tail:
            yield tail
        self.usage["calls"] += 1

    def _complete(
        self, system: str, user: str, output: type[T], max_output_tokens: int, limit: int
    ) -> list[T]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        schema_hint = json.dumps(output.model_json_schema())[:6000]
        messages[0]["content"] += f"\n\nThe JSON must satisfy this JSON Schema:\n{schema_hint}"
        last_problem = ""
        cut_off = False
        for _attempt in (1, 2):  # one corrective attempt
            text, truncated = self._chat(messages, max_output_tokens)
            if os.environ.get("NVIDIA_DEBUG_ALL") == "1":
                _debug_dump(text, prefix="reply")
            if truncated:
                if cut_off:
                    raise LlmError(
                        "the model's reply was cut off twice at the output limit; "
                        "ask for a smaller, more specific change"
                    )
                cut_off = True
                last_problem = "cut off"
                # Do not send the cut-off text back: it is huge and unusable.
                messages = [
                    *messages[:2],
                    {
                        "role": "user",
                        "content": "Your reply was cut off at the output limit. Reply again, much "
                        'shorter: use only small exact text replacements ("edits") for the lines '
                        "that must change, never whole files, and touch as few files as possible. "
                        "JSON object only.",
                    },
                ]
                continue
            try:
                return _parse_objects(text, output, limit)
            except (ValueError, ValidationError) as exc:
                _debug_dump(text)
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

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, bool]:
        """The reply text and whether the model stopped because it hit the output limit."""
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_output_override or max_tokens,
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

    def _read(self, raw: bytes) -> tuple[str, bool]:
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            text = choice["message"]["content"]
            truncated = choice.get("finish_reason") == "length"
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmError("the API reply had an unexpected shape") from None
        if not isinstance(text, str) or not text.strip():
            raise LlmError("the model returned an empty reply")
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["output_tokens"] += int(usage.get("completion_tokens") or 0)
        return _strip_reasoning(text), truncated


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Drop a reasoning model's <think> block so braces inside it cannot be mistaken for JSON."""
    return _THINK.sub("", text).strip()


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
    # Several objects back to back ({...}{...}) or trailing prose: take the FIRST complete one.
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = decoder.raw_decode(candidate, match.start())
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    raise ValueError("no JSON object found")


def _parse_objects(text: str, output: type[T], limit: int) -> list[T]:
    """The valid ``output`` objects in a reply, in order. Raises if there is none.

    With ``limit == 1`` this is the old behaviour (the first object, strictly validated); with more,
    objects that are not valid ``output`` are skipped, which also drops the argument dictionaries of
    a malformed multi-step reply."""
    if limit == 1:
        return [output.model_validate(_extract_json(text))]
    found: list[T] = []
    decoder = json.JSONDecoder()
    position = 0
    for candidate in [text, *_FENCE.findall(text)]:
        position = 0
        while len(found) < limit:
            start = candidate.find("{", position)
            if start < 0:
                break
            try:
                value, end = decoder.raw_decode(candidate, start)
            except ValueError:
                position = start + 1
                continue
            position = end
            if isinstance(value, dict):
                try:
                    found.append(output.model_validate(value))
                except ValidationError:
                    continue
        if found:
            return found
    raise ValueError("no valid JSON object found")


def _short_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:300]


_dump_counter = 0


def _debug_dump(text: str, prefix: str = "bad_reply") -> None:
    """Opt-in (NVIDIA_DEBUG_DIR): keep a reply that could not be parsed, to see what the model said.
    The reply may contain project code, so this is for local debugging only."""
    global _dump_counter
    folder = os.environ.get("NVIDIA_DEBUG_DIR")
    if not folder:
        return
    try:
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        _dump_counter += 1
        (target / f"{prefix}_{_dump_counter:03d}.txt").write_text(text[:100_000], encoding="utf-8")
    except OSError:
        pass
