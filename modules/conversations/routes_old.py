import asyncio
import io
import httpx
import uuid

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from modules.common.database import AsyncSessionLocal, get_db
from modules.common.models import User, Conversation, Message, Tag, ConversationTag, ConversationNote, Organization
from modules.auth.jwt import get_current_user
from modules.common.logger import get_logger
from modules.common.masking import MaskingConfig, apply_masking_to_dict
from modules.message.sender import send_whatsapp_text, get_whatsapp_config

logger = get_logger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["Conversations"])

# ---------- Schemas ----------
class MessageCreate(BaseModel):
    text: str
    sender_type: str  # 'agent'

class NoteCreate(BaseModel):
    note: str

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = "#4F46E5"

class AssignAgentRequest(BaseModel):
    agent_id: UUID

# ---------- WhatsApp Media Helpers ----------
DOCUMENT_MIME_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain'
}

MAX_ATTACHMENT_SIZES = {
    'image': 5 * 1024 * 1024,
    'video': 16 * 1024 * 1024,
    'audio': 10 * 1024 * 1024,
    'document': 100 * 1024 * 1024,
}

async def upload_media_to_whatsapp(
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    org_whatsapp_token: str,
    org_phone_number_id: str
) -> str:
    """
    Uploads a file (image/video/audio/document) to WhatsApp Cloud API.
    Returns the media ID that can be used to send the message.
    """
    files = {
        'file': (file_name, file_bytes, content_type)
    }
    headers = {
        'Authorization': f'Bearer {org_whatsapp_token}'
    }
    url = f"https://graph.facebook.com/v17.0/{org_phone_number_id}/media"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, files=files, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data['id']  # media ID

