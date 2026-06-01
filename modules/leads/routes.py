from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from modules.common.database import get_db
from modules.common.models import User, Conversation, Lead, LeadSchema, Organization
from modules.auth.jwt import get_current_user
from modules.common.masking import MaskingConfig, apply_masking_to_dict
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from modules.auth.routes import get_current_user
import uuid

router = APIRouter(prefix="/api/leads", tags=["Leads"])

class LeadSchemaBase(BaseModel):
    name: str
    schema_fields: List[Dict[str, Any]]
    extraction_prompt: Optional[str] = None
    is_active: bool = True

class LeadUpdate(BaseModel):
    status: str

@router.get("")
async def list_leads(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(Lead).order_by(Lead.created_at.desc())
    if org_id:
        query = query.where(Lead.organization_id == org_id)
    result = await db.execute(query)
    leads = result.scalars().all()
    
    # Get organization settings for masking
    if org_id:
        org_result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = org_result.scalar_one_or_none()
        masking_config = MaskingConfig.from_dict(org.settings or {}) if org else MaskingConfig()
    else:
        masking_config = MaskingConfig()
    
    # Apply masking based on role
    user_role = current_user.get("role", "viewer")
    masked_leads = [
        apply_masking_to_dict(
            {**lead.__dict__, "_sa_instance_state": None},
            user_role,
            masking_config,
            phone_fields=["customer_phone"],
            email_fields=["email"]
        ) for lead in leads
    ]
    # Remove SQLAlchemy internal attributes
    masked_leads = [
        {k: v for k, v in l.items() if not k.startswith("_")}
        for l in masked_leads
    ]
    
    return masked_leads


def _serialize_model(model):
    return {k: v for k, v in model.__dict__.items() if not k.startswith("_")}


@router.post("/schemas")
async def create_lead_schema(
    payload: LeadSchemaBase,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="Organization context is required")

    schema = LeadSchema(
        organization_id=org_id,
        name=payload.name,
        schema_fields=payload.schema_fields,
        extraction_prompt=payload.extraction_prompt,
        is_active=payload.is_active
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)
    return _serialize_model(schema)


@router.get("/schemas")
async def list_lead_schemas(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(LeadSchema).where(LeadSchema.organization_id == org_id, LeadSchema.is_active == True)
    result = await db.execute(query)
    schemas = result.scalars().all()
    return [_serialize_model(schema) for schema in schemas]


@router.get("/schemas/{schema_id}")
async def get_lead_schema(
    schema_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(LeadSchema).where(LeadSchema.id == schema_id, LeadSchema.organization_id == org_id)
    result = await db.execute(query)
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    return _serialize_model(schema)


@router.put("/schemas/{schema_id}")
async def update_lead_schema(
    schema_id: UUID,
    payload: LeadSchemaBase,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(LeadSchema).where(LeadSchema.id == schema_id, LeadSchema.organization_id == org_id)
    result = await db.execute(query)
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    schema.name = payload.name
    schema.schema_fields = payload.schema_fields
    schema.extraction_prompt = payload.extraction_prompt
    schema.is_active = payload.is_active
    await db.commit()
    await db.refresh(schema)
    return _serialize_model(schema)


@router.delete("/schemas/{schema_id}")
async def delete_lead_schema(
    schema_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(LeadSchema).where(LeadSchema.id == schema_id, LeadSchema.organization_id == org_id)
    result = await db.execute(query)
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    await db.delete(schema)
    await db.commit()
    return {"status": "deleted"}


@router.get("/conversation/{conv_id}")
async def get_lead_by_conversation(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    conversation_result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.organization_id == org_id)
    )
    conversation = conversation_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    query = select(Lead).where(
        Lead.organization_id == org_id,
        or_(
            Lead.conversation_id == conv_id,
            Lead.customer_phone == conversation.customer_phone_number,
        )
    )
    result = await db.execute(query)
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead_payload = _serialize_model(lead)
    if lead.schema_id:
        schema_result = await db.execute(
            select(LeadSchema).where(LeadSchema.id == lead.schema_id, LeadSchema.organization_id == org_id)
        )
        schema = schema_result.scalar_one_or_none()
        lead_payload["schema"] = _serialize_model(schema) if schema else None
    else:
        lead_payload["schema"] = None
    return lead_payload


@router.get("/analytics/summary")
async def get_lead_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    query = select(Lead).where(Lead.organization_id == org_id)
    result = await db.execute(query)
    leads = result.scalars().all()

    status_counts = {}
    stage_counts = {}
    urgency_counts = {}
    sentiment_counts = {}
    total_probability = 0.0

    for lead in leads:
        status_counts[lead.status or "unknown"] = status_counts.get(lead.status or "unknown", 0) + 1
        stage_counts[lead.lead_stage or "unknown"] = stage_counts.get(lead.lead_stage or "unknown", 0) + 1
        urgency_counts[lead.urgency or "medium"] = urgency_counts.get(lead.urgency or "medium", 0) + 1
        sentiment_counts[lead.sentiment or "neutral"] = sentiment_counts.get(lead.sentiment or "neutral", 0) + 1
        total_probability += float(lead.conversion_probability or 0.0)

    average_conversion_probability = float(total_probability / len(leads)) if leads else 0.0

    return {
        "lead_count": len(leads),
        "status_counts": status_counts,
        "stage_counts": stage_counts,
        "urgency_counts": urgency_counts,
        "sentiment_counts": sentiment_counts,
        "average_conversion_probability": round(average_conversion_probability, 3),
    }


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: UUID,
    update: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    # Find lead, ensuring it belongs to the organization
    query = select(Lead).where(Lead.id == lead_id)
    if org_id:
        query = query.where(Lead.organization_id == org_id)
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.status = update.status
    await db.commit()
    return {"status": "updated"}

@router.get("/by-conversation/{conversation_id}")
async def get_lead_by_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    stmt = select(Lead).where(
        Lead.conversation_id == uuid.UUID(conversation_id),
        Lead.organization_id == uuid.UUID(org_id)
    ).order_by(Lead.created_at.desc())  # most recent first
    result = await db.execute(stmt)
    lead = result.scalars().first()   # ✅ returns first row or None
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
