"""
State Synchronizer - Keeps Redis and PostgreSQL in sync
Ensures all services see consistent state via WebSocket broadcasts
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import json
import uuid
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.logger import get_logger

logger = get_logger(__name__)


class StateSynchronizer:
    """
    Ensures conversation state consistency across:
    - Redis (hot cache)
    - PostgreSQL (persistent storage)
    - WebSocket (real-time frontend)
    """

    @staticmethod
    async def sync_to_redis(
        redis_client,
        conversation_id: str,
        state_dict: Dict[str, Any],
        ttl: int = 30 * 24 * 60 * 60,  # 30 days
    ) -> bool:
        """Sync state to Redis."""
        try:
            if not redis_client:
                return False

            key = f"conv_state:{conversation_id}"
            redis_client.setex(
                key,
                ttl,
                json.dumps(state_dict, default=str)
            )
            logger.debug(f"Synced state to Redis: {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to sync to Redis: {e}")
            return False

    @staticmethod
    async def sync_to_db(
        conversation_id: str,
        state_dict: Dict[str, Any],
    ) -> bool:
        """Sync state to PostgreSQL."""
        try:
            async with AsyncSessionLocal() as db:
                from modules.common.models import Conversation

                result = await db.execute(
                    select(Conversation).where(
                        Conversation.id == uuid.UUID(conversation_id)
                    )
                )
                conv = result.scalars().first()

                if conv:
                    conv.conversation_stage = state_dict.get("stage", "greeting")
                    conv.completed_fields = state_dict.get("completed_fields", {})
                    conv.booking_status = state_dict.get("booking_status")
                    conv.recommendation_shown = state_dict.get("recommendation_shown", False)
                    conv.last_intent = state_dict.get("last_intent")
                    conv.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.debug(f"Synced state to DB: {conversation_id}")
                    return True
        except Exception as e:
            logger.error(f"Failed to sync to DB: {e}")
            return False

    @staticmethod
    async def broadcast_state_update(
        websocket_manager,
        conversation_id: str,
        state_dict: Dict[str, Any],
        event_type: str = "state_update",
    ) -> bool:
        """Broadcast state update to connected WebSocket clients."""
        try:
            if not websocket_manager:
                return False

            payload = {
                "type": event_type,
                "conversation_id": conversation_id,
                "state": state_dict,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await websocket_manager.broadcast(payload)
            logger.debug(f"Broadcasted state update: {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to broadcast state: {e}")
            return False

    @staticmethod
    async def sync_stage_update(
        redis_client,
        conversation_id: str,
        new_stage: str,
        old_stage: str,
        websocket_manager=None,
    ) -> bool:
        """Sync stage update across all layers."""
        try:
            # Prepare state dict
            state_dict = {
                "stage": new_stage,
                "previous_stage": old_stage,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Sync to Redis
            await StateSynchronizer.sync_to_redis(redis_client, conversation_id, state_dict)

            # Sync to DB
            await StateSynchronizer.sync_to_db(conversation_id, state_dict)

            # Broadcast to WebSocket
            if websocket_manager:
                await StateSynchronizer.broadcast_state_update(
                    websocket_manager,
                    conversation_id,
                    state_dict,
                    event_type="stage_changed"
                )

            logger.info(f"Stage synced: {conversation_id} {old_stage} → {new_stage}")
            return True
        except Exception as e:
            logger.error(f"Failed to sync stage update: {e}")
            return False

    @staticmethod
    async def sync_booking_created(
        redis_client,
        conversation_id: str,
        booking_dict: Dict[str, Any],
        websocket_manager=None,
    ) -> bool:
        """Sync booking creation across all layers."""
        try:
            # Update state
            state_dict = {
                "booking_status": "confirmed",
                "booking_id": booking_dict.get("id"),
                "booking_date": booking_dict.get("booking_date"),
                "booking_time": booking_dict.get("booking_time"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Sync
            await StateSynchronizer.sync_to_redis(redis_client, conversation_id, state_dict)
            await StateSynchronizer.sync_to_db(conversation_id, state_dict)

            # Broadcast
            if websocket_manager:
                await StateSynchronizer.broadcast_state_update(
                    websocket_manager,
                    conversation_id,
                    booking_dict,
                    event_type="booking_created"
                )

            logger.info(f"Booking synced: {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to sync booking: {e}")
            return False

    @staticmethod
    async def broadcast_ai_response(
        websocket_manager,
        conversation_id: str,
        ai_response: str,
        message_id: str,
    ) -> bool:
        """Broadcast AI response for real-time UI update."""
        try:
            if not websocket_manager:
                return False

            payload = {
                "type": "ai_response",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "content": ai_response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await websocket_manager.broadcast(payload)
            logger.debug(f"Broadcasted AI response: {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to broadcast AI response: {e}")
            return False