async def send_whatsapp_media(
    to_number: str,
    media_id: str,
    media_type: str,  # 'image', 'video', 'document', 'audio'
    caption: Optional[str],
    org_whatsapp_token: str,
    org_phone_number_id: str
) -> tuple[bool, Optional[str]]:
    """
    Sends a media message via WhatsApp Cloud API.
    Returns (success, whatsapp_message_id).
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": media_type,
    }
    if media_type == "image":
        payload["image"] = {"id": media_id}
        if caption:
            payload["image"]["caption"] = caption
    elif media_type == "video":
        payload["video"] = {"id": media_id}
        if caption:
            payload["video"]["caption"] = caption
    elif media_type == "audio":
        payload["audio"] = {"id": media_id}
        if caption:
            payload["audio"]["caption"] = caption
    elif media_type == "document":
        payload["document"] = {"id": media_id}
        if caption:
            payload["document"]["caption"] = caption
    else:
        return False, None

    headers = {
        "Authorization": f"Bearer {org_whatsapp_token}",
        "Content-Type": "application/json"
    }
    url = f"https://graph.facebook.com/v17.0/{org_phone_number_id}/messages"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code in (200, 201):
            data = response.json()
            wamid = data.get('messages', [{}])[0].get('id')
            return True, wamid
        logger.error(f"WhatsApp media send failed: {response.status_code} {response.text}")
        return False, None

async def _get_media_type_and_limit(content_type: str, filename: str = ''):
    if content_type.startswith('image/'):
        return 'image', MAX_ATTACHMENT_SIZES['image']
    if content_type.startswith('video/'):
        return 'video', MAX_ATTACHMENT_SIZES['video']
    if content_type.startswith('audio/'):
        return 'audio', MAX_ATTACHMENT_SIZES['audio']
    if content_type in DOCUMENT_MIME_TYPES:
        return 'document', MAX_ATTACHMENT_SIZES['document']

    if not content_type and filename:
        ext = filename.lower().rsplit('.', 1)[-1]
        if ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt'):
            return 'document', MAX_ATTACHMENT_SIZES['document']
        if ext in ('mp3', 'wav', 'm4a', 'ogg', 'aac'):
            return 'audio', MAX_ATTACHMENT_SIZES['audio']
        if ext in ('mp4', 'mov', 'webm'):
            return 'video', MAX_ATTACHMENT_SIZES['video']
        if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
            return 'image', MAX_ATTACHMENT_SIZES['image']

    return None, None

async def _stream_whatsapp_media(message_id: UUID, org_id: UUID, db: AsyncSession):
    message = await db.execute(
        select(Message).where(
            Message.id == message_id
        ).join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.organization_id == org_id)
    )
    message = message.scalar_one_or_none()
    if not message or not message.media_whatsapp_id:
        raise HTTPException(404, "Media not found")

    whatsapp_config = await get_whatsapp_config(str(org_id))
    if not whatsapp_config:
        raise HTTPException(400, "WhatsApp configuration missing")

    access_token = whatsapp_config.get('access_token')
    if not access_token:
        raise HTTPException(400, "WhatsApp access token missing")

    async with httpx.AsyncClient(timeout=60.0) as client:
        metadata_resp = await client.get(
            f"https://graph.facebook.com/v17.0/{message.media_whatsapp_id}",
            params={"fields": "url"},
            headers={"Authorization": f"Bearer {access_token}"}
        )
        metadata_resp.raise_for_status()
        media_url = metadata_resp.json().get('url')
        if not media_url:
            raise HTTPException(404, "Media download URL unavailable")

        file_resp = await client.get(media_url, timeout=60.0)
        file_resp.raise_for_status()
        return StreamingResponse(
            io.BytesIO(file_resp.content),
            media_type=message.media_content_type or file_resp.headers.get('Content-Type', 'application/octet-stream'),
            headers={
                'Content-Disposition': f'inline; filename="{message.media_file_name or message.id}.bin"'
            }
        )

async def _process_media_delivery(
    message_id: UUID,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    file_size: int,
    caption: str,
    org_id: UUID,
    conv_id: UUID
):
    max_attempts = 3
    async with AsyncSessionLocal() as session:
        message = await session.execute(
            select(Message).where(Message.id == message_id)
        )
        message = message.scalar_one_or_none()
        if not message:
            logger.error(f"Queued media message {message_id} missing")
            return

        whatsapp_config = await get_whatsapp_config(str(org_id))
        if not whatsapp_config:
            message.status = 'failed'
            message.retry_count = max_attempts
            await session.commit()
            return

        access_token = whatsapp_config.get('access_token')
        phone_number_id = whatsapp_config.get('phone_number_id')
        if not access_token or not phone_number_id:
            message.status = 'failed'
            message.retry_count = max_attempts
            await session.commit()
            return

        conversation = await session.execute(
            select(Conversation).where(Conversation.id == message.conversation_id)
        )
        conversation = conversation.scalar_one_or_none()
        if not conversation:
            logger.error(f"Conversation for queued media message {message_id} missing")
            message.status = 'failed'
            await session.commit()
            return

        media_id = None
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                media_id = await upload_media_to_whatsapp(filename, content_type, file_bytes, access_token, phone_number_id)
                success, wamid = await send_whatsapp_media(
                    to_number=conversation.customer_phone_number,
                    media_id=media_id,
                    media_type=message.message_type,
                    caption=caption,
                    org_whatsapp_token=access_token,
                    org_phone_number_id=phone_number_id
                )
                if success:
                    message.status = 'sent'
                    message.whatsapp_message_id = wamid
                    message.media_whatsapp_id = media_id
                    message.retry_count = attempt - 1
                    await session.commit()
                    return
                last_error = f"WhatsApp send returned false on attempt {attempt}"
            except Exception as exc:
                last_error = str(exc)
                message.retry_count = attempt
                await session.commit()
                await asyncio.sleep(2 ** attempt)

        message.status = 'failed'
        await session.commit()
        logger.error(f"Media delivery failed after {max_attempts} attempts for message {message_id}: {last_error}")

# ---------- Conversation List ----------
@router.get("")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    stmt = select(Conversation).where(Conversation.organization_id == org_id)
    stmt = stmt.order_by(Conversation.last_message_at.desc())
    result = await db.execute(stmt)
    convs = result.scalars().all()
    
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one_or_none()
    masking_config = MaskingConfig.from_dict(org.settings or {}) if org else MaskingConfig()
    
    output = []
    for c in convs:
        last_msg_result = await db.execute(
            select(Message).where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc()).limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()
        
        assigned_name = None
        if c.assigned_agent_id:
            agent_res = await db.execute(select(User.full_name).where(User.id == c.assigned_agent_id))
            assigned_name = agent_res.scalar_one_or_none()
        
        conv_data = {
            "id": c.id,
            "customer_phone_number": c.customer_phone_number,
            "customer_name": c.customer_name or "",
            "last_message": last_msg.content if last_msg else None,
            "last_message_at": c.last_message_at,
            "status": c.status,
            "lead_score": c.lead_score,
            "reply_mode": c.reply_mode,
            "unread_count": 0,
            "assigned_agent_id": c.assigned_agent_id,
            "assigned_agent_name": assigned_name or "Unassigned"
        }
        
        masked_data = apply_masking_to_dict(
            conv_data,
            role,
            masking_config,
            phone_fields=["customer_phone_number"],
            email_fields=[]
        )
        output.append(masked_data)
    
    return output

# ---------- Messages ----------
@router.get("/{conv_id}/messages")
async def get_messages(
    conv_id: UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == org_id
        )
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(404, "Conversation not found")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return list(reversed(messages))

# ---------- Send text message ----------
@router.post("/{conv_id}/send")
async def send_message(
    conv_id: UUID,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    org_id = current_user.get("org_id")
    
    if role not in ["org_admin", "agent"]:
        raise HTTPException(403, "Only admins and agents can send messages")
    
    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == org_id
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    
    if role == "org_admin":
        pass
    elif role == "agent":
        if str(conv.assigned_agent_id) != user_id:
            raise HTTPException(403, f"You are not assigned to this conversation")
        if conv.assigned_agent_id is None:
            conv.assigned_agent_id = user_id
            conv.reply_mode = 'human'
            await db.commit()
    else:
        raise HTTPException(403, "Insufficient permissions")
    
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        direction="outbound",
        message_type="text",
        content=data.text,
        is_ai_generated=False,
        human_agent_id=user_id,
        status="sent",
        created_at=datetime.utcnow()
    )
    db.add(msg)
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conv_id)
        .values(last_message_at=datetime.utcnow())
    )
    await db.commit()
    
    success, wamid = await send_whatsapp_text(
        to_number=conv.customer_phone_number,
        text=data.text,
        org_id=str(conv.organization_id)
    )
    if success:
        msg.whatsapp_message_id = wamid
        await db.commit()
    
    if not success:
        logger.error(f"Failed to send WhatsApp message to {conv.customer_phone_number}")
    
    return {"status": "sent", "message_id": msg.id}

# ---------- Notes ----------
@router.get("/{conv_id}/notes")
async def get_notes(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stmt = select(ConversationNote).where(ConversationNote.conversation_id == conv_id).order_by(ConversationNote.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/{conv_id}/notes")
async def add_note(
    conv_id: UUID,
    data: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    note = ConversationNote(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        agent_id=current_user.get("user_id"),
        note=data.note,
        created_at=datetime.utcnow()
    )
    db.add(note)
    await db.commit()
    return note

@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    await db.execute(delete(ConversationNote).where(ConversationNote.id == note_id))
    await db.commit()
    return {"status": "deleted"}

# ---------- Tags ----------
@router.get("/tags")
async def list_tags(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stmt = select(Tag).where(Tag.organization_id == current_user["org_id"]).order_by(Tag.name)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/tags")
async def create_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    tag = Tag(
        id=uuid.uuid4(),
        organization_id=current_user["org_id"],
        name=data.name,
        color=data.color
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag

@router.get("/{conv_id}/tags")
async def get_conv_tags(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stmt = select(Tag).join(ConversationTag).where(ConversationTag.conversation_id == conv_id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/{conv_id}/tags/{tag_id}")
async def attach_tag(
    conv_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    tag = await db.execute(select(Tag).where(Tag.id == tag_id, Tag.organization_id == current_user["org_id"]))
    if not tag.scalar_one_or_none():
        raise HTTPException(404, "Tag not found")
    ct = ConversationTag(conversation_id=conv_id, tag_id=tag_id)
    db.add(ct)
    await db.commit()
    return {"status": "attached"}

@router.delete("/{conv_id}/tags/{tag_id}")
async def detach_tag(
    conv_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    await db.execute(
        delete(ConversationTag).where(
            ConversationTag.conversation_id == conv_id,
            ConversationTag.tag_id == tag_id
        )
    )
    await db.commit()
    return {"status": "detached"}

# ---------- Agent Assignment ----------
@router.post("/{conv_id}/assign")
async def assign_agent(
    conv_id: UUID,
    req: AssignAgentRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "org_admin":
        raise HTTPException(403, "Only organization admin can assign agents")
    
    agent = await db.execute(
        select(User).where(
            User.id == req.agent_id,
            User.role == "agent",
            User.organization_id == current_user["org_id"]
        )
    )
    agent = agent.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found in this organization")
    
    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == current_user["org_id"]
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    
    conv.assigned_agent_id = req.agent_id
    conv.reply_mode = 'human'
    await db.commit()
    return {"status": "assigned", "agent_id": req.agent_id}

@router.post("/{conv_id}/unassign")
async def unassign_agent(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "org_admin":
        raise HTTPException(403, "Only organization admin can unassign agents")
    
    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == current_user["org_id"]
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    
    conv.assigned_agent_id = None
    await db.commit()
    return {"status": "unassigned"}

@router.get("/agents")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.get("role") != "org_admin":
        raise HTTPException(403, "Only organization admin can list agents")
    result = await db.execute(
        select(User).where(
            User.organization_id == current_user["org_id"],
            User.role == "agent"
        )
    )
    agents = result.scalars().all()
    return [{"id": a.id, "full_name": a.full_name or a.email} for a in agents]

# ---------- Mode Toggle ----------
@router.patch("/{conv_id}/mode")
async def toggle_mode(
    conv_id: UUID,
    mode: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    role = current_user.get("role")
    if role != "org_admin":
        raise HTTPException(403, "Only organization admin can change conversation mode")
    
    if mode not in ('ai', 'human', 'rule'):
        raise HTTPException(400, "Mode must be 'ai', 'human', or 'rule'")
    await db.execute(
        update(Conversation).where(Conversation.id == conv_id).values(reply_mode=mode)
    )
    await db.commit()
    return {"reply_mode": mode}

# ---------- Media Proxy ----------
@router.get("/media/{message_id}")
async def fetch_message_media(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    return await _stream_whatsapp_media(message_id, org_id, db)

# ---------- Send Media Message ----------
@router.post("/{conv_id}/send-media")
async def send_media_message(
    conv_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    caption: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    logger.info(f"send-media called: conv_id={conv_id}, filename={file.filename}, caption={caption[:50]}")
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    org_id = current_user.get("org_id")

    if role not in ["org_admin", "agent"]:
        raise HTTPException(403, "Only admins and agents can send media")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == org_id
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    if role == "agent" and str(conv.assigned_agent_id) != user_id:
        raise HTTPException(403, "Not assigned to this conversation")
    if role == "agent" and conv.assigned_agent_id is None:
        conv.assigned_agent_id = user_id
        conv.reply_mode = 'human'
        await db.commit()

    content_type = file.content_type or ''
    media_type, max_size = await _get_media_type_and_limit(content_type, file.filename)
    if not media_type:
        raise HTTPException(400, f"Unsupported file type: {content_type}")

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > max_size:
        raise HTTPException(413, f"File too large: {file_size} bytes, max {max_size} bytes")

    file_bytes = await file.read()

    whatsapp_config = await get_whatsapp_config(str(org_id))
    if not whatsapp_config:
        logger.error(f"No WhatsApp config for org {org_id}")
        raise HTTPException(400, "No active WhatsApp channel configured")

    access_token = whatsapp_config.get("access_token")
    phone_number_id = whatsapp_config.get("phone_number_id")
    if not access_token or not phone_number_id:
        logger.error(f"Incomplete config for org {org_id}: token={bool(access_token)}, phone_id={bool(phone_number_id)}")
        raise HTTPException(400, "Incomplete WhatsApp configuration")

    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        direction="outbound",
        message_type=media_type,
        content=caption,
        media_url=f"/api/conversations/media/{uuid.uuid4()}",
        media_content_type=content_type,
        media_file_name=file.filename,
        media_file_size=file_size,
        retry_count=0,
        is_ai_generated=False,
        human_agent_id=user_id,
        status="queued",
        created_at=datetime.utcnow()
    )
    db.add(msg)
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conv_id)
        .values(last_message_at=datetime.utcnow())
    )
    await db.commit()
    await db.refresh(msg)

    msg.media_url = f"/api/conversations/media/{msg.id}"
    await db.commit()

    background_tasks.add_task(
        _process_media_delivery,
        msg.id,
        file_bytes,
        file.filename,
        content_type,
        file_size,
        caption,
        org_id,
        conv_id
    )

    return {
        "status": "queued",
        "message_id": msg.id,
        "media_type": media_type,
        "message_status": "queued"
    }
