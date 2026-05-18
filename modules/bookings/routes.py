from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from modules.common.database import get_db
from modules.common.models import Booking
from modules.auth.jwt import get_current_user
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])

@router.get("")
async def list_bookings(
    period: str = Query("daily", pattern="^(daily|weekly|monthly|yearly)$"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    org_id = current_user.get("org_id")
    if not org_id:
        # Super admin could see all, but for now return empty
        return []

    now = datetime.now()
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(days=now.weekday())  # Monday
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

    query = select(Booking).where(
        Booking.organization_id == org_id,
        Booking.booking_date >= start.date(),
        Booking.booking_date < end.date()
    ).order_by(Booking.booking_date, Booking.booking_time)

    result = await db.execute(query)
    bookings = result.scalars().all()
    return bookings