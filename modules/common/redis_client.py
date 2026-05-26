# modules/common/redis_client.py
import os
import redis.asyncio as redis
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_redis_client():
    """Return a singleton Redis client. Reads REDIS_URL from environment."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        logger.info(f"Redis client initialized with URL: {redis_url.split('@')[-1] if '@' in redis_url else redis_url}")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        # Return a dummy client that logs errors instead of crashing
        class DummyRedis:
            async def get(self, key):
                logger.warning(f"DummyRedis: get({key}) called")
                return None
            async def setex(self, key, ttl, value):
                logger.warning(f"DummyRedis: setex({key}) called")
            async def rpush(self, key, value):
                logger.warning(f"DummyRedis: rpush({key}) called")
            async def lrange(self, key, start, end):
                return []
            async def delete(self, key):
                logger.warning(f"DummyRedis: delete({key}) called")
            async def expire(self, key, ttl):
                pass
        return DummyRedis()

# Alias for backward compatibility (used by jwt.py and other modules)
get_redis = get_redis_client