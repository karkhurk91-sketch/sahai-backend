import uuid
from datetime import datetime, date, time
from uuid import UUID
from modules.common.database import AsyncSessionLocal
from modules.common.models import Booking


async def save_booking_generic(org_id: str, state: dict, industry: str):
    """
    Save a booking to database (async, returns booking object).
    
    Args:
        org_id: Organization UUID as string
        state: Dict with keys: customer_phone, customer_name, booking_date, booking_time, service, lead_id (optional)
        industry: Industry type (restaurant, salon, default)
    
    Returns:
        Booking object or None if creation failed
    """
    try:
        # Extract state values (work with dict)
        customer_phone = state.get('customer_phone')
        customer_name = state.get('customer_name', '')
        service = state.get('service', '')
        booking_date = state.get('booking_date')
        booking_time = state.get('booking_time')
        lead_id = state.get('lead_id')
        
        if not customer_phone or not booking_date:
            return None
        
        # Convert to proper types if needed
        if isinstance(booking_date, str):
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
        if isinstance(booking_time, str):
            booking_time = datetime.strptime(booking_time, '%H:%M').time()
        
        # Convert lead_id to UUID if provided
        lead_uuid = None
        if lead_id:
            try:
                lead_uuid = UUID(lead_id) if isinstance(lead_id, str) else lead_id
            except (ValueError, TypeError):
                pass
        
        # Create booking record
        async with AsyncSessionLocal() as db:
            booking = Booking(
                id=uuid.uuid4(),
                organization_id=UUID(org_id) if isinstance(org_id, str) else org_id,
                lead_id=lead_uuid,
                customer_phone=customer_phone,
                customer_name=customer_name,
                service=service,
                booking_date=booking_date,
                booking_time=booking_time,
                status='confirmed'
            )
            db.add(booking)
            await db.commit()
            await db.refresh(booking)
            return booking
    except Exception as e:
        import logging
        logging.error(f"Failed to save booking: {e}", exc_info=True)
        return None