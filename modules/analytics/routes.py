from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from modules.common.database import get_db
from modules.common.models import Message, Conversation, Lead, Customer
from modules.auth.jwt import get_current_user, get_current_super_admin
from typing import Optional

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])
@router.get("/activity")
async def get_activity(
    period: str = Query("daily", pattern="^(daily|weekly|monthly|yearly)$"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organization associated")
    
    now = datetime.utcnow()
    if period == "daily":
        start = now - timedelta(days=30)
        group_by = func.date(Message.created_at)
    elif period == "weekly":
        start = now - timedelta(weeks=12)
        group_by = func.date_trunc('week', Message.created_at)
    elif period == "monthly":
        start = now - timedelta(days=365)
        group_by = func.date_trunc('month', Message.created_at)
    else:
        start = now - timedelta(days=365*5)
        group_by = func.date_trunc('year', Message.created_at)

    # Correct query: join with conversations to filter by organization
    msg_query = select(
        group_by.label("date"),
        func.count(Message.id).label("count")
    ).join(Conversation, Message.conversation_id == Conversation.id).where(
        Conversation.organization_id == org_id,
        Message.created_at >= start
    ).group_by(group_by).order_by("date")
    
    result = await db.execute(msg_query)
    messages = [{"date": str(r.date), "count": r.count} for r in result]

    # Similar fix for leads (leads has organization_id directly, so no join needed)
    lead_query = select(
        group_by.label("date"),
        func.count(Lead.id).label("count")
    ).where(
        Lead.organization_id == org_id,
        Lead.created_at >= start
    ).group_by(group_by).order_by("date")
    leads_result = await db.execute(lead_query)
    leads = [{"date": str(r.date), "count": r.count} for r in leads_result]

    # Top customers (join with conversations)
    top_query = select(
        Conversation.customer_phone_number,
        func.count(Message.id).label("msg_count")
    ).join(Message, Message.conversation_id == Conversation.id
    ).where(Conversation.organization_id == org_id
    ).group_by(Conversation.customer_phone_number
    ).order_by(func.count(Message.id).desc()).limit(10)
    top = await db.execute(top_query)
    top_customers = [{"phone": row.customer_phone_number, "messages": row.msg_count} for row in top]

    # Funnel
    total_leads = (await db.execute(select(func.count(Lead.id)).where(Lead.organization_id == org_id))).scalar()
    contacted = (await db.execute(select(func.count(Lead.id)).where(Lead.organization_id == org_id, Lead.status == "contacted"))).scalar()
    converted = (await db.execute(select(func.count(Lead.id)).where(Lead.organization_id == org_id, Lead.status == "converted"))).scalar()
    funnel = {"total_leads": total_leads or 0, "contacted": contacted or 0, "converted": converted or 0}

    return {"messages": messages, "leads": leads, "top_customers": top_customers, "funnel": funnel}