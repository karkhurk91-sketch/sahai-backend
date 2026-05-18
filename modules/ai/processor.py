import asyncio
import uuid
from datetime import datetime, timedelta
from sqlalchemy import text
from modules.ai.agent import get_agent_for_user_compat
from modules.message.sender import send_whatsapp_text, send_whatsapp_template
from modules.ai.lead_capture import create_lead
from modules.common.database import sync_engine, AsyncSessionLocal
from modules.common.models import Conversation, Message
from modules.common.logger import get_logger

logger = get_logger(__name__)

def has_recent_customer_message(customer_phone: str, org_id: str) -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    with sync_engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1 FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE c.customer_phone_number = :phone
                AND c.organization_id = :org_id
                AND m.direction = 'inbound'
                AND m.created_at > :cutoff
                LIMIT 1
            """),
            {"phone": customer_phone, "org_id": org_id, "cutoff": cutoff}
        )
        return result.fetchone() is not None

def get_lead_capture_enabled(org_id: str) -> bool:
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT enable_lead_capture FROM ai_configurations WHERE organization_id = :org_id"),
                {"org_id": org_id}
            )
            row = result.fetchone()
            return row[0] if row else True
    except Exception as e:
        logger.error(f"Error checking lead capture config: {e}")
        return True

async def process_incoming_message(message: dict):
    conversation_id = message.get("conversation_id")
    user_id = message["from_number"]
    user_text = message["text"]
    org_id = message.get("org_id")
    timestamp = message.get("timestamp")

    if not conversation_id:
        logger.error("Missing conversation_id")
        return

    await _process_and_reply(
        conversation_id=conversation_id,
        customer_phone=user_id,
        customer_message=user_text,
        org_id=org_id,
        timestamp=timestamp
    )

async def _process_and_reply(
    conversation_id: str,
    customer_phone: str,
    customer_message: str,
    org_id: str,
    timestamp: int = None
):
    logger.info(f"Processing message from {customer_phone}: {customer_message}")

    recent = has_recent_customer_message(customer_phone, org_id)
    lead_capture_enabled = get_lead_capture_enabled(org_id)
    logger.info(f"Lead capture enabled: {lead_capture_enabled}")

    agent = get_agent_for_user_compat(customer_phone, org_id)
    ai_response = agent.predict(customer_message)
    logger.info(f"AI response (first 200 chars): {ai_response[:200]}")

    lead_data = getattr(agent, '_pending_lead', None)
    logger.info(f"Raw lead_data from agent: {lead_data} (type: {type(lead_data)})")

    # --- Lead extraction: handle dictionary or boolean lead_data ---
    is_lead = False
    interest = customer_message[:100]  # fallback interest
    service = None
    score = 70

    if lead_capture_enabled and lead_data is not None:
        if isinstance(lead_data, dict):
            # lead_data is a dictionary: could have 'lead' key or be the lead itself
            if 'lead' in lead_data:
                is_lead = lead_data.get('lead', False)
                interest = lead_data.get('interest', customer_message[:100])
                service = lead_data.get('service')
                score = lead_data.get('score', 70)
            else:
                # Assume lead_data itself is the lead info (e.g., {"interest": "...", ...})
                is_lead = True
                interest = lead_data.get('interest', customer_message[:100])
                service = lead_data.get('service')
                score = lead_data.get('score', 70)
        elif isinstance(lead_data, bool):
            is_lead = lead_data
            # No additional details; keep fallback interest
        else:
            logger.warning(f"Unhandled lead_data type: {type(lead_data)}")

    # Send reply
    if recent:
        success, wamid = await send_whatsapp_text(to_number=customer_phone, text=ai_response, org_id=str(org_id))
    else:
        success, wamid = await send_whatsapp_template(
            to_number=customer_phone,
            template_name="hello",
            language_code="en",
            category="UTILITY",
            org_id=str(org_id)
        )

    if not success:
        logger.error(f"Failed to send reply to {customer_phone}")
        return

    logger.info(f"Reply sent to {customer_phone}")

    # Store AI message
    async with AsyncSessionLocal() as db:
        try:
            ai_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                direction="outbound",
                message_type="text",
                content=ai_response,
                is_ai_generated=True,
                status="sent",
                created_at=datetime.utcnow(),
                whatsapp_message_id=wamid
            )
            db.add(ai_msg)
            await db.execute(
                text("UPDATE conversations SET last_message_at = NOW() WHERE id = :conv_id"),
                {"conv_id": conversation_id}
            )
            await db.commit()
            logger.info("Stored AI reply")
        except Exception as e:
            logger.error(f"Failed to store message: {e}")
            await db.rollback()

    # --- Lead creation (only if is_lead is True) ---
    if is_lead:
        # Ensure score is integer
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 70
        logger.info(f"Creating lead: org={org_id}, phone={customer_phone}, interest={interest}, service={service}, score={score}")
        try:
            await create_lead(org_id, customer_phone, interest, service=service, lead_score=score)
            logger.info(f"Lead created for {customer_phone}")
        except Exception as e:
            logger.error(f"Lead creation failed: {e}", exc_info=True)
    else:
        logger.info(f"Lead NOT created. lead_data={lead_data}, lead_capture_enabled={lead_capture_enabled}")