"""Celery application for the android-test worker (queue: android_test)."""

from celery import Celery

from androai_contracts import Queues

app = Celery("androai_android_test")
app.conf.task_default_queue = Queues.ANDROID_TEST
# Register tasks by adding modules here, e.g. app.autodiscover_tasks(["androai_android_test.tasks"])
