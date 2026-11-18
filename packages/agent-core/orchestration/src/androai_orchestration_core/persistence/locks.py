"""Per-run mutual exclusion so two result deliveries never advance the same run concurrently."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from typing import Iterator, Protocol


class RunLock(Protocol):
    def hold(self, run_id: str, timeout: float = 30.0) -> "contextmanager[None]": ...


class LocalRunLock:
    """In-process lock. Sufficient for tests and a single worker process only."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, run_id: str, timeout: float = 30.0) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(run_id, threading.Lock())
        if not lock.acquire(timeout=timeout):
            raise TimeoutError(f"could not lock run {run_id}")
        try:
            yield
        finally:
            lock.release()


_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class RedisRunLock:
    """Cross-process lock (SET NX PX + token-checked release). `ttl` must exceed the
    longest single graph step; runs that outlive it are caught by recovery, not by this lock."""

    def __init__(self, client, ttl_seconds: int = 300, prefix: str = "androai:orch:lock:"):
        self._r, self._ttl, self._prefix = client, ttl_seconds, prefix

    @contextmanager
    def hold(self, run_id: str, timeout: float = 30.0) -> Iterator[None]:
        import time

        key, token = self._prefix + run_id, uuid.uuid4().hex
        deadline = time.monotonic() + timeout
        while not self._r.set(key, token, nx=True, ex=self._ttl):
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock run {run_id}")
            time.sleep(0.1)
        try:
            yield
        finally:
            self._r.eval(_RELEASE, 1, key, token)
