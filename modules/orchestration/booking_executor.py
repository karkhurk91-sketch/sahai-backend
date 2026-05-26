"""
Booking Executor - Deterministic booking creation and validation.

Features:
- Deterministic date/time parsing
- Validation of bookings
- Create bookings in database
- Update conversation state
- Schedule reminders
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from modules.orchestration.booking_parser import BookingDateTimeParser
from modules.common.models import Conversation, Booking, Lead

logger = logging.getLogger(__name__)


@dataclass
class BookingResult:
    """Result of booking attempt"""
    success: bool
    booking_id: Optional[str]
    user_message: str
    next_stage: str
    error_code: Optional[str] = None


class BookingExecutor:
    """
    Executes bookings deterministically.
    
    Replaces LLM-based booking logic which was error-prone.
    """
    
    def __init__(
        self,
        db: AsyncSession,
        parser: BookingDateTimeParser,
        timezone: str = "UTC"
    ):
        self.db = db
        self.parser = parser
        self.timezone = timezone
    
    async def execute_booking(
        self,
        conversation_id: str,
        phone: str,
        organization_id: str,
        date_input: str,
        time_input: str,
        notes: Optional[str] = None
    ) -> BookingResult:
        """
        Execute booking with full validation and state update.
        
        Args:
            conversation_id: Conversation ID
            phone: User's phone number
            organization_id: Organization ID
            date_input: User's date input
            time_input: User's time input
            notes: Optional booking notes
        
        Returns:
            BookingResult with success/failure details
        """
        
        # Parse date
        booking_date = self.parser.parse_date(date_input)
        if not booking_date:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message=(
                    f"I couldn't understand the date '{date_input}'. "
                    "Please try: 'tomorrow', 'next Monday', or '25th May'"
                ),
                next_stage="booking",
                error_code="INVALID_DATE_FORMAT"
            )
        
        # Parse time
        booking_time = self.parser.parse_time(time_input)
        if not booking_time:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message=(
                    f"I couldn't understand the time '{time_input}'. "
                    "Please try: '2pm', '14:30', or 'morning'"
                ),
                next_stage="booking",
                error_code="INVALID_TIME_FORMAT"
            )
        
        # Combine date and time
        from datetime import datetime as dt
        booking_datetime = dt.combine(booking_date.date(), booking_time)
        
        # Validate booking
        is_valid, error_msg = self.parser.validate_booking(booking_datetime)
        if not is_valid:
            return BookingResult(
                success=False,
                booking_id=None,
                user_message=f"Sorry, that booking is not available: {error_msg}",
                next_stage="booking",
                error_code="INVALID_BOOKING"
            )
        
        # Create booking in database
        try:
            # Get conversation
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            
            if not conversation:
                logger.error(f"Conversation not found: {conversation_id}")
                return BookingResult(
                    success=False,
                    booking_id=None,
                    user_message="System error: Conversation not found",
                    next_stage="booking",
                    error_code="CONVERSATION_NOT_FOUND"
                )
            
            # Get or create lead
            result = await self.db.execute(
                select(Lead).where(
                    (Lead.phone_number == phone) &
                    (Lead.organization_id == organization_id)
                )
            )
            lead = result.scalar_one_or_none()
            
            if not lead:
                # Create lead
                lead = Lead(
                    phone_number=phone,
                    organization_id=organization_id,
                    data={}
                )
                self.db.add(lead)
                await self.db.flush()
            
            # Create booking
            booking = Booking(
                conversation_id=conversation_id,
                lead_id=lead.id,
                booking_date=booking_date.date(),
                booking_time=booking_time,
                status="confirmed",
                notes=notes,
                reminder_sent=False
            )
            
            self.db.add(booking)
            
            # Update conversation state
            conversation.booking_status = "confirmed"
            conversation.conversation_stage = "followup"
            
            # Update completed fields
            if conversation.completed_fields is None:
                conversation.completed_fields = {}
            
            conversation.completed_fields["booking_date"] = {
                "value": str(booking_date.date()),
                "completed_at": datetime.utcnow().isoformat(),
                "source": "booking_parser"
            }
            conversation.completed_fields["booking_time"] = {
                "value": str(booking_time),
                "completed_at": datetime.utcnow().isoformat(),
                "source": "booking_parser"
            }
            
            conversation.updated_at = datetime.utcnow()
            
            await self.db.commit()
            
            formatted_time = self.parser.format_for_user(booking_datetime)
            
            return BookingResult(
                success=True,
                booking_id=str(booking.id),
                user_message=(
                    f"Perfect! Your booking is confirmed for {formatted_time}. "
                    f"We'll send you a reminder 24 hours before. "
                    f"See you soon! 🎉"
                ),
                next_stage="followup",
                error_code=None
            )
        
        except Exception as e:
            logger.error(f"Error executing booking: {e}", exc_info=True)
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="System error: Could not create booking. Please try again.",
                next_stage="booking",
                error_code="BOOKING_CREATION_ERROR"
            )
    
    async def validate_booking_date(
        self,
        date_input: str
    ) -> tuple[bool, str]:
        """Validate if date input is valid"""
        parsed_date = self.parser.parse_date(date_input)
        if not parsed_date:
            return False, "Could not parse date"
        return True, str(parsed_date.date())
    
    async def validate_booking_time(
        self,
        time_input: str
    ) -> tuple[bool, str]:
        """Validate if time input is valid"""
        parsed_time = self.parser.parse_time(time_input)
        if not parsed_time:
            return False, "Could not parse time"
        return True, str(parsed_time)
    
    async def cancel_booking(
        self,
        booking_id: str,
        reason: Optional[str] = None
    ) -> BookingResult:
        """Cancel an existing booking"""
        try:
            result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.scalar_one_or_none()
            
            if not booking:
                return BookingResult(
                    success=False,
                    booking_id=None,
                    user_message="Booking not found",
                    next_stage="booking",
                    error_code="BOOKING_NOT_FOUND"
                )
            
            booking.status = "cancelled"
            booking.cancelled_at = datetime.utcnow()
            booking.cancellation_reason = reason
            
            await self.db.commit()
            
            return BookingResult(
                success=True,
                booking_id=booking_id,
                user_message="Your booking has been cancelled.",
                next_stage="booking"
            )
        
        except Exception as e:
            logger.error(f"Error cancelling booking: {e}")
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="Error cancelling booking",
                next_stage="booking",
                error_code="CANCEL_ERROR"
            )
    
    async def reschedule_booking(
        self,
        booking_id: str,
        date_input: str,
        time_input: str
    ) -> BookingResult:
        """Reschedule an existing booking"""
        try:
            result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.scalar_one_or_none()
            
            if not booking:
                return BookingResult(
                    success=False,
                    booking_id=None,
                    user_message="Booking not found",
                    next_stage="booking",
                    error_code="BOOKING_NOT_FOUND"
                )
            
            # Parse new date/time
            new_date = self.parser.parse_date(date_input)
            if not new_date:
                return BookingResult(
                    success=False,
                    booking_id=None,
                    user_message="Invalid date format",
                    next_stage="booking",
                    error_code="INVALID_DATE"
                )
            
            new_time = self.parser.parse_time(time_input)
            if not new_time:
                return BookingResult(
                    success=False,
                    booking_id=None,
                    user_message="Invalid time format",
                    next_stage="booking",
                    error_code="INVALID_TIME"
                )
            
            # Update booking
            booking.booking_date = new_date.date()
            booking.booking_time = new_time
            booking.rescheduled_at = datetime.utcnow()
            
            await self.db.commit()
            
            formatted_time = self.parser.format_for_user(
                new_date.replace(hour=new_time.hour, minute=new_time.minute)
            )
            
            return BookingResult(
                success=True,
                booking_id=booking_id,
                user_message=f"Your booking has been rescheduled to {formatted_time}",
                next_stage="followup"
            )
        
        except Exception as e:
            logger.error(f"Error rescheduling booking: {e}")
            return BookingResult(
                success=False,
                booking_id=None,
                user_message="Error rescheduling booking",
                next_stage="booking",
                error_code="RESCHEDULE_ERROR"
            )
