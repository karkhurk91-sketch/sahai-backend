"""
Enterprise Memory Engine - Persistent conversation context
Uses Redis (short-term) + PostgreSQL (long-term) with rolling summaries
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import json
import redis
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.logger import get_logger
import uuid

logger = get_logger(__name__)


class EnterpriseMemoryEngine:
    """
    Manages conversation memory with:
    - Redis: Hot memory (last 50 messages, current session)
    - PostgreSQL: Cold memory (summaries, completed fields, preferences)
    - Rolling summaries: Compress old messages into summaries
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.short_term_ttl = 24 * 60 * 60  # 24 hours
        self.summary_window = 20  # Summarize after 20 messages

    def _short_term_key(self, conversation_id: str) -> str:
        """Redis key for short-term memory."""
        return f"memory:short:{conversation_id}"

    def _summary_key(self, conversation_id: str) -> str:
        """Redis key for conversation summary."""
        return f"memory:summary:{conversation_id}"

    async def load_context(self, conversation_id: str) -> Dict[str, Any]:
        """Load complete context for conversation."""
        context = {
            "short_term": {},
            "long_term": {},
            "summary": "",
            "preferences": {},
            "completed_fields": {},
        }

        # Load from Redis
        if self.redis:
            try:
                # Short-term messages
                messages_data = self.redis.get(self._short_term_key(conversation_id))
                if messages_data:
                    context["short_term"] = json.loads(messages_data)

                # Summary
                summary_data = self.redis.get(self._summary_key(conversation_id))
                if summary_data:
                    context["summary"] = summary_data.decode("utf-8")
            except Exception as e:
                logger.error(f"Failed to load from Redis: {e}")

        # Load long-term from DB
        try:
            async with AsyncSessionLocal() as db:
                from modules.common.models import ConversationMemory
                result = await db.execute(
                    select(ConversationMemory).where(
                        ConversationMemory.conversation_id == uuid.UUID(conversation_id)
                    ).order_by(ConversationMemory.created_at.desc()).limit(1)
                )
                memory = result.scalars().first()
                if memory:
                    context["long_term"] = memory.memory_data or {}
                    context["preferences"] = memory.preferences or {}
                    context["completed_fields"] = memory.completed_fields or {}
        except Exception as e:
            logger.debug(f"No long-term memory found: {e}")

        return context

    async def add_message_to_memory(
        self,
        conversation_id: str,
        role: str,  # "user" or "assistant"
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a message to short-term memory."""
        if not self.redis:
            return

        try:
            # Get existing messages
            messages_data = self.redis.get(self._short_term_key(conversation_id))
            messages = json.loads(messages_data) if messages_data else []

            # Add new message
            messages.append({
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            })

            # Keep only last 50 messages in Redis
            messages = messages[-50:]

            # Check if we need to summarize
            if len(messages) >= self.summary_window:
                await self._create_rolling_summary(conversation_id, messages)

            # Save to Redis
            self.redis.setex(
                self._short_term_key(conversation_id),
                self.short_term_ttl,
                json.dumps(messages, default=str)
            )
        except Exception as e:
            logger.error(f"Failed to add message to memory: {e}")

    async def _create_rolling_summary(
        self,
        conversation_id: str,
        messages: list,
    ) -> None:
        """Create a rolling summary of conversation."""
        try:
            # Group messages into chunks
            text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

            # Simple summarization: extract key facts
            summary = self._extract_summary_facts(text)

            # Save summary to Redis
            if self.redis:
                self.redis.setex(
                    self._summary_key(conversation_id),
                    30 * 24 * 60 * 60,  # 30 days
                    json.dumps(summary, default=str)
                )

            logger.debug(f"Created rolling summary for {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to create summary: {e}")

    @staticmethod
    def _extract_summary_facts(text: str) -> Dict[str, Any]:
        """Extract key facts from conversation."""
        facts = {
            "key_points": [],
            "entities": {},
            "decisions": [],
        }

        lines = text.split("\n")
        for line in lines:
            if "budget" in line.lower():
                facts["key_points"].append(line)
            if "confirm" in line.lower() or "agree" in line.lower():
                facts["decisions"].append(line)

        return facts

    async def update_preferences(
        self,
        conversation_id: str,
        preferences: Dict[str, Any],
    ) -> None:
        """Store user preferences for future interactions."""
        try:
            async with AsyncSessionLocal() as db:
                from modules.common.models import ConversationMemory

                result = await db.execute(
                    select(ConversationMemory).where(
                        ConversationMemory.conversation_id == uuid.UUID(conversation_id)
                    )
                )
                memory = result.scalars().first()

                if memory:
                    memory.preferences = {**(memory.preferences or {}), **preferences}
                    memory.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                else:
                    # Create new memory record
                    memory = ConversationMemory(
                        id=uuid.uuid4(),
                        conversation_id=uuid.UUID(conversation_id),
                        preferences=preferences,
                        memory_data={},
                        completed_fields={},
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(memory)
                    await db.commit()

                logger.debug(f"Updated preferences for {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to update preferences: {e}")

    async def mark_field_remembered(
        self,
        conversation_id: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Mark that we remember a field to avoid re-asking."""
        try:
            async with AsyncSessionLocal() as db:
                from modules.common.models import ConversationMemory

                result = await db.execute(
                    select(ConversationMemory).where(
                        ConversationMemory.conversation_id == uuid.UUID(conversation_id)
                    )
                )
                memory = result.scalars().first()

                if memory:
                    completed = memory.completed_fields or {}
                    completed[field_name] = {
                        "value": value,
                        "remembered_at": datetime.now(timezone.utc).isoformat(),
                    }
                    memory.completed_fields = completed
                    await db.commit()
                    logger.debug(f"Remembered field: {field_name}")
        except Exception as e:
            logger.error(f"Failed to mark field remembered: {e}")
