class Queues:
    """Celery queue names, one per worker. Single source of truth."""

    ORCHESTRATION = "orchestration"
    AI_AGENT = "ai_agent"
    ANDROID_BUILD = "android_build"
    ANDROID_TEST = "android_test"
