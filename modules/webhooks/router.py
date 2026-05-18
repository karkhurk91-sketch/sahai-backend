from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.message.models import IncomingMessage
from modules.common.config import VERIFY_TOKEN
from modules.common.database import get_db
from modules.common.models import Organization, Conversation, Message
from modules.ai.processor import process_incoming_message
from modules.common.logger import get_logger
import uuid
from datetime import datetime

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp"])

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
    body = await request.json()
    logger.info(f"Webhook received: {body}")

    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        if "messages" in value:
            msg_data = value["messages"][0]
            from_number = msg_data["from"]
            text = msg_data["text"]["body"]
            timestamp = int(msg_data["timestamp"])
            business_phone_number = value["metadata"]["display_phone_number"]

            # Find organization
            result = await db.execute(
                select(Organization.id).where(Organization.whatsapp_phone_number == business_phone_number)
            )
            org = result.scalar_one_or_none()
            if not org:
                logger.warning(f"No organization found for WhatsApp number: {business_phone_number}")
                return {"status": "ignored", "reason": "unknown_whatsapp_number"}

            # Find or create conversation
            conv_result = await db.execute(
                select(Conversation).where(
                    Conversation.organization_id == org,
                    Conversation.customer_phone_number == from_number
                )
            )
            conv = conv_result.scalar_one_or_none()
            if not conv:
                conv = Conversation(
                    id=uuid.uuid4(),
                    organization_id=org,
                    customer_phone_number=from_number,
                    status="open",
                    started_at=datetime.utcnow(),
                    last_message_at=datetime.utcnow()
                )
                db.add(conv)
                await db.flush()

            # Save incoming message
            new_message = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                direction="inbound",
                content=text,
                is_ai_generated=False,
                created_at=datetime.utcnow()
            )
            db.add(new_message)
            await db.commit()

            # Queue for AI processing (using BackgroundTasks)
            background_tasks.add_task(
                process_incoming_message,
                {
                    "from_number": from_number,
                    "text": text,
                    "timestamp": timestamp,
                    "org_id": str(org),
                    "conversation_id": str(conv.id)
                }
            )
            logger.info(f"Scheduled processing for message from {from_number}")

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")

    return {"status": "ok"}