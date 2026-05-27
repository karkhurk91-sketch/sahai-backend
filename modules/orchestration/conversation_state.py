"""
Conversation State Machine - Persistent conversation stage tracking
Prevents repetitive questions and ensures consistent workflow
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.models import Conversation
from modules.common.logger import get_logger
import json
import redis.asyncio as redis  # Use async Redis client

logger = get_logger(__name__)

# Conversation stages
STAGE_GREETING = "greeting"
STAGE_QUALIFICATION = "qualification"
STAGE_RECOMMENDATION = "recommendation"
STAGE_BOOKING = "booking"
STAGE_FOLLOWUP = "followup"
STAGE_SUPPORT = "support"
STAGE_CLOSED = "closed"

# Stage progression
STAGE_FLOW = {
    STAGE_GREETING: [STAGE_QUALIFICATION, STAGE_CLOSED],
    STAGE_QUALIFICATION: [STAGE_RECOMMENDATION, STAGE_BOOKING, STAGE_CLOSED],
    STAGE_RECOMMENDATION: [STAGE_BOOKING, STAGE_FOLLOWUP, STAGE_CLOSED],
    STAGE_BOOKING: [STAGE_FOLLOWUP, STAGE_CLOSED],
    STAGE_FOLLOWUP: [STAGE_CLOSED],
    STAGE_SUPPORT: [STAGE_CLOSED],
    STAGE_CLOSED: [],
}


class ConversationStateManager:
    """Manages persistent conversation state to prevent AI repetition."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.ttl = 30 * 24 * 60 * 60  # 30 days

    def _state_key(self, conversation_id: str) -> str:
        """Redis key for conversation state."""
        return f"conv_state:{conversation_id}"

    async def get_state(self, conversation_id: str) -> Dict[str, Any]:
        """Fetch conversation state from Redis or DB."""
        try:
            # Try Redis first
            if self.redis:
                # AWAIT the get call
                state_json = await self.redis.get(self._state_key(conversation_id))
                if state_json:
                    logger.debug(f"Loaded conversation state from Redis: {conversation_id}")
                    return json.loads(state_json)

            # Fall back to DB
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
                )
                conv = result.scalars().first()
                if conv:
                    state = {
                        "stage": getattr(conv, "conversation_stage", STAGE_GREETING),
                        "completed_fields": getattr(conv, "completed_fields", {}),
                        "booking_status": getattr(conv, "booking_status", None),
                        "recommendation_shown": getattr(conv, "recommendation_shown", False),
                        "last_intent": getattr(conv, "last_intent", None),
                        "created_at": conv.created_at.isoformat() if conv.created_at else None,
                    }
                    # Cache in Redis
                    if self.redis:
                        await self.redis.setex(
                            self._state_key(conversation_id),
                            self.ttl,
                            json.dumps(state, default=str)
                        )
                    return state
        except Exception as e:
            logger.error(f"Failed to load conversation state: {e}")

        # Default state
        return {
            "stage": STAGE_GREETING,
            "completed_fields": {},
            "booking_status": None,
            "recommendation_shown": False,
            "last_intent": None,
        }

    async def update_stage(
        self,
        conversation_id: str,
        new_stage: str,
        reason: str = ""
    ) -> bool:
        """Update conversation stage and validate transition."""
        if new_stage not in STAGE_FLOW:
            logger.error(f"Invalid stage: {new_stage}")
            return False

        current_state = await self.get_state(conversation_id)
        current_stage = current_state.get("stage", STAGE_GREETING)

        # Validate transition
        if new_stage not in STAGE_FLOW.get(current_stage, []):
            logger.warning(
                f"Invalid stage transition: {current_stage} → {new_stage}. Reason: {reason}"
            )
            return False

        # Update state
        current_state["stage"] = new_stage
        current_state["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Persist to Redis
        if self.redis:
            await self.redis.setex(
                self._state_key(conversation_id),
                self.ttl,
                json.dumps(current_state, default=str)
            )

        # Persist to DB
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
                )
                conv = result.scalars().first()
                if conv:
                    conv.conversation_stage = new_stage
                    conv.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(f"Stage updated: {conversation_id} {current_stage} → {new_stage}")
                    return True
        except Exception as e:
            logger.error(f"Failed to update stage in DB: {e}")

        return True  # Redis update succeeded

    async def mark_field_completed(
        self,
        conversation_id: str,
        field_name: str,
        value: Any
    ) -> None:
        """Mark a qualification field as completed."""
        state = await self.get_state(conversation_id)
        if "completed_fields" not in state:
            state["completed_fields"] = {}

        state["completed_fields"][field_name] = {
            "value": value,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        if self.redis:
            await self.redis.setex(
                self._state_key(conversation_id),
                self.ttl,
                json.dumps(state, default=str)
            )
        logger.debug(f"Marked field completed: {field_name} = {value}")

    async def is_field_completed(
        self,
        conversation_id: str,
        field_name: str
    ) -> bool:
        """Check if a field was already collected."""
        state = await self.get_state(conversation_id)
        return field_name in state.get("completed_fields", {})

    async def set_last_intent(
        self,
        conversation_id: str,
        intent: str
    ) -> None:
        """Store last detected intent to prevent duplicate processing."""
        state = await self.get_state(conversation_id)
        state["last_intent"] = intent
        state["last_intent_at"] = datetime.now(timezone.utc).isoformat()

        if self.redis:
            await self.redis.setex(
                self._state_key(conversation_id),
                self.ttl,
                json.dumps(state, default=str)
            )