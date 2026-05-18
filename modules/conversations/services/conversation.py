# modules/conversations/services/conversation.py
import asyncio
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete as sql_delete

from modules.common.models import Conversation, Message, Tag, ConversationTag, ConversationNote, Organization, User
from modules.common.logger import get_logger
from modules.common.masking import MaskingConfig, mask_phone_number
from modules.common.audit import AuditService
from modules.message.sender import get_whatsapp_config, WhatsAppService
from ..repositories import ConversationRepository, MessageRepository, TagRepository, ConversationTagRepository, ConversationNoteRepository
from ..utils import get_media_type_and_limit

logger = get_logger(__name__)

# ========== BACKGROUND MEDIA DELIVERY (unchanged) ==========
async def _background_media_delivery(
    message_id: UUID,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    caption: str,
    org_id: UUID
):
    """Background media delivery using a fresh database session."""
    try:
        from modules.common.database import AsyncSessionLocal
    except ImportError:
        logger.error("AsyncSessionLocal not found in modules.common.database")
        return

    from modules.message.sender import get_whatsapp_config, WhatsAppService
    from modules.conversations.repositories import MessageRepository, ConversationRepository

    max_attempts = 3

    async with AsyncSessionLocal() as session:
        msg_repo = MessageRepository(session)
        conv_repo = ConversationRepository(session)

        message = await msg_repo.get_by_id(message_id)
        if not message:
            logger.error(f"Message {message_id} not found for media delivery")
            return

        logger.info(f"Starting media delivery for message {message_id}")

        whatsapp_config = await get_whatsapp_config(str(org_id))
        if not whatsapp_config:
            logger.error(f"No WhatsApp config for org {org_id}")
            message.status = 'failed'
            await session.commit()
            return

        service = WhatsAppService(
            whatsapp_config['access_token'],
            whatsapp_config['phone_number_id']
        )

        conv = await conv_repo.get_by_id(message.conversation_id)
        if not conv:
            logger.error(f"Conversation {message.conversation_id} not found")
            message.status = 'failed'
            await session.commit()
            return

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Attempt {attempt}: Uploading media to WhatsApp...")
                media_id = await service.upload_media(filename, content_type, file_bytes)
                logger.info(f"Media uploaded, media_id={media_id}")

                logger.info(f"Attempt {attempt}: Sending media message...")
                success, wamid = await service.send_media_message(
                    to_number=conv.customer_phone_number,
                    media_id=media_id,
                    media_type=message.message_type,
                    caption=caption
                )
                if success:
                    logger.info(f"Media message sent, wamid={wamid}")
                    message.status = 'sent'
                    message.whatsapp_message_id = wamid
                    message.media_whatsapp_id = media_id
                    message.retry_count = attempt - 1
                    await session.commit()
                    return
                logger.error(f"WhatsApp send returned false on attempt {attempt}")
            except Exception as exc:
                logger.error(f"Attempt {attempt} failed: {exc}")
                message.retry_count = attempt
                await session.commit()
                await asyncio.sleep(2 ** attempt)

        logger.error(f"Media delivery failed after {max_attempts} attempts")
        message.status = 'failed'
        await session.commit()


