"""Fixed-window rate limiting. Redis-backed (shared across API replicas) with an
in-process fallback so a Redis outage degrades protection instead of availability."""

from __future__ import annotations

import threading
import time

from fastapi import Request

from .config import get_settings
from .errors import AppError
from .redis_client import get_redis

_lock = threading.Lock()
_local: dict[str, int] = {}  # key (includes window) -> count


def reset_local_state() -> None:
    with _lock:
        _local.clear()


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def hit(scope: str, ident: str, limit: int, window_seconds: int = 60) -> None:
    """Count one event; raise 429 once `limit` is exceeded in the current window."""
    if not get_settings().rate_limit_enabled:
        return
    window = int(time.time() // window_seconds)
    key = f"rl:{scope}:{ident}:{window}"
    try:
        r = get_redis()
        count = r.incr(key)
        if count == 1:
            r.expire(key, window_seconds + 5)
    except Exception:
        with _lock:
            if len(_local) > 10_000:  # bounded memory: drop everything not in this window
                for k in [k for k in _local if not k.endswith(f":{window}")]:
                    del _local[k]
            count = _local[key] = _local.get(key, 0) + 1
    if count > limit:
        raise AppError(429, "rate_limited", "Too many requests, try again shortly")


def limit_by_ip(scope: str):
    def dep(request: Request) -> None:
        hit(scope, client_ip(request), get_settings().rate_limit_auth_per_minute)

    return dep
