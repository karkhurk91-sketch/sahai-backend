from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from pathlib import Path
import httpx
import uuid
from datetime import datetime

from modules.common.config import VERIFY_TOKEN
from modules.common.database import get_db, AsyncSessionLocal
from modules.common.models import Organization, Conversation, Message
from modules.ai.processor import process_incoming_message
from modules.ai.rule_processor import get_rule_reply
from modules.message.sender import send_whatsapp_text, get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])

# ---------- Background Media Download (for both incoming & outgoing) ----------
async def download_media_background(
    message_id: uuid.UUID,
    media_id: str,
    conv_id: uuid.UUID,
    org_id: str,
    filename: str,
    mime_type: str
):
    """Download media from WhatsApp and save locally (used for both incoming & outgoing)."""
    try:
        config = await get_whatsapp_config(org_id)
        if not config:
            logger.error(f"No WhatsApp config for org {org_id}")
            return

        wa = WhatsAppService(config['access_token'], config['phone_number_id'])

        # Get temporary download URL from WhatsApp
        media_url = await wa.get_media_url(media_id)
        if not media_url:
            logger.error(f"No media URL for media_id {media_id}")
            return

        # Download the file using the same access token
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {wa.access_token}"}
            )
            if resp.status_code != 200:
                logger.error(f"Failed to download media: {resp.status_code} {resp.text}")
                return
            content = resp.content

        # Save to local storage
        root_dir = Path(__file__).resolve().parents[2]
        media_dir = root_dir / "storage" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = filename.split('.')[-1] if '.' in filename else 'bin'
        local_filename = f"{message_id}.{ext}"
        local_path = media_dir / local_filename
        with open(local_path, "wb") as f:
            f.write(content)
        logger.info(f"Media saved locally: {local_path}")

        # Update message record with local path and local media URL
        async with AsyncSessionLocal() as session:
            stmt = update(Message).where(Message.id == message_id).values(
                local_media_path=str(local_path),
                media_url=f"/api/conversations/media/{local_filename}"
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Updated message {message_id} with local media URL")

    except Exception as e:
        logger.error(f"Media download failed for message {message_id}: {e}", exc_info=True)

# ---------- Webhook Endpoints ----------
@router.get("")
async def verify_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: int = None
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    logger.info("Webhook POST request received")
    try:
        body = await request.json()
        logger.info(f"Webhook body: {body}")
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
        return {"status": "error", "detail": "Invalid JSON"}

    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # ---------- Handle Status Updates (for outgoing messages) ----------
        if "statuses" in value:
            status_map = {
                "sent": "sent",
                "delivered": "delivered",
                "read": "read",
                "failed": "failed",
            }
            for status_update in value.get("statuses") or []:
                wamid = status_update.get("id")
                raw_status = (status_update.get("status") or "").lower()
                if not wamid or not raw_status:
                    continue
                mapped = status_map.get(raw_status)
                if not mapped:
                    continue

                try:
                    # Update message status
                    await db.execute(
                        update(Message)
                        .where(Message.whatsapp_message_id == wamid)
                        .values(status=mapped)
                    )
                    await db.commit()
                    logger.info(f"Updated message {wamid} status -> {mapped}")

                    # If status is sent/delivered and this is a media message without local copy, trigger download
                    if raw_status in {"sent", "delivered"}:
                        msg_result = await db.execute(
                            select(Message).where(Message.whatsapp_message_id == wamid)
                        )
                        msg = msg_result.scalar_one_or_none()
                        if msg and msg.media_whatsapp_id and not getattr(msg, 'local_media_path', None):
                            conv_result = await db.execute(
                                select(Conversation).where(Conversation.id == msg.conversation_id)
                            )
                            conv = conv_result.scalar_one_or_none()
                            if conv:
                                background_tasks.add_task(
                                    download_media_background,
                                    msg.id,
                                    msg.media_whatsapp_id,
                                    conv.id,
                                    str(conv.organization_id),
                                    msg.media_file_name or "file",
                                    msg.media_content_type or "application/octet-stream"
                                )
                except Exception as ex:
                    logger.warning(f"Could not process status for {wamid}: {ex}")
                    await db.rollback()

        # ---------- Handle Incoming Messages ----------
        if "messages" in value:
            msg_data = value["messages"][0]
            from_number = msg_data["from"]
            timestamp = int(msg_data["timestamp"])
            business_phone_number = value["metadata"]["display_phone_number"]

            # Determine incoming message content and type
            msg_type = msg_data.get("type")
            caption = ""
            media_whatsapp_id = None
            media_file_name = None
            media_content_type = None
            content = ""
            message_type = "text"

            if msg_type == "text":
                content = msg_data["text"]["body"]
                message_type = "text"
            elif msg_type in {"image", "video", "audio", "document"}:
                payload = msg_data.get(msg_type, {}) or {}
                media_whatsapp_id = payload.get("id")
                caption = payload.get("caption") or ""
                media_file_name = payload.get("filename")
                media_content_type = payload.get("mime_type")
                message_type = msg_type
                content = caption or f"{msg_type} attachment"
            else:
                content = msg_data.get("text", {}).get("body") or msg_data.get(msg_type, {}).get("caption") or f"Unsupported message type: {msg_type}"
                message_type = msg_type or "text"

            # Find organization
            result = await db.execute(
                select(Organization.id, Organization.business_type)
                .where(Organization.whatsapp_phone_number == business_phone_number)
            )
            row = result.first()
            if not row:
                logger.warning(f"No organization found for WhatsApp number: {business_phone_number}")
                return {"status": "ignored", "reason": "unknown_whatsapp_number"}
            org_id, business_type = row

            # Find or create conversation
            conv_stmt = select(Conversation).where(
                Conversation.organization_id == org_id,
                Conversation.customer_phone_number == from_number
            )
            conv = (await db.execute(conv_stmt)).scalar_one_or_none()

            if not conv:
                conv = Conversation(
                    id=uuid.uuid4(),
                    organization_id=org_id,
                    customer_phone_number=from_number,
                    status="open",
                    reply_mode="ai",
                    started_at=datetime.utcnow(),
                    last_message_at=datetime.utcnow(),
                    rule_state={}
                )
                db.add(conv)
                try:
                    await db.flush()
                    logger.info(f"Created new conversation for {from_number} under org {org_id}")
                except IntegrityError:
                    await db.rollback()
                    conv = (await db.execute(conv_stmt)).scalar_one()
                    logger.info(f"Retrieved existing conversation {conv.id} for {from_number}")
            else:
                if conv.reply_mode is None:
                    conv.reply_mode = 'ai'
                logger.info(f"Using existing conversation {conv.id} for {from_number}")

            # Save incoming message
            new_message_id = uuid.uuid4()
            new_message = Message(
                id=new_message_id,
                conversation_id=conv.id,
                organization_id=org_id,
                direction="inbound",
                content=content,
                message_type=message_type,
                media_whatsapp_id=media_whatsapp_id,
                media_file_name=media_file_name,
                media_content_type=media_content_type,
                media_url=f"/api/conversations/media/{new_message_id}" if media_whatsapp_id else None,
                is_ai_generated=False,
                status="delivered",
                created_at=datetime.utcnow()
            )
            db.add(new_message)
            conv.last_message_at = datetime.utcnow()
            db.add(conv)
            await db.commit()

            # 🔽 NEW: Trigger background download for incoming media
            if media_whatsapp_id:
                background_tasks.add_task(
                    download_media_background,
                    new_message_id,
                    media_whatsapp_id,
                    conv.id,
                    str(org_id),
                    media_file_name or "file",
                    media_content_type or "application/octet-stream"
                )

            # Rule Mode Handling
            if conv.reply_mode == 'rule':
                reply, _ = await get_rule_reply(str(org_id), str(conv.id), content)
                if reply:
                    success, wamid = await send_whatsapp_text(to_number=from_number, text=reply, org_id=str(org_id))
                    if success:
                        out_msg = Message(
                            id=uuid.uuid4(),
                            conversation_id=conv.id,
                            direction="outbound",
                            content=reply,
                            is_ai_generated=False,
                            status="sent",
                            created_at=datetime.utcnow(),
                            whatsapp_message_id=wamid
                        )
                        db.add(out_msg)
                        conv.last_message_at = datetime.utcnow()
                        await db.commit()
                        logger.info(f"Rule-based reply sent to {from_number}")
                        return {"status": "ok"}
                else:
                    logger.info(f"No rule matched for {from_number}, falling back to AI mode")
                    conv.reply_mode = 'ai'
                    await db.commit()

            # Human or AI Mode
            if conv.reply_mode == 'human':
                logger.info(f"Conversation {conv.id} in human mode – skipping AI reply")
                return {"status": "ok"}
            else:
                background_tasks.add_task(
                    process_incoming_message,
                    {
                        "from_number": from_number,
                        "text": content,
                        "timestamp": timestamp,
                        "org_id": str(org_id),
                        "conversation_id": str(conv.id)
                    }
                )
                logger.info(f"Scheduled AI processing for message from {from_number}")

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        await db.rollback()

    return {"status": "ok"}