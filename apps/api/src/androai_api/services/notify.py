"""Delivery of build/test results to the orchestration layer (Person 2).

Results are sent as `androai_contracts` models to the existing Celery tasks by name, so the
API never imports orchestration code. Delivery is best-effort after the DB commit: the
database is the source of truth and orchestration's `recover_runs` task reconciles runs
whose result message was lost (a transactional outbox is a possible later hardening).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from androai_contracts import BuildResult, Queues, TestResult

from ..config import get_settings

log = logging.getLogger("androai_api.notify")


class ResultNotifier(Protocol):
    def build_finished(self, result: BuildResult) -> None: ...

    def test_finished(self, result: TestResult) -> None: ...


class NoopNotifier:
    def build_finished(self, result: BuildResult) -> None:
        pass

    def test_finished(self, result: TestResult) -> None:
        pass


class CeleryNotifier:
    def __init__(self):
        from celery import Celery

        self._app = Celery("androai_api_producer", broker=str(get_settings().redis_url))

    def _send(self, task: str, payload: dict) -> None:
        try:
            self._app.send_task(task, args=[payload], queue=Queues.ORCHESTRATION)
        except Exception:  # never fail a worker's completion call because the broker hiccuped
            log.exception("failed to notify orchestration (%s); recover_runs will reconcile", task)

    def build_finished(self, result: BuildResult) -> None:
        self._send("androai_orchestration.handle_build_result", result.model_dump(mode="json"))

    def test_finished(self, result: TestResult) -> None:
        self._send("androai_orchestration.handle_test_result", result.model_dump(mode="json"))


@lru_cache
def get_notifier() -> ResultNotifier:
    return CeleryNotifier() if get_settings().notify_orchestration else NoopNotifier()
