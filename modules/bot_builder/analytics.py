from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text
from datetime import datetime, timedelta
from uuid import UUID
from modules.common.database import get_db
from modules.common.models import Conversation, Lead, Message
from modules.auth.jwt import get_current_user

router = APIRouter(prefix="/api/bots/analytics", tags=["Bot Analytics"])

@router.get("/overview")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    days: int = 30
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization required")
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Total bot conversations started (reply_mode='bot' and created in period)
    total_started = await db.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.organization_id == UUID(org_id),
            Conversation.reply_mode == 'bot',
            Conversation.started_at >= start_date
        )
    ) or 0
    
    # Completed conversations (those with at least one lead created from generic bot)
    # We can check leads with data->>'completed' or simply count leads from bot mode
    completed = await db.scalar(
        select(func.count(Lead.id)).where(
            Lead.organization_id == UUID(org_id),
            Lead.created_at >= start_date,
            Lead.data.isnot(None)  # leads from generic bot have data field
        )
    ) or 0
    
    completion_rate = (completed / total_started * 100) if total_started > 0 else 0
    
    # Average completion time (time from conversation start to lead creation)
    # We need to join leads and conversations
    result = await db.execute(
        select(func.avg(func.extract('epoch', Lead.created_at - Conversation.started_at))).where(
            Conversation.id == Lead.conversation_id,
            Conversation.organization_id == UUID(org_id),
            Conversation.reply_mode == 'bot',
            Lead.created_at >= start_date
        )
    )
    avg_seconds = result.scalar() or 0
    avg_minutes = round(avg_seconds / 60, 1)
    
    return {
        "total_started": total_started,
        "completed": completed,
        "completion_rate": round(completion_rate, 1),
        "avg_completion_minutes": avg_minutes
    }

@router.get("/dropoffs")
async def get_dropoffs(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization required")
    
    # This requires parsing the rule_state of bot conversations.
    # We look at the last_asked_field and responses count.
    # Drop-off at field N means users who answered up to field N-1 but never answered field N.
    # We can query conversations that are not completed and extract the last field name.
    # Simpler: count distribution of number of responses in completed vs all.
    # For a more detailed per-field dropoff, we need to analyze the bot config.
    # We'll return a simple array of field names and completion percentages.
    
    # For now, we'll compute the average number of fields answered per conversation
    # and the completion rate by step.
    # We'll query all bot conversations that are still in 'bot' mode (not completed) and not switched.
    # We need to parse rule_state JSON.
    from sqlalchemy import cast, JSON
    result = await db.execute(
        select(
            Conversation.rule_state,
            Conversation.started_at
        ).where(
            Conversation.organization_id == UUID(org_id),
            Conversation.reply_mode == 'bot',
            Conversation.rule_state.isnot(None)
        )
    )
    rows = result.all()
    
    # Count how many conversations have how many responses
    response_counts = []
    for row in rows:
        state = row.rule_state or {}
        responses = state.get("responses", {})
        response_counts.append(len(responses))
    
    # Compute distribution (for a simple chart)
    total = len(response_counts)
    if total == 0:
        return {"dropoffs": []}
    
    max_fields = max(response_counts) if response_counts else 0
    dropoff_data = []
    for i in range(1, max_fields + 1):
        completed_at_least_i = sum(1 for c in response_counts if c >= i)
        percent = (completed_at_least_i / total) * 100
        dropoff_data.append({
            "field_index": i,
            "percent_completed": round(percent, 1)
        })
    
    return {"dropoffs": dropoff_data}

@router.get("/custom-values")
async def get_custom_values(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization required")
    
    # Look for '_other' selections in conversation rule_state
    # This requires scanning rule_state JSON for fields where the value is not in original options.
    # Simpler: we can parse the data field of leads created from generic bot.
    # Lead.data contains all collected responses. We can extract values that are not in the original options.
    # But we don't have original options in lead data. We'll instead look at rule_state and detect custom values.
    # We'll query all bot conversations and extract responses where the value is not in the predefined options.
    # This is complex. For MVP, return a static message or list of common custom values from lead.data.
    
    # Alternative: return top 10 custom values from lead.data where the key is "other" or field value is free text.
    # We'll query leads that have data and extract values that are likely custom (e.g., long text, not in a list).
    result = await db.execute(
        select(Lead.data)
        .where(
            Lead.organization_id == UUID(org_id),
            Lead.data.isnot(None)
        )
        .limit(100)
    )
    leads = result.scalars().all()
    custom_values = []
    for lead_data in leads:
        for key, value in lead_data.items():
            if isinstance(value, str) and len(value) > 20:  # heuristic for custom text
                custom_values.append(value[:100])
    # Count frequency
    from collections import Counter
    freq = Counter(custom_values).most_common(10)
    return {"custom_values": [{"value": v, "count": c} for v, c in freq]}