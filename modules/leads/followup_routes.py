from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from uuid import UUID
from modules.common.database import get_db
from modules.common.models import Lead
from modules.queue.producer import celery_app
from modules.common.logger import get_logger
from modules.auth.jwt import get_current_user
from datetime import datetime

router = APIRouter(prefix="/api/leads", tags=["Follow-ups"])
logger = get_logger(__name__)


class SchedulePayload(BaseModel):
    scheduled_at: datetime


@router.get("/followups")
async def list_followups(limit: int = Query(50, ge=1, le=500), offset: int = 0, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get('org_id')
    q = select(Lead).where(Lead.organization_id == org_id, Lead.follow_up_scheduled_at != None).order_by(Lead.follow_up_scheduled_at).limit(limit).offset(offset)
    res = await db.execute(q)
    rows = res.scalars().all()
    out = []
    for l in rows:
        out.append({
            'id': str(l.id),
            'customer_phone': l.customer_phone,
            'customer_name': l.customer_name,
            'scheduled_at': l.follow_up_scheduled_at.isoformat() if l.follow_up_scheduled_at else None,
            'status': l.status
        })
    return out


@router.post("/{lead_id}/followup/schedule")
async def schedule_followup(lead_id: UUID, payload: SchedulePayload, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get('org_id')
    q = select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
    res = await db.execute(q)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.follow_up_scheduled_at = payload.scheduled_at
    db.add(lead)
    await db.commit()
    return {"status": "scheduled", "lead_id": str(lead.id), "scheduled_at": payload.scheduled_at.isoformat()}


@router.post("/{lead_id}/followup/cancel")
async def cancel_followup(lead_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get('org_id')
    q = select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
    res = await db.execute(q)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.follow_up_scheduled_at = None
    db.add(lead)
    await db.commit()
    return {"status": "cancelled", "lead_id": str(lead.id)}


@router.post("/{lead_id}/followup/trigger")
async def trigger_followup(lead_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get('org_id')
    q = select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
    res = await db.execute(q)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    # enqueue immediate celery task
    try:
        celery_app.send_task('modules.queue.tasks.process_follow_up', args=[str(lead.id)])
    except Exception:
        logger.exception('Failed to enqueue follow-up')
        raise HTTPException(status_code=500, detail='Failed to enqueue follow-up')
    return {"status": "triggered", "lead_id": str(lead.id)}
