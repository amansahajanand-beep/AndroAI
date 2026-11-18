"""Entry point: `python -m androai_android_build` or the `androai-android-build` console script."""

import os
import sys

from .celery_app import app


def main() -> None:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        sys.exit("REDIS_URL is required to start the android-build worker")
    app.conf.broker_url = redis_url
    app.conf.result_backend = redis_url
    concurrency = os.environ.get("WORKER_CONCURRENCY", "2")
    app.worker_main(["worker", "--loglevel=INFO", f"--concurrency={concurrency}",
                     "-Q", app.conf.task_default_queue])


if __name__ == "__main__":
    main()
