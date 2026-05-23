import asyncio
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete as sql_delete, func, update

from modules.common.models import Conversation, Message, Tag, ConversationTag, ConversationNote, Organization, User, ConversationAssignmentHistory, Customer
from modules.common.logger import get_logger
from modules.common.masking import MaskingConfig, mask_phone_number
from modules.common.audit import AuditService
from modules.message.sender import get_whatsapp_config, WhatsAppService
from ..repositories import ConversationRepository, MessageRepository, TagRepository, ConversationTagRepository, ConversationNoteRepository
from ..utils import get_media_type_and_limit
from datetime import datetime, timedelta, timezone


logger = get_logger(__name__)

# ========== BACKGROUND MEDIA DELIVERY ==========
async def _background_media_delivery(
    message_id: UUID,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    caption: str,
    org_id: UUID
):
    # ... (keep your existing implementation, unchanged) ...
    pass  # I'll omit for brevity – you can keep yours

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
        if user_role == 'org_admin':
            return await self.conv_repo.get_by_org_id(org_id)
        else:
            return await self.conv_repo.get_by_agent_id(org_id, user_id)

    async def _compute_sla_status(self, conv: Conversation, org: Organization) -> tuple[str, int]:
        if not conv.last_customer_message_at:
            return "on_time", 0
        sla_minutes = getattr(org, 'sla_minutes', 60)
        due_time = conv.last_customer_message_at + timedelta(minutes=sla_minutes)
        now = datetime.now(timezone.utc)  # timezone‑aware
        minutes_left = int((due_time - now).total_seconds() / 60)
        if minutes_left < 0:
            return "breached", minutes_left
        return "on_time", minutes_left

    async def list_conversations(self, org_id: UUID, user_id: UUID, user_role: str, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        conversations = await self._get_conversations_for_user(org_id, user_id, user_role)

        org_result = await self.session.execute(select(Organization).where(Organization.id == org_id))
        org = org_result.scalar_one_or_none()
        masking_config = MaskingConfig.from_dict(org.settings or {}) if org else MaskingConfig()

        if filter_type == 'assigned_to_me':
            conversations = [c for c in conversations if c.assigned_agent_id == user_id]
        elif filter_type == 'unassigned':
            conversations = [c for c in conversations if c.assigned_agent_id is None]

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

            sla_status, minutes_left = "on_time", 0
            if org:
                sla_status, minutes_left = await self._compute_sla_status(conv, org)

            if filter_type == 'sla_breached' and sla_status != 'breached':
                continue

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
                "unread_count": conv.unread_count or 0,
                "last_customer_message_at": conv.last_customer_message_at.isoformat() if conv.last_customer_message_at else None,
                "custom_fields": conv.custom_fields or {},
                "sla_status": sla_status,
                "minutes_left": minutes_left,
            }
            if masking_config.mask_phone and conv_data["customer_phone_number"]:
                conv_data["customer_phone_number"] = mask_phone_number(
                    conv_data["customer_phone_number"],
                    partial=masking_config.phone_partial,
                )
            output.append(conv_data)
        return output

    # ---------- Get conversation messages ----------
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
        messages = await self.msg_repo.get_by_conversation(conv_id, limit=limit, offset=offset)
        return [
            {
                "id": str(msg.id),
                "text": msg.content,
                "sender_type": msg.direction,
                "direction": msg.direction, 
                "created_at": msg.created_at.isoformat(),
                "sort_timestamp": msg.sort_timestamp.isoformat() if msg.sort_timestamp else msg.created_at.isoformat(),
                "status": msg.status,
                "message_type": msg.message_type,
                "media_url": msg.media_url,
                "media_file_name": msg.media_file_name,
                "media_content_type": msg.media_content_type,
                "whatsapp_message_id": msg.whatsapp_message_id,
            }
            for msg in messages
        ]

    # ---------- Send message ----------
    async def send_message(self, conv_id: UUID, text: str, org_id: UUID, user_id: UUID, user_role: str) -> Dict[str, Any]:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")
        if user_role != 'org_admin' and conv.assigned_agent_id != user_id:
            raise PermissionError("You are not assigned to this conversation")
        
        # Create message with "sending" status and proper sort_timestamp
        sort_ts = datetime.now(timezone.utc)
        message = Message(
            conversation_id=conv_id,
            content=text,
            direction="outbound",
            message_type="text",
            is_ai_generated=False,
            human_agent_id=user_id,
            status="sending",  # START as sending (before API call)
            created_at=datetime.now(timezone.utc),
            sort_timestamp=sort_ts,  # Use current time as sort key
            whatsapp_timestamp=int(sort_ts.timestamp())
        )
        message = await self.msg_repo.create(message)
        conv.last_message_at = datetime.utcnow()
        conv.unread_count = 0
        await self.session.commit()
        
        # Send async and update message when response arrives
        whatsapp_config = await get_whatsapp_config(str(org_id))
        if whatsapp_config:
            service = WhatsAppService(whatsapp_config['access_token'], whatsapp_config['phone_number_id'])
            asyncio.create_task(self._send_whatsapp_text(conv.customer_phone_number, text, service, message.id))
        
        return {
            "id": str(message.id),
            "text": message.content,
            "sender_type": message.direction,
            "created_at": message.created_at.isoformat(),
            "sort_timestamp": message.sort_timestamp.isoformat() if message.sort_timestamp else None,
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
                # Broadcast message update via WebSocket
                from modules.websocket import manager
                manager.broadcast_message_update({
                    "type": "message_updated",
                    "conversation_id": str(message.conversation_id),
                    "message_id": str(message.id),
                    "status": message.status,
                    "whatsapp_message_id": wamid
                })
        except Exception as e:
            logger.error(f"Error sending WhatsApp text: {e}")

    # ---------- Upload media ----------
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
        # ... keep your existing implementation (unchanged) ...
        pass

    # ---------- Agent assignment (with history) ----------
    async def assign_agent(self, conv_id: UUID, agent_id: UUID, org_id: UUID, user_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")
        agent_result = await self.session.execute(select(User).where(User.id == agent_id, User.organization_id == org_id))
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise ValueError("Agent not found or access denied")
        history = ConversationAssignmentHistory(conversation_id=conv_id, assigned_to=agent_id, assigned_by=user_id)
        self.session.add(history)
        conv.assigned_agent_id = agent_id
        await self.session.commit()
        return True

    async def unassign_agent(self, conv_id: UUID, org_id: UUID, user_id: UUID) -> bool:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found or access denied")
        history = ConversationAssignmentHistory(conversation_id=conv_id, assigned_to=None, assigned_by=user_id)
        self.session.add(history)
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
        conv_note = ConversationNote(conversation_id=conv_id, note=note, agent_id=user_id)
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
        tag = Tag(name=name, color=color, organization_id=org_id)
        tag = await self.tag_repo.create(tag)
        return {"id": str(tag.id), "name": tag.name, "color": tag.color}

    async def list_tags(self, org_id: UUID) -> List[Dict[str, Any]]:
        tags = await self.tag_repo.get_by_org_id(org_id)
        return [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags]

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

    # ---------- Conversation creation / search ----------
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
            last_message_at=datetime.now(timezone.utc)
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
        allowed_conversations = await self._get_conversations_for_user(org_id, user_id, user_role)
        if not allowed_conversations:
            return []
        allowed_ids = [c.id for c in allowed_conversations]
        conversations = await self.conv_repo.search_by_phone_or_name(org_id, search_term)
        conversations = [c for c in conversations if c.id in allowed_ids]
        org_result = await self.session.execute(select(Organization).where(Organization.id == org_id))
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
                tags.append({"id": str(tag.id), "name": tag.name, "color": tag.color})
        return tags

    # ---------- NEW METHODS for DoubleTick UI ----------
    async def mark_conversation_read(self, conv_id: UUID, org_id: UUID) -> None:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found")
        conv.unread_count = 0
        await self.session.commit()

    async def get_assignment_history(self, conv_id: UUID, org_id: UUID) -> List[Dict[str, Any]]:
        stmt = select(ConversationAssignmentHistory).where(
            ConversationAssignmentHistory.conversation_id == conv_id
        ).order_by(ConversationAssignmentHistory.assigned_at.desc())
        result = await self.session.execute(stmt)
        history = result.scalars().all()
        return [
            {
                "id": str(h.id),
                "assigned_to": str(h.assigned_to) if h.assigned_to else None,
                "assigned_by": str(h.assigned_by) if h.assigned_by else None,
                "assigned_at": h.assigned_at.isoformat(),
            }
            for h in history
        ]

    async def update_conversation_custom_fields(self, conv_id: UUID, org_id: UUID, fields: Dict[str, Any]) -> None:
        conv = await self.conv_repo.get_by_id(conv_id)
        if not conv or conv.organization_id != org_id:
            raise ValueError("Conversation not found")
        current = conv.custom_fields or {}
        current.update(fields)
        conv.custom_fields = current
        await self.session.commit()

    async def update_customer_optin(self, cust_id: UUID, org_id: UUID, opt_in: bool) -> None:
        stmt = select(Customer).where(Customer.id == cust_id, Customer.organization_id == org_id)
        result = await self.session.execute(stmt)
        cust = result.scalar_one_or_none()
        if not cust:
            raise ValueError("Customer not found")
        cust.opt_in = opt_in
        await self.session.commit()

    async def get_conversation_counts(self, org_id: UUID, user_id: UUID, user_role: str) -> Dict[str, int]:
        conversations = await self._get_conversations_for_user(org_id, user_id, user_role)
        org_result = await self.session.execute(select(Organization).where(Organization.id == org_id))
        org = org_result.scalar_one_or_none()
        open_count = 0
        closed_count = 0
        unread_count = 0
        sla_breached_count = 0
        for conv in conversations:
            if conv.status == 'open':
                open_count += 1
            else:
                closed_count += 1
            if conv.unread_count and conv.unread_count > 0:
                unread_count += 1
            if org and conv.last_customer_message_at:
                sla_status, _ = await self._compute_sla_status(conv, org)
                if sla_status == 'breached':
                    sla_breached_count += 1
        return {
            "open": open_count,
            "closed": closed_count,
            "unread": unread_count,
            "sla_breached": sla_breached_count,
        }