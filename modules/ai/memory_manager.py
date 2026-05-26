import json
import os
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.database import AsyncSessionLocal
from modules.common.models import ConversationMemory
from modules.common.logger import get_logger
from datetime import datetime, timezone

logger = get_logger(__name__)

class MemoryManager:
    def __init__(self, redis_url: str = None):
        # Use environment variable or fallback
        if redis_url is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)

    async def get_context(self, conversation_id: str) -> dict:
        """Load short-term context from Redis, fallback to long-term from PostgreSQL."""
        key = f"conv:{conversation_id}:context"
        data = await self.redis_client.get(key)
        if data:
            return json.loads(data)
        # Fallback to PostgreSQL (long-term memory)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
            )
            mem = result.scalar_one_or_none()
            if mem:
                return {"facts": mem.facts or {}, "summary": mem.last_summary or ""}
        return {"facts": {}, "summary": ""}

    async def save_context(self, conversation_id: str, context: dict, ttl_seconds: int = 3600):
        """Save short-term context to Redis, and update long-term facts in PostgreSQL."""
        key = f"conv:{conversation_id}:context"
        await self.redis_client.setex(key, ttl_seconds, json.dumps(context))

        # Persist important facts into PostgreSQL (long-term)
        facts = context.get("facts", {})
        if facts:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
                )
                mem = result.scalar_one_or_none()
                if mem:
                    # Merge new facts with existing
                    merged = {**mem.facts, **facts}
                    mem.facts = merged
                    mem.last_summary = context.get("summary", mem.last_summary)
                    mem.updated_at = datetime.now(timezone.utc)
                else:
                    mem = ConversationMemory(
                        conversation_id=conversation_id,
                        facts=facts,
                        last_summary=context.get("summary", "")
                    )
                    db.add(mem)
                await db.commit()

    async def update_facts(self, conversation_id: str, new_facts: dict):
        """Merge new facts into existing memory (short-term and long-term)."""
        context = await self.get_context(conversation_id)
        context["facts"] = {**context.get("facts", {}), **new_facts}
        await self.save_context(conversation_id, context)