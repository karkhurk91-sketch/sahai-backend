# modules/common/redis_client.py
import os
import redis.asyncio as redis
from functools import lru_cache

@lru_cache(maxsize=1)
def get_redis_client():
    """Return a singleton Redis client."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url, decode_responses=True)