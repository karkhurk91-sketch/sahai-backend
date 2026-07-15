"""
Pinned Message Service – handles pin/unpin logic, limit validation, and WebSocket broadcasting.
"""
from uuid import UUID
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from datetime import datetime, timezone

from modules.common.logger import get_logger
from modules.common.models import PinnedMessage, Conversation, Message, Organization
from modules.websocket import manager
from modules.common.database import get_db

logger = get_logger(__name__)

class PinnedMessageService:
    def __init__(self, db: AsyncSession, audit_service = None):
        self.db = db
        self.audit = audit_service

    async def _get_org_max_pins(self, org_id: UUID) -> int:
        """Get the max number of pinned messages allowed for the organisation."""
        stmt = select(Organization.max_pinned_messages).where(Organization.id == org_id)
        result = await self.db.execute(stmt)
        max_pins = result.scalar_one_or_none()
        return max_pins or 3  # fallback to default

    async def _broadcast_pin_update(self, conv_id: UUID) -> None:
        """Broadcast pin_updated event to all users in the conversation."""
        pins = await self.get_pinned_messages(conv_id)
        await manager.broadcast_pin_update(str(conv_id), pins)

    async def pin_message(self, conv_id: UUID, msg_id: UUID, user_id: UUID, org_id: UUID) -> Dict[str, Any]:
        """
        Pin a message in a conversation.
        Raises ValueError if pin limit is reached or message is already pinned.
        """
        # 1. Check that the message belongs to the conversation
        stmt = select(Message).where(
            Message.id == msg_id,
            Message.conversation_id == conv_id
        )
        result = await self.db.execute(stmt)
        msg = result.scalar_one_or_none()
        if not msg:
            raise ValueError("Message not found in this conversation")

        # 2. Check if already pinned
        stmt = select(PinnedMessage).where(
            PinnedMessage.conversation_id == conv_id,
            PinnedMessage.message_id == msg_id,
            PinnedMessage.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        existing_pin = result.scalar_one_or_none()
        if existing_pin:
            raise ValueError("Message is already pinned")

        # 3. Check pin limit
        max_pins = await self._get_org_max_pins(org_id)
        stmt = select(func.count()).where(
            PinnedMessage.conversation_id == conv_id,
            PinnedMessage.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        current_pin_count = result.scalar()
        if current_pin_count >= max_pins:
            raise ValueError(f"Cannot pin more than {max_pins} messages in this conversation")

        # 4. Create pin
        pin = PinnedMessage(
            organization_id=org_id,
            conversation_id=conv_id,
            message_id=msg_id,
            pinned_by=user_id,
            pinned_at=datetime.now(timezone.utc),
            order_index=current_pin_count
        )
        self.db.add(pin)
        await self.db.commit()
        await self.db.refresh(pin)

        # 5. Broadcast update
        await self._broadcast_pin_update(conv_id)

        return {
            "id": str(pin.id),
            "message_id": str(msg_id),
            "conversation_id": str(conv_id),
            "pinned_at": pin.pinned_at.isoformat(),
            "pinned_by": str(user_id)
        }

    async def unpin_message(self, conv_id: UUID, msg_id: UUID) -> Dict[str, Any]:
        """
        Unpin a message (soft delete).
        Raises ValueError if the pin does not exist.
        """
        # 1. Find the pin
        stmt = select(PinnedMessage).where(
            PinnedMessage.conversation_id == conv_id,
            PinnedMessage.message_id == msg_id,
            PinnedMessage.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        pin = result.scalar_one_or_none()
        if not pin:
            raise ValueError("Pin not found")

        # 2. Soft delete
        pin.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

        # 3. Broadcast update
        await self._broadcast_pin_update(conv_id)

        return {
            "message": "Unpinned successfully",
            "conversation_id": str(conv_id),
            "message_id": str(msg_id)
        }

    async def get_pinned_messages(self, conv_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetch all pinned messages for a conversation with full message details.
        """
        stmt = select(PinnedMessage).where(
            PinnedMessage.conversation_id == conv_id,
            PinnedMessage.deleted_at.is_(None)
        ).order_by(PinnedMessage.pinned_at.desc())
        result = await self.db.execute(stmt)
        pins = result.scalars().all()

        if not pins:
            return []

        # Get message IDs and fetch full message details
        msg_ids = [pin.message_id for pin in pins]
        stmt = select(Message).where(Message.id.in_(msg_ids))
        result = await self.db.execute(stmt)
        messages = result.scalars().all()
        msg_map = {str(m.id): m for m in messages}

        output = []
        for pin in pins:
            msg = msg_map.get(str(pin.message_id))
            if not msg:
                continue
            output.append({
                "id": str(pin.id),
                "message_id": str(pin.message_id),
                "conversation_id": str(pin.conversation_id),
                "pinned_at": pin.pinned_at.isoformat(),
                "pinned_by": str(pin.pinned_by),
                "message": {
                    "id": str(msg.id),
                    "text": msg.content,
                    "sender_type": msg.direction,
                    "direction": msg.direction,
                    "created_at": msg.created_at.isoformat(),
                    "sort_timestamp": msg.sort_timestamp.isoformat() if msg.sort_timestamp else None,
                    "status": msg.status,
                    "mode": msg.mode,
                    "message_type": msg.message_type,
                    "media_url": msg.media_url,
                    "media_file_name": msg.media_file_name,
                    "media_content_type": msg.media_content_type,
                    "whatsapp_message_id": msg.whatsapp_message_id,
                    "sender_name": None,  # will be resolved in the frontend
                }
            })
        return output