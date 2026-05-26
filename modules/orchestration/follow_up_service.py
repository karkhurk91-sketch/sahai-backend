# modules/orchestration/follow_up_service.py
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.common.models import LeadNurturingStep
from modules.queue.tasks import send_follow_up_message  # existing Celery task

logger = logging.getLogger(__name__)

class FollowUpService:
    def __init__(self, db: AsyncSession, celery_app):
        self.db = db
        self.celery = celery_app
    
    async def schedule_follow_up(
        self,
        conversation_id: str,
        lead_id: str,
        delay_days: int,
        message_template: str,
        condition: Optional[Dict] = None
    ) -> str:
        scheduled_at = datetime.utcnow() + timedelta(days=delay_days)
        step = LeadNurturingStep(
            lead_id=lead_id,
            step_order=1,
            delay_days=delay_days,
            scheduled_at=scheduled_at,
            message_template=message_template,
            condition=condition or {},
            status="scheduled"
        )
        self.db.add(step)
        await self.db.commit()
        
        # Enqueue Celery task with ETA
        task = self.celery.send_task(
            "send_follow_up_message",
            args=[str(step.id), str(lead_id)],
            eta=scheduled_at,
            retry=True
        )
        return task.id