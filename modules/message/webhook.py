from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from pathlib import Path
import tempfile
import httpx
import uuid
import asyncio
import os
import json
from datetime import datetime, timezone
from uuid import UUID

from groq import Groq
from modules.common.config import GROQ_API_KEY, VERIFY_TOKEN
from modules.common.database import get_db, AsyncSessionLocal
from modules.common.models import Organization, Conversation, Message, Lead, LeadSchema
from modules.ai.processor import process_incoming_message
from modules.ai.orchestrated_processor import OrchestratedProcessor
from modules.ai.rule_processor import get_rule_reply
from modules.message.sender import send_whatsapp_text, get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger

from modules.ai.bot_config_loader import get_active_bot_config
from modules.ai.generic_bot_engine import GenericBotEngine
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.ai.lead_capture import create_lead

from modules.ml.sentiment import analyze_sentiment
from modules.ml.intent import simple_intent
from modules.ml.scoring import predict_conversion_probability
from modules.ml.feature_extractor import extract_features_for_lead
from modules.ml.duplicates import get_embedding
from modules.websocket import send_alert
from modules.tasks.message_tasks import process_message_task
from modules.websocket import manager

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])
USE_ORCHESTRATION = os.getenv("USE_ORCHESTRATION", "false").lower() == "true"

# ========== Gradual Rollout ==========
USE_GENERIC_BOT = os.getenv("USE_GENERIC_BOT", "false").lower() == "true"
GENERIC_BOT_ORG_WHITELIST = os.getenv("GENERIC_BOT_ORG_IDS", "")
WHITELIST_ORGS = set(GENERIC_BOT_ORG_WHITELIST.split(",")) if GENERIC_BOT_ORG_WHITELIST else set()

def is_generic_enabled_for_org(org_id: str) -> bool:
    if WHITELIST_ORGS:
        return org_id in WHITELIST_ORGS
    return USE_GENERIC_BOT

# ========== Phase 18: Voice Transcription ==========
async def transcribe_voice_note(audio_url: str, access_token: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(audio_url, headers={"Authorization": f"Bearer {access_token}"})
            if resp.status_code != 200:
                logger.error(f"Failed to download audio: {resp.status_code}")
                return ""
            audio_bytes = resp.content

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        groq_client = Groq(api_key=GROQ_API_KEY)
        with open(tmp_path, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text"
            )
        os.unlink(tmp_path)
        return transcription if isinstance(transcription, str) else transcription.text
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        return ""

# ========== Phase 14: Smart Defaults ==========
async def get_last_lead_data(phone_number: str, org_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lead)
            .where(
                Lead.customer_phone == phone_number,
                Lead.organization_id == UUID(org_id)
            )
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return {}
        prefill = {}
        if lead.data and isinstance(lead.data, dict):
            prefill["name"] = lead.data.get("name") or lead.customer_name or ""
            prefill["email"] = lead.data.get("email") or lead.email or ""
            prefill["phone"] = lead.data.get("phone") or lead.customer_phone or phone_number
        else:
            prefill["name"] = lead.customer_name or ""
            prefill["email"] = lead.email or ""
            prefill["phone"] = lead.customer_phone or phone_number
        return prefill

# ========== Helper: send media ==========
async def send_whatsapp_media(to_number: str, media: dict, org_id: str) -> tuple:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False, None
    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
    media_type = media.get("type")
    url = media.get("url")
    caption = media.get("caption", "")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": media_type,
        media_type: {"link": url, "caption": caption[:1024] if caption else None}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v18.0/{wa.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {wa.access_token}"},
            json=payload
        )
        if resp.status_code == 201:
            data = resp.json()
            wamid = data.get("messages", [{}])[0].get("id")
            return True, wamid
        else:
            logger.error(f"Media send failed: {resp.status_code} {resp.text}")
            return False, None

# ========== Helper: send interactive ==========
async def send_whatsapp_interactive(to_number: str, question: str, options: list, org_id: str) -> tuple:
    config = await get_whatsapp_config(org_id)
    if not config:
        logger.error(f"No WhatsApp config for org {org_id}")
        return False, None
    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
    if len(options) <= 3:
        buttons = [{"type": "reply", "reply": {"id": opt["id"], "title": opt["title"][:20]}} for opt in options]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": question[:1024]},
                "action": {"buttons": buttons}
            }
        }
    else:
        rows = [{"id": opt["id"], "title": opt["title"][:24], "description": opt.get("description", "")[:60]} for opt in options]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": question[:1024]},
                "action": {
                    "button": "Select",
                    "sections": [{"title": "Options", "rows": rows}]
                }
            }
        }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v18.0/{wa.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {wa.access_token}"},
            json=payload
        )
        if resp.status_code == 201:
            data = resp.json()
            wamid = data.get("messages", [{}])[0].get("id")
            return True, wamid
        else:
            logger.error(f"Interactive send failed: {resp.status_code} {resp.text}")
            return False, None

