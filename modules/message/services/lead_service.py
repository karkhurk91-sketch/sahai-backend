import uuid
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal
from modules.common.models import Lead
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def get_last_lead_data(phone_number: str, org_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lead)
            .where(
                Lead.customer_phone == phone_number,
                Lead.organization_id == UUID(org_id)
            )
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return {}
        prefill = {}
        if lead.data and isinstance(lead.data, dict):
            prefill["name"] = lead.data.get("name") or lead.customer_name or ""
            prefill["email"] = lead.data.get("email") or lead.email or ""
            prefill["phone"] = lead.data.get("phone") or lead.customer_phone or phone_number
        else:
            prefill["name"] = lead.customer_name or ""
            prefill["email"] = lead.email or ""
            prefill["phone"] = lead.customer_phone or phone_number
        return prefill

async def create_lead_from_generic_bot(org_id: str, conversation_id: str, customer_phone: str, responses: dict):
    try:
        customer_name = responses.get("name") or responses.get("customer_name") or ""
        email = responses.get("email") or ""
        phone = responses.get("phone") or customer_phone
        lead = Lead(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(org_id),
            conversation_id=uuid.UUID(conversation_id),
            customer_phone=phone,
            customer_name=customer_name,
            email=email,
            status="new",
            lead_score=70,
            conversion_probability=0.5,
            created_at=datetime.utcnow()
        )
        if hasattr(lead, 'data'):
            lead.data = responses
        async with AsyncSessionLocal() as session:
            session.add(lead)
            await session.commit()
            logger.info(f"Lead created from generic bot for conversation {conversation_id}")
            return lead.id
    except Exception as e:
        logger.error(f"Failed to create lead from generic bot: {e}", exc_info=True)
        return None
