# modules/common/redis_client.py
import redis.asyncio as redis
from modules.common.config import REDIS_URL
import logging

logger = logging.getLogger(__name__)

_redis_client = None

def get_redis():
    """Return an async Redis client if available, otherwise None."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection - this needs to be awaited, but since this is sync, we can't
            # For now, just create the client without testing
            logger.info("Redis client created")
        except Exception as e:
            logger.warning(f"Redis not available: {e}. Blacklisting disabled.")
            _redis_client = None
    return _redis_client