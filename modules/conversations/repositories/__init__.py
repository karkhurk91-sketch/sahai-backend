from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from modules.common.models import Conversation, Message, Tag, ConversationTag, ConversationNote
from .base import BaseRepository

class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Conversation)

    async def get_by_org_id(self, org_id: UUID) -> List[Conversation]:
        result = await self.session.execute(
            select(Conversation).where(Conversation.organization_id == org_id)
            .order_by(desc(Conversation.last_message_at))
        )
        return result.scalars().all()

    # Inside ConversationRepository class
    async def get_by_agent_id(self, org_id: UUID, agent_id: UUID) -> List[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(
                Conversation.organization_id == org_id,
                Conversation.assigned_agent_id == agent_id
            )
            .order_by(desc(Conversation.last_message_at))
        )
        return result.scalars().all()   
         
    async def get_by_phone_and_org(self, phone_number: str, org_id: UUID) -> Optional[Conversation]:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.customer_phone_number == phone_number,
                Conversation.organization_id == org_id
            )
        )
        return result.scalar_one_or_none()

    async def search_by_phone_or_name(self, org_id: UUID, search_term: str) -> List[Conversation]:
        from sqlalchemy import or_, func
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.organization_id == org_id,
                or_(
                    Conversation.customer_phone_number.ilike(f"%{search_term}%"),
                    Conversation.customer_name.ilike(f"%{search_term}%")
                )
            ).order_by(desc(Conversation.last_message_at))
        )
        return result.scalars().all()

    async def get_with_messages(self, conv_id: UUID, limit: int = 50) -> Optional[Conversation]:
        result = await self.session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            # Load messages
            msg_result = await self.session.execute(
                select(Message).where(Message.conversation_id == conv_id)
                .order_by(desc(Message.created_at)).limit(limit)
            )
            conv.messages = list(reversed(msg_result.scalars().all()))
        return conv

class MessageRepository(BaseRepository[Message]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Message)

    async def get_by_conversation(self, conv_id: UUID, limit: int = 50, offset: int = 0) -> List[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.sort_timestamp.asc(), Message.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
class TagRepository(BaseRepository[Tag]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Tag)

    async def get_by_org_id(self, org_id: UUID) -> List[Tag]:
        result = await self.session.execute(
            select(Tag).where(Tag.organization_id == org_id)
        )
        return result.scalars().all()

    async def get_by_whatsapp_message_id(self, wamid: str) -> Optional[Message]:
        stmt = select(Message).where(Message.whatsapp_message_id == wamid)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

class ConversationTagRepository(BaseRepository[ConversationTag]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ConversationTag)

    async def get_by_conversation(self, conv_id: UUID) -> List[ConversationTag]:
        result = await self.session.execute(
            select(ConversationTag).where(ConversationTag.conversation_id == conv_id)
        )
        return result.scalars().all()

class ConversationNoteRepository(BaseRepository[ConversationNote]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ConversationNote)

    async def get_by_conversation(self, conv_id: UUID) -> List[ConversationNote]:
        result = await self.session.execute(
            select(ConversationNote).where(ConversationNote.conversation_id == conv_id)
            .order_by(desc(ConversationNote.created_at))
        )
        return result.scalars().all()

