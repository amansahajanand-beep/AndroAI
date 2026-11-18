"""Celery application for the orchestration worker (queue: orchestration)."""

from celery import Celery

from androai_contracts import Queues

app = Celery("androai_orchestration")
app.conf.task_default_queue = Queues.ORCHESTRATION
# Register tasks by adding modules here, e.g. app.autodiscover_tasks(["androai_orchestration.tasks"])
