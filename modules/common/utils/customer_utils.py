from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from modules.common.models import Customer

def normalize_phone(phone: str) -> str:
    """Normalize phone number by removing +, spaces, dashes, parentheses."""
    if not phone:
        return ""
    return phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()

async def find_customer_by_phone(db: AsyncSession, org_id: UUID, phone_number: str) -> Customer | None:
    """Find an active customer by normalized phone number."""
    phone_norm = normalize_phone(phone_number)
    if not phone_norm:
        return None
    stmt = select(Customer).where(
        Customer.organization_id == org_id,
        func.replace(Customer.phone_number, '+', '') == phone_norm,
        Customer.deleted_at.is_(None)
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def link_customer_to_record(db: AsyncSession, org_id: UUID, phone_number: str, record) -> bool:
    """
    Find a customer by phone and set record.customer_id and record.customer_name (if applicable).
    Returns True if linked, False otherwise.
    """
    customer = await find_customer_by_phone(db, org_id, phone_number)
    if customer:
        record.customer_id = customer.id
        # Optionally set name if record has a name field
        if hasattr(record, 'customer_name') and not record.customer_name:
            record.customer_name = customer.name
        return True
    return False