import asyncio
from datetime import datetime
from modules.queue.producer import celery_app
from modules.common.database import sync_engine
from sqlalchemy import text
from modules.common.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name='modules.queue.tasks.check_due_followups')
def check_due_followups():
	"""Scan for leads with follow_up_scheduled_at <= now and queue follow-up processing."""
	now = datetime.utcnow()
	with sync_engine.connect() as conn:
		result = conn.execute(
			text("""
				SELECT id, organization_id, customer_phone, follow_up_scheduled_at
				FROM leads
				WHERE follow_up_scheduled_at IS NOT NULL
				  AND follow_up_scheduled_at <= NOW()
				  AND status NOT IN ('converted', 'lost')
				LIMIT 100
			""")
		)
		rows = result.fetchall()
	for row in rows:
		lead_id = str(row[0])
		try:
			celery_app.send_task('modules.queue.tasks.process_follow_up', args=[lead_id])
			logger.info(f"Enqueued follow-up for lead {lead_id}")
		except Exception as e:
			logger.error(f"Failed to enqueue follow-up for {lead_id}: {e}")


@celery_app.task(name='modules.queue.tasks.process_follow_up')
def process_follow_up(lead_id: str):
	"""Process a single lead follow-up: send message and clear scheduled follow-up."""
	try:
		# Import async sender here to avoid circular imports at module import time
		from modules.message.sender import send_whatsapp_text

		# Fetch lead details synchronously
		with sync_engine.connect() as conn:
			res = conn.execute(
				text("SELECT id, organization_id, customer_phone, follow_up_scheduled_at, data FROM leads WHERE id = :id"),
				{"id": lead_id}
			)
			row = res.fetchone()
			if not row:
				logger.warning(f"Lead not found for follow-up: {lead_id}")
				return
			org_id = str(row[1])
			phone = row[2]

		# Build a simple follow-up message; in future, use templates or org settings
		message = "Hi — just checking in on your request. Can I help with anything else?"

		# Call async sender
		try:
			asyncio.run(send_whatsapp_text(phone, message, org_id=org_id))
			logger.info(f"Sent follow-up to lead {lead_id} ({phone})")
		except Exception as e:
			logger.error(f"Failed sending follow-up for lead {lead_id}: {e}")

		# Clear follow_up_scheduled_at so we don't repeat the follow-up
		with sync_engine.connect() as conn:
			conn.execute(
				text("UPDATE leads SET follow_up_scheduled_at = NULL, updated_at = NOW() WHERE id = :id"),
				{"id": lead_id}
			)
			conn.commit()

	except Exception as e:
		logger.error(f"Error processing follow-up for {lead_id}: {e}")

