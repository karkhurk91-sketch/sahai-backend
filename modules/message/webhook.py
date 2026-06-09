from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from pathlib import Path
import httpx
import uuid
import asyncio
import os
import json
from datetime import datetime, timezone

from modules.common.config import VERIFY_TOKEN
from modules.common.database import get_db, AsyncSessionLocal
from modules.common.models import Organization, Conversation, Message, Lead, LeadSchema
from modules.ai.processor import process_incoming_message
from modules.ai.orchestrated_processor import OrchestratedProcessor
from modules.ai.rule_processor import get_rule_reply
from modules.message.sender import send_whatsapp_text, get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger

# Phase 4 imports
from modules.ai.bot_config_loader import get_active_bot_config
from modules.ai.generic_bot_engine import GenericBotEngine

# Lead capture imports
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.ai.lead_capture import create_lead

# ML imports
from modules.ml.sentiment import analyze_sentiment
from modules.ml.intent import simple_intent
from modules.ml.scoring import predict_conversion_probability
from modules.ml.feature_extractor import extract_features_for_lead
from modules.ml.duplicates import get_embedding
from modules.websocket import send_alert
from modules.tasks.message_tasks import process_message_task

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])
USE_ORCHESTRATION = os.getenv("USE_ORCHESTRATION", "false").lower() == "true"

# ========== Phase 9: Gradual Rollout for Bot Mode ==========
USE_GENERIC_BOT = os.getenv("USE_GENERIC_BOT", "false").lower() == "true"
GENERIC_BOT_ORG_WHITELIST = os.getenv("GENERIC_BOT_ORG_IDS", "")
WHITELIST_ORGS = set(GENERIC_BOT_ORG_WHITELIST.split(",")) if GENERIC_BOT_ORG_WHITELIST else set()

def is_generic_enabled_for_org(org_id: str) -> bool:
    """Check if generic bot should be used for this organisation (bot mode only)."""
    if WHITELIST_ORGS:
        return org_id in WHITELIST_ORGS
    return USE_GENERIC_BOT

# ========== Optional metrics helper (uncomment if Redis available) ==========
# async def increment_metric(org_id: str, metric_name: str):
#     from modules.common.redis_client import get_redis_client
#     try:
#         redis = get_redis_client()
#         today = datetime.utcnow().strftime("%Y-%m-%d")
#         key = f"bot_metrics:{org_id}:{metric_name}:{today}"
#         await redis.incr(key)
#         await redis.expire(key, 86400*7)
#     except Exception as e:
#         logger.warning(f"Metric increment failed: {e}")

# ========== Helper: send interactive message ==========
async def send_whatsapp_interactive(to_number: str, question: str, options: list, org_id: str) -> tuple:
    """Send an interactive message (buttons or list) using WhatsApp Cloud API."""
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
    """Create a lead using the fields collected by the generic bot."""
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

# ========== Existing helper functions (unchanged) ==========
async def download_media_background(
    message_id: uuid.UUID,
    media_id: str,
    conv_id: uuid.UUID,
    org_id: str,
    filename: str,
    mime_type: str
):
    """Download media from WhatsApp and save locally."""
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
    """Run sentiment, intent, scoring, and duplicate detection on a lead."""
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
    # First, try to find lead linked to this conversation
    result = await session.execute(
        select(Lead).where(Lead.conversation_id == conversation.id)
    )
    lead = result.scalars().first()

    if not lead:
        # Then try to find lead by phone and organisation (most recent)
        result = await session.execute(
            select(Lead)
            .where(Lead.customer_phone == phone_number)
            .where(Lead.organization_id == conversation.organization_id)
            .order_by(Lead.created_at.desc())
        )
        lead = result.scalars().first()

    if not lead:
        # Create new lead
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

        # ---------- Handle Status Updates ----------
        if "statuses" in value:
            statuses = value["statuses"]
            for status_data in statuses:
                wamid = status_data.get("id")
                status = status_data.get("status")
                if not wamid:
                    continue
                stmt = update(Message).where(Message.whatsapp_message_id == wamid).values(status=status)
                await db.execute(stmt)
                await db.commit()
                logger.info(f"Updated message {wamid} status to {status}")

        # ---------- Handle Incoming Messages ----------
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

            # Handle interactive replies
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

            # Create message record (upsert)
            new_message_id = uuid.uuid4()
            sort_ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            insert_stmt = pg_insert(Message).values(
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
                created_at=datetime.now(timezone.utc),
                whatsapp_message_id=wamid,
                whatsapp_timestamp=timestamp,
                sort_timestamp=sort_ts
            )
            upsert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=['whatsapp_message_id'],
                set_={
                    'status': 'delivered',
                    'content': content,
                    'message_type': message_type,
                    'media_whatsapp_id': media_whatsapp_id,
                    'media_file_name': media_file_name,
                    'media_content_type': media_content_type
                }
            )
            await db.execute(upsert_stmt)

            # Update conversation stats
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

            background_tasks.add_task(
                process_lead_ml_background,
                lead.id,
                conv.id,
                content
            )

            # ---------- REPLY LOGIC ----------
            # 1. OLD RULE ENGINE (industry‑specific, hardcoded)
            if conv.reply_mode == 'rule':
                logger.info(f"Using rule engine for org {org_id}, conv {conv.id}")
                reply, updated_state = await get_rule_reply(str(org_id), str(conv.id), content, from_number)
                if updated_state:
                    conv.rule_state = updated_state
                    await db.execute(
                        update(Conversation)
                        .where(Conversation.id == conv.id)
                        .values(rule_state=updated_state)
                    )
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
                            logger.info(f"Skipping duplicate outbound reply to {from_number}")
                            send_reply = False
                    if send_reply:
                        success, wamid = await send_whatsapp_text(to_number=from_number, text=reply, org_id=str(org_id))
                    else:
                        success = False
                        wamid = None
                    if success:
                        now_utc = datetime.now(timezone.utc)
                        out_msg = Message(
                            id=uuid.uuid4(),
                            conversation_id=conv.id,
                            direction="outbound",
                            content=reply,
                            is_ai_generated=False,
                            status="sent",
                            created_at=now_utc,
                            whatsapp_message_id=wamid,
                            whatsapp_timestamp=int(now_utc.timestamp()),
                            sort_timestamp=now_utc
                        )
                        db.add(out_msg)
                        await db.execute(
                            update(Conversation)
                            .where(Conversation.id == conv.id)
                            .values(last_message_at=now_utc)
                        )
                        await db.commit()
                        logger.info(f"Rule-based reply sent to {from_number}")
                    # Lead capture in rule mode (existing)
                    try:
                        schema_result = await db.execute(
                            select(LeadSchema)
                            .where(LeadSchema.organization_id == org_id, LeadSchema.is_active == True)
                            .order_by(LeadSchema.updated_at.desc())
                        )
                        lead_schema = schema_result.scalars().first()
                        if lead_schema:
                            msg_result = await db.execute(
                                select(Message)
                                .where(Message.conversation_id == conv.id)
                                .order_by(Message.sort_timestamp.asc())
                                .limit(5)
                            )
                            history_messages = msg_result.scalars().all()
                            history = [
                                {"role": "assistant" if msg.direction == "outbound" else "customer", "text": msg.content or ""}
                                for msg in history_messages
                            ]
                            if not history or history[-1]["text"] != content:
                                history.append({"role": "customer", "text": content})
                            extracted_data = await extract_lead_from_conversation(
                                history,
                                lead_schema.schema_fields or [],
                                lead_schema.extraction_prompt
                            )
                            if extracted_data:
                                await create_lead(
                                    org_id=str(org_id),
                                    customer_phone=from_number,
                                    extracted_data=extracted_data,
                                    schema_id=str(lead_schema.id),
                                    conversation_id=str(conv.id),
                                    customer_name=extracted_data.get("name", ""),
                                    lead_score=extracted_data.get("lead_score", 70),
                                    interest=extracted_data.get("interest", ""),
                                    service=extracted_data.get("service", ""),
                                    urgency=extracted_data.get("urgency", "medium"),
                                    intent=extracted_data.get("intent", "general"),
                                    sentiment=extracted_data.get("sentiment", "neutral"),
                                    conversion_probability=extracted_data.get("conversion_probability", 0.0),
                                    follow_up_scheduled_at=extracted_data.get("follow_up_scheduled_at"),
                                    lead_stage=extracted_data.get("lead_stage", "new"),
                                    rule_state=extracted_data.get("rule_state", {})
                                )
                                logger.info(f"Lead captured in rule mode")
                    except Exception as e:
                        logger.error(f"Lead capture in rule mode failed: {e}", exc_info=True)
                    return {"status": "ok"}
                else:
                    # No rule matched -> fall back to AI mode
                    logger.info(f"No rule matched, falling back to AI mode")
                    conv.reply_mode = 'ai'
                    await db.commit()
                    # Continue to AI processing below (not reached due to return, but we let it fall through)
            # 2. NEW GENERIC BOT ENGINE (JSON‑driven)
            elif conv.reply_mode == 'bot':
                # Check if generic bot is allowed for this organisation
                if not is_generic_enabled_for_org(str(org_id)):
                    logger.warning(f"Bot mode enabled but generic bot not allowed for org {org_id}. Falling back to AI.")
                    conv.reply_mode = 'ai'
                    await db.commit()
                else:
                    active_config = await get_active_bot_config(str(org_id))
                    if not active_config:
                        logger.warning(f"Bot mode enabled but no active config for org {org_id}. Falling back to AI.")
                        conv.reply_mode = 'ai'
                        await db.commit()
                    else:
                        logger.info(f"Using GenericBotEngine for org {org_id}, conv {conv.id}")
                        logger.info(json.dumps({
                            "event": "generic_bot_used",
                            "org_id": str(org_id),
                            "conversation_id": str(conv.id)
                        }))
                        engine = GenericBotEngine(active_config)
                        current_state = conv.rule_state or {}
                        try:
                            action = engine.process(content, current_state)
                            if action:
                                # Persist the new state immediately
                                new_state = action.get("new_state", current_state)
                                conv.rule_state = new_state
                                await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=new_state))
                                await db.commit()
                                logger.info(f"DEBUG: Saving state: {new_state}")

                                action_type = action["action"]
                                data = action.get("data", {})

                                logger.info(f"Generic bot action: {action_type} for conv {conv.id}")

                                if action_type == "ask":
                                    question = data["question"]
                                    field_type = data.get("field_type", "text")
                                    options = data.get("options", [])
                                    if field_type in ["button", "list"] and options:
                                        success, wamid = await send_whatsapp_interactive(
                                            from_number, question, options, str(org_id)
                                        )
                                    else:
                                        success, wamid = await send_whatsapp_text(from_number, question, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type in ["validation_error", "invalid_field", "confirmation_invalid"]:
                                    error_msg = data.get("error") or data.get("message") or "Invalid input"
                                    await send_whatsapp_text(from_number, error_msg, str(org_id))
                                    return {"status": "ok"}

                                elif action_type == "ask_confirmation":
                                    # Send interactive buttons (Confirm / Change)
                                    question = data.get("message")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}
                                elif action_type == "ask_which_field":
                                    # Send interactive list for field selection
                                    question = data.get("question", "Which field would you like to change?")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "ask_new_value":
                                    await send_whatsapp_text(from_number, f"Please provide the new value for {data['field']}:", str(org_id))
                                    return {"status": "ok"}

                                elif action_type == "create_lead":
                                    await create_lead_from_generic_bot(str(org_id), str(conv.id), from_number, data)
                                    await send_whatsapp_text(from_number, "Thank you! Your information has been saved.", str(org_id))
                                    # Mark conversation as completed
                                    conv.rule_state["completed"] = True
                                    await db.execute(
                                        update(Conversation)
                                        .where(Conversation.id == conv.id)
                                        .values(rule_state=conv.rule_state)
                                    )
                                    await db.commit()
                                    return {"status": "ok"}
                                elif action_type == "ask_which_field":
                                    # Send interactive list for field selection
                                    question = data.get("question", "Which field would you like to change?")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    if success:
                                        # Save the sent message (optional)
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "ask_new_value_with_options":
                                    # Send interactive message (buttons or list) to choose new value
                                    question = data.get("question")
                                    options = data.get("options", [])
                                    if data.get("type") == "button":
                                        # Use interactive buttons
                                        success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    else:
                                        # Use list
                                        success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "ask_custom_field":
                                    # Plain text prompt to type field name
                                    message = data.get("message", "Please type the field name you want to change:")
                                    success, wamid = await send_whatsapp_text(from_number, message, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=message,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "ask_custom_value":
                                    # Plain text prompt to type custom value
                                    message = data.get("message", "Please type the new value:")
                                    success, wamid = await send_whatsapp_text(from_number, message, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=message,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}
                                elif action_type == "ask_continue_or_new":
                                    question = data.get("message")
                                    options = data.get("options", [])
                                    success, wamid = await send_whatsapp_interactive(from_number, question, options, str(org_id))
                                    if success:
                                        out_msg = Message(
                                            id=uuid.uuid4(),
                                            conversation_id=conv.id,
                                            direction="outbound",
                                            content=question,
                                            is_ai_generated=True,
                                            status="sent",
                                            created_at=datetime.now(timezone.utc),
                                            whatsapp_message_id=wamid,
                                            whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                                            sort_timestamp=datetime.now(timezone.utc)
                                        )
                                        db.add(out_msg)
                                        await db.commit()
                                    return {"status": "ok"}

                                elif action_type == "send_text":
                                    await send_whatsapp_text(from_number, data["message"], str(org_id))
                                    return {"status": "ok"}

                        except Exception as e:
                            logger.exception(f"Generic bot engine error: {e}")
                            # On error, fall back to AI mode
                            conv.reply_mode = 'ai'
                            await db.commit()
                            # Continue to AI processing (outside this block)

            # 3. HUMAN MODE – no reply
            if conv.reply_mode == 'human':
                logger.info(f"Conversation {conv.id} in human mode – skipping AI reply")
                return {"status": "ok"}

            # 4. AI MODE (fallback for any other mode, including when bot/rule fallbacks happen)
            # This also covers the case where reply_mode is 'ai' initially
            if conv.reply_mode in ['ai', None] or (conv.reply_mode == 'bot' and not action):
                if USE_ORCHESTRATION:
                    logger.info(f"Using ORCHESTRATED processor for {from_number}")
                    background_tasks.add_task(
                        OrchestratedProcessor().process_message,
                        str(conv.id),
                        from_number,
                        content,
                        str(org_id)
                    )
                else:
                    logger.info(f"Using LEGACY processor for {from_number}")
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