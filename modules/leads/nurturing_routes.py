from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from uuid import UUID
from modules.common.database import get_db
from modules.auth.jwt import get_current_user
from modules.common.models import LeadNurturingSequence, LeadNurturingStep, LeadNurturingLog, Lead
from modules.common.logger import get_logger
import uuid

router = APIRouter(prefix="/api/leads", tags=["Lead Nurturing"])
logger = get_logger(__name__)


class StepCreate(BaseModel):
    step_order: int
    delay_days: int
    template_id: Optional[UUID] = None
    custom_message: Optional[str] = None
    condition: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SequenceCreate(BaseModel):
    name: str
    is_active: Optional[bool] = True
    steps: List[StepCreate] = []


class SequenceUpdate(BaseModel):
    name: Optional[str]
    is_active: Optional[bool]
    steps: Optional[List[StepCreate]]


class AssignPayload(BaseModel):
    sequence_id: UUID


@router.get("/nurturing/sequences")
async def list_sequences(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    result = await db.execute(select(LeadNurturingSequence).where(LeadNurturingSequence.organization_id == org_id))
    sequences = result.scalars().all()
    out = []
    for seq in sequences:
        steps_res = await db.execute(select(LeadNurturingStep).where(LeadNurturingStep.sequence_id == seq.id).order_by(LeadNurturingStep.step_order))
        steps = [s.__dict__ for s in steps_res.scalars().all()]
        seq_dict = {k: v for k, v in seq.__dict__.items() if not k.startswith('_')}
        seq_dict['steps'] = [{k: v for k, v in s.items() if not k.startswith('_')} for s in steps]
        out.append(seq_dict)
    return out


@router.post("/nurturing/sequences")
async def create_sequence(payload: SequenceCreate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    seq = LeadNurturingSequence(id=uuid.uuid4(), organization_id=org_id, name=payload.name, is_active=payload.is_active)
    db.add(seq)
    await db.commit()
    for step in payload.steps:
        s = LeadNurturingStep(id=uuid.uuid4(), sequence_id=seq.id, step_order=step.step_order, delay_days=step.delay_days, template_id=step.template_id, custom_message=step.custom_message, condition=step.condition or {})
        db.add(s)
    await db.commit()
    return {"status": "created", "id": str(seq.id)}


@router.get("/nurturing/sequences/{sequence_id}")
async def get_sequence(sequence_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    res = await db.execute(select(LeadNurturingSequence).where(LeadNurturingSequence.id == sequence_id, LeadNurturingSequence.organization_id == org_id))
    seq = res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    steps_res = await db.execute(select(LeadNurturingStep).where(LeadNurturingStep.sequence_id == seq.id).order_by(LeadNurturingStep.step_order))
    steps = [ {k:v for k,v in s.__dict__.items() if not k.startswith('_')} for s in steps_res.scalars().all() ]
    seq_dict = {k:v for k,v in seq.__dict__.items() if not k.startswith('_')}
    seq_dict['steps'] = steps
    return seq_dict


@router.put("/nurturing/sequences/{sequence_id}")
async def update_sequence(sequence_id: UUID, payload: SequenceUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    res = await db.execute(select(LeadNurturingSequence).where(LeadNurturingSequence.id == sequence_id, LeadNurturingSequence.organization_id == org_id))
    seq = res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if payload.name is not None:
        seq.name = payload.name
    if payload.is_active is not None:
        seq.is_active = payload.is_active
    await db.commit()
    if payload.steps is not None:
        # delete existing steps and recreate
        await db.execute(delete(LeadNurturingStep).where(LeadNurturingStep.sequence_id == seq.id))
        for step in payload.steps:
            s = LeadNurturingStep(id=uuid.uuid4(), sequence_id=seq.id, step_order=step.step_order, delay_days=step.delay_days, template_id=step.template_id, custom_message=step.custom_message, condition=step.condition or {})
            db.add(s)
        await db.commit()
    return {"status": "updated"}


@router.delete("/nurturing/sequences/{sequence_id}")
async def delete_sequence(sequence_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    res = await db.execute(select(LeadNurturingSequence).where(LeadNurturingSequence.id == sequence_id, LeadNurturingSequence.organization_id == org_id))
    seq = res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    await db.delete(seq)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{lead_id}/nurturing/assign")
async def assign_sequence_to_lead(lead_id: UUID, payload: AssignPayload, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    # Ensure lead exists and belongs to org
    res = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    # verify sequence exists
    seq_res = await db.execute(select(LeadNurturingSequence).where(LeadNurturingSequence.id == payload.sequence_id, LeadNurturingSequence.organization_id == org_id))
    seq = seq_res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    lead.active_nurturing_sequence_id = seq.id
    lead.last_nurturing_step = 0
    lead.last_nurturing_sent_at = None
    await db.commit()
    # enqueue immediate check for this lead
    try:
        from modules.queue.producer import celery_app
        celery_app.send_task('modules.leads.nurturing_scheduler.process_nurturing_for_lead', args=[str(lead.id)])
    except Exception:
        logger.exception("Failed to enqueue nurturing task after assign")
    return {"status": "assigned"}


@router.post("/{lead_id}/nurturing/unassign")
async def unassign_sequence_from_lead(lead_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    res = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.active_nurturing_sequence_id = None
    lead.last_nurturing_step = 0
    lead.last_nurturing_sent_at = None
    await db.commit()
    return {"status": "unassigned"}


@router.post("/{lead_id}/nurturing/trigger")
async def trigger_next_step_for_lead(lead_id: UUID, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    res = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        from modules.leads.nurturing_scheduler import process_nurturing_for_lead_sync
        await process_nurturing_for_lead_sync(str(lead.id))
        return {"status": "triggered"}
    except Exception as e:
        logger.exception("Manual trigger failed")
        raise HTTPException(status_code=500, detail=str(e))
