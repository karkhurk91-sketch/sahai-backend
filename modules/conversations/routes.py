import asyncio
import io
import httpx
import uuid
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Body
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from modules.common.database import get_db
from modules.common.models import User, Organization, Conversation, Message, Customer
from modules.auth.jwt import get_current_user
from modules.common.logger import get_logger
from modules.common.audit import get_audit_service, AuditService
from modules.message.sender import WhatsAppService, get_whatsapp_config

from modules.conversations.services import ConversationService

from .schemas import MessageCreate, NoteCreate, TagCreate, AssignAgentRequest, ConversationModeUpdate
from .utils import get_media_type_and_limit

logger = get_logger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["Conversations"])

# ---------- Helper: Download and save media ----------
async def download_and_save_media(media_id: str, filename: str, mime_type: str, org_id: str, message_id: uuid.UUID) -> tuple[str, str]:
    config = await get_whatsapp_config(org_id)
    if not config:
        raise Exception("WhatsApp config missing")
    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
    media_url = await wa.get_media_url(media_id)
    if not media_url:
        raise Exception("No media URL")
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url, headers={"Authorization": f"Bearer {wa.access_token}"})
        if resp.status_code != 200:
            raise Exception(f"Download failed: {resp.status_code}")
        content = resp.content
    root_dir = Path(__file__).resolve().parents[2]
    media_dir = root_dir / "storage" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    ext = filename.split('.')[-1] if '.' in filename else 'bin'
    local_filename = f"{message_id}.{ext}"
    local_path = media_dir / local_filename
    with open(local_path, "wb") as f:
        f.write(content)
    local_url = f"/api/conversations/media/{local_filename}"
    return str(local_path), local_url

# ---------- Dependency Injections ----------
def get_conversation_service(
    db: Any = Depends(get_db),
    audit: Any = Depends(get_audit_service)
) -> ConversationService:
    return ConversationService(db, audit)

# WhatsApp official size limits
SIZE_LIMITS = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
}

# ---------- Local Media Serving Endpoint ----------
@router.get("/media/{filename}")
async def serve_local_media(filename: str):
    root_dir = Path(__file__).resolve().parents[2]
    file_path = root_dir / "storage" / "media" / filename
    if not file_path.exists():
        raise HTTPException(404, "Media not found")
    return FileResponse(file_path)

# ---------- Conversation Routes ----------
@router.get("", response_model=None)
async def list_conversations(
    filter: Optional[str] = Query(None, description="Filter: assigned_to_me, unassigned, sla_breached"),
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    user_role = current_user.get("role")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    # Build base query joining conversations with customers
    # Use func.replace to remove leading '+' from customer phone number
    stmt = select(
        Conversation,
        Customer.name.label("customer_name_from_customer"),
        Customer.phone_number.label("customer_phone_from_customer"),
        Customer.email.label("customer_email")
    ).outerjoin(
        Customer,
        and_(
            Conversation.organization_id == Customer.organization_id,
            func.replace(Customer.phone_number, '+', '') == Conversation.customer_phone_number,
            Customer.deleted_at.is_(None)   # ignore soft-deleted customers
        )
    ).where(Conversation.organization_id == UUID(org_id))

    # Apply filters
    if filter == "assigned_to_me":
        stmt = stmt.where(Conversation.assigned_agent_id == UUID(user_id))
    elif filter == "unassigned":
        stmt = stmt.where(Conversation.assigned_agent_id.is_(None))
    elif filter == "sla_breached":
        # SLA logic can be added later; for now ignore
        pass

    stmt = stmt.order_by(Conversation.last_message_at.desc())
    result = await db.execute(stmt)
    rows = result.all()

    # Build response list
    conversations_data = []
    for row in rows:
        conv = row.Conversation
        customer_name = row.customer_name_from_customer or conv.customer_name
        customer_phone = row.customer_phone_from_customer or conv.customer_phone_number
        customer_email = row.customer_email

        conv_dict = {
            "id": str(conv.id),
            "organization_id": str(conv.organization_id),
            "customer_phone_number": customer_phone,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "status": conv.status,
            "lead_score": conv.lead_score,
            "service": conv.service,
            "tags": conv.tags or [],
            "reply_mode": conv.reply_mode,
            "started_at": conv.started_at.isoformat() if conv.started_at else None,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            "closed_at": conv.closed_at.isoformat() if conv.closed_at else None,
            "assigned_agent_id": str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
            "unread_count": conv.unread_count,
            "last_customer_message_at": conv.last_customer_message_at.isoformat() if conv.last_customer_message_at else None,
            "custom_fields": conv.custom_fields,
            "conversation_stage": conv.conversation_stage,
            "completed_fields": conv.completed_fields,
            "booking_status": conv.booking_status,
            "recommendation_shown": conv.recommendation_shown,
            "last_intent": conv.last_intent,
        }
        conversations_data.append(conv_dict)

    return conversations_data

# ---------- Other endpoints unchanged (only import Customer added) ----------
@router.post("", response_model=None)
async def create_conversation(
    phone_number: str = Body(None, embed=True),
    phone_number_form: str = Form(None),
    current_user = Depends(get_current_user),
    service: Any = Depends(get_conversation_service)
) -> Any:
    phone_number = phone_number or phone_number_form
    if not phone_number:
        raise HTTPException(400, "Phone number is required")
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.create_or_get_conversation(phone_number, UUID(org_id))
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(500, "Internal server error")

@router.get("/search", response_model=None)
async def search_conversations(
    q: str = Query(..., description="Search term for phone number or customer name"),
    current_user = Depends(get_current_user),
    service: Any = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    user_role = current_user.get("role")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.search_conversations(UUID(org_id), q, UUID(user_id), user_role)
    except Exception as e:
        logger.error(f"Error searching conversations: {e}")
        raise HTTPException(500, "Internal server error")

@router.get("/{conv_id}/messages", response_model=None)
async def get_messages(
    conv_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user = Depends(get_current_user),
    service: Any = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.get_conversation_messages(
            conv_id, UUID(org_id), limit=limit, offset=offset
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/{conv_id}/messages", response_model=None)
async def send_message(
    conv_id: UUID,
    message: MessageCreate,
    current_user = Depends(get_current_user),
    service: Any = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    user_role = current_user.get("role")
    if not org_id or not user_id:
        raise HTTPException(403, "Authentication required")
    try:
        return await service.send_message(conv_id, message.text, UUID(org_id), UUID(user_id), user_role)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(500, "Internal server error")

# ==================== MEDIA UPLOAD ENDPOINT (unchanged) ====================
@router.post("/{conv_id}/media", response_model=None)
async def upload_media(
    conv_id: UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    logger.info(f"upload_media called for conv_id: {conv_id}, file: {file.filename}, size: {file.size}, caption: {caption}")
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    if not org_id or not user_id:
        logger.error("Authentication failed - missing org_id or user_id")
        raise HTTPException(403, "Authentication required")

    if not file.filename:
        raise HTTPException(400, "Filename missing")
    mime_type = file.content_type
    if not mime_type:
        raise HTTPException(400, "Content-Type missing")

    # Determine media category
    supported_mime_types = {
        "image": ["image/jpeg", "image/png", "image/webp"],
        "video": ["video/mp4", "video/3gpp"],
        "audio": ["audio/mpeg", "audio/aac", "audio/amr", "audio/ogg"],
        "document": ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     "text/plain", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
    }
    media_category = None
    for cat, mimes in supported_mime_types.items():
        if mime_type in mimes:
            media_category = cat
            break
    if not media_category:
        raise HTTPException(400, f"Unsupported MIME type: {mime_type}")

    size_limits = {"image": 5*1024*1024, "video": 16*1024*1024, "audio": 16*1024*1024, "document": 100*1024*1024}
    if file.size is None or file.size == 0:
        raise HTTPException(400, "Cannot determine file size")
    max_size = size_limits[media_category]
    if file.size > max_size:
        raise HTTPException(400, f"File too large: {file.size/(1024*1024):.1f}MB > {max_size/(1024*1024)}MB")

    if caption and media_category == "audio":
        raise HTTPException(400, "Captions are not allowed for audio messages")

    # Verify conversation
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == UUID(org_id)
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    whatsapp_config = await get_whatsapp_config(org_id)
    if not whatsapp_config:
        raise HTTPException(400, "WhatsApp configuration missing for this organization")

    # ------------------------------------------------------------------
    # 1. CREATE OPTIMISTIC MESSAGE (sending) WITH TIMESTAMPS
    # ------------------------------------------------------------------
    now_utc = datetime.now(timezone.utc)
    message_id = uuid.uuid4()
    temp_message = Message(
        id=message_id,
        conversation_id=conv_id,
        direction="outbound",
        message_type=media_category,
        content=caption or "",
        mode="human",
        status="sending",
        created_at=now_utc,
        sort_timestamp=now_utc,
        whatsapp_timestamp=int(now_utc.timestamp()),
        organization_id=UUID(org_id),
        is_ai_generated=False,
        human_agent_id=UUID(user_id),
        media_file_name=file.filename,
        media_content_type=mime_type,
        media_file_size=file.size,
        status_updated_at=now_utc  # <-- Phase 3: initial timestamp
    )
    db.add(temp_message)
    await db.flush()

    # Read file bytes
    file_bytes = await file.read()

    # ------------------------------------------------------------------
    # 2. UPLOAD MEDIA TO WHATSAPP
    # ------------------------------------------------------------------
    whatsapp_service = WhatsAppService(
        whatsapp_config['access_token'],
        whatsapp_config['phone_number_id']
    )
    try:
        media_id = await whatsapp_service.upload_media(str(file.filename), mime_type, file_bytes)
        logger.info(f"Media uploaded successfully, media_id: {media_id}")
    except Exception as e:
        logger.error(f"WhatsApp upload failed: {e}")
        temp_message.status = "failed"
        temp_message.status_updated_at = datetime.now(timezone.utc)  # <-- Phase 3
        await db.commit()
        raise HTTPException(502, f"WhatsApp upload error: {str(e)}")

    # ------------------------------------------------------------------
    # 3. SEND MEDIA MESSAGE
    # ------------------------------------------------------------------
    try:
        success, wamid = await whatsapp_service.send_media_message(
            to_number=conv.customer_phone_number,
            media_id=media_id,
            media_type=media_category,
            caption=caption
        )
        if not success:
            temp_message.status = "failed"
            temp_message.status_updated_at = datetime.now(timezone.utc)  # <-- Phase 3
            await db.commit()
            raise HTTPException(502, "Failed to send media message")
        logger.info(f"Media message sent, wamid: {wamid}")
    except Exception as e:
        logger.error(f"Failed to send media message: {e}")
        temp_message.status = "failed"
        temp_message.status_updated_at = datetime.now(timezone.utc)  # <-- Phase 3
        await db.commit()
        raise HTTPException(502, f"Failed to send media: {str(e)}")

    # ------------------------------------------------------------------
    # 4. UPDATE MESSAGE WITH WHATSAPP IDs
    # ------------------------------------------------------------------
    temp_message.status = "sent"
    temp_message.whatsapp_message_id = wamid
    temp_message.media_whatsapp_id = media_id
    temp_message.status_updated_at = datetime.now(timezone.utc)  # <-- Phase 3

    # Try immediate download (optional)
    local_path = None
    local_url = None
    try:
        local_path, local_url = await download_and_save_media(
            media_id=media_id,
            filename=file.filename,
            mime_type=mime_type,
            org_id=org_id,
            message_id=message_id
        )
        logger.info(f"Media downloaded and saved to {local_path}")
        temp_message.local_media_path = local_path
        temp_message.media_url = local_url
    except Exception as e:
        logger.error(f"Immediate media download failed, will rely on webhook: {e}")

    await db.commit()
    await db.refresh(temp_message)

    logger.info(f"Media uploaded, sent, and saved: message_id={temp_message.id}, media_id={media_id}")
    return {
        "message_id": str(temp_message.id),
        "media_id": media_id,
        "whatsapp_message_id": wamid,
        "status": "sent",
        "media_url": local_url
    }
# ---------- Media Fetch Endpoint ----------
@router.get("/{conv_id}/media/{message_id}", response_model=None)
async def fetch_message_media(
    conv_id: UUID,
    message_id: UUID,
    db: Any = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    try:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.organization_id == UUID(org_id)
            )
        )
        conv = conv_result.scalar_one_or_none()
        if not conv:
            raise HTTPException(404, "Conversation not found")

        msg_result = await db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conv_id
            )
        )
        message = msg_result.scalar_one_or_none()
        if not message or not message.media_whatsapp_id:
            raise HTTPException(404, "Media not found")

        if message.local_media_path and Path(message.local_media_path).exists():
            return FileResponse(message.local_media_path)

        whatsapp_config = await get_whatsapp_config(org_id)
        if not whatsapp_config:
            raise HTTPException(400, "WhatsApp configuration missing")

        service = WhatsAppService(
            whatsapp_config['access_token'],
            whatsapp_config['phone_number_id']
        )

        media_url = await service.get_media_url(message.media_whatsapp_id)
        if not media_url:
            raise HTTPException(404, "Media URL unavailable")

        async def stream_media():
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("GET", media_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk

        return StreamingResponse(
            stream_media(),
            media_type=message.media_content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'inline; filename="{message.media_file_name or message.id}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching media: {e}")
        raise HTTPException(500, "Internal server error")

# ---------- Assignment Routes (unchanged) ----------
@router.post("/{conv_id}/assign", response_model=None)
async def assign_agent(
    conv_id: UUID,
    request: AssignAgentRequest,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.assign_agent(conv_id, request.agent_id, UUID(org_id), UUID(user_id))
        return {"status": "assigned"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error assigning agent: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/{conv_id}/unassign", response_model=None)
async def unassign_agent(
    conv_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.unassign_agent(conv_id, UUID(org_id), UUID(user_id))
        return {"status": "unassigned"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error unassigning agent: {e}")
        raise HTTPException(500, "Internal server error")

@router.get("/agents", response_model=None)
async def list_agents(
    db: Any = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        stmt = select(User).where(
            User.organization_id == UUID(org_id),
            or_(
                User.role == 'agent',
                User.role == 'org_admin',
                User.role == 'team_member'
            )
        )
        result = await db.execute(stmt)
        agents = result.scalars().all()
        return [
            {
                "id": str(agent.id),
                "name": agent.full_name or agent.email,
                "email": agent.email,
                "role": agent.role,
            }
            for agent in agents
        ]
    except Exception as e:
        logger.error(f"Error listing agents: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/{conv_id}/mode", response_model=None)
async def toggle_mode(
    conv_id: UUID,
    request: ConversationModeUpdate,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.toggle_mode(conv_id, request.mode, UUID(org_id))
        return {"status": "updated", "mode": request.mode}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Error toggling mode: {e}")
        raise HTTPException(500, "Internal server error")

# ---------- Notes Routes (unchanged) ----------
@router.get("/{conv_id}/notes", response_model=None)
async def get_notes(
    conv_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.get_notes(conv_id, UUID(org_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error getting notes: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/{conv_id}/notes", response_model=None)
async def add_note(
    conv_id: UUID,
    note: NoteCreate,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    if not org_id or not user_id:
        raise HTTPException(403, "Authentication required")
    try:
        return await service.add_note(conv_id, note.note, UUID(org_id), UUID(user_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error adding note: {e}")
        raise HTTPException(500, "Internal server error")

# ---------- Tags Routes (unchanged) ----------
@router.get("/tags", response_model=None)
async def list_tags(
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.list_tags(UUID(org_id))
    except Exception as e:
        logger.error(f"Error listing tags: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/tags", response_model=None)
async def create_tag(
    tag: TagCreate,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.create_tag(tag.name, tag.color or "#4F46E5", UUID(org_id))
    except Exception as e:
        logger.error(f"Error creating tag: {e}")
        raise HTTPException(500, "Internal server error")

@router.post("/{conv_id}/tags/{tag_id}", response_model=None)
async def attach_tag(
    conv_id: UUID,
    tag_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.attach_tag(conv_id, tag_id, UUID(org_id))
        return {"status": "attached"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error attaching tag: {e}")
        raise HTTPException(500, "Internal server error")

@router.delete("/{conv_id}/tags/{tag_id}", response_model=None)
async def detach_tag(
    conv_id: UUID,
    tag_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        success = await service.detach_tag(conv_id, tag_id, UUID(org_id))
        if not success:
            raise HTTPException(404, "Tag not attached")
        return {"status": "detached"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error detaching tag: {e}")
        raise HTTPException(500, "Internal server error")

@router.get("/{conv_id}/tags", response_model=None)
async def get_conversation_tags(
    conv_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        return await service.get_conversation_tags(conv_id, UUID(org_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error getting conversation tags: {e}")
        raise HTTPException(500, "Internal server error")

# ---------- Additional endpoints (counts, mark-read, etc.) ----------
class MetadataUpdate(BaseModel):
    metadata: Dict[str, Any]

class OptInUpdate(BaseModel):
    opt_in: bool

@router.get("/counts", response_model=None)
async def get_conversation_counts(
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    user_role = current_user.get("role")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    counts = await service.get_conversation_counts(UUID(org_id), UUID(user_id), user_role)
    return counts

@router.put("/{conv_id}/mark-read", response_model=None)
async def mark_conversation_read(
    conv_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    await service.mark_conversation_read(conv_id, UUID(org_id))
    return {"status": "read"}

@router.get("/{conv_id}/assignment-history", response_model=None)
async def get_assignment_history(
    conv_id: UUID,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        history = await service.get_assignment_history(conv_id, UUID(org_id))
        return history
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise HTTPException(500, "Internal server error")

class CustomFieldsUpdate(BaseModel):
    custom_fields: Dict[str, Any]

@router.patch("/{conv_id}/custom-fields", response_model=None)
async def update_conversation_custom_fields(
    conv_id: UUID,
    data: CustomFieldsUpdate,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.update_custom_fields(conv_id, UUID(org_id), data.custom_fields)
        return {"status": "updated"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error updating custom fields: {e}")
        raise HTTPException(500, "Internal server error")

@router.put("/customers/{cust_id}/opt-in", response_model=None)
async def update_customer_optin(
    cust_id: UUID,
    data: OptInUpdate,
    current_user = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service)
) -> Any:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    try:
        await service.update_customer_optin(cust_id, UUID(org_id), data.opt_in)
        return {"status": "updated"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error updating opt-in: {e}")
        raise HTTPException(500, "Internal server error")

@router.patch("/{conv_id}/mode")
async def set_conversation_mode(
    conv_id: UUID,
    mode: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Change conversation reply mode: ai, human, rule, bot"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    
    # Check user has access to the organisation
    user_org_id = current_user.get("org_id")
    user_role = current_user.get("role")
    if user_role != "super_admin" and str(conv.organization_id) != user_org_id:
        raise HTTPException(403, "Access denied")
    
    if mode not in ["ai", "human", "rule", "bot"]:
        raise HTTPException(400, "Invalid mode. Allowed: ai, human, rule, bot")
    
    conv.reply_mode = mode
    await db.commit()
    return {"message": f"Conversation mode changed to {mode}", "reply_mode": mode}