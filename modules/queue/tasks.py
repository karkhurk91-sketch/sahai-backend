# Add these imports at the top of the file (if not present)
import asyncio
from celery_app import celery_app
from modules.leads.nurturing_engine import run_due_nurturing_steps
from modules.leads.scoring_engine import rescore_all_active_leads
from modules.bookings.reminders import send_booking_reminders
from modules.common.logger import get_logger
from celery import shared_task
from modules.message.sender import send_whatsapp_text

logger = get_logger(__name__)

# Add these tasks (they will be discovered by Celery)
@celery_app.task(name='modules.queue.tasks.run_nurturing_task')
def run_nurturing_task():
    """Run the advanced lead nurturing engine (checks sequences, delays, etc.)."""
    try:
        asyncio.run(run_due_nurturing_steps())
        logger.info("Nurturing engine run completed")
    except Exception as e:
        logger.error(f"Nurturing engine failed: {e}", exc_info=True)

@celery_app.task(name='modules.queue.tasks.rescore_leads_task')
def rescore_leads_task():
    """Periodically rescore all active leads."""
    try:
        asyncio.run(rescore_all_active_leads())
        logger.info("Lead rescoring completed")
    except Exception as e:
        logger.error(f"Lead rescoring failed: {e}", exc_info=True)

@celery_app.task(name='modules.queue.tasks.send_booking_reminders')
def send_booking_reminders_task():
    """Daily reminder for upcoming bookings."""
    try:
        asyncio.run(send_booking_reminders())
        logger.info("Booking reminders sent")
    except Exception as e:
        logger.error(f"Booking reminders failed: {e}", exc_info=True)

@shared_task(bind=True, max_retries=3)
def send_follow_up_message(self, follow_up_id: str, lead_id: str):
    from modules.common.database import AsyncSessionLocal
    from modules.common.models import Lead, LeadNurturingStep
    import asyncio

    async def _send():
        async with AsyncSessionLocal() as db:
            step = await db.get(LeadNurturingStep, follow_up_id)
            lead = await db.get(Lead, lead_id)
            if step and lead and step.status == "scheduled":
                success, _ = await send_whatsapp_text(lead.phone_number, step.message_template, str(lead.organization_id))
                if success:
                    step.status = "sent"
                    await db.commit()
    asyncio.run(_send())