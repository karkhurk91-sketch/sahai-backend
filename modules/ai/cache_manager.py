import json
import logging
from typing import Optional, Dict, Any
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.models import Conversation
from modules.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)

class CacheManager:
    """Redis + PostgreSQL dual‑layer cache for conversation state."""
    
    def __init__(self, db_session: AsyncSession, ttl_seconds: int = 86400):
        self.redis = get_redis_client()
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
        
        # Fallback to DB
        conv = await self.db.get(Conversation, conversation_id)
        if not conv:
            return None
        state = {
            "stage": conv.conversation_stage,
            "completed_fields": conv.completed_fields or {},
            "booking_status": getattr(conv, "booking_status", "none"),
            "last_intent": getattr(conv, "last_intent", None)
        }
        # Cache for next time
        await self.set_conversation_state(conversation_id, state)
        return state
    
    async def set_conversation_state(self, conversation_id: str, state: Dict[str, Any]) -> None:
        """Store state in Redis."""
        key = f"conv_state:{conversation_id}"
        try:
            await self.redis.setex(key, self.ttl, json.dumps(state))
        except Exception as e:
            logger.warning(f"Redis write error: {e}")
    
    async def update_field(self, conversation_id: str, field: str, value: Any) -> None:
        """Atomically update a single completed field."""
        state = await self.get_conversation_state(conversation_id)
        if not state:
            state = {"completed_fields": {}}
        if "completed_fields" not in state:
            state["completed_fields"] = {}
        state["completed_fields"][field] = {
            "value": value,
            "completed_at": datetime.utcnow().isoformat()
        }
        await self.set_conversation_state(conversation_id, state)
        
        # Also update DB
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(completed_fields=state["completed_fields"])
        )
        await self.db.commit()