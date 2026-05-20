from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from uuid import UUID
from pydantic import BaseModel
from typing import List, Optional, Any
from modules.common.database import get_db
from modules.auth.jwt import get_current_user
from modules.common.models import ConversationCustomFieldDefinition
from modules.common.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/conversations/custom-fields-definitions", tags=["Conversations Custom Fields"])

class FieldDefinitionCreate(BaseModel):
    field_name: str
    field_label: str
    field_type: str  # text, number, date, select
    field_options: Optional[List[str]] = []
    display_order: Optional[int] = 0

class FieldDefinitionUpdate(BaseModel):
    field_label: Optional[str] = None
    field_type: Optional[str] = None
    field_options: Optional[List[str]] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None

@router.get("/")
async def list_field_definitions(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    stmt = select(ConversationCustomFieldDefinition).where(
        ConversationCustomFieldDefinition.organization_id == UUID(org_id),
        ConversationCustomFieldDefinition.is_active == True
    ).order_by(ConversationCustomFieldDefinition.display_order)
    result = await db.execute(stmt)
    fields = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "field_name": f.field_name,
            "field_label": f.field_label,
            "field_type": f.field_type,
            "field_options": f.field_options,
            "display_order": f.display_order,
        }
        for f in fields
    ]

@router.post("/")
async def create_field_definition(
    data: FieldDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    # Check if field name already exists
    stmt = select(ConversationCustomFieldDefinition).where(
        ConversationCustomFieldDefinition.organization_id == UUID(org_id),
        ConversationCustomFieldDefinition.field_name == data.field_name
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"Field name '{data.field_name}' already exists")
    field = ConversationCustomFieldDefinition(
        organization_id=UUID(org_id),
        field_name=data.field_name,
        field_label=data.field_label,
        field_type=data.field_type,
        field_options=data.field_options,
        display_order=data.display_order,
    )
    db.add(field)
    await db.commit()
    await db.refresh(field)
    return {"id": str(field.id), "message": "created"}

@router.patch("/{field_id}")
async def update_field_definition(
    field_id: UUID,
    data: FieldDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    stmt = select(ConversationCustomFieldDefinition).where(
        ConversationCustomFieldDefinition.id == field_id,
        ConversationCustomFieldDefinition.organization_id == UUID(org_id)
    )
    field = (await db.execute(stmt)).scalar_one_or_none()
    if not field:
        raise HTTPException(404, "Field definition not found")
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(field, key, value)
    await db.commit()
    return {"message": "updated"}

@router.delete("/{field_id}")
async def delete_field_definition(
    field_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")
    stmt = select(ConversationCustomFieldDefinition).where(
        ConversationCustomFieldDefinition.id == field_id,
        ConversationCustomFieldDefinition.organization_id == UUID(org_id)
    )
    field = (await db.execute(stmt)).scalar_one_or_none()
    if not field:
        raise HTTPException(404, "Field definition not found")
    await db.delete(field)
    await db.commit()
    return {"message": "deleted"}