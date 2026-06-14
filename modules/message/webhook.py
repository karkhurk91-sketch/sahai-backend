from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from uuid import UUID

from modules.common.database import get_db
from modules.common.models import Organization, Conversation
from modules.message.handlers import process_status_updates, parse_incoming_message, save_incoming_message, handle_rule_mode, handle_bot_mode, handle_ai_mode
from modules.message.utils import download_media_background, get_or_create_lead
from modules.message.services.lead_service import get_last_lead_data
from modules.message.services.transcription import transcribe_voice_note
from modules.message.services.media_service import send_whatsapp_media, send_whatsapp_interactive
from modules.common.logger import get_logger
from modules.ml.sentiment import analyze_sentiment
from modules.ml.intent import simple_intent
from modules.websocket import send_alert
from modules.message.utils import download_media_background, get_or_create_lead, process_lead_ml_background


logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])

@router.get("")
async def verify_webhook(hub_mode: str = None, hub_verify_token: str = None, hub_challenge: int = None):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("VERIFY_TOKEN"):
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

        # Process status updates
        await process_status_updates(value, db)

        # Process incoming messages
        if "messages" in value:
            msg_data = value["messages"][0]
            parsed = await parse_incoming_message(msg_data, value)
            from_number = parsed["from_number"]
            timestamp = parsed["timestamp"]
            business_phone_number = parsed["business_phone_number"]

            # Find organisation
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

            # Language detection
            if not conv.rule_state.get("lang"):
                user_locale = msg_data.get("user_locale")
                if user_locale:
                    detected = "hi" if user_locale.startswith("hi") else "en"
                    conv.rule_state["lang"] = detected
                    await db.commit()
                    logger.info(f"Auto-detected language: {detected} for conv {conv.id}")

            # Voice transcription
            if parsed["message_type"] == "audio" and parsed["media_whatsapp_id"]:
                config = await get_whatsapp_config(str(org_id))
                if config:
                    wa = WhatsAppService(config['access_token'], config['phone_number_id'])
                    media_url = await wa.get_media_url(parsed["media_whatsapp_id"])
                    if media_url:
                        transcribed = await transcribe_voice_note(media_url, config['access_token'])
                        if transcribed:
                            parsed["content"] = transcribed
                            parsed["message_type"] = "text"
                            logger.info(f"Transcribed voice note: {transcribed[:100]}...")

            # Save incoming message
            new_message_id = await save_incoming_message(db, conv.id, org_id, parsed, parsed.get("media_whatsapp_id"))

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

            if parsed.get("media_whatsapp_id"):
                background_tasks.add_task(
                    download_media_background,
                    new_message_id,
                    parsed["media_whatsapp_id"],
                    conv.id,
                    str(org_id),
                    parsed.get("media_file_name", "file"),
                    parsed.get("media_content_type", "application/octet-stream")
                )

            # Sentiment analysis
            if conv.reply_mode == 'bot':
                sentiment = analyze_sentiment(parsed["content"])
                sentiment_score = 1.0 if sentiment['label'] == 'POSITIVE' else -1.0 if sentiment['label'] == 'NEGATIVE' else 0.0
                lead.sentiment_score = sentiment_score
                lead.intent_label = simple_intent(parsed["content"])
                await db.commit()
            else:
                background_tasks.add_task(process_lead_ml_background, lead.id, conv.id, parsed["content"])

            # Dispatch reply based on mode
            handled = False
            org_id_str = str(org_id)
            conv_id_str = str(conv.id)

            if conv.reply_mode == 'rule':
                handled = await handle_rule_mode(conv, from_number, parsed["content"], org_id_str, conv_id_str, db)
            elif conv.reply_mode == 'bot':
                handled = await handle_bot_mode(conv, from_number, parsed["content"], org_id_str, conv_id_str, db, org_id, background_tasks)

            if not handled and conv.reply_mode in ['ai', None] or (conv.reply_mode == 'bot' and not handled):
                await handle_ai_mode(conv, from_number, parsed["content"], org_id_str, conv_id_str, background_tasks)

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        await db.rollback()

    return {"status": "ok"}
