"""
Message Ordering Service - Ensures chronological message ordering using Meta timestamps.

Features:
- Uses Meta's whatsapp_timestamp as source of truth
- Prevents duplicate messages (whatsapp_message_id unique constraint)
- Fast ordering via database indexes
- Handles webhook retries
- Maintains consistent message history
"""

from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import logging

from modules.common.models import Message, Conversation

logger = logging.getLogger(__name__)


class MessageOrderingService:
    """
    Ensures messages are ordered chronologically using Meta timestamps.
    
    Key principles:
    - whatsapp_timestamp (from Meta) is source of truth
    - whatsapp_message_id prevents duplicates
    - sort_timestamp enables fast queries
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def process_message(
        self,
        conversation_id: str,
        whatsapp_message_id: str,
        content: str,
        whatsapp_timestamp: int,
        sender: str = "user",
        media_url: Optional[str] = None
    ) -> Optional[Message]:
        """
        Process message with ordering guarantees.
        
        Args:
            conversation_id: UUID of conversation
            whatsapp_message_id: Unique ID from Meta webhook
            content: Message text
            whatsapp_timestamp: Unix seconds from Meta (source of truth)
            sender: "user" or "bot"
            media_url: Optional media attachment URL
        
        Returns:
            Message object, or None if duplicate
        """
        
        # Check for duplicate (Meta webhook retries)
        result = await self.db.execute(
            select(Message).where(
                Message.whatsapp_message_id == whatsapp_message_id
            )
        )
        
        existing_msg = result.scalar_one_or_none()
        if existing_msg:
            logger.debug(
                f"Duplicate message detected: {whatsapp_message_id}, "
                f"skipping creation"
            )
            return existing_msg  # Return existing, don't create new
        
        # Create message with proper timestamps
        sort_timestamp = datetime.fromtimestamp(whatsapp_timestamp)
        
        message = Message(
            conversation_id=conversation_id,
            whatsapp_message_id=whatsapp_message_id,
            content=content,
            whatsapp_timestamp=whatsapp_timestamp,
            sort_timestamp=sort_timestamp,
            mode=("user" if sender == "user" else ("bot" if sender == "bot" else "ai")),
            media_url=media_url,
            created_at=datetime.utcnow()
        )
        
        self.db.add(message)
        
        try:
            await self.db.flush()
            logger.debug(
                f"Created message {whatsapp_message_id} for conversation {conversation_id}"
            )
            return message
        
        except Exception as e:
            logger.error(f"Error creating message: {e}")
            raise
    
    async def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0,
        include_count: bool = False
    ) -> tuple[List[Message], Optional[int]]:
        """
        Get messages in chronological order (oldest first).
        
        Args:
            conversation_id: UUID of conversation
            limit: Maximum messages to return
            offset: Number of messages to skip
            include_count: If True, also return total message count
        
        Returns:
            (list of messages, total_count if requested)
        """
        
        query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sort_timestamp.asc())  # Chronological (oldest first)
            .offset(offset)
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        messages = result.scalars().all()
        
        total_count = None
        if include_count:
            count_result = await self.db.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
            total_count = len(count_result.scalars().all())
        
        logger.debug(
            f"Retrieved {len(messages)} messages for conversation {conversation_id}"
        )
        
        return messages, total_count
    
    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Message]:
        """
        Get most recent messages (newest first).
        
        Args:
            conversation_id: UUID of conversation
            limit: Maximum messages to return
        
        Returns:
            List of messages (newest first)
        """
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.sort_timestamp))  # Newest first
            .limit(limit)
        )
        
        messages = result.scalars().all()
        return list(reversed(messages))  # Reverse to return newest at end
    
    async def get_messages_since(
        self,
        conversation_id: str,
        since_timestamp: int,
        limit: int = 50
    ) -> List[Message]:
        """
        Get messages since a specific timestamp.
        
        Useful for pagination or updates.
        
        Args:
            conversation_id: UUID of conversation
            since_timestamp: Unix seconds
            limit: Maximum messages to return
        
        Returns:
            List of messages after timestamp (chronological)
        """
        
        since_datetime = datetime.fromtimestamp(since_timestamp)
        
        result = await self.db.execute(
            select(Message)
            .where(
                (Message.conversation_id == conversation_id) &
                (Message.sort_timestamp > since_datetime)
            )
            .order_by(Message.sort_timestamp.asc())
            .limit(limit)
        )
        
        return result.scalars().all()
    
    async def get_message_by_whatsapp_id(
        self,
        whatsapp_message_id: str
    ) -> Optional[Message]:
        """Get message by WhatsApp message ID"""
        
        result = await self.db.execute(
            select(Message).where(
                Message.whatsapp_message_id == whatsapp_message_id
            )
        )
        
        return result.scalar_one_or_none()
    
    async def verify_message_ordering(
        self,
        conversation_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Verify messages are in correct chronological order.
        
        Returns:
            (is_correct, error_message)
        """
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sort_timestamp.asc())
        )
        
        messages = result.scalars().all()
        
        if len(messages) < 2:
            return True, None
        
        # Check each message is >= previous
        for i in range(1, len(messages)):
            current_ts = messages[i].sort_timestamp
            previous_ts = messages[i - 1].sort_timestamp
            
            if current_ts < previous_ts:
                error = (
                    f"Message ordering violation at position {i}: "
                    f"{current_ts} < {previous_ts}"
                )
                logger.error(error)
                return False, error
        
        logger.info(f"Message ordering verified for {conversation_id}")
        return True, None
    
    async def get_ordering_stats(
        self,
        conversation_id: str
    ) -> dict:
        """Get statistics about message ordering"""
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sort_timestamp.asc())
        )
        
        messages = result.scalars().all()
        
        if not messages:
            return {
                "total_messages": 0,
                "ordering_correct": True,
                "first_message_time": None,
                "last_message_time": None,
                "span_seconds": 0
            }
        
        is_correct, _ = await self.verify_message_ordering(conversation_id)
        
        first_time = messages[0].sort_timestamp
        last_time = messages[-1].sort_timestamp
        span = (last_time - first_time).total_seconds()
        
        return {
            "total_messages": len(messages),
            "ordering_correct": is_correct,
            "first_message_time": first_time.isoformat(),
            "last_message_time": last_time.isoformat(),
            "span_seconds": int(span)
        }
    
    async def get_messages_for_context(
        self,
        conversation_id: str,
        num_messages: int = 10
    ) -> List[dict]:
        """
        Get messages formatted for LLM context.
        
        Returns:
            List of formatted messages with role and content
        """
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.sort_timestamp))
            .limit(num_messages)
        )
        
        messages = result.scalars().all()
        messages = list(reversed(messages))  # Chronological order
        
        formatted = []
        for msg in messages:
            formatted.append({
                "role": "user" if msg.sender == "user" else "assistant",
                "content": msg.content,
                "timestamp": msg.sort_timestamp.isoformat(),
                "whatsapp_id": msg.whatsapp_message_id
            })
        
        return formatted
