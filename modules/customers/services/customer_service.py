from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from modules.common.models import Customer, Conversation, Lead, Booking, CustomerGroupMember
from modules.common.logger import get_logger

logger = get_logger(__name__)

class CustomerService:
    # ... existing methods (if any) ...

    async def soft_delete_customer(self, db: AsyncSession, customer_id: UUID, deleted_by: UUID) -> None:
        """Soft‑delete a customer and all associated records."""
        # 1. Fetch the customer
        customer = await db.get(Customer, customer_id)
        if not customer:
            raise ValueError("Customer not found")

        now = datetime.now(timezone.utc)

        # 2. Soft‑delete the customer
        customer.deleted_at = now

        # 3. Soft‑delete related conversations (by customer_id)
        await db.execute(
            update(Conversation)
            .where(
                Conversation.customer_id == customer_id,
                Conversation.deleted_at.is_(None)
            )
            .values(deleted_at=now)
        )

        # 4. Soft‑delete related leads (by customer_id)
        await db.execute(
            update(Lead)
            .where(
                Lead.customer_id == customer_id,
                Lead.deleted_at.is_(None)
            )
            .values(deleted_at=now)
        )

        # 5. Soft‑delete related bookings (by customer_id)
        await db.execute(
            update(Booking)
            .where(
                Booking.customer_id == customer_id,
                Booking.deleted_at.is_(None)
            )
            .values(deleted_at=now)
        )

        # 6. Soft‑delete customer group memberships
        await db.execute(
            update(CustomerGroupMember)
            .where(
                CustomerGroupMember.customer_id == customer_id,
                CustomerGroupMember.deleted_at.is_(None)
            )
            .values(deleted_at=now)
        )

        await db.commit()
        logger.info(f"Customer {customer_id} and all associations soft‑deleted by user {deleted_by}")