# modules/orchestration/cache_manager.py
import json
import logging
from typing import Optional, Dict, Any
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from modules.common.models import Conversation

logger = logging.getLogger(__name__)

class CacheManager:
    """Redis + PostgreSQL dual‑layer cache for conversation state."""
    
    def __init__(self, redis_client: redis.Redis, db_session: AsyncSession, ttl_seconds: int = 86400):
        self.redis = redis_client
        self.db = db_session
        self.ttl = ttl_seconds

    async def get_conversation_state(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Load state from Redis, fallback to DB."""
        key = f"conv_state:{conversation_id}"
        try:
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis read error: {e}, falling back to DB")
        
        # Fallback to PostgreSQL
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        
        state = {
            "stage": conv.conversation_stage,
            "completed_fields": conv.completed_fields or {},
            "booking_status": conv.booking_status,
            "last_intent": conv.last_intent
        }
        # Cache it for next time
        await self.set_conversation_state(conversation_id, state)
        return state

    async def set_conversation_state(self, conversation_id: str, state: Dict[str, Any]) -> None:
        """Store state in Redis and optionally update DB if needed."""
        key = f"conv_state:{conversation_id}"
        try:
            await self.redis.setex(key, self.ttl, json.dumps(state))
        except Exception as e:
            logger.warning(f"Redis write error: {e}")
        
        # Optionally sync to DB (called separately for atomic updates)

    async def update_field(self, conversation_id: str, field: str, value: Any) -> None:
        """Atomically update a single completed field in both cache and DB."""
        state = await self.get_conversation_state(conversation_id)
        if not state:
            state = {"completed_fields": {}}
        if "completed_fields" not in state:
            state["completed_fields"] = {}
        state["completed_fields"][field] = {"value": value, "completed_at": "now"}
        await self.set_conversation_state(conversation_id, state)
        
        # Also update DB
        stmt = update(Conversation).where(Conversation.id == conversation_id).values(
            completed_fields=state["completed_fields"]
        )
        await self.db.execute(stmt)
        await self.db.commit()