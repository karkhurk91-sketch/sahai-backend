from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_
from modules.common.database import AsyncSessionLocal
from modules.common.models import Booking
from modules.message.sender import send_whatsapp_text
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def send_booking_reminders():
    """Send reminders for bookings happening tomorrow."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    async with AsyncSessionLocal() as db:
        bookings = await db.execute(
            select(Booking).where(
                and_(
                    Booking.booking_date == tomorrow,
                    Booking.status == 'confirmed',
                    Booking.reminder_sent.is_(False)
                )
            )
        )
        for booking in bookings.scalars():
            try:
                success, _ = await send_whatsapp_text(
                    to_number=booking.customer_phone,
                    text=f"🔔 Reminder: Your booking is tomorrow at {booking.booking_time}. Reply YES to confirm.",
                    org_id=str(booking.organization_id)
                )
                if success:
                    booking.reminder_sent = True
                    await db.commit()
                    logger.info(f"Reminder sent for booking {booking.id}")
            except Exception as e:
                logger.error(f"Failed to send reminder for booking {booking.id}: {e}", exc_info=True)