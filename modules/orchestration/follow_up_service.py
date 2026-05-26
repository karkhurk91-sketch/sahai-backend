"""
Follow-up Service - Deterministic follow-up scheduling and execution.

Features:
- Schedule follow-ups with specific delays
- Evaluate conditions before sending
- Prevent duplicate follow-ups
- Integrate with Celery for scheduling
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FollowUpStatus(str, Enum):
    """Follow-up status"""
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class FollowUpService:
    """
    Deterministic follow-up service.
    
    Replaces LLM-based follow-up logic with deterministic scheduling.
    """
    
    def __init__(self, db: AsyncSession, celery_app=None):
        self.db = db
        self.celery_app = celery_app
    
    async def schedule_follow_up(
        self,
        conversation_id: str,
        lead_id: str,
        delay_days: int,
        message_template: str,
        condition: Optional[Dict] = None,
        priority: str = "normal"
    ) -> str:
        """
        Schedule a follow-up message.
        
        Args:
            conversation_id: UUID of conversation
            lead_id: UUID of lead
            delay_days: Days to wait before sending
            message_template: Pre-formatted message (no LLM call)
            condition: Optional conditions to evaluate before sending
            priority: "high", "normal", or "low"
        
        Returns:
            Follow-up ID
        """
        
        from modules.common.models import LeadNurturingStep
        
        scheduled_at = datetime.utcnow() + timedelta(days=delay_days)
        
        # Create follow-up record
        follow_up = LeadNurturingStep(
            lead_id=lead_id,
            conversation_id=conversation_id,
            delay_days=delay_days,
            scheduled_at=scheduled_at,
            message_template=message_template,
            condition=condition or {},
            status=FollowUpStatus.SCHEDULED.value,
            priority=priority
        )
        
        self.db.add(follow_up)
        await self.db.flush()
        
        logger.info(
            f"Scheduled follow-up {follow_up.id} for lead {lead_id}, "
            f"delay {delay_days} days"
        )
        
        # Schedule Celery task if available
        if self.celery_app:
            try:
                self.celery_app.send_task(
                    'send_follow_up_message',
                    args=[str(follow_up.id)],
                    eta=scheduled_at,
                    retry=True,
                    retry_policy={
                        'max_retries': 3,
                        'interval_start': 1,
                        'interval_step': 1,
                        'interval_max': 10,
                    }
                )
                logger.debug(f"Enqueued Celery task for follow-up {follow_up.id}")
            except Exception as e:
                logger.error(f"Error enqueueing Celery task: {e}")
        
        await self.db.commit()
        
        return str(follow_up.id)
    
    async def evaluate_condition(
        self,
        condition: Dict,
        lead_data: Dict,
        conversation_data: Dict,
        context: Optional[Dict] = None
    ) -> bool:
        """
        Evaluate if follow-up condition is met.
        
        Condition format:
        {
            "lead.budget_min": 1000000,
            "lead.booking_status": "confirmed",
            "conversation.stage": "followup"
        }
        
        Args:
            condition: Condition dict
            lead_data: Lead data
            conversation_data: Conversation data
            context: Optional additional context
        
        Returns:
            True if condition is met
        """
        
        if not condition:
            return True  # No condition = always send
        
        for key, expected_value in condition.items():
            # Check lead data
            if key.startswith("lead."):
                field = key.replace("lead.", "")
                actual_value = lead_data.get(field)
                
                if isinstance(expected_value, dict):
                    # Range check for numeric values
                    if expected_value.get("min") is not None:
                        if actual_value is None or actual_value < expected_value["min"]:
                            logger.debug(
                                f"Condition failed: {key} min check "
                                f"({actual_value} < {expected_value['min']})"
                            )
                            return False
                    
                    if expected_value.get("max") is not None:
                        if actual_value is None or actual_value > expected_value["max"]:
                            logger.debug(
                                f"Condition failed: {key} max check "
                                f"({actual_value} > {expected_value['max']})"
                            )
                            return False
                else:
                    # Exact match
                    if actual_value != expected_value:
                        logger.debug(
                            f"Condition failed: {key} "
                            f"({actual_value} != {expected_value})"
                        )
                        return False
            
            # Check conversation data
            elif key.startswith("conversation."):
                field = key.replace("conversation.", "")
                actual_value = conversation_data.get(field)
                
                if actual_value != expected_value:
                    logger.debug(
                        f"Condition failed: {key} "
                        f"({actual_value} != {expected_value})"
                    )
                    return False
        
        logger.debug(f"All conditions met for follow-up")
        return True
    
    async def send_follow_up(
        self,
        follow_up_id: str,
        phone: str,
        message_template: str,
        lead_data: Optional[Dict] = None,
        conversation_data: Optional[Dict] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Send follow-up message.
        
        Args:
            follow_up_id: Follow-up ID
            phone: User's phone
            message_template: Message to send
            lead_data: Lead data (for condition eval)
            conversation_data: Conversation data (for condition eval)
        
        Returns:
            (success, error_message)
        """
        
        from modules.common.models import LeadNurturingStep
        
        try:
            # Load follow-up
            result = await self.db.execute(
                select(LeadNurturingStep).where(
                    LeadNurturingStep.id == follow_up_id
                )
            )
            follow_up = result.scalar_one_or_none()
            
            if not follow_up:
                logger.error(f"Follow-up not found: {follow_up_id}")
                return False, "Follow-up not found"
            
            # Evaluate condition
            if follow_up.condition:
                if not await self.evaluate_condition(
                    follow_up.condition,
                    lead_data or {},
                    conversation_data or {}
                ):
                    logger.info(f"Follow-up condition not met: {follow_up_id}")
                    follow_up.status = FollowUpStatus.SKIPPED.value
                    follow_up.skipped_at = datetime.utcnow()
                    await self.db.commit()
                    return True, "Condition not met (skipped)"
            
            # Format message (no LLM)
            message = message_template
            if lead_data:
                for key, value in lead_data.items():
                    message = message.replace(f"{{{key}}}", str(value))
            
            # Send via WhatsApp (assuming service is available)
            try:
                from modules.common.whatsapp_service import send_message
                await send_message(phone, message)
            except Exception as e:
                logger.error(f"Error sending WhatsApp message: {e}")
                follow_up.status = FollowUpStatus.FAILED.value
                follow_up.failed_at = datetime.utcnow()
                follow_up.failure_reason = str(e)
                await self.db.commit()
                return False, f"WhatsApp send error: {e}"
            
            # Mark as sent
            follow_up.status = FollowUpStatus.SENT.value
            follow_up.sent_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info(f"Follow-up sent: {follow_up_id}")
            return True, None
        
        except Exception as e:
            logger.error(f"Error sending follow-up: {e}", exc_info=True)
            return False, str(e)
    
    async def cancel_follow_up(
        self,
        follow_up_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """Cancel a scheduled follow-up"""
        
        from modules.common.models import LeadNurturingStep
        
        try:
            result = await self.db.execute(
                select(LeadNurturingStep).where(
                    LeadNurturingStep.id == follow_up_id
                )
            )
            follow_up = result.scalar_one_or_none()
            
            if not follow_up:
                logger.error(f"Follow-up not found: {follow_up_id}")
                return False
            
            if follow_up.status != FollowUpStatus.SCHEDULED.value:
                logger.warning(
                    f"Cannot cancel follow-up {follow_up_id}: "
                    f"status is {follow_up.status}"
                )
                return False
            
            follow_up.status = FollowUpStatus.CANCELLED.value
            follow_up.cancelled_at = datetime.utcnow()
            follow_up.cancellation_reason = reason
            
            await self.db.commit()
            
            logger.info(f"Cancelled follow-up: {follow_up_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error cancelling follow-up: {e}")
            return False
    
    async def get_pending_follow_ups(
        self,
        limit: int = 100
    ) -> List:
        """Get follow-ups due to be sent soon"""
        
        from modules.common.models import LeadNurturingStep
        
        # Find follow-ups scheduled for next 1 hour
        now = datetime.utcnow()
        future = now + timedelta(hours=1)
        
        result = await self.db.execute(
            select(LeadNurturingStep).where(
                (LeadNurturingStep.status == FollowUpStatus.SCHEDULED.value) &
                (LeadNurturingStep.scheduled_at <= future) &
                (LeadNurturingStep.scheduled_at >= now)
            ).limit(limit)
        )
        
        return result.scalars().all()
    
    async def get_overdue_follow_ups(
        self,
        limit: int = 100
    ) -> List:
        """Get follow-ups that should have been sent"""
        
        from modules.common.models import LeadNurturingStep
        
        now = datetime.utcnow()
        
        result = await self.db.execute(
            select(LeadNurturingStep).where(
                (LeadNurturingStep.status == FollowUpStatus.SCHEDULED.value) &
                (LeadNurturingStep.scheduled_at < now)
            ).limit(limit)
        )
        
        return result.scalars().all()
