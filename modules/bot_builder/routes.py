from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
import uuid
from uuid import UUID
from typing import List, Optional
from datetime import datetime

from modules.common.database import get_db
from modules.common.models import BotConfig
from modules.auth.jwt import get_current_user
from modules.auth.dependencies import require_permission
from modules.bot_builder.schemas import (
    BotConfigCreate, BotConfigUpdate, BotConfigResponse,
    BotConfigListResponse
)
from modules.common.logger import get_logger
from modules.bot_builder.analytics import router as analytics_router


logger = get_logger(__name__)
router = APIRouter(prefix="/api/bots", tags=["Bot Builder"], dependencies=[Depends(require_permission("manage_bot_builder"))])

# ---------- Helper: validate JSON config schema ----------
def validate_config_schema(config: dict):
    if "fields" not in config:
        raise HTTPException(status_code=400, detail="Config must contain 'fields' array")
    if not isinstance(config["fields"], list):
        raise HTTPException(status_code=400, detail="'fields' must be an array")
    for field in config["fields"]:
        if "name" not in field or "question" not in field:
            raise HTTPException(status_code=400, detail="Each field must have 'name' and 'question'")
        if field.get("type") not in ["text", "button", "list"]:
            raise HTTPException(status_code=400, detail="Invalid field type. Must be text/button/list")
    return True

# ---------- Permission helpers (user is a dict) ----------
async def can_access_bot(user: dict, bot_config: BotConfig) -> bool:
    if user.get("role") == "super_admin":
        return True
    if user.get("role") == "org_admin" and user.get("org_id") == str(bot_config.organization_id):
        return True
    return False

async def get_bot_or_404(db: AsyncSession, bot_id: UUID, user: dict) -> BotConfig:
    result = await db.execute(select(BotConfig).where(BotConfig.id == bot_id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot config not found")
    if not await can_access_bot(user, bot):
        raise HTTPException(status_code=403, detail="Access denied")
    return bot

# ---------- CRUD Endpoints ----------
@router.get("", response_model=BotConfigListResponse)
async def list_bots(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    organization_id: Optional[UUID] = Query(None, description="Filter by org (super admin only)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    role = current_user.get("role")
    if role == "super_admin":
        if organization_id:
            query = select(BotConfig).where(BotConfig.organization_id == organization_id)
        else:
            query = select(BotConfig)
    elif role == "org_admin":
        org_id = current_user.get("org_id")
        if not org_id:
            raise HTTPException(status_code=400, detail="Organization ID missing for org_admin")
        query = select(BotConfig).where(BotConfig.organization_id == UUID(org_id))
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = query.order_by(BotConfig.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    bots = result.scalars().all()
    
    # Convert SQLAlchemy models to Pydantic responses
    bot_responses = [BotConfigResponse.model_validate(bot) for bot in bots]
    return BotConfigListResponse(items=bot_responses, total=total)

@router.post("", response_model=BotConfigResponse)
async def create_bot(
    data: BotConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    role = current_user.get("role")
    if role == "super_admin":
        # Option: accept organization_id in request body; for simplicity, we reject.
        raise HTTPException(status_code=400, detail="Super admin must provide organization_id in request body (extend schema)")
    elif role == "org_admin":
        org_id_str = current_user.get("org_id")
        if not org_id_str:
            raise HTTPException(status_code=400, detail="Organization ID missing")
        org_id = UUID(org_id_str)
    else:
        raise HTTPException(status_code=403, detail="Only org admin or super admin can create bots")

    validate_config_schema(data.config)

    new_bot = BotConfig(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=data.name,
        description=data.description,
        config=data.config,
        version=data.version,
        is_active=False,
        created_by=UUID(current_user["user_id"]),
        created_at=datetime.utcnow()
    )
    db.add(new_bot)
    await db.commit()
    await db.refresh(new_bot)
    return BotConfigResponse.model_validate(new_bot)

@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    bot = await get_bot_or_404(db, bot_id, current_user)
    return BotConfigResponse.model_validate(bot)

@router.put("/{bot_id}", response_model=BotConfigResponse)
async def update_bot(
    bot_id: UUID,
    data: BotConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    bot = await get_bot_or_404(db, bot_id, current_user)
    if bot.is_active:
        raise HTTPException(status_code=400, detail="Cannot update an active bot. Deactivate first.")
    
    if data.name is not None:
        bot.name = data.name
    if data.description is not None:
        bot.description = data.description
    if data.config is not None:
        validate_config_schema(data.config)
        bot.config = data.config
    if data.version is not None:
        bot.version = data.version
    
    await db.commit()
    await db.refresh(bot)
    return BotConfigResponse.model_validate(bot)

@router.post("/{bot_id}/activate")
async def activate_bot(
    bot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    bot = await get_bot_or_404(db, bot_id, current_user)
    # Deactivate any other active bot for the same organisation
    await db.execute(
        update(BotConfig)
        .where(BotConfig.organization_id == bot.organization_id, BotConfig.is_active == True)
        .values(is_active=False)
    )
    bot.is_active = True
    await db.commit()
    return {"message": f"Bot '{bot.name}' activated"}

@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    bot = await get_bot_or_404(db, bot_id, current_user)
    if bot.is_active:
        raise HTTPException(status_code=400, detail="Cannot delete an active bot. Deactivate first.")
    await db.delete(bot)
    await db.commit()
    return {"message": "Bot deleted"}