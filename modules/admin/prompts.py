
# modules/admin/prompts.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from modules.common.database import get_db
from modules.common.models import OrganizationPrompt, Organization
from modules.auth.jwt import get_current_super_admin
from pydantic import BaseModel
from uuid import UUID
from typing import List, Optional

router = APIRouter(prefix="/api/admin/prompts", tags=["Admin Prompts"])

class PromptCreate(BaseModel):
    organization_id: UUID
    name: str
    prompt_text: str

class PromptUpdate(BaseModel):
    name: Optional[str] = None
    prompt_text: Optional[str] = None
    is_primary: Optional[bool] = None

@router.get("/organizations/{org_id}")
async def list_prompts_for_org(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(
        select(OrganizationPrompt).where(OrganizationPrompt.organization_id == org_id)
        .order_by(OrganizationPrompt.created_at.desc())
    )
    prompts = result.scalars().all()
    return prompts

@router.post("/")
async def create_prompt(
    data: PromptCreate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    # Check organization exists
    org = await db.execute(select(Organization).where(Organization.id == data.organization_id))
    if not org.scalar_one_or_none():
        raise HTTPException(404, "Organization not found")
    
    new_prompt = OrganizationPrompt(
        organization_id=data.organization_id,
        name=data.name,
        prompt_text=data.prompt_text,
        is_primary=False
    )
    db.add(new_prompt)
    await db.commit()
    await db.refresh(new_prompt)
    return new_prompt

@router.put("/{prompt_id}")
async def update_prompt(
    prompt_id: UUID,
    data: PromptUpdate,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(OrganizationPrompt).where(OrganizationPrompt.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(404, "Prompt not found")
    
    if data.name is not None:
        prompt.name = data.name
    if data.prompt_text is not None:
        prompt.prompt_text = data.prompt_text
    if data.is_primary is not None and data.is_primary:
        # Remove primary flag from other prompts of same organization
        await db.execute(
            update(OrganizationPrompt)
            .where(OrganizationPrompt.organization_id == prompt.organization_id)
            .values(is_primary=False)
        )
        prompt.is_primary = True
    elif data.is_primary is not None:
        prompt.is_primary = data.is_primary
    
    await db.commit()
    await db.refresh(prompt)
    return prompt

@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(OrganizationPrompt).where(OrganizationPrompt.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(404, "Prompt not found")
    await db.execute(delete(OrganizationPrompt).where(OrganizationPrompt.id == prompt_id))
    await db.commit()
    return {"status": "deleted"}

@router.post("/{prompt_id}/set-primary")
async def set_primary_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    _ = Depends(get_current_super_admin)
):
    result = await db.execute(select(OrganizationPrompt).where(OrganizationPrompt.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(404, "Prompt not found")
    # Set all others to false for this organization
    await db.execute(
        update(OrganizationPrompt)
        .where(OrganizationPrompt.organization_id == prompt.organization_id)
        .values(is_primary=False)
    )
    prompt.is_primary = True
    await db.commit()
    return {"status": "primary set"}
