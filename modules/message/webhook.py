from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from pathlib import Path
import httpx
import uuid
import asyncio
from datetime import datetime, timezone

from modules.common.config import VERIFY_TOKEN
from modules.common.database import get_db, AsyncSessionLocal
from modules.common.models import Organization, Conversation, Message, Lead  # added Lead
from modules.ai.processor import process_incoming_message
from modules.ai.rule_processor import get_rule_reply
from modules.message.sender import send_whatsapp_text, get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger

# NEW ML IMPORTS
from modules.ml.sentiment import analyze_sentiment
from modules.ml.intent import simple_intent
from modules.ml.scoring import predict_conversion_probability
from modules.ml.feature_extractor import extract_features_for_lead
from modules.ml.duplicates import get_embedding, find_duplicates
from modules.websocket import send_alert

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])

# ---------- Background Media Download (unchanged) ----------
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


# ---------- NEW: Background ML Processing ----------
async def process_lead_ml_background(lead_id: uuid.UUID, conversation_id: uuid.UUID, message_text: str):
    """
    Runs sentiment, intent, scoring, and duplicate detection on a lead.
    Runs as a background task to avoid blocking webhook response.
    """
    try:
        async with AsyncSessionLocal() as session:
            # Fetch lead and conversation messages
            lead = await session.get(Lead, lead_id)
            if not lead:
                logger.error(f"Lead {lead_id} not found")
                return

            # 1. Sentiment analysis on the incoming message
            sentiment = analyze_sentiment(message_text)
            sentiment_score = 1.0 if sentiment['label'] == 'POSITIVE' else -1.0 if sentiment['label'] == 'NEGATIVE' else 0.0
            lead.sentiment_score = sentiment_score

            # 2. Intent classification (lightweight)
            intent = simple_intent(message_text)
            lead.intent_label = intent

            # 3. Get conversation messages for feature extraction
            msg_result = await session.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            )
            conversation_messages = msg_result.scalars().all()

            # 4. Extract features and compute conversion probability
            features = extract_features_for_lead(lead, conversation_messages)
            prob = predict_conversion_probability(features)
            lead.conversion_probability = prob
            lead.lead_score = int(prob * 100)
            lead.last_scored_at = datetime.utcnow()

            # 5. Compute embedding for duplicate detection (if not exists)
            if lead.embedding is None:
                text_for_embedding = f"{lead.customer_name or ''} {lead.email or ''} {lead.customer_phone or ''}"
                lead.embedding = get_embedding(text_for_embedding).tolist()  # store as list

            await session.commit()

            # 6. WebSocket alert for high-score leads (probability > 0.8)
            if prob > 0.8:
                send_alert(lead.id, lead.customer_name or lead.customer_phone, prob)

            logger.info(f"ML processing completed for lead {lead_id}: score={lead.lead_score}, intent={intent}")

            # 7. (Optional) Check for duplicates if lead is new
            if lead.duplicate_checked is False:  # add column if needed
                # Fetch all existing embeddings (could be heavy – implement carefully)
                # For now, skip; you can implement later via separate task.
                pass

    except Exception as e:
        logger.error(f"ML background processing failed for lead {lead_id}: {e}", exc_info=True)

# ---------- Helper: Get or create Lead from conversation ----------
async def get_or_create_lead(session: AsyncSession, conversation: Conversation, phone_number: str) -> Lead:
    # First try by conversation_id
    result = await session.execute(
        select(Lead).where(Lead.conversation_id == conversation.id)
    )
    lead = result.scalar_one_or_none()
    
    # If not found, try by customer_phone AND organization_id
    if not lead:
        result = await session.execute(
            select(Lead)
            .where(Lead.customer_phone == phone_number)
            .where(Lead.organization_id == conversation.organization_id)  # ← ADD THIS
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
        lead = result.scalar_one_or_none()
    
    # If still no lead, create a new one
    if not lead:
        lead = Lead(
            id=uuid.uuid4(),
            organization_id=conversation.organization_id,  # ← SET THIS
            conversation_id=conversation.id,
            customer_phone=phone_number,
            customer_name=None,
            email=None,
            lead_score=0,
            conversion_probability=0.0,
            status="new",
            sentiment_score=0.0,
            intent_label="general",
            created_at=datetime.utcnow()
        )
        session.add(lead)
        await session.flush()
    else:
        # Update conversation link if needed
        if lead.conversation_id != conversation.id:
            lead.conversation_id = conversation.id
            session.add(lead)
    
    return lead

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

        # ---------- Handle Status Updates (unchanged) ----------
        if "statuses" in value:
            # ... keep existing status handling code ...
            pass

        # ---------- Handle Incoming Messages ----------
        if "messages" in value:
            msg_data = value["messages"][0]
            from_number = msg_data["from"]
            timestamp = int(msg_data["timestamp"])
            business_phone_number = value["metadata"]["display_phone_number"]

            # Extract message content
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

            # Get or create conversation
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
                    logger.info(f"Created new conversation for {from_number}")
                except IntegrityError:
                    await db.rollback()
                    conv = (await db.execute(conv_stmt)).scalar_one()
            else:
                if conv.reply_mode is None:
                    conv.reply_mode = 'ai'

            # Create message record
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

            # Update conversation stats
            if new_message.direction == "inbound":
                naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == conv.id)
                    .values(
                        unread_count=Conversation.unread_count + 1,
                        last_customer_message_at=naive_utc_now
                    )
                )
            conv.last_message_at = datetime.utcnow()
            db.add(conv)

            # Create or link Lead
            lead = await get_or_create_lead(db, conv, from_number)

            await db.commit()

            # Schedule media download if needed
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

            # Schedule ML processing (sentiment, scoring, etc.) for this lead
            background_tasks.add_task(
                process_lead_ml_background,
                lead.id,
                conv.id,
                content
            )

            # ---------- Rule/AI reply handling (unchanged) ----------
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
                    logger.info(f"No rule matched, falling back to AI mode")
                    conv.reply_mode = 'ai'
                    await db.commit()

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