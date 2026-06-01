# modules/leads/nurturing_engine.py
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from modules.common.database import AsyncSessionLocal  # ✅ ADD THIS IMPORT
from modules.common.models import Lead, LeadNurturingStep, LeadNurturingLog
from modules.message.sender import send_whatsapp_text

logger = logging.getLogger(__name__)

async def run_due_nurturing_steps():
    """
    Called periodically by Celery beat to send any due nurturing steps.
    """
    async with AsyncSessionLocal() as db:
        # Find all leads that have an active nurturing sequence
        result = await db.execute(
            select(Lead).where(Lead.active_nurturing_sequence_id.is_not(None))
        )
        leads = result.scalars().all()

        for lead in leads:
            # Get all steps for the assigned sequence, ordered by step_order
            step_result = await db.execute(
                select(LeadNurturingStep)
                .where(LeadNurturingStep.sequence_id == lead.active_nurturing_sequence_id)
                .order_by(LeadNurturingStep.step_order)
            )
            steps = step_result.scalars().all()
            if not steps:
                continue

            # Determine the next step index (0-based)
            current_index = lead.last_nurturing_step or 0
            if current_index >= len(steps):
                continue  # all steps completed

            next_step = steps[current_index]

            # Calculate the due time based on delay_days from last sent time
            if lead.last_nurturing_sent_at is None:
                due_time = datetime.utcnow()  # first step: send immediately
            else:
                due_time = lead.last_nurturing_sent_at + timedelta(days=next_step.delay_days)

            if due_time <= datetime.utcnow():
                # Send the message
                message = next_step.custom_message
                if not message and next_step.template_id:
                    # Fetch template content (simplified; you may need to query templates table)
                    # For now, if no custom message, skip or use a default.
                    logger.warning(f"No message for step {next_step.id} – skipping")
                    continue

                success, wamid = await send_whatsapp_text(
                    to_number=lead.customer_phone,
                    text=message,
                    org_id=str(lead.organization_id)
                )

                if success:
                    # Update lead progress
                    lead.last_nurturing_step = next_step.step_order
                    lead.last_nurturing_sent_at = datetime.utcnow()
                    # Log the sent step
                    log = LeadNurturingLog(
                        lead_id=lead.id,
                        sequence_id=lead.active_nurturing_sequence_id,
                        step_order=next_step.step_order,
                        sent_at=datetime.utcnow(),
                        status="sent"
                    )
                    db.add(log)
                    await db.commit()
                    logger.info(f"Nurturing step {next_step.step_order} sent to lead {lead.id}")
                else:
                    logger.error(f"Failed to send nurturing step to lead {lead.id}")


async def process_nurturing_for_lead_sync(lead_id: str):
    """
    Immediately trigger the next nurturing step for a specific lead (manual trigger).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead or not lead.active_nurturing_sequence_id:
            logger.warning(f"Lead {lead_id} has no active nurturing sequence")
            return

        # Get steps in order
        step_result = await db.execute(
            select(LeadNurturingStep)
            .where(LeadNurturingStep.sequence_id == lead.active_nurturing_sequence_id)
            .order_by(LeadNurturingStep.step_order)
        )
        steps = step_result.scalars().all()
        if not steps:
            return

        current_index = lead.last_nurturing_step or 0
        if current_index >= len(steps):
            logger.info(f"Lead {lead_id} has already completed all nurturing steps")
            return

        next_step = steps[current_index]
        message = next_step.custom_message
        if not message:
            logger.warning(f"No message for step {next_step.id} – cannot send")
            return

        success, wamid = await send_whatsapp_text(
            to_number=lead.customer_phone,
            text=message,
            org_id=str(lead.organization_id)
        )

        if success:
            lead.last_nurturing_step = next_step.step_order
            lead.last_nurturing_sent_at = datetime.utcnow()
            log = LeadNurturingLog(
                lead_id=lead.id,
                sequence_id=lead.active_nurturing_sequence_id,
                step_order=next_step.step_order,
                sent_at=datetime.utcnow(),
                status="sent"
            )
            db.add(log)
            await db.commit()
            logger.info(f"Manual trigger: nurturing step {next_step.step_order} sent to lead {lead.id}")
        else:
            logger.error(f"Manual trigger failed to send message to lead {lead.id}")