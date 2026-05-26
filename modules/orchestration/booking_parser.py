"""
Booking Date/Time Parser - Deterministic parsing with validation.

Features:
- Parses relative dates: "today", "tomorrow", "next Monday"
- Parses absolute dates: "25th May", "2026-05-25"
- Parses times: "2pm", "14:30", "morning", "afternoon"
- Timezone-aware
- Validates dates are in valid range
- Prevents invalid bookings (past, too far future, outside hours)
"""

from datetime import datetime, timedelta, time
import re
from typing import Optional, Tuple
import pytz
import logging

logger = logging.getLogger(__name__)


class BookingDateTimeParser:
    """
    Deterministic booking date/time parser.
    
    Replaces LLM-based parsing which was unreliable.
    """
    
    def __init__(self, organization_timezone: str = "UTC"):
        """Initialize parser with organization timezone"""
        self.tz = pytz.timezone(organization_timezone)
    
    def parse_date(self, user_input: str) -> Optional[datetime]:
        """
        Parse user input for booking date.
        
        Supports:
        - Relative: "today", "tomorrow", "next Monday"
        - Absolute: "25th May", "25 May 2026", "2026-05-25", "25-05-2026"
        
        Args:
            user_input: User's date input
        
        Returns:
            datetime object in organization timezone, or None if parse failed
        """
        if not user_input:
            return None
        
        user_input = user_input.lower().strip()
        now = datetime.now(self.tz)
        today = now.date()
        
        # Relative dates
        if user_input in ["today", "tdy", "today please", "today ok"]:
            return self.tz.localize(datetime.combine(today, time.min))
        
        if user_input in ["tomorrow", "tmrw", "next day", "tomorrow please"]:
            tomorrow = today + timedelta(days=1)
            return self.tz.localize(datetime.combine(tomorrow, time.min))
        
        if user_input in ["day after tomorrow", "day after tmrw"]:
            day_after = today + timedelta(days=2)
            return self.tz.localize(datetime.combine(day_after, time.min))
        
        # Day of week patterns
        days_of_week = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        
        for day_name, day_num in days_of_week.items():
            if day_name in user_input or f"next {day_name}" in user_input:
                # Find next occurrence of this day
                days_ahead = (day_num - today.weekday()) % 7
                
                # If today is the target day and it's already in the past, go to next week
                if days_ahead == 0:
                    days_ahead = 7
                
                target_date = today + timedelta(days=days_ahead)
                return self.tz.localize(datetime.combine(target_date, time.min))
        
        # Absolute date formats
        # Pattern 1: "25th May 2026" or "25 May 2026" or "25th May"
        match = re.search(r'(\d{1,2})\s*(?:st|nd|rd|th)?\s+(\w+)\s*(?:(\d{4}))?', user_input)
        if match:
            try:
                day_str, month_str, year_str = match.groups()
                year = year_str if year_str else str(today.year)
                date_str = f"{day_str} {month_str} {year}"
                
                parsed = datetime.strptime(date_str, "%d %B %Y")
                return self.tz.localize(datetime.combine(parsed.date(), time.min))
            except ValueError as e:
                logger.debug(f"Failed to parse date format 1: {user_input}, {e}")
        
        # Pattern 2: "2026-05-25" (ISO format)
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', user_input)
        if match:
            try:
                parsed = datetime.strptime(match.group(0), "%Y-%m-%d")
                return self.tz.localize(datetime.combine(parsed.date(), time.min))
            except ValueError as e:
                logger.debug(f"Failed to parse date format 2: {user_input}, {e}")
        
        # Pattern 3: "25-05-2026" (DD-MM-YYYY)
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})', user_input)
        if match:
            try:
                parsed = datetime.strptime(match.group(0), "%d-%m-%Y")
                return self.tz.localize(datetime.combine(parsed.date(), time.min))
            except ValueError as e:
                logger.debug(f"Failed to parse date format 3: {user_input}, {e}")
        
        # Pattern 4: "25/05/2026" (DD/MM/YYYY)
        match = re.search(r'(\d{2})/(\d{2})/(\d{4})', user_input)
        if match:
            try:
                parsed = datetime.strptime(match.group(0), "%d/%m/%Y")
                return self.tz.localize(datetime.combine(parsed.date(), time.min))
            except ValueError as e:
                logger.debug(f"Failed to parse date format 4: {user_input}, {e}")
        
        logger.warning(f"Could not parse date input: {user_input}")
        return None
    
    def parse_time(self, user_input: str) -> Optional[time]:
        """
        Parse user input for booking time.
        
        Supports:
        - Time blocks: "morning", "afternoon", "evening"
        - Specific times: "2pm", "14:30", "2:30 PM"
        
        Args:
            user_input: User's time input
        
        Returns:
            time object, or None if parse failed
        """
        if not user_input:
            return None
        
        user_input = user_input.lower().strip()
        
        # Time blocks
        if user_input in ["morning", "am", "early", "early morning", "good morning"]:
            return time(9, 0)  # 9 AM
        
        if user_input in ["afternoon", "midday", "lunch", "lunch time", "pm", "afternoon please"]:
            return time(12, 0)  # 12 PM
        
        if user_input in ["evening", "evening please", "evening time"]:
            return time(18, 0)  # 6 PM
        
        if user_input in ["late evening", "night"]:
            return time(19, 0)  # 7 PM
        
        # Specific time formats
        # Pattern 1: "2:30 PM" or "14:30"
        match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', user_input)
        if match:
            try:
                hour_str, minute_str, meridiem = match.groups()
                hour = int(hour_str)
                minute = int(minute_str)
                
                # Handle 12-hour format
                if meridiem:
                    meridiem = meridiem.lower()
                    if meridiem == "pm" and hour != 12:
                        hour += 12
                    elif meridiem == "am" and hour == 12:
                        hour = 0
                
                # Validate hours and minutes
                if 0 <= hour < 24 and 0 <= minute < 60:
                    return time(hour, minute)
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse time format 1: {user_input}, {e}")
        
        # Pattern 2: "2pm" or "2 pm"
        match = re.search(r'(\d{1,2})\s*(am|pm)', user_input)
        if match:
            try:
                hour_str, meridiem = match.groups()
                hour = int(hour_str)
                
                if meridiem.lower() == "pm" and hour != 12:
                    hour += 12
                elif meridiem.lower() == "am" and hour == 12:
                    hour = 0
                
                if 0 <= hour < 24:
                    return time(hour, 0)
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse time format 2: {user_input}, {e}")
        
        logger.warning(f"Could not parse time input: {user_input}")
        return None
    
    def validate_booking(
        self,
        booking_datetime: datetime,
        min_advance_minutes: int = 60,
        max_days_ahead: int = 90,
        business_start_hour: int = 6,
        business_end_hour: int = 22
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate booking is within allowed parameters.
        
        Args:
            booking_datetime: Proposed booking date/time
            min_advance_minutes: Minimum advance booking time
            max_days_ahead: Maximum days in advance
            business_start_hour: Business hours start (24-hour format)
            business_end_hour: Business hours end (24-hour format)
        
        Returns:
            (is_valid, error_message)
        """
        now = datetime.now(self.tz)
        
        # Convert booking_datetime to same timezone if needed
        if booking_datetime.tzinfo is None:
            booking_datetime = self.tz.localize(booking_datetime)
        else:
            booking_datetime = booking_datetime.astimezone(self.tz)
        
        # Check not in past (with buffer)
        min_booking_time = now + timedelta(minutes=min_advance_minutes)
        if booking_datetime < min_booking_time:
            minutes_diff = int((min_booking_time - booking_datetime).total_seconds() / 60)
            return False, f"Please book at least {min_advance_minutes} minutes in advance"
        
        # Check not too far in future
        max_booking_time = now + timedelta(days=max_days_ahead)
        if booking_datetime > max_booking_time:
            return False, f"Bookings available up to {max_days_ahead} days in advance"
        
        # Check business hours
        booking_hour = booking_datetime.hour
        if booking_hour < business_start_hour:
            return False, f"We open at {business_start_hour}:00 AM. Please book after then."
        
        if booking_hour >= business_end_hour:
            return False, f"We close at {business_end_hour}:00. Please book before then."
        
        return True, None
    
    def format_for_user(self, booking_datetime: datetime) -> str:
        """Format booking datetime for display to user"""
        if booking_datetime.tzinfo is None:
            booking_datetime = self.tz.localize(booking_datetime)
        
        return booking_datetime.strftime("%B %d, %Y at %I:%M %p")
    
    def suggest_next_available(
        self,
        reason: str = "no reason provided"
    ) -> str:
        """Suggest next available booking slot"""
        now = datetime.now(self.tz)
        
        # Suggest tomorrow at 10 AM
        tomorrow = now + timedelta(days=1)
        suggested = self.tz.localize(
            datetime.combine(tomorrow.date(), time(10, 0))
        )
        
        return f"How about {self.format_for_user(suggested)} instead?"
