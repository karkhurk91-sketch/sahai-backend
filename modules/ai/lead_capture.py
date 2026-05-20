# modules/ai/lead_capture.py
from modules.common.database import AsyncSessionLocal
from modules.common.models import Lead
from sqlalchemy import select
import uuid
from datetime import datetime, timedelta
from modules.common.logger import get_logger

logger = get_logger(__name__)

async def create_lead(
    org_id: str,
    customer_phone: str,
    extracted_data=None,
    schema_id: str = None,
    conversation_id: str = None,
    customer_name: str = "",
    lead_score: int = 70,
    interest: str = "",
    service: str = None,
    urgency: str = None,
    intent: str = None,
    sentiment: str = None,
    conversion_probability: float = None,
    follow_up_scheduled_at=None,
    lead_stage: str = None,
    rule_state: dict = None,
    status: str = "new"
):
    """
    Create or update a lead. Supports schema-based extraction data and retains backward compatibility with older positional calls.
    """
    if not isinstance(extracted_data, dict):
        # Backwards compatibility: positional interest string passed as extracted_data
        if not interest and isinstance(extracted_data, str):
            interest = extracted_data
        extracted_data = {}

    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with AsyncSessionLocal() as session:
        query = select(Lead).where(
            Lead.organization_id == uuid.UUID(org_id),
            Lead.customer_phone == customer_phone,
            Lead.created_at > cutoff
        )
        if schema_id:
            query = query.where(Lead.schema_id == uuid.UUID(schema_id))
        else:
            query = query.where(Lead.schema_id.is_(None))

        result = await session.execute(query.order_by(Lead.created_at.desc()))
        existing = result.scalars().first()

        if existing:
            existing.status = status or existing.status
            existing.updated_at = datetime.utcnow()
            if customer_name:
                existing.customer_name = customer_name
            if interest:
                existing.interest = interest
            if service is not None:
                existing.service = service
            if extracted_data:
                merged = {**(existing.data or {}), **extracted_data}
                existing.data = merged
                if extracted_data.get('interest'):
                    existing.interest = extracted_data.get('interest')
                if extracted_data.get('service') is not None:
                    existing.service = extracted_data.get('service')
                if extracted_data.get('lead_score') is not None:
                    try:
                        existing.lead_score = int(extracted_data.get('lead_score') or existing.lead_score)
                    except (TypeError, ValueError):
                        pass
                if extracted_data.get('urgency') is not None:
                    existing.urgency = extracted_data.get('urgency')
                if extracted_data.get('intent') is not None:
                    existing.intent = extracted_data.get('intent')
                if extracted_data.get('sentiment') is not None:
                    existing.sentiment = extracted_data.get('sentiment')
            if schema_id:
                existing.schema_id = uuid.UUID(schema_id)
            if conversation_id:
                existing.conversation_id = uuid.UUID(conversation_id)
            if lead_score is not None:
                existing.lead_score = lead_score
            if urgency is not None:
                existing.urgency = urgency
            if intent is not None:
                existing.intent = intent
            if sentiment is not None:
                existing.sentiment = sentiment
            if conversion_probability is not None:
                existing.conversion_probability = conversion_probability
            if follow_up_scheduled_at is not None:
                existing.follow_up_scheduled_at = follow_up_scheduled_at
            if lead_stage is not None:
                existing.lead_stage = lead_stage
            if rule_state is not None:
                existing.rule_state = rule_state
            await session.commit()
            logger.info(f"Updated lead for {customer_phone} (schema_id={schema_id}, service={service})")
            # Enqueue follow-up task if scheduled
            try:
                if getattr(existing, 'follow_up_scheduled_at', None):
                    from modules.queue.producer import celery_app
                    celery_app.send_task('modules.queue.tasks.process_follow_up', args=[str(existing.id)])
            except Exception:
                logger.exception("Failed to enqueue follow-up task after lead update")
        else:
            lead = Lead(
                id=uuid.uuid4(),
                organization_id=uuid.UUID(org_id),
                conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
                customer_phone=customer_phone,
                customer_name=customer_name,
                interest=interest,
                data=extracted_data or {},
                schema_id=uuid.UUID(schema_id) if schema_id else None,
                service=service,
                status=status or "new",
                lead_score=lead_score,
                urgency=urgency or "medium",
                intent=intent,
                sentiment=sentiment or "neutral",
                conversion_probability=conversion_probability or 0.0,
                follow_up_scheduled_at=follow_up_scheduled_at,
                lead_stage=lead_stage or "new",
                rule_state=rule_state or {},
                assigned_to=None
            )
            session.add(lead)
            await session.commit()
            logger.info(f"Created new lead for {customer_phone} (schema_id={schema_id}, service={service})")
            # Enqueue follow-up task if scheduled
            try:
                if getattr(lead, 'follow_up_scheduled_at', None):
                    from modules.queue.producer import celery_app
                    celery_app.send_task('modules.queue.tasks.process_follow_up', args=[str(lead.id)])
            except Exception:
                logger.exception("Failed to enqueue follow-up task after lead creation")
