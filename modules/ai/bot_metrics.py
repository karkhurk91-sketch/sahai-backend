from modules.common.redis_client import get_redis_client
from datetime import datetime

async def increment_metric(org_id: str, metric_name: str):
    try:
        redis = get_redis_client()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"bot_metrics:{org_id}:{metric_name}:{today}"
        await redis.incr(key)
        await redis.expire(key, 86400*7)  # keep 7 days
    except Exception as e:
        logger.warning(f"Failed to increment metric: {e}")

# Use in webhook:
# await increment_metric(str(org_id), "generic_messages")