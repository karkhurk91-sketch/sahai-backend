# modules/leads/scoring_engine.py
from sqlalchemy.ext.asyncio import AsyncSession  # <-- ADD THIS LINE
from sqlalchemy import select, update
from modules.common.models import Lead
from modules.ml.scoring import predict_conversion_probability
from modules.ml.feature_extractor import extract_features_for_lead
from modules.common.database import AsyncSessionLocal
from modules.common.logger import get_logger
from datetime import datetime

logger = get_logger(__name__)

async def score_lead(db: AsyncSession, lead_id: str):
    """Recalculate lead score using ML model."""
    try:
        lead = await db.get(Lead, lead_id)
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return

        # Fetch conversation messages if needed
        from modules.common.models import Message
        msg_result = await db.execute(
            select(Message).where(Message.conversation_id == lead.conversation_id).order_by(Message.created_at)
        )
        conversation_messages = msg_result.scalars().all()

        features = extract_features_for_lead(lead, conversation_messages)
        prob = predict_conversion_probability(features)
        lead.conversion_probability = prob
        lead.lead_score = int(prob * 100)
        lead.last_scored_at = datetime.utcnow()

        await db.commit()
        logger.info(f"Scored lead {lead_id}: {lead.lead_score}")
    except Exception as e:
        logger.error(f"Error scoring lead {lead_id}: {e}", exc_info=True)
        await db.rollback()


async def rescore_all_active_leads():
    """Background task to rescore all active leads."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead).where(Lead.status.in_(['new', 'contacted', 'qualified']))
        )
        leads = result.scalars().all()
        for lead in leads:
            await score_lead(db, str(lead.id))
        logger.info(f"Rescored {len(leads)} leads")