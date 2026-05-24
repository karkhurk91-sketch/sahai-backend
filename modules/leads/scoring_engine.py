from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from modules.common.models import Lead
from datetime import datetime

async def score_lead(db: AsyncSession, lead_id: str):
    """Score a single lead"""
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    
    if not lead:
        return None
    
    # Simple scoring logic
    score = 50  # Base score
    
    # Update score
    await db.execute(
        update(Lead)
        .where(Lead.id == lead_id)
        .values(score=score, last_scored_at=datetime.now())
    )
    await db.commit()
    
    return score

async def rescore_all_active_leads(db: AsyncSession):
    """Rescore all active leads"""
    result = await db.execute(
        select(Lead).where(Lead.status == 'active')
    )
    leads = result.scalars().all()
    
    for lead in leads:
        await score_lead(db, lead.id)
    
    return len(leads)
