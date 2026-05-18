# modules/ai/lead_capture.py
from modules.common.database import AsyncSessionLocal
from modules.common.models import Lead
from sqlalchemy import select
import uuid
from datetime import datetime, timedelta
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def create_lead(org_id: str, customer_phone: str, interest: str, service: str = None, customer_name: str = "", lead_score: int = 70):
    """
    Create or update a lead for a customer per service within 24 hours.
    Different services create separate leads.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with AsyncSessionLocal() as session:
        # Build query: match same customer and same service (if provided)
        query = select(Lead).where(
            Lead.organization_id == uuid.UUID(org_id),
            Lead.customer_phone == customer_phone,
            Lead.created_at > cutoff
        )
        if service:
            query = query.where(Lead.service == service)
        else:
            # If no service, fallback to old behavior (match only phone)
            query = query.where(Lead.service.is_(None))
        
        result = await session.execute(query.order_by(Lead.created_at.desc()))
        existing = result.scalars().first()
        
        if existing:
            # Update existing lead for the same service
            existing.interest = interest
            existing.status = "new"
            existing.lead_score = lead_score
            existing.updated_at = datetime.utcnow()
            if customer_name:
                existing.customer_name = customer_name
            await session.commit()
            logger.info(f"Updated lead for {customer_phone} (service: {service})")
        else:
            # Create new lead
            lead = Lead(
                id=uuid.uuid4(),
                organization_id=uuid.UUID(org_id),
                customer_phone=customer_phone,
                customer_name=customer_name,
                interest=interest,
                service=service,
                status="new",
                lead_score=lead_score
            )
            session.add(lead)
            await session.commit()
            logger.info(f"Created new lead for {customer_phone} (service: {service})")
