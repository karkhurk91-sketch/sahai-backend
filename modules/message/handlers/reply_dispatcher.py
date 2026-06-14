from datetime import datetime, timezone
import uuid
import os
from sqlalchemy import select, update
from modules.common.models import Conversation, Message
from modules.message.sender import send_whatsapp_text
from modules.ai.rule_processor import get_rule_reply
from modules.ai.generic_bot_engine import GenericBotEngine
from modules.ai.bot_config_loader import get_active_bot_config
from modules.ai.processor import process_incoming_message
from modules.ai.orchestrated_processor import OrchestratedProcessor
from modules.message.services.lead_service import get_last_lead_data, create_lead_from_generic_bot
from modules.message.services.media_service import send_whatsapp_media, send_whatsapp_interactive
from modules.websocket import manager
from modules.common.logger import get_logger

logger = get_logger(__name__)
USE_ORCHESTRATION = os.getenv("USE_ORCHESTRATION", "false").lower() == "true"
USE_GENERIC_BOT = os.getenv("USE_GENERIC_BOT", "false").lower() == "true"
GENERIC_BOT_ORG_WHITELIST = os.getenv("GENERIC_BOT_ORG_IDS", "")
WHITELIST_ORGS = set(GENERIC_BOT_ORG_WHITELIST.split(",")) if GENERIC_BOT_ORG_WHITELIST else set()

def is_generic_enabled_for_org(org_id: str) -> bool:
    if WHITELIST_ORGS:
        return org_id in WHITELIST_ORGS
    return USE_GENERIC_BOT

# ---------- Rule engine ----------
async def handle_rule_mode(conv, from_number, content, org_id_str, conv_id_str, db):
    logger.info(f"Using rule engine for org {org_id_str}")
    await manager.send_typing_start(org_id_str, conv_id_str, "rule")
    try:
        reply, updated_state = await get_rule_reply(org_id_str, conv_id_str, content, from_number)
        if updated_state:
            conv.rule_state = updated_state
            await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=updated_state))
            await db.commit()
        if reply == "__INTERACTIVE__":
            return True
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
            return True
        else:
            conv.reply_mode = 'ai'
            await db.commit()
            return False
    finally:
        await manager.send_typing_stop(org_id_str, conv_id_str)

# ---------- Bot engine (full) ----------
async def handle_bot_mode(conv, from_number, content, org_id_str, conv_id_str, db, org_id, background_tasks):
    if not is_generic_enabled_for_org(str(org_id)):
        logger.warning("Bot mode not allowed, falling back to AI")
        conv.reply_mode = 'ai'
        await db.commit()
        return False
    active_config = await get_active_bot_config(str(org_id))
    if not active_config:
        logger.warning("No active config, falling back to AI")
        conv.reply_mode = 'ai'
        await db.commit()
        return False
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
            # ===== Action handlers =====
            if action_type == "ask_language":
                question = data.get("message")
                options = data.get("options", [])
                success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                if success:
                    await save_bot_message(question, wamid, msg_type="interactive")
                return True
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
                return True
            elif action_type in ["validation_error", "invalid_field", "confirmation_invalid"]:
                error_msg = data.get("error") or data.get("message") or "Invalid input"
                success, wamid = await send_whatsapp_text(from_number, error_msg, org_id_str)
                if success:
                    await save_bot_message(error_msg, wamid)
                return True
            elif action_type == "ask_confirmation":
                question = data.get("message")
                options = data.get("options", [])
                success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                if success:
                    await save_bot_message(question, wamid, msg_type="interactive")
                return True
            elif action_type == "ask_which_field":
                question = data.get("question", "Which field would you like to change?")
                options = data.get("options", [])
                success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                if success:
                    await save_bot_message(question, wamid, msg_type="interactive")
                return True
            elif action_type == "ask_new_value":
                msg = f"Please provide the new value for {data['field']}:"
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                return True
            elif action_type == "ask_new_value_with_options":
                question = data.get("question")
                options = data.get("options", [])
                success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                if success:
                    await save_bot_message(question, wamid, msg_type="interactive")
                return True
            elif action_type == "ask_custom_field":
                msg = data.get("message", "Please type the field name you want to change:")
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                return True
            elif action_type == "ask_custom_value":
                msg = data.get("message", "Please type the new value:")
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                return True
            elif action_type == "ask_continue_or_new":
                question = data.get("message")
                options = data.get("options", [])
                success, wamid = await send_whatsapp_interactive(from_number, question, options, org_id_str)
                if success:
                    await save_bot_message(question, wamid, msg_type="interactive")
                return True
            elif action_type == "send_text":
                msg = data["message"]
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                return True
            elif action_type == "unmatched":
                msg = "I'll switch to AI mode to better answer your question."
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                conv.reply_mode = 'ai'
                await db.execute(update(Conversation).where(Conversation.id == conv.id).values(reply_mode='ai'))
                await db.commit()
                # Fall through to AI mode
                return False
            elif action_type == "create_lead":
                await create_lead_from_generic_bot(org_id_str, conv_id_str, from_number, data)
                msg = "Thank you! Your information has been saved."
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                conv.rule_state["completed"] = True
                await db.execute(update(Conversation).where(Conversation.id == conv.id).values(rule_state=conv.rule_state))
                await db.commit()
                return True
            elif action_type == "ask_booking":
                from modules.bot_builder.booking_helper import get_available_slots
                slots = await get_available_slots(org_id, data.get("booking_config"))
                if not slots:
                    msg = "No slots available. Please try later."
                    success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                    if success:
                        await save_bot_message(msg, wamid)
                    return True
                options = [{"id": slot["id"], "title": slot["display"]} for slot in slots]
                success, wamid = await send_whatsapp_interactive(from_number, data["question"], options, org_id_str)
                if success:
                    await save_bot_message(data["question"], wamid, msg_type="interactive")
                return True
            elif action_type == "create_booking":
                from modules.bot_builder.booking_helper import create_booking
                booking_id = await create_booking(org_id, conv.id, from_number, data)
                msg = f"Your booking has been confirmed! ID: {booking_id}"
                success, wamid = await send_whatsapp_text(from_number, msg, org_id_str)
                if success:
                    await save_bot_message(msg, wamid)
                conv.rule_state["completed"] = True
                await db.commit()
                return True
        return False
    except Exception as e:
        logger.exception(f"Generic bot engine error: {e}")
        conv.reply_mode = 'ai'
        await db.commit()
        return False
    finally:
        await manager.send_typing_stop(org_id_str, conv_id_str)

# ---------- AI mode ----------
async def handle_ai_mode(conv, from_number, content, org_id_str, conv_id_str, background_tasks):
    if USE_ORCHESTRATION:
        background_tasks.add_task(OrchestratedProcessor().process_message, conv_id_str, from_number, content, org_id_str)
    else:
        background_tasks.add_task(process_incoming_message, {"from_number": from_number, "text": content, "timestamp": None, "org_id": org_id_str, "conversation_id": conv_id_str})
    logger.info(f"Scheduled AI processing for message from {from_number}")
    return True
