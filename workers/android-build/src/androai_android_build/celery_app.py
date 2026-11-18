"""Celery application for the android-build worker (queue: android_build)."""

from celery import Celery

from androai_contracts import Queues

app = Celery("androai_android_build")
app.conf.task_default_queue = Queues.ANDROID_BUILD
# Register tasks by adding modules here, e.g. app.autodiscover_tasks(["androai_android_build.tasks"])
