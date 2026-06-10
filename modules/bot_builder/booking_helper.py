import httpx
from datetime import datetime, timedelta
from uuid import UUID
from modules.common.database import AsyncSessionLocal
from modules.common.models import Booking, Conversation, Lead

async def get_available_slots(org_id: str, booking_config: dict) -> list:
    """
    Fetch available time slots from your booking system.
    For MVP, generate slots for next 7 days (9am-5pm, hourly).
    Replace with call to your actual booking API.
    """
    # Example: generate dummy slots
    slots = []
    start_date = datetime.now().date()
    for i in range(7):
        date = start_date + timedelta(days=i)
        for hour in range(9, 18):  # 9 AM to 5 PM
            slot_id = f"{date}_{hour}"
            display = f"{date.strftime('%d %b')} {hour}:00"
            slots.append({"id": slot_id, "display": display})
    return slots

async def create_booking(org_id: str, conversation_id: str, customer_phone: str, data: dict) -> str:
    """Create a booking record using your existing Booking model."""
    async with AsyncSessionLocal() as session:
        # Extract fields from the collected responses
        responses = data.get("responses", {})
        booking = Booking(
            id=uuid.uuid4(),
            organization_id=UUID(org_id),
            conversation_id=UUID(conversation_id),
            customer_phone=customer_phone,
            customer_name=responses.get("name", ""),
            service=responses.get("service", ""),
            booking_date=datetime.strptime(responses.get("date"), "%Y-%m-%d").date(),
            booking_time=responses.get("time", ""),
            status="confirmed",
            created_at=datetime.utcnow()
        )
        session.add(booking)
        await session.commit()
        return str(booking.id)