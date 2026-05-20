import asyncio
import uuid
from datetime import datetime, timedelta
from sqlalchemy import text, select
from modules.ai.agent import get_agent_for_user_compat
from modules.ai.lead_capture import create_lead
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.common.database import sync_engine, AsyncSessionLocal
from modules.common.models import Conversation, Message, LeadSchema
from modules.common.logger import get_logger
from modules.leads.assignment_engine import auto_assign_lead, determine_lead_intelligence
from modules.message.sender import send_whatsapp_text, send_whatsapp_template

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

    lead_schema = None
    extracted_lead_data = {}
    conversation = None
    history = []
    if lead_capture_enabled:
        try:
            async with AsyncSessionLocal() as db:
                schema_result = await db.execute(
                    select(LeadSchema)
                    .where(LeadSchema.organization_id == uuid.UUID(org_id), LeadSchema.is_active == True)
                    .order_by(LeadSchema.updated_at.desc())
                )
                lead_schema = schema_result.scalars().first()
                conversation = await db.get(Conversation, uuid.UUID(conversation_id))
                message_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == uuid.UUID(conversation_id))
                    .order_by(Message.created_at.desc())
                    .limit(10)
                )
                history_messages = message_result.scalars().all()
                history = [
                    {
                        "role": "assistant" if msg.direction == "outbound" else "customer",
                        "text": msg.content or ""
                    }
                    for msg in reversed(history_messages)
                ]
                if lead_schema:
                    extracted_lead_data = await extract_lead_from_conversation(
                        history,
                        lead_schema.schema_fields or [],
                        lead_schema.extraction_prompt
                    )
                    logger.info(f"Extracted lead data from schema {lead_schema.id}: {extracted_lead_data}")
        except Exception as e:
            logger.error(f"Lead schema extraction failed: {e}", exc_info=True)

    # --- Lead extraction: handle dictionary or boolean lead_data ---
    is_lead = False
    interest = customer_message[:100]  # fallback interest
    service = None
    score = 70

    if lead_capture_enabled and lead_data is not None:
        if isinstance(lead_data, dict):
            if 'lead' in lead_data:
                is_lead = lead_data.get('lead', False)
                interest = lead_data.get('interest', customer_message[:100])
                service = lead_data.get('service')
                score = lead_data.get('score', 70)
            else:
                is_lead = True
                interest = lead_data.get('interest', customer_message[:100])
                service = lead_data.get('service')
                score = lead_data.get('score', 70)
        elif isinstance(lead_data, bool):
            is_lead = lead_data
        else:
            logger.warning(f"Unhandled lead_data type: {type(lead_data)}")

    if extracted_lead_data:
        is_lead = True
        score = int(extracted_lead_data.get('lead_score', score) or score)

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

        try:
            intelligence = await determine_lead_intelligence(history, extracted_lead_data or {
                "interest": interest,
                "service": service,
                "lead_score": score,
            })

            urgency_value = extracted_lead_data.get('urgency') or intelligence.get('urgency')
            intent_value = extracted_lead_data.get('intent') or intelligence.get('intent')
            sentiment_value = extracted_lead_data.get('sentiment') or intelligence.get('sentiment')
            conversion_probability_value = extracted_lead_data.get('conversion_probability') or intelligence.get('conversion_probability')
            score_value = extracted_lead_data.get('lead_score') or score
            interest_value = extracted_lead_data.get('interest') or interest
            service_value = extracted_lead_data.get('service') if extracted_lead_data.get('service') is not None else service

            if extracted_lead_data:
                logger.info(f"Creating schema-backed lead for conversation {conversation_id}")
                await create_lead(
                    org_id,
                    customer_phone,
                    extracted_data=extracted_lead_data,
                    schema_id=str(lead_schema.id) if lead_schema else None,
                    conversation_id=conversation_id,
                    customer_name=(conversation.customer_name if conversation else ""),
                    lead_score=score_value,
                    interest=interest_value,
                    service=service_value,
                    urgency=urgency_value,
                    intent=intent_value,
                    sentiment=sentiment_value,
                    conversion_probability=conversion_probability_value,
                    follow_up_scheduled_at=intelligence.get("follow_up_scheduled_at"),
                    lead_stage=intelligence.get("lead_stage"),
                    rule_state=intelligence.get("rule_state")
                )
                await auto_assign_lead(org_id, conversation_id, extracted_lead_data)
            else:
                logger.info(f"Fallback lead creation: org={org_id}, phone={customer_phone}, interest={interest}, service={service}, score={score}")
                await create_lead(
                    org_id,
                    customer_phone,
                    extracted_data={},
                    schema_id=None,
                    conversation_id=conversation_id,
                    customer_name=(conversation.customer_name if conversation else ""),
                    lead_score=score_value,
                    interest=interest_value,
                    service=service_value,
                    urgency=urgency_value,
                    intent=intent_value,
                    sentiment=sentiment_value,
                    conversion_probability=conversion_probability_value,
                    follow_up_scheduled_at=intelligence.get("follow_up_scheduled_at"),
                    lead_stage=intelligence.get("lead_stage"),
                    rule_state=intelligence.get("rule_state")
                )
                await auto_assign_lead(org_id, conversation_id, extracted_lead_data or {"service": service, "interest": interest})
            logger.info(f"Lead created for {customer_phone}")
        except Exception as e:
            logger.error(f"Lead creation failed: {e}", exc_info=True)
    else:
        logger.info(f"Lead NOT created. lead_data={lead_data}, extracted_lead_data={extracted_lead_data}, lead_capture_enabled={lead_capture_enabled}")

