import uuid
from pathlib import Path
import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.database import AsyncSessionLocal
from modules.common.models import Message, Lead, Conversation
from modules.message.sender import get_whatsapp_config, WhatsAppService
from modules.common.logger import get_logger
from datetime import datetime
from modules.ml.sentiment import analyze_sentiment
from modules.ml.intent import simple_intent
from modules.ml.scoring import predict_conversion_probability
from modules.ml.feature_extractor import extract_features_for_lead
from modules.ml.duplicates import get_embedding
from modules.websocket import send_alert
from sqlalchemy import select

logger = get_logger(__name__)

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
                from modules.websocket import send_alert
                send_alert(lead.id, lead.customer_name or lead.customer_phone, prob)

            logger.info(f"ML processing completed for lead {lead_id}: score={lead.lead_score}, intent={intent}")

    except Exception as e:
        logger.error(f"ML background processing failed for lead {lead_id}: {e}", exc_info=True)
