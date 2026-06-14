from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from modules.common.database import get_db
from modules.common.models import Booking
from modules.auth.jwt import get_current_user
from modules.auth.dependencies import require_permission
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

router = APIRouter(prefix="/api/bookings", tags=["Bookings"], dependencies=[Depends(require_permission("manage_bookings"))])

@router.get("")
async def list_bookings(
    period: str = Query("daily", pattern="^(daily|weekly|monthly|yearly)$"),
    lead_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        return []

    now = datetime.now()
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    elif period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end = now.replace(year=now.year+1, month=1, day=1)
        else:
            end = now.replace(month=now.month+1, day=1)
    else:  # yearly
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(year=now.year+1, month=1, day=1)

    # Build query with filters
    filters = [
        Booking.organization_id == org_id,
        Booking.booking_date >= start.date(),
        Booking.booking_date < end.date()
    ]
    
    # Add lead_id filter if provided and column exists
    if lead_id:
        try:
            lead_uuid = UUID(lead_id) if isinstance(lead_id, str) else lead_id
            # Only filter by lead_id if it's available (after migration)
            if hasattr(Booking, 'lead_id'):
                filters.append(Booking.lead_id == lead_uuid)
        except (ValueError, TypeError):
            pass

    try:
        query = select(Booking).where(and_(*filters)).order_by(Booking.booking_date, Booking.booking_time)
        result = await db.execute(query)
        bookings = result.scalars().all()
        return bookings
    except Exception as e:
        # Fallback: if lead_id column doesn't exist, query without it
        import logging
        logging.warning(f"Query failed (likely lead_id column not migrated yet): {e}")
        
        filters_no_lead = [f for f in filters if 'lead_id' not in str(f)]
        query = select(Booking).where(and_(*filters_no_lead)).order_by(Booking.booking_date, Booking.booking_time)
        result = await db.execute(query)
        bookings = result.scalars().all()
        return bookings