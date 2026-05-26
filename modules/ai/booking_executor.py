import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.models import Booking, Conversation, Lead
from .booking_parser import BookingDateTimeParser

logger = logging.getLogger(__name__)

@dataclass
class BookingResult:
    success: bool
    booking_id: Optional[str]
    user_message: str
    next_stage: str

class BookingExecutor:
    def __init__(self, db: AsyncSession, parser: BookingDateTimeParser):
        self.db = db
        self.parser = parser
    
    async def execute_booking(
        self,
        conversation_id: str,
        lead_id: str,
        user_message: str,
        notes: Optional[str] = None
    ) -> BookingResult:
        """Parse user message and create a booking."""
        # Parse date and time
        booking_date = self.parser.parse_date(user_message)
        booking_time = self.parser.parse_time(user_message)
        
        if not booking_date:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="I couldn't understand the date. Please say 'tomorrow', 'next Monday', or '25th May'.",
                next_stage="booking"
            )
        if not booking_time:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="I couldn't understand the time. Please say '2pm', '14:30', or 'morning'.",
                next_stage="booking"
            )
        
        # Validate
        booking_datetime = datetime.combine(booking_date.date(), booking_time)
        is_valid, error = self.parser.validate_booking(booking_datetime)
        if not is_valid:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message=f"Sorry, that time is not available: {error}",
                next_stage="booking"
            )
        
        # Get lead to ensure organisation_id
        lead = await self.db.get(Lead, lead_id)
        if not lead:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="Unable to create booking. Lead not found.",
                next_stage="booking"
            )
        
        # Create booking
        booking = Booking(
            conversation_id=conversation_id,
            lead_id=lead_id,
            organisation_id=lead.organisation_id,
            booking_date=booking_datetime.date(),
            booking_time=booking_time,
            status="confirmed",
            notes=notes
        )
        self.db.add(booking)
        await self.db.flush()
        
        # Update conversation
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                booking_status="confirmed",
                conversation_stage="followup"
            )
        )
        await self.db.commit()
        
        formatted_time = booking_datetime.strftime('%B %d, %Y at %I:%M %p')
        return BookingResult(
            success=True,
            booking_id=str(booking.id),
            user_message=f"Perfect! Your booking is confirmed for {formatted_time}. We'll send a reminder 24 hours before.",
            next_stage="followup"
        )