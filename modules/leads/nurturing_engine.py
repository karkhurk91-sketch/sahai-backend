from sqlalchemy import select, and_
from datetime import datetime, timedelta
from modules.common.models import Lead, LeadNurturingStep, LeadNurturingLog
from modules.message.sender import send_whatsapp_text

async def run_due_nurturing_steps():
    async with AsyncSessionLocal() as db:
        # Find leads that have an active sequence and are due for next step
        now = datetime.utcnow()
        leads = await db.execute(
            select(Lead).where(
                Lead.active_nurturing_sequence_id.is_not(None),
                Lead.last_nurturing_sent_at < now - timedelta(days=1)  # simplified; real logic uses steps.delay_days
            )
        )
        for lead in leads.scalars():
            # Get current step
            step = await db.get(LeadNurturingStep, lead.last_nurturing_step + 1)  # simplified
            if step:
                # Send message via WhatsApp
                success, msg_id = await send_whatsapp_text(
                    to_number=lead.customer_phone,
                    text=step.custom_message or step.template.content,
                    org_id=str(lead.organization_id)
                )
                if success:
                    lead.last_nurturing_step = step.step_order
                    lead.last_nurturing_sent_at = now
                    log = LeadNurturingLog(lead_id=lead.id, step_id=step.id, status="sent")
                    db.add(log)
                    await db.commit()