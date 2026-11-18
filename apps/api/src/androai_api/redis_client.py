from functools import lru_cache

import redis

from .config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        str(get_settings().redis_url), socket_connect_timeout=2, socket_timeout=2
    )


def check_redis() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
