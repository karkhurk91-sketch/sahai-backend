import re
from datetime import datetime, timedelta, time
from typing import Optional, Tuple
import pytz

class BookingDateTimeParser:
    """Deterministic parser for dates and times from natural language."""
    
    def __init__(self, timezone_str: str = "Asia/Kolkata"):
        self.tz = pytz.timezone(timezone_str)
    
    def parse_date(self, user_input: str) -> Optional[datetime]:
        """Return datetime object or None."""
        user_input = user_input.lower().strip()
        today = datetime.now(self.tz).date()
        
        # Today / tomorrow
        if user_input in ["today", "tdy"]:
            return datetime.combine(today, time.min)
        if user_input in ["tomorrow", "tmrw", "next day"]:
            return datetime.combine(today + timedelta(days=1), time.min)
        
        # Weekdays
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, day in enumerate(weekdays):
            if day in user_input:
                delta = (i - today.weekday()) % 7
                if delta == 0:
                    delta = 7  # next week
                return datetime.combine(today + timedelta(days=delta), time.min)
        
        # Absolute dates: 25th May, 2026-05-25, 25-05-2026, 25/05/2026
        patterns = [
            (r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)(?:\s+(\d{4}))?", lambda m: f"{m[1]} {m[2]} {m[3] if m[3] else today.year}"),
            (r"(\d{4})-(\d{2})-(\d{2})", lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
            (r"(\d{2})-(\d{2})-(\d{4})", lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
            (r"(\d{2})/(\d{2})/(\d{4})", lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
        ]
        for pattern, formatter in patterns:
            match = re.search(pattern, user_input)
            if match:
                try:
                    return datetime.strptime(formatter(match.groups()), "%Y-%m-%d")
                except ValueError:
                    continue
        return None
    
    def parse_time(self, user_input: str) -> Optional[time]:
        """Return time object or None."""
        user_input = user_input.lower()
        # Time blocks
        blocks = {"morning": 9, "afternoon": 12, "evening": 18, "night": 21}
        for block, hour in blocks.items():
            if block in user_input:
                return time(hour=hour, minute=0)
        
        # Specific times: 2pm, 2:30 PM, 14:30
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", user_input)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            meridiem = match.group(3) if match.group(3) else ""
            if meridiem == "pm" and hour != 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            # Basic validation
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return time(hour=hour, minute=minute)
        return None
    
    def validate_booking(self, booking_datetime: datetime) -> Tuple[bool, Optional[str]]:
        """Check if booking date/time is valid."""
        now = datetime.now(self.tz)
        if booking_datetime < now:
            return False, "Booking date/time is in the past"
        if booking_datetime > now + timedelta(days=90):
            return False, "Booking date too far in future (max 90 days)"
        hour = booking_datetime.hour
        if hour < 6 or hour > 22:
            return False, "Booking time outside business hours (6 AM – 10 PM)"
        return True, None