# ========== Helper: create lead from generic bot ==========
async def create_lead_from_generic_bot(org_id: str, conversation_id: str, customer_phone: str, responses: dict):
    try:
        customer_name = responses.get("name") or responses.get("customer_name") or ""
        email = responses.get("email") or ""
        phone = responses.get("phone") or customer_phone
        lead = Lead(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(org_id),
            conversation_id=uuid.UUID(conversation_id),
            customer_phone=phone,
            customer_name=customer_name,
            email=email,
            status="new",
            lead_score=70,
            conversion_probability=0.5,
            created_at=datetime.utcnow()
        )
        if hasattr(lead, 'data'):
            lead.data = responses
        async with AsyncSessionLocal() as session:
            session.add(lead)
            await session.commit()
            logger.info(f"Lead created from generic bot for conversation {conversation_id}")
            return lead.id
    except Exception as e:
        logger.error(f"Failed to create lead from generic bot: {e}", exc_info=True)
        return None

# ========== Helper: AI fallback ==========
async def get_ai_fallback_reply(org_id: str, user_input: str, current_question: str) -> str:
    return (f"I understand you're asking: '{user_input}'. "
            f"Could you please answer the question: '{current_question}'?")

# ========== Original helpers ==========
async def download_media_background(
    message_id: uuid.UUID,
    media_id: str,
    conv_id: uuid.UUID,
    org_id: str,
    filename: str,
    mime_type: str
):
    try:
        config = await get_whatsapp_config(org_id)
        if not config:
            logger.error(f"No WhatsApp config for org {org_id}")
            return

        wa = WhatsAppService(config['access_token'], config['phone_number_id'])
        media_url = await wa.get_media_url(media_id)
        if not media_url:
            logger.error(f"No media URL for media_id {media_id}")
            return

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {wa.access_token}"}
            )
            if resp.status_code != 200:
                logger.error(f"Failed to download media: {resp.status_code} {resp.text}")
                return
            content = resp.content

        root_dir = Path(__file__).resolve().parents[2]
        media_dir = root_dir / "storage" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = filename.split('.')[-1] if '.' in filename else 'bin'
        local_filename = f"{message_id}.{ext}"
        local_path = media_dir / local_filename
        with open(local_path, "wb") as f:
            f.write(content)
        logger.info(f"Media saved locally: {local_path}")

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

async def process_lead_ml_background(lead_id: uuid.UUID, conversation_id: uuid.UUID, message_text: str):
    try:
        async with AsyncSessionLocal() as session:
            lead = await session.get(Lead, lead_id)
            if not lead:
                logger.error(f"Lead {lead_id} not found")
                return

            sentiment = analyze_sentiment(message_text)
            sentiment_score = 1.0 if sentiment['label'] == 'POSITIVE' else -1.0 if sentiment['label'] == 'NEGATIVE' else 0.0
            lead.sentiment_score = sentiment_score
            intent = simple_intent(message_text)
            lead.intent_label = intent

            msg_result = await session.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            )
            conversation_messages = msg_result.scalars().all()

            features = extract_features_for_lead(lead, conversation_messages)
            prob = predict_conversion_probability(features)
            lead.conversion_probability = prob
            lead.lead_score = int(prob * 100)
            lead.last_scored_at = datetime.utcnow()

            if lead.embedding is None:
                text_for_embedding = f"{lead.customer_name or ''} {lead.email or ''} {lead.customer_phone or ''}"
                lead.embedding = get_embedding(text_for_embedding).tolist()

            await session.commit()

            if prob > 0.8:
                send_alert(lead.id, lead.customer_name or lead.customer_phone, prob)

            logger.info(f"ML processing completed for lead {lead_id}: score={lead.lead_score}, intent={intent}")

    except Exception as e:
        logger.error(f"ML background processing failed for lead {lead_id}: {e}", exc_info=True)

async def get_or_create_lead(session: AsyncSession, conversation: Conversation, phone_number: str) -> Lead:
    result = await session.execute(
        select(Lead).where(Lead.conversation_id == conversation.id)
    )
    lead = result.scalars().first()

    if not lead:
        result = await session.execute(
            select(Lead)
            .where(Lead.customer_phone == phone_number)
            .where(Lead.organization_id == conversation.organization_id)
            .order_by(Lead.created_at.desc())
        )
        lead = result.scalars().first()

    if not lead:
        lead = Lead(
            id=uuid.uuid4(),
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            customer_phone=phone_number,
            status="new",
            lead_score=0,
            conversion_probability=0.0,
            created_at=datetime.utcnow()
        )
        session.add(lead)
        await session.flush()
    else:
        if lead.conversation_id != conversation.id:
            lead.conversation_id = conversation.id
            session.add(lead)
    return lead

# ========== Webhook endpoints ==========
@router.get("")
async def verify_webhook(hub_mode: str = None, hub_verify_token: str = None, hub_challenge: int = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
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

        # Status updates
        if "statuses" in value:
            for status_data in value["statuses"]:
                wamid = status_data.get("id")
                status = status_data.get("status")
                if not wamid:
                    continue
                
                status_timestamp = status_data.get("timestamp")
                if status_timestamp:
                    try:
                        status_ts_int = int(status_timestamp)
                        status_updated_at = datetime.fromtimestamp(status_ts_int, tz=timezone.utc)
                    except (TypeError, ValueError):
                        status_updated_at = datetime.now(timezone.utc)
                else:
                    status_updated_at = datetime.now(timezone.utc)   

                errors = status_data.get("errors")
                if status == "failed" and errors:
                    logger.error(f"Message {wamid} failed: {errors}")
                
                stmt = update(Message).where(Message.whatsapp_message_id == wamid).values(
                    status=status,
                    status_updated_at=status_updated_at
                )
                await db.execute(stmt)
                await db.commit()
                logger.info(f"Updated message {wamid} status to {status} at {status_updated_at}")

        # Incoming messages
        if "messages" in value:
            msg_data = value["messages"][0]
            from_number = msg_data["from"]
            timestamp = int(msg_data["timestamp"])
            wamid = msg_data.get("id")
            business_phone_number = value["metadata"]["display_phone_number"]

            msg_type = msg_data.get("type")
            caption = ""
            media_whatsapp_id = None
            media_file_name = None
            media_content_type = None
            content = ""
            message_type = "text"

            if "interactive" in msg_data:
                interactive = msg_data["interactive"]
                if interactive["type"] == "button_reply":
                    content = interactive["button_reply"]["id"]
                elif interactive["type"] == "list_reply":
                    content = interactive["list_reply"]["id"]
                else:
                    content = ""
                message_type = "text"
            else:
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

            result = await db.execute(
                select(Organization.id, Organization.business_type)
                .where(Organization.whatsapp_phone_number == business_phone_number)
            )
            row = result.first()
            if not row:
                logger.warning(f"No organization found for WhatsApp number: {business_phone_number}")
                return {"status": "ignored", "reason": "unknown_whatsapp_number"}
            org_id, business_type = row

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

            if not conv.rule_state.get("lang"):
                user_locale = msg_data.get("user_locale")
                if user_locale:
                    detected = "hi" if user_locale.startswith("hi") else "en"
                    conv.rule_state["lang"] = detected
                    await db.commit()
                    logger.info(f"Auto-detected language: {detected} for conv {conv.id}")

            if msg_type == "audio" and media_whatsapp_id:
                config = await get_whatsapp_config(str(org_id))
                if config:
                    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
                    media_url = await wa.get_media_url(media_whatsapp_id)
                    if media_url:
                        transcribed = await transcribe_voice_note(media_url, config['access_token'])
                        if transcribed:
                            content = transcribed
                            message_type = "text"
                            logger.info(f"Transcribed voice note: {content[:100]}...")

            new_message_id = uuid.uuid4()
            sort_ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            insert_stmt = pg_insert(Message).values(
                id=new_message_id,
                conversation_id=conv.id,
                organization_id=org_id,
                direction="inbound",
                mode="user",
                content=content,
                message_type=message_type,
                media_whatsapp_id=media_whatsapp_id,
                media_file_name=media_file_name,
                media_content_type=media_content_type,
                media_url=f"/api/conversations/media/{new_message_id}" if media_whatsapp_id else None,
                is_ai_generated=False,
                status="delivered",
                created_at=datetime.now(timezone.utc),
                whatsapp_message_id=wamid,
                whatsapp_timestamp=timestamp,
                sort_timestamp=sort_ts,
                status_updated_at=datetime.now(timezone.utc)
            )
            upsert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=['whatsapp_message_id'],
                set_={
                    'status': 'delivered',
                    'status_updated_at': datetime.now(timezone.utc),
                    'content': content,
                    'message_type': message_type,
                    'media_whatsapp_id': media_whatsapp_id,
                    'media_file_name': media_file_name,
                    'media_content_type': media_content_type
                }
            )
            await db.execute(upsert_stmt)

            naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conv.id)
                .values(
                    unread_count=Conversation.unread_count + 1,
                    last_customer_message_at=naive_utc_now,
                    last_message_at=datetime.now(timezone.utc)
                )
            )

            lead = await get_or_create_lead(db, conv, from_number)
            await db.commit()

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

            if conv.reply_mode == 'bot':
                sentiment = analyze_sentiment(content)
                sentiment_score = 1.0 if sentiment['label'] == 'POSITIVE' else -1.0 if sentiment['label'] == 'NEGATIVE' else 0.0
                lead.sentiment_score = sentiment_score
                lead.intent_label = simple_intent(content)
                await db.commit()
                if sentiment_score < -0.5:
                    logger.info(f"Negative sentiment detected (score={sentiment_score}) for conv {conv.id} – no action taken.")
            else:
                background_tasks.add_task(process_lead_ml_background, lead.id, conv.id, content)

            # ========== REPLY LOGIC ==========
            # 1. Rule engine
            if conv.reply_mode == 'rule':
                logger.info(f"Using rule engine for org {org_id}")
                
                # Store IDs before try to avoid expired object issue
                conv_id_str = str(conv.id)
                org_id_str = str(org_id)
                await manager.send_typing_start(org_id_str, conv_id_str, "rule")
                
                try:
                    reply, updated_state = await get_rule_reply(org_id_str, conv_id_str, content, from_number)
                    if updated_state:
                        conv.rule_state = updated_state
                        await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=updated_state))
                        await db.commit()
                    
                    if reply == "__INTERACTIVE__":
                        return {"status": "ok"}
                    
                    if reply:
                        last_out_stmt = select(Message).where(
                            Message.conversation_id == conv.id,
                            Message.direction == "outbound"
                        ).order_by(Message.sort_timestamp.desc()).limit(1)
                        last_out = (await db.execute(last_out_stmt)).scalar_one_or_none()
                        send_reply = True
                        if last_out and last_out.content == reply:
                            delta = datetime.now(timezone.utc) - last_out.created_at
                            if delta.total_seconds() < 5:
                                logger.info("Skipping duplicate outbound reply")
                                send_reply = False
                        if send_reply:
                            success, wamid = await send_whatsapp_text(to_number=from_number, text=reply, org_id=org_id_str)
                            if success:
                                out_msg = Message(
                                    id=uuid.uuid4(),
                                    conversation_id=conv.id,
                                    direction="outbound",
                                    mode="rule",
                                    content=reply,
                                    is_ai_generated=False,
                                    status="sent",
                                    created_at=datetime.now(timezone.utc),
                                    whatsapp_message_id=wamid,
                                    whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                    sort_timestamp=datetime.now(timezone.utc),
                                    status_updated_at=datetime.now(timezone.utc)
                                )
                                db.add(out_msg)
                                await db.execute(update(Conversation).where(Conversation.id == conv.id).values(last_message_at=datetime.now(timezone.utc)))
                                await db.commit()
                                logger.info(f"Rule-based reply sent to {from_number}")
                        return {"status": "ok"}
                    else:
                        conv.reply_mode = 'ai'
                        await db.commit()
                finally:
                    await manager.send_typing_stop(org_id_str, conv_id_str)
        
            # 2. Generic Bot Engine
            elif conv.reply_mode == 'bot':
                if not is_generic_enabled_for_org(str(org_id)):
                    logger.warning("Bot mode not allowed, falling back to AI")
                    conv.reply_mode = 'ai'
                    await db.commit()
                else:
                    active_config = await get_active_bot_config(str(org_id))
                    if not active_config:
                        logger.warning("No active config, falling back to AI")
                        conv.reply_mode = 'ai'
                        await db.commit()
                    else:
                        logger.info(f"Using GenericBotEngine for org {org_id}, conv {conv.id}")
                        current_state = conv.rule_state or {}
                        if not current_state.get("responses"):
                            last_lead = await get_last_lead_data(from_number, str(org_id))
                            if last_lead:
                                bot_fields = {f["name"] for f in active_config.get("fields", [])}
                                prefill = {k: v for k, v in last_lead.items() if k in bot_fields}
                                if prefill:
                                    current_state["responses"] = prefill
                                    logger.info(f"Pre-filled fields: {list(prefill.keys())}")
                                    if prefill.get("name"):
                                        conv.customer_name = prefill["name"]
                                        await db.execute(update(Conversation).where(Conversation.id == conv.id).values(customer_name=prefill["name"]))
                                        await db.commit()
                        engine = GenericBotEngine(active_config)
                        action = None
                        
                        # Helper to save bot messages – fixed to include all required fields
                        async def save_bot_message(content: str, wamid: str, msg_type: str = "text"):
                            now_utc = datetime.now(timezone.utc)
                            out_msg = Message(
                                id=uuid.uuid4(),
                                conversation_id=conv.id,
                                organization_id=conv.organization_id,
                                direction="outbound",
                                mode="bot",
                                message_type=msg_type,
                                content=content,
                                is_ai_generated=True,
                                status="sent",
                                created_at=now_utc,
                                whatsapp_message_id=wamid,
                                whatsapp_timestamp=int(now_utc.timestamp()),
                                sort_timestamp=now_utc,
                                status_updated_at=now_utc
                            )
                            db.add(out_msg)
                            await db.commit()
                        
                        # Store IDs before try to avoid expired object in finally
                        conv_id_str = str(conv.id)
                        org_id_str = str(org_id)
                        await manager.send_typing_start(org_id_str, conv_id_str, "bot")
                        try:
                            action = engine.process(content, current_state)
                            if action:
                                new_state = action.get("new_state", current_state)
                                conv.rule_state = new_state
                                await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=new_state))
                                await db.commit()

                                action_type = action["action"]
                                data = action.get("data", {})

                                if action_type == "ask_language":
                                    question = data.get("message")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                    if success:
                                        await save_bot_message(question, wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                if action_type == "ask":
                                    question = data["question"]
                                    field_type = data.get("field_type", "text")
                                    options = data.get("options", [])
                                    media = data.get("media")
                                    if media:
                                        await send_whatsapp_media(from_number, media, org_id_str)
                                    if field_type in ["button", "list"] and options:
                                        success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                        if success:
                                            await save_bot_message(question, wamid, msg_type="interactive")
                                    else:
                                        success, wamid = await send_whatsapp_text(from_number, question, org_id_str)
                                        if success:
                                            await save_bot_message(question, wamid)
                                    return {"status": "ok"}

                                elif action_type in ["validation_error", "invalid_field", "confirmation_invalid"]:
                                    error_msg = data.get("error") or data.get("message") or "Invalid input"
                                    success, wamid = await send_whatsapp_text(from_number, error_msg, org_id_str)
                                    if success:
                                        await save_bot_message(error_msg, wamid)
                                    return {"status": "ok"}

                                elif action_type == "ask_confirmation":
                                    question = data.get("message")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                    if success:
                                        await save_bot_message(question, wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                elif action_type == "ask_which_field":
                                    question = data.get("question", "Which field would you like to change?")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                    if success:
                                        await save_bot_message(question, wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                elif action_type == "ask_new_value":
                                    msg = f"Please provide the new value for {data['field']}:"
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    return {"status": "ok"}

                                elif action_type == "ask_new_value_with_options":
                                    question = data.get("question")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                    if success:
                                        await save_bot_message(question, wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                elif action_type == "ask_custom_field":
                                    msg = data.get("message", "Please type the field name you want to change:")
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    return {"status": "ok"}

                                elif action_type == "ask_custom_value":
                                    msg = data.get("message", "Please type the new value:")
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    return {"status": "ok"}

                                elif action_type == "ask_continue_or_new":
                                    question = data.get("message")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                                    if success:
                                        await save_bot_message(question, wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                elif action_type == "send_text":
                                    msg = data["message"]
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    return {"status": "ok"}

                                elif action_type == "unmatched":
                                    msg = "I'll switch to AI mode to better answer your question."
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    conv.reply_mode = 'ai'
                                    await db.execute(
                                        update(Conversation)
                                        .where(Conversation.id == conv.id)
                                        .values(reply_mode='ai')
                                    )
                                    await db.commit()
                                    # Continue to AI processing

                                elif action_type == "create_lead":
                                    await create_lead_from_generic_bot(org_id_str, conv_id_str, from_number, data)
                                    msg = "Thank you! Your information has been saved."
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    conv.rule_state["completed"] = True
                                    await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=conv.rule_state))
                                    await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "ask_booking":
                                    from modules.bot_builder.booking_helper import get_available_slots
                                    slots = await get_available_slots(org_id, data.get("booking_config"))
                                    if not slots:
                                        msg = "No slots available. Please try later."
                                        success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                        if success:
                                            await save_bot_message(msg, wamid)
                                        return {"status": "ok"}
                                    options = [{"id": slot["id"], "title": slot["display"]} for slot in slots]
                                    success, wamid = await send_whatsapp_interactive(from_number, data["question"], options, org_id_str)
                                    if success:
                                        await save_bot_message(data["question"], wamid, msg_type="interactive")
                                    return {"status": "ok"}

                                elif action_type == "create_booking":
                                    from modules.bot_builder.booking_helper import create_booking
                                    booking_id = await create_booking(org_id, conv.id, from_number, data)
                                    msg = f"Your booking has been confirmed! ID: {booking_id}"
                                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                                    if success:
                                        await save_bot_message(msg, wamid)
                                    conv.rule_state["completed"] = True
                                    await db.commit()
                                    return {"status": "ok"}

                        except Exception as e:
                            logger.exception(f"Generic bot engine error: {e}")
                            conv.reply_mode = 'ai'
                            await db.commit()
                        finally:
                            await manager.send_typing_stop(org_id_str, conv_id_str)

            # 3. Human mode
            if conv.reply_mode == 'human':
                logger.info(f"Conversation {conv.id} in human mode – skipping AI reply")
                return {"status": "ok"}

            # 4. AI mode (fallback)
            if conv.reply_mode in ['ai', None] or (conv.reply_mode == 'bot' and not action):
                if USE_ORCHESTRATION:
                    background_tasks.add_task(OrchestratedProcessor().process_message, str(conv.id), from_number, content, str(org_id))
                else:
                    background_tasks.add_task(process_incoming_message, {"from_number": from_number, "text": content, "timestamp": timestamp, "org_id": str(org_id), "conversation_id": str(conv.id)})
                logger.info(f"Scheduled AI processing for message from {from_number}")

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        await db.rollback()

    return {"status": "ok"}