# modules/ai/conversation_state.py
from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime
import json
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.database import get_async_session
from modules.ai.models import ConversationMemory  # assume existing model

class ConversationStage(str, Enum):
    GREETING = "greeting"
    QUALIFICATION = "qualification"
    BOOKING = "booking"
    PROPERTY_RECOMMENDATION = "property_recommendation"
    FOLLOWUP = "followup"
    CLOSED = "closed"

# modules/ai/conversation_state.py (generic)
class ConversationState(BaseModel):
    whatsapp_number: str
    stage: str  # "greeting", "qualification", "booking", "recommendation", "followup", "closed"
    completed_fields: Dict[str, bool]  # dynamic keys from org config
    lead_data: Dict[str, Any]          # stores values for any field
    booking_confirmed: bool = False
    booking_details: Optional[dict] = None
    conversation_summary: str = ""
    
    def is_field_completed(self, field: str) -> bool:
        return self.completed_fields.get(field, False)

    def mark_field_completed(self, field: str):
        self.completed_fields[field] = True
        self.last_updated = datetime.utcnow()

    def update_lead_data(self, new_data: dict):
        # Merge, do not overwrite existing values unless new data is non-empty
        for k, v in new_data.items():
            if v and not self.lead_data.get(k):
                self.lead_data[k] = v
                self.mark_field_completed(k)

class ConversationStateManager:
    REDIS_KEY_PREFIX = "conv_state:"
    TTL_SECONDS = 86400  # 24 hours

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def get_state(self, whatsapp_number: str) -> ConversationState:
        key = f"{self.REDIS_KEY_PREFIX}{whatsapp_number}"
        data = await self.redis.get(key)
        if data:
            return ConversationState.parse_raw(data)
        # Fallback: load from PostgreSQL if needed (optional, keep Redis as primary)
        return ConversationState(whatsapp_number=whatsapp_number)

    async def save_state(self, state: ConversationState):
        key = f"{self.REDIS_KEY_PREFIX}{state.whatsapp_number}"
        await self.redis.setex(key, self.TTL_SECONDS, state.json())

    async def update_stage(self, whatsapp_number: str, new_stage: ConversationStage):
        state = await self.get_state(whatsapp_number)
        state.stage = new_stage
        await self.save_state(state)

    async def update_completed_field(self, whatsapp_number: str, field: str):
        state = await self.get_state(whatsapp_number)
        state.mark_field_completed(field)
        await self.save_state(state)

    async def merge_lead_data(self, whatsapp_number: str, extracted: dict):
        state = await self.get_state(whatsapp_number)
        state.update_lead_data(extracted)
        await self.save_state(state)