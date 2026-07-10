from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth.jwt import get_current_user
from modules.common.database import get_db
from modules.common.models import QuickReply

router = APIRouter(prefix="/api/quick-replies", tags=["Quick Replies"])


class QuickReplyCreate(BaseModel):
    name: str
    content: str
    category: str = "general"
    is_shared: bool = False


class QuickReplyUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    category: str | None = None
    is_shared: bool | None = None


@router.get("", response_model=List[dict[str, Any]])
async def list_quick_replies(
    q: str | None = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    stmt = select(QuickReply).where(QuickReply.organization_id == UUID(org_id))
    if q:
        stmt = stmt.where(QuickReply.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(QuickReply.category.asc(), QuickReply.name.asc())

    result = await db.execute(stmt)
    replies = result.scalars().all()

    return [
        {
            "id": str(reply.id),
            "name": reply.name,
            "content": reply.content,
            "category": reply.category,
            "is_shared": reply.is_shared,
            "created_by": str(reply.created_by) if reply.created_by else None,
        }
        for reply in replies
    ]


@router.post("", response_model=dict[str, Any])
async def create_quick_reply(
    payload: QuickReplyCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("org_id")
    user_id = current_user.get("user_id")
    if not org_id or not user_id:
        raise HTTPException(403, "Authentication required")

    reply = QuickReply(
        organization_id=UUID(org_id),
        created_by=UUID(user_id),
        name=payload.name.strip(),
        content=payload.content.strip(),
        category=payload.category.strip() or "general",
        is_shared=payload.is_shared,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    return {
        "id": str(reply.id),
        "name": reply.name,
        "content": reply.content,
        "category": reply.category,
        "is_shared": reply.is_shared,
        "created_by": str(reply.created_by) if reply.created_by else None,
    }


@router.put("/{reply_id}", response_model=dict[str, Any])
async def update_quick_reply(
    reply_id: UUID,
    payload: QuickReplyUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    result = await db.execute(select(QuickReply).where(QuickReply.id == reply_id, QuickReply.organization_id == UUID(org_id)))
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "Quick reply not found")

    if payload.name is not None:
        reply.name = payload.name.strip()
    if payload.content is not None:
        reply.content = payload.content.strip()
    if payload.category is not None:
        reply.category = payload.category.strip() or "general"
    if payload.is_shared is not None:
        reply.is_shared = payload.is_shared

    await db.commit()
    await db.refresh(reply)
    return {
        "id": str(reply.id),
        "name": reply.name,
        "content": reply.content,
        "category": reply.category,
        "is_shared": reply.is_shared,
        "created_by": str(reply.created_by) if reply.created_by else None,
    }


@router.delete("/{reply_id}")
async def delete_quick_reply(
    reply_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization not found")

    result = await db.execute(select(QuickReply).where(QuickReply.id == reply_id, QuickReply.organization_id == UUID(org_id)))
    reply = result.scalar_one_or_none()
    if not reply:
        raise HTTPException(404, "Quick reply not found")

    await db.delete(reply)
    await db.commit()
    return {"status": "deleted"}
