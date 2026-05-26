# modules/orchestration/memory_engine.py
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from modules.common.models import ConversationMemory

logger = logging.getLogger(__name__)

class MemoryEngine:
    """Short‑term (Redis) + long‑term (PostgreSQL) conversation memory."""

    def __init__(self, redis_client: redis.Redis, db_session: AsyncSession, ttl_seconds: int = 86400):
        self.redis = redis_client
        self.db = db_session
        self.ttl = ttl_seconds

    async def add_message(self, conversation_id: str, role: str, content: str) -> None:
        """Store a message in Redis and optionally trigger rolling summary."""
        key = f"conv_mem:{conversation_id}:messages"
        msg = json.dumps({"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()})
        await self.redis.rpush(key, msg)
        await self.redis.expire(key, self.ttl)

        length = await self.redis.llen(key)
        if length % 20 == 0:
            await self._create_rolling_summary(conversation_id)

    async def get_recent_messages(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Return last N messages from Redis (fast) or fallback to DB."""
        key = f"conv_mem:{conversation_id}:messages"
        try:
            messages = await self.redis.lrange(key, -limit, -1)
            if messages:
                return [json.loads(m) for m in messages]
        except Exception as e:
            logger.warning(f"Redis read error: {e}, falling back to DB")

        # Fallback to DB – order by updated_at (most recent first)
        # If your model has a 'created_at' column, use that; otherwise 'updated_at' works.
        order_column = ConversationMemory.updated_at  # Use updated_at because created_at is missing
        result = await self.db.execute(
            select(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .order_by(desc(order_column))
            .limit(limit)
        )
        memories = result.scalars().all()
        # Return the messages in chronological order (oldest first for conversation context)
        return [{"role": "assistant", "content": m.content} for m in reversed(memories)]

    async def _create_rolling_summary(self, conversation_id: str) -> None:
        """Generate a summary of last 20 messages and store in DB."""
        messages = await self.get_recent_messages(conversation_id, 20)
        if not messages:
            return
        summary_text = " ".join([f"{m['role']}: {m['content']}" for m in messages])[:500]
        # Use updated_at as a stand‑in for creation time
        mem = ConversationMemory(
            conversation_id=conversation_id,
            summary_type="message_summary",
            content=summary_text,
            created_at=datetime.utcnow(),   # Ensure your model has 'created_at' or change to 'updated_at'
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        self.db.add(mem)
        await self.db.commit()