"""Celery application for the orchestration worker (queue: orchestration)."""

from celery import Celery

from androai_contracts import Queues

app = Celery("androai_orchestration", include=["androai_orchestration.tasks"])
app.conf.task_default_queue = Queues.ORCHESTRATION
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1  # long-lived LLM calls: do not hoard messages
# Periodic recovery of crashed/stalled runs. Requires `celery beat` (or an equivalent scheduler).
app.conf.beat_schedule = {
    "recover-runs": {"task": "androai_orchestration.recover_runs", "schedule": 300.0},
}