# ========== CONVERSATION SERVICE ==========
class ConversationService:
    def __init__(self, session: AsyncSession, audit_service: Optional[AuditService] = None):
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.tag_repo = TagRepository(session)
        self.conv_tag_repo = ConversationTagRepository(session)
        self.note_repo = ConversationNoteRepository(session)
        self.audit = audit_service

    # ---------- Helper to get conversations based on role ----------
    async def _get_conversations_for_user(self, org_id: UUID, user_id: UUID, user_role: str) -> List[Conversation]:
        """Return list of conversations the user is allowed to see."""
        if user_role == 'org_admin':
            # Org admin sees all conversations in the organization
            return await self.conv_repo.get_by_org_id(org_id)
        else:
            # Agent or viewer sees only conversations assigned to them
            return await self.conv_repo.get_by_agent_id(org_id, user_id)

    # ---------- List conversations (with role‑based filtering) ----------
    async def list_conversations(self, org_id: UUID, user_id: UUID, user_role: str) -> List[Dict[str, Any]]:
        conversations = await self._get_conversations_for_user(org_id, user_id, user_role)

        # Get organization for masking
        org_result = await self.session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        masking_config = MaskingConfig.from_dict(org.settings or {}) if org else MaskingConfig()

        # Fetch agent names for those who are assigned
        agent_ids = {c.assigned_agent_id for c in conversations if c.assigned_agent_id}
        agent_names: Dict[UUID, str] = {}
        if agent_ids:
            agents_result = await self.session.execute(select(User).where(User.id.in_(agent_ids)))
            for ag in agents_result.scalars().all():
                agent_names[ag.id] = ag.full_name or ag.email or str(ag.id)

        output = []
        for conv in conversations:
            # Get last message
            last_msgs = await self.msg_repo.get_by_conversation(conv.id, limit=1)
            last_msg = last_msgs[0] if last_msgs else None
            last_msg_data = None
            if last_msg:
                last_msg_data = {
                    "id": str(last_msg.id),
                    "text": last_msg.content,
                    "sender_type": last_msg.direction,
                    "created_at": last_msg.created_at.isoformat(),
                    "status": last_msg.status,
                    "message_type": last_msg.message_type,
                }

            conv_data = {
                "id": str(conv.id),
                "customer_phone_number": conv.customer_phone_number,
                "customer_name": conv.customer_name,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                "assigned_agent_id": str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
                "assigned_agent_name": agent_names.get(conv.assigned_agent_id) if conv.assigned_agent_id else None,
                "reply_mode": conv.reply_mode,
                "status": conv.status,
                "last_message": last_msg_data,
            }
            if masking_config.mask_phone and conv_data["customer_phone_number"]:
                conv_data["customer_phone_number"] = mask_phone_number(
                    conv_data["customer_phone_number"],
                    partial=masking_config.phone_partial,
                )
            output.append(conv_data)

        return output

    # ---------- Get conversation messages (no role filter beyond ownership) ----------
    async def get_conversation_messages(
        self,
        conv_id: UUID,
        org_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        messages = await self.msg_repo.get_by_conversation(
            conv_id, limit=limit, offset=offset
        )
        return [
            {
                "id": str(msg.id),
                "text": msg.content,
                "sender_type": msg.direction,
                "created_at": msg.created_at.isoformat(),
                "status": msg.status,
                "message_type": msg.message_type,
                "media_url": msg.media_url,
                "media_file_name": msg.media_file_name,
                "media_content_type": msg.media_content_type,
                "whatsapp_message_id": msg.whatsapp_message_id,
            }
            for msg in messages
        ]

    # ---------- Send message (only assigned agent or org_admin) ----------
    async def send_message(
        self,
        conv_id: UUID,
        text: str,
        org_id: UUID,
        user_id: UUID,
        user_role: str
    ) -> Dict[str, Any]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        # Permission check: only org_admin or the assigned agent can reply
        if user_role != 'org_admin' and conv.assigned_agent_id != user_id:
            raise PermissionError("You are not assigned to this conversation")

        message = Message(
            conversation_id=conv_id,
            content=text,
            direction="outbound",
            message_type="text",
            is_ai_generated=False,
            human_agent_id=user_id,
            status="sent",
            created_at=datetime.utcnow()
        )
        message = await self.msg_repo.create(message)

        conv.last_message_at = datetime.utcnow()
        await self.session.commit()

        whatsapp_config = await get_whatsapp_config(str(org_id))
        if whatsapp_config:
            service = WhatsAppService(
                whatsapp_config['access_token'],
                whatsapp_config['phone_number_id']
            )
            asyncio.create_task(
                self._send_whatsapp_text(conv.customer_phone_number, text, service, message.id)
            )

        return {
            "id": str(message.id),
            "text": message.content,
            "sender_type": message.direction,
            "created_at": message.created_at.isoformat(),
            "status": message.status,
            "message_type": message.message_type,
            "whatsapp_message_id": message.whatsapp_message_id,
        }

    async def _send_whatsapp_text(self, to_number: str, text: str, service: WhatsAppService, message_id: UUID):
        try:
            success, wamid = await service.send_text_message(to_number, text)
            message = await self.msg_repo.get_by_id(message_id)
            if message:
                if success:
                    message.status = "sent"
                    message.whatsapp_message_id = wamid
                else:
                    message.status = "failed"
                await self.session.commit()
        except Exception as e:
            logger.error(f"Error sending WhatsApp text: {e}")

    async def upload_media(
        self,
        conv_id: UUID,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        file_size: int,
        caption: Optional[str],
        org_id: UUID,
        user_id: UUID
    ) -> Dict[str, Any]:
        logger.info(f"ConversationService.upload_media called: conv_id={conv_id}, filename={filename}, size={file_size}, content_type={content_type}")
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            logger.error(f"Conversation not found or access denied: conv_id={conv_id}, org_id={org_id}")
            raise ValueError("Conversation not found or access denied")

        media_type, max_size = get_media_type_and_limit(content_type, filename)
        if not media_type:
            logger.error(f"Unsupported media type: content_type={content_type}, filename={filename}")
            raise ValueError("Unsupported media type")
        if file_size > max_size:
            logger.error(f"File too large: size={file_size}, max={max_size}")
            raise ValueError(f"File too large. Max size for {media_type}: {max_size} bytes")

        # Create message record
        message = Message(
            conversation_id=conv_id,
            organization_id=org_id,
            content=caption or "",
            direction="outbound",
            message_type=media_type,
            media_file_name=filename,
            media_content_type=content_type,
            media_file_size=file_size,
            is_ai_generated=False,
            human_agent_id=user_id,
            status="sending",
            created_at=datetime.utcnow()
        )
        message = await self.msg_repo.create(message)
        await self.msg_repo.update(
            message.id,
            media_url=f"/api/conversations/media/{message.id}"
        )
        logger.info(f"Created outbound media message {message.id} for conversation {conv_id}")

        # Launch background delivery
        asyncio.create_task(
            _background_media_delivery(
                message.id,
                file_bytes,
                filename,
                content_type,
                caption or "",
                org_id
            )
        )
        return {
            "id": str(message.id),
            "status": "sending",
            "message_type": media_type,
        }

    # ---------- Agent assignment (only org_admin should call, but no role check here) ----------
    async def assign_agent(self, conv_id: UUID, agent_id: UUID, org_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        agent_result = await self.session.execute(
            select(User).where(User.id == agent_id, User.organization_id == org_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise ValueError("Agent not found or access denied")

        conv.assigned_agent_id = agent_id
        await self.session.commit()
        return True

    async def unassign_agent(self, conv_id: UUID, org_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        conv.assigned_agent_id = None
        await self.session.commit()
        return True

    async def toggle_mode(self, conv_id: UUID, mode: str, org_id: UUID) -> bool:
        if mode not in ['ai', 'rule', 'human']:
            raise ValueError("Invalid mode")

        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        conv.reply_mode = mode
        await self.session.commit()
        return True

    # ---------- Notes ----------
    async def add_note(self, conv_id: UUID, note: str, org_id: UUID, user_id: UUID) -> Dict[str, Any]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        conv_note = ConversationNote(
            conversation_id=conv_id,
            note=note,
            agent_id=user_id,
        )
        conv_note = await self.note_repo.create(conv_note)

        return {
            "id": str(conv_note.id),
            "note": conv_note.note,
            "created_at": conv_note.created_at.isoformat(),
            "created_by": str(conv_note.agent_id) if conv_note.agent_id else None,
        }

    async def get_notes(self, conv_id: UUID, org_id: UUID) -> List[Dict[str, Any]]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        notes = await self.note_repo.get_by_conversation(conv_id)
        return [
            {
                "id": str(note.id),
                "note": note.note,
                "created_at": note.created_at.isoformat(),
                "created_by": str(note.agent_id) if note.agent_id else None,
            }
            for note in notes
        ]

    # ---------- Tags ----------
    async def create_tag(self, name: str, color: str, org_id: UUID) -> Dict[str, Any]:
        tag = Tag(
            name=name,
            color=color,
            organization_id=org_id
        )
        tag = await self.tag_repo.create(tag)
        return {
            "id": str(tag.id),
            "name": tag.name,
            "color": tag.color,
        }

    async def list_tags(self, org_id: UUID) -> List[Dict[str, Any]]:
        tags = await self.tag_repo.get_by_org_id(org_id)
        return [
            {
                "id": str(tag.id),
                "name": tag.name,
                "color": tag.color,
            }
            for tag in tags
        ]

    async def attach_tag(self, conv_id: UUID, tag_id: UUID, org_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag or tag.organization_id != org_id:
            raise ValueError("Tag not found or access denied")

        existing = await self.conv_tag_repo.get_by_conversation(conv_id)
        if any(ct.tag_id == tag_id for ct in existing):
            return True

        conv_tag = ConversationTag(conversation_id=conv_id, tag_id=tag_id)
        await self.conv_tag_repo.create(conv_tag)
        return True

    async def detach_tag(self, conv_id: UUID, tag_id: UUID, org_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        existing = await self.conv_tag_repo.get_by_conversation(conv_id)
        for ct in existing:
            if ct.tag_id == tag_id:
                await self.session.execute(
                    sql_delete(ConversationTag).where(
                        ConversationTag.conversation_id == conv_id,
                        ConversationTag.tag_id == tag_id,
                    )
                )
                await self.session.commit()
                return True
        return False

    # ---------- Conversation creation / search (with role‑based filtering) ----------
    async def create_or_get_conversation(self, phone_number: str, org_id: UUID) -> Dict[str, Any]:
        existing = await self.conv_repo.get_by_phone_and_org(phone_number, org_id)
        if existing:
            return {
                "id": str(existing.id),
                "customer_phone_number": existing.customer_phone_number,
                "customer_name": existing.customer_name,
                "last_message_at": existing.last_message_at.isoformat() if existing.last_message_at else None,
                "assigned_agent_id": str(existing.assigned_agent_id) if existing.assigned_agent_id else None,
                "reply_mode": existing.reply_mode,
                "status": existing.status,
            }

        conv = Conversation(
            customer_phone_number=phone_number,
            organization_id=org_id,
            reply_mode="human",
            status="active",
            last_message_at=datetime.utcnow()
        )
        conv = await self.conv_repo.create(conv)

        return {
            "id": str(conv.id),
            "customer_phone_number": conv.customer_phone_number,
            "customer_name": conv.customer_name,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            "assigned_agent_id": str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
            "reply_mode": conv.reply_mode,
            "status": conv.status,
        }

    async def search_conversations(self, org_id: UUID, search_term: str, user_id: UUID, user_role: str) -> List[Dict[str, Any]]:
        # First get the allowed conversations (based on role)
        allowed_conversations = await self._get_conversations_for_user(org_id, user_id, user_role)
        if not allowed_conversations:
            return []
        allowed_ids = [c.id for c in allowed_conversations]
        # Now search within those IDs
        conversations = await self.conv_repo.search_by_phone_or_name(org_id, search_term)
        conversations = [c for c in conversations if c.id in allowed_ids]

        org_result = await self.session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        masking_config = MaskingConfig.from_dict(org.settings or {}) if org else MaskingConfig()

        agent_ids = {c.assigned_agent_id for c in conversations if c.assigned_agent_id}
        agent_names: Dict[UUID, str] = {}
        if agent_ids:
            agents_result = await self.session.execute(select(User).where(User.id.in_(agent_ids)))
            for ag in agents_result.scalars().all():
                agent_names[ag.id] = ag.full_name or ag.email or str(ag.id)

        output = []
        for conv in conversations:
            last_msgs = await self.msg_repo.get_by_conversation(conv.id, limit=1)
            last_msg = last_msgs[0] if last_msgs else None
            last_msg_data = None
            if last_msg:
                last_msg_data = {
                    "id": str(last_msg.id),
                    "text": last_msg.content,
                    "sender_type": last_msg.direction,
                    "created_at": last_msg.created_at.isoformat(),
                    "status": last_msg.status,
                    "message_type": last_msg.message_type,
                }

            conv_data = {
                "id": str(conv.id),
                "customer_phone_number": conv.customer_phone_number,
                "customer_name": conv.customer_name,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                "assigned_agent_id": str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
                "assigned_agent_name": agent_names.get(conv.assigned_agent_id) if conv.assigned_agent_id else None,
                "reply_mode": conv.reply_mode,
                "status": conv.status,
                "last_message": last_msg_data,
            }
            if masking_config.mask_phone and conv_data["customer_phone_number"]:
                conv_data["customer_phone_number"] = mask_phone_number(
                    conv_data["customer_phone_number"],
                    partial=masking_config.phone_partial,
                )
            output.append(conv_data)

        return output

    async def get_conversation_tags(self, conv_id: UUID, org_id: UUID) -> List[Dict[str, Any]]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")

        conv_tags = await self.conv_tag_repo.get_by_conversation(conv_id)
        tags = []
        for ct in conv_tags:
            tag = await self.tag_repo.get_by_id(ct.tag_id)
            if tag:
                tags.append({
                    "id": str(tag.id),
                    "name": tag.name,
                    "color": tag.color,
                })
        return tags