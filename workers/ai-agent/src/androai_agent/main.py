"""Entry point: `python -m androai_agent` (worker) or `python -m androai_agent modify ...` (local try)."""

import os
import sys

from .celery_app import app


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "modify":
        from .cli import main as cli_main

        sys.exit(cli_main(sys.argv[2:]))
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        sys.exit("REDIS_URL is required to start the ai-agent worker")
    app.conf.broker_url = redis_url
    app.conf.result_backend = redis_url
    concurrency = os.environ.get("WORKER_CONCURRENCY", "2")
    app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            f"--concurrency={concurrency}",
            "-Q",
            app.conf.task_default_queue,
        ]
    )


if __name__ == "__main__":
    main()
