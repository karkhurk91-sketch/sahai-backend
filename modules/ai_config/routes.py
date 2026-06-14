from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.database import get_db
from modules.common.models import AIConfig
from modules.auth.jwt import get_current_user, get_current_super_admin
from modules.auth.dependencies import require_permission
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

router = APIRouter(prefix="/api/ai/config", tags=["AI Config"], dependencies=[Depends(require_permission("manage_ai_prompts"))])

class AIConfigUpdate(BaseModel):
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enable_lead_capture: Optional[bool] = None
    enable_auto_escalation: Optional[bool] = None
    escalation_keywords: Optional[str] = None

async def get_or_create_config(db: AsyncSession, org_id: Optional[UUID] = None):
    query = select(AIConfig).where(AIConfig.organization_id == org_id)
    result = await db.execute(query)
    config = result.scalar_one_or_none()
    if not config:
        config = AIConfig(organization_id=org_id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config

@router.get("/global")
async def get_global_config(
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    config = await get_or_create_config(db, None)
    return config

@router.put("/global")
async def update_global_config(
    update: AIConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):

    config = await get_or_create_config(db, None)
    for key, value in update.dict(exclude_unset=True).items():
        setattr(config, key, value)
    await db.commit()
    return config

@router.get("")
async def get_org_config(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    config = await get_or_create_config(db, current_user["org_id"])
    return config

@router.put("")
async def update_org_config(
    update: AIConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):

    if current_user.get("role") != "org_admin":
        raise HTTPException(403, "Only organization admin can modify AI configuration")

    config = await get_or_create_config(db, current_user["org_id"])
    for key, value in update.dict(exclude_unset=True).items():
        setattr(config, key, value)
    await db.commit()
    return config

@router.get("/{org_id}")
async def get_org_config_by_id(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    config = await get_or_create_config(db, org_id)
    return config

@router.put("/{org_id}")
async def update_org_config_by_id(
    org_id: UUID,
    update: AIConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    config = await get_or_create_config(db, org_id)
    for key, value in update.dict(exclude_unset=True).items():
        setattr(config, key, value)
    await db.commit()
    return config
