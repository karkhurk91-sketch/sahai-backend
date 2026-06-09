# modules/ai/bot_config_loader.py
import json
import logging
from typing import Optional, Dict
from sqlalchemy import select, text
from modules.common.database import AsyncSessionLocal
from modules.common.models import BotConfig
from modules.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)

async def get_active_bot_config(org_id: str) -> Optional[Dict]:
    """
    Fetch the active bot configuration for an organisation.
    Returns the `config` JSON dict, or None if no active config exists.
    """
    # Try Redis cache first
    redis_client = get_redis_client()
    cache_key = f"bot_config:active:{org_id}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis error in get_active_bot_config: {e}")

    # Fallback to database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BotConfig.config)
            .where(BotConfig.organization_id == org_id, BotConfig.is_active == True)
            .order_by(BotConfig.updated_at.desc())
        )
        config = result.scalar_one_or_none()
        if config:
            # Cache for 5 minutes (adjust TTL as needed)
            try:
                await redis_client.setex(cache_key, 300, json.dumps(config))
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
        return config