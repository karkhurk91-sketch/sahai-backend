import uuid
from datetime import datetime
from modules.common.database import sync_engine
from sqlalchemy import text

def save_booking_generic(org_id: str, state, industry: str):
    if industry == "restaurant":
        customer_phone = getattr(state, 'phone', None)
        customer_name = getattr(state, 'name', None)
        service = str(getattr(state, 'order_items', {}))
        booking_date = datetime.now().date()
        booking_time = datetime.now().time()
    elif industry == "salon":
        customer_phone = getattr(state, 'phone', None)
        customer_name = getattr(state, 'name', None)
        service = getattr(state, 'service', None)
        booking_date = datetime.now().date()
        booking_time = getattr(state, 'time', "14:00:00")
    else:
        return

    with sync_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO bookings (id, organization_id, customer_phone, customer_name, service, booking_date, booking_time, status)
                VALUES (:id, :org_id, :phone, :name, :service, :date, :time, 'confirmed')
            """),
            {
                "id": uuid.uuid4(),
                "org_id": org_id,
                "phone": customer_phone,
                "name": customer_name,
                "service": service,
                "date": booking_date,
                "time": booking_time
            }
        )
        conn.commit()