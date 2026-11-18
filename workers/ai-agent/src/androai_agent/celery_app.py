"""Celery application for the ai-agent worker (queue: ai_agent)."""

from celery import Celery

from androai_contracts import Queues

app = Celery("androai_agent")
app.conf.task_default_queue = Queues.AI_AGENT
# Register tasks by adding modules here, e.g. app.autodiscover_tasks(["androai_agent.tasks"])
