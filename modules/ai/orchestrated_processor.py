# modules/ai/orchestrated_processor.py
import uuid
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.database import AsyncSessionLocal
from modules.common.redis_client import get_redis_client
from modules.websocket import ConnectionManager
from modules.orchestration.cache_manager import CacheManager
from modules.orchestration.conversation_state_machine import ConversationStateMachine
from modules.orchestration.intent_detector import IntentDetector
from modules.orchestration.workflow_engine import WorkflowOrchestrator
from modules.orchestration.memory_engine import MemoryEngine
from modules.orchestration.booking_executor import BookingExecutor, BookingDateTimeParser
from modules.orchestration.lead_merge_service import LeadMergeService
from modules.orchestration.follow_up_service import FollowUpService
from modules.orchestration.state_sync import StateSynchronizer
from modules.ai.agent import get_agent_for_user_compat
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.message.sender import send_whatsapp_text
from modules.common.models import Conversation, LeadSchema
from celery_app import celery_app
import uuid

def is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except ValueError:
        return False

logger = logging.getLogger(__name__)

class OrchestratedProcessor:
    def __init__(self):
        self.redis = get_redis_client()
        self.ws_manager = ConnectionManager()
        self.db_session = AsyncSessionLocal

    async def _get_or_create_conversation(self, db: AsyncSession, conversation_id: str, customer_phone: str, org_id: str) -> Conversation:
        """Helper to fetch or create conversation."""
        conv = await db.get(Conversation, conversation_id)
        if not conv:
            conv = Conversation(
                id=conversation_id,
                customer_phone_number=customer_phone,
                organization_id=org_id,
                conversation_stage="greeting",
                completed_fields={},
                booking_status="none"
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
        return conv

    async def _get_active_lead_schema(self, db: AsyncSession, org_id: str) -> Optional[LeadSchema]:
        """Fetch active lead schema for organisation."""
        from sqlalchemy import select
        result = await db.execute(
            select(LeadSchema)
            .where(LeadSchema.organization_id == org_id, LeadSchema.is_active == True)
            .order_by(LeadSchema.updated_at.desc())
        )
        return result.scalars().first()

    async def get_industry_for_org(self, org_id: str):
        """Return industry instance based on organisation settings."""
        async with AsyncSessionLocal() as db:
            from modules.common.models import Organization
            org = await db.get(Organization, org_id)
            industry_type = org.industry_type if org else "real_estate"

        if industry_type == "real_estate":
            from modules.ai.industries.realestate import RealEstateIndustry
            return RealEstateIndustry()
        elif industry_type == "restaurant":
            from modules.ai.industries.restaurant import RestaurantIndustry
            return RestaurantIndustry()
        elif industry_type == "salon":
            from modules.ai.industries.salon import SalonIndustry
            return SalonIndustry()
        else:
            # Fallback to real estate if unknown industry
            from modules.ai.industries.realestate import RealEstateIndustry
            return RealEstateIndustry()

    async def process_message(self, conversation_id: str, customer_phone: str, message: str, org_id: str) -> None:
        """Main orchestrated message processing pipeline."""
        async with self.db_session() as db:
            try:
                # 1. Get or create conversation
                conv = await self._get_or_create_conversation(db, conversation_id, customer_phone, org_id)

                # 2. Initialise components
                cache = CacheManager(db_session=db)
                state_machine = ConversationStateMachine(industry_rules={})
                memory = MemoryEngine(self.redis, db)
                parser = BookingDateTimeParser()
                booking_exec = BookingExecutor(db, parser)
                lead_merge = LeadMergeService(db)
                follow_up = FollowUpService(db, celery_app)
                sync = StateSynchronizer(cache, self.ws_manager)
                orchestrator = WorkflowOrchestrator(state_machine)

                # 3. Load current state
                state = await cache.get_conversation_state(conversation_id)
                if not state:
                    state = {
                        "stage": conv.conversation_stage,
                        "completed_fields": conv.completed_fields or {},
                        "booking_status": getattr(conv, "booking_status", "none"),
                        "last_intent": getattr(conv, "last_intent", None)
                    }

                # 4. Detect intent
                intent, entities = IntentDetector.detect(message)

                # 5. Extract lead data from conversation history
                history = await memory.get_recent_messages(conversation_id, limit=5)
                lead_schema = await self._get_active_lead_schema(db, org_id)
                extracted_data = {}
                if lead_schema:
                    extracted_data = await extract_lead_from_conversation(
                        history,
                        lead_schema.schema_fields or [],
                        lead_schema.extraction_prompt
                    )
                # Merge entities from intent detector
                extracted_data.update(entities)

                # 6. Update completed fields
                if extracted_data:
                    for field, value in extracted_data.items():
                        if value:
                            await cache.update_field(conversation_id, field, value)
                            if conv.completed_fields is None:
                                conv.completed_fields = {}
                            conv.completed_fields[field] = {"value": value, "completed_at": datetime.utcnow().isoformat()}

                # 7. Advance state machine
                new_stage, reason = await state_machine.try_advance_stage(conv, message, intent)
                if new_stage:
                    state["stage"] = new_stage
                    conv.conversation_stage = new_stage
                    await sync.sync_state(conversation_id, org_id, state)
                    logger.info(f"Stage advanced: {conv.conversation_stage} → {new_stage}, reason: {reason}")

                # 8. Determine next action
                action = await orchestrator.get_next_action(conv, message, {"intent": intent, "entities": extracted_data})

                # 9. Execute action
                ai_response = ""
                lead_id = None

                if action.get("action") == "create_booking":
                    lead_id, _ = await lead_merge.extract_or_update_lead(
                        phone=customer_phone,
                        organization_id=org_id,
                        extracted_data=extracted_data,
                        conversation_id=conversation_id,
                        customer_name=extracted_data.get("name", "")
                    )
                    result = await booking_exec.execute_booking(conversation_id, lead_id, message)
                    ai_response = result.user_message
                    if result.success:
                        state["booking_status"] = "confirmed"
                        conv.booking_status = "confirmed"
                        await sync.sync_state(conversation_id, org_id, state)
                        await follow_up.schedule_follow_up(
                            conversation_id=conversation_id,
                            lead_id=lead_id,
                            delay_days=1,
                            message_template="Reminder: Your visit is scheduled for tomorrow. Please confirm."
                        )

                elif action.get("action") == "ask_field":
                    missing_field = action.get("field", "requirements")
                    agent = get_agent_for_user_compat(customer_phone, org_id)
                    ai_response = agent.predict(f"Ask the customer for: {missing_field}")

                elif action.get("action") == "show_recommendations":
                    industry = await self.get_industry_for_org(org_id)
                    recommendations = await industry.get_recommendations(extracted_data or {}, limit=3)
                    if recommendations:
                        rec_text = "\n".join([f"• {r.get('title', 'Option')} – {r.get('price', 'Price on request')}" for r in recommendations])
                        ai_response = f"Here are some options matching your criteria:\n{rec_text}\nWould you like details on any?"
                    else:
                        ai_response = "I couldn't find any matching options right now. Could you adjust your criteria?"

                else:
                    # Fallback to existing AI agent
                    agent = get_agent_for_user_compat(customer_phone, org_id)
                    ai_response = agent.predict(message)

                # 10. Send response
                if not is_valid_uuid(conversation_id):
                    logger.error(f"Invalid conversation_id: {conversation_id}")
                    await send_whatsapp_text(customer_phone, "Internal error. Please try again.", org_id)
                    return
                success, _ = await send_whatsapp_text(customer_phone, ai_response, org_id)
                if not success:
                    logger.error(f"Failed to send WhatsApp message to {customer_phone}")

                # 11. Update memory
                await memory.add_message(conversation_id, "user", message)
                await memory.add_message(conversation_id, "assistant", ai_response)

                # 12. Persist conversation
                conv.last_intent = intent
                conv.updated_at = datetime.utcnow()
                await db.commit()

                # 13. Update final cache
                await cache.set_conversation_state(conversation_id, state)

                logger.info(f"Orchestrated message processed for {conversation_id}")

            except Exception as e:
                logger.error(f"Orchestrated processor error: {e}", exc_info=True)
                await send_whatsapp_text(customer_phone, "Sorry, I'm having trouble right now. Please try again later.", org_id)
                raise