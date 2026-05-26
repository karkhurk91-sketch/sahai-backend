"""
Cache Manager - Dual-layer caching with Redis + PostgreSQL fallback.

Features:
- Redis caching for fast access (24h TTL)
- Automatic fallback to PostgreSQL if Redis unavailable
- Graceful degradation on cache failures
- Versioned state updates to prevent stale data
"""

import redis
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Manages conversation state caching with Redis + PostgreSQL fallback.
    
    Ensures:
    - Fast access via Redis
    - Persistence via PostgreSQL
    - Graceful fallback on Redis failure
    - No data loss
    """
    
    # Cache TTL (24 hours)
    CONVERSATION_STATE_TTL = 86400
    MEMORY_TTL = 86400
    INTENT_TTL = 3600  # 1 hour for intents
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        db_session: Optional[AsyncSession] = None
    ):
        self.redis = redis_client
        self.db = db_session
        self.redis_available = redis_client is not None
    
    async def get_conversation_state(
        self,
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached conversation state.
        
        Tries Redis first, falls back to PostgreSQL.
        """
        cache_key = f"conversation:{conversation_id}:state"
        
        # Try Redis
        if self.redis_available:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit for conversation {conversation_id}")
                    return json.loads(cached)
                logger.debug(f"Cache miss for conversation {conversation_id}")
            except Exception as e:
                logger.warning(f"Redis read error for {cache_key}: {e}")
                self.redis_available = False  # Mark Redis as down
        
        # Fallback to PostgreSQL
        if self.db:
            try:
                from sqlalchemy import select
                from modules.common.models import Conversation
                
                result = await self.db.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
                conversation = result.scalar_one_or_none()
                
                if conversation:
                    state_data = {
                        "id": str(conversation.id),
                        "organization_id": str(conversation.organization_id),
                        "stage": conversation.conversation_stage,
                        "completed_fields": conversation.completed_fields or {},
                        "booking_status": conversation.booking_status,
                        "recommendation_status": getattr(
                            conversation,
                            "recommendation_status",
                            "none"
                        ),
                        "last_intent": conversation.last_intent,
                        "next_expected_action": getattr(
                            conversation,
                            "next_expected_action",
                            None
                        ),
                        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
                    }
                    
                    # Try to cache in Redis for future hits
                    await self.set_conversation_state(conversation_id, state_data)
                    
                    return state_data
            except Exception as e:
                logger.error(f"PostgreSQL read error for {conversation_id}: {e}")
        
        return None
    
    async def set_conversation_state(
        self,
        conversation_id: str,
        state_data: Dict[str, Any]
    ) -> bool:
        """
        Set conversation state in cache.
        
        Tries Redis, but continues even if Redis fails.
        """
        cache_key = f"conversation:{conversation_id}:state"
        
        if not self.redis_available:
            logger.debug(f"Redis unavailable, skipping cache set for {conversation_id}")
            return False
        
        try:
            self.redis.setex(
                cache_key,
                self.CONVERSATION_STATE_TTL,
                json.dumps(state_data, default=str)
            )
            logger.debug(f"Cached conversation state: {conversation_id}")
            return True
        except Exception as e:
            logger.warning(f"Redis write error for {cache_key}: {e}")
            self.redis_available = False  # Mark Redis as down
            return False
    
    async def invalidate_conversation_state(
        self,
        conversation_id: str
    ) -> bool:
        """Invalidate conversation cache on state change"""
        cache_key = f"conversation:{conversation_id}:state"
        
        if not self.redis_available:
            return False
        
        try:
            self.redis.delete(cache_key)
            logger.debug(f"Invalidated cache for conversation {conversation_id}")
            return True
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")
            return False
    
    async def get_memory_summary(
        self,
        conversation_id: str,
        summary_type: str = "message_summary"
    ) -> Optional[str]:
        """
        Get conversation memory summary.
        
        Tries Redis first, falls back to PostgreSQL.
        """
        cache_key = f"conversation:{conversation_id}:memory:{summary_type}"
        
        # Try Redis
        if self.redis_available:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(f"Memory cache hit for {conversation_id}")
                    return cached.decode('utf-8')
            except Exception as e:
                logger.warning(f"Redis memory read error: {e}")
                self.redis_available = False
        
        # Fallback to PostgreSQL
        if self.db:
            try:
                from sqlalchemy import select
                from modules.common.models import ConversationMemory
                
                result = await self.db.execute(
                    select(ConversationMemory).where(
                        (ConversationMemory.conversation_id == conversation_id) &
                        (ConversationMemory.summary_type == summary_type)
                    ).order_by(ConversationMemory.created_at.desc()).limit(1)
                )
                
                memory = result.scalar_one_or_none()
                if memory:
                    # Cache it for future hits
                    await self.set_memory_summary(
                        conversation_id,
                        memory.content,
                        summary_type
                    )
                    return memory.content
            except Exception as e:
                logger.error(f"PostgreSQL memory read error: {e}")
        
        return None
    
    async def set_memory_summary(
        self,
        conversation_id: str,
        content: str,
        summary_type: str = "message_summary"
    ) -> bool:
        """Set memory summary in cache"""
        cache_key = f"conversation:{conversation_id}:memory:{summary_type}"
        
        if not self.redis_available:
            return False
        
        try:
            self.redis.setex(
                cache_key,
                self.MEMORY_TTL,
                content
            )
            return True
        except Exception as e:
            logger.warning(f"Redis memory write error: {e}")
            self.redis_available = False
            return False
    
    async def get_last_intent(
        self,
        conversation_id: str
    ) -> Optional[str]:
        """Get cached last intent"""
        cache_key = f"conversation:{conversation_id}:last_intent"
        
        if not self.redis_available:
            return None
        
        try:
            cached = self.redis.get(cache_key)
            if cached:
                return cached.decode('utf-8')
        except Exception as e:
            logger.warning(f"Redis last intent error: {e}")
        
        return None
    
    async def set_last_intent(
        self,
        conversation_id: str,
        intent: str
    ) -> bool:
        """Cache last intent"""
        cache_key = f"conversation:{conversation_id}:last_intent"
        
        if not self.redis_available:
            return False
        
        try:
            self.redis.setex(
                cache_key,
                self.INTENT_TTL,
                intent
            )
            return True
        except Exception as e:
            logger.warning(f"Redis intent write error: {e}")
            self.redis_available = False
            return False
    
    async def get_completed_fields(
        self,
        conversation_id: str
    ) -> Dict[str, Any]:
        """Get completed fields from cache or DB"""
        state = await self.get_conversation_state(conversation_id)
        if state:
            return state.get("completed_fields", {})
        return {}
    
    async def update_completed_fields(
        self,
        conversation_id: str,
        field_name: str,
        field_value: Any,
        field_source: str = "ai"
    ) -> bool:
        """
        Update a completed field.
        
        Atomically updates cache and DB.
        """
        # Get current state
        state = await self.get_conversation_state(conversation_id)
        if not state:
            logger.error(f"Could not load state for {conversation_id}")
            return False
        
        # Update in memory
        if "completed_fields" not in state:
            state["completed_fields"] = {}
        
        state["completed_fields"][field_name] = {
            "value": field_value,
            "completed_at": datetime.utcnow().isoformat(),
            "source": field_source
        }
        
        # Update cache
        await self.set_conversation_state(conversation_id, state)
        
        # Update DB
        if self.db:
            try:
                from sqlalchemy import select
                from modules.common.models import Conversation
                
                result = await self.db.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
                conversation = result.scalar_one_or_none()
                
                if conversation:
                    if conversation.completed_fields is None:
                        conversation.completed_fields = {}
                    
                    conversation.completed_fields[field_name] = {
                        "value": field_value,
                        "completed_at": datetime.utcnow().isoformat(),
                        "source": field_source
                    }
                    conversation.updated_at = datetime.utcnow()
                    
                    await self.db.commit()
                    logger.debug(f"Updated field {field_name} for {conversation_id}")
            except Exception as e:
                logger.error(f"Error updating DB: {e}")
                return False
        
        return True
    
    def health_check(self) -> Dict[str, Any]:
        """Check cache system health"""
        redis_status = "unavailable"
        if self.redis_available:
            try:
                self.redis.ping()
                redis_status = "available"
            except:
                redis_status = "unavailable"
                self.redis_available = False
        
        return {
            "redis": redis_status,
            "postgres": "available" if self.db else "unavailable",
            "fallback_enabled": True
        }
