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
from modules.orchestration.conversation_state_machine import ConversationStateMachine, ConversationStage
from modules.orchestration.intent_detector import IntentDetector
from modules.orchestration.workflow_engine import WorkflowOrchestrator
from modules.orchestration.memory_engine import MemoryEngine
from modules.orchestration.booking_executor import BookingExecutor, BookingDateTimeParser
from modules.orchestration.lead_merge_service import LeadMergeService
from modules.orchestration.follow_up_service import FollowUpService
from modules.orchestration.state_sync import StateSynchronizer
from modules.ai.agent import get_agent_for_user_compat
from modules.ai.lead_extractor import extract_lead_from_conversation  # existing
from modules.message.sender import send_whatsapp_text
from modules.orchestration.industries.real_estate import RealEstateIndustry
from modules.orchestration.industries.restaurant import RestaurantIndustry
from celery_app import app as celery_app  # import once at top
from modules.common.models import Conversation, LeadSchema
from modules.orchestration.booking_parser import BookingDateTimeParser
from modules.orchestration.booking_executor import BookingExecutor

logger = logging.getLogger(__name__)

class OrchestratedProcessor:
    def __init__(self):
        self.redis = get_redis_client()
        self.ws_manager = ConnectionManager()
        self.db_session = AsyncSessionLocal

    @staticmethod
    def get_industry_for_org(org_id: str):
        """Return industry instance based on organization settings."""
        # TODO: Query organisation.industry_type from DB
        industry_type = "real_estate"  # default, read from DB
        if industry_type == "real_estate":
            return RealEstateIndustry()
        elif industry_type == "restaurant":
            return RestaurantIndustry()
        return RealEstateIndustry()

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

    async def process_message(self, conversation_id: str, customer_phone: str, message: str, org_id: str) -> None:
        """
        Main orchestrated message processing pipeline.
        Feature flag USE_ORCHESTRATION must be 'true' to use this.
        """
        async with self.db_session() as db:
            try:
                # 1. Get or create conversation
                conv = await self._get_or_create_conversation(db, conversation_id, customer_phone, org_id)

                # 2. Initialise components
                cache = CacheManager(self.redis, db)
                state_machine = ConversationStateMachine(industry_rules={})
                memory = MemoryEngine(self.redis, db)
                parser = BookingDateTimeParser()
                booking_exec = BookingExecutor(db, parser)
                lead_merge = LeadMergeService(db)
                follow_up = FollowUpService(db, celery_app)
                sync = StateSynchronizer(cache, self.ws_manager)
                orchestrator = WorkflowOrchestrator(state_machine)

                # 3. Load current state from cache
                state = await cache.get_conversation_state(conversation_id)
                if not state:
                    state = {
                        "stage": conv.conversation_stage,
                        "completed_fields": conv.completed_fields or {},
                        "booking_status": conv.booking_status or "none",
                        "last_intent": conv.last_intent
                    }

                # 4. Detect intent and extract entities
                intent, entities = IntentDetector.detect(message)

                # 5. Full lead extraction (using existing lead_extractor)
                #    Get conversation history for context
                history = await memory.get_recent_messages(conversation_id, limit=5)
                lead_schema = await self._get_active_lead_schema(db, org_id)
                extracted_data = {}
                if lead_schema:
                    extracted_data = await extract_lead_from_conversation(
                        history,
                        lead_schema.schema_fields or [],
                        lead_schema.extraction_prompt
                    )
                # Merge intent entities into extracted data
                extracted_data.update(entities)

                # 6. Update completed fields
                if extracted_data:
                    for field, value in extracted_data.items():
                        if value:
                            await cache.update_field(conversation_id, field, value)
                            # Also update conv.completed_fields for consistency
                            if conv.completed_fields is None:
                                conv.completed_fields = {}
                            conv.completed_fields[field] = {"value": value, "completed_at": datetime.utcnow().isoformat()}

                # 7. Advance state machine (deterministic)
                new_stage, reason = await state_machine.try_advance_stage(conv, message, intent)
                if new_stage:
                    state["stage"] = new_stage
                    conv.conversation_stage = new_stage
                    await sync.sync_state(conversation_id, org_id, state)
                    logger.info(f"Stage advanced: {conv.conversation_stage} → {new_stage}, reason: {reason}")

                # 8. Determine next action via workflow engine
                action = await orchestrator.get_next_action(conv, message, {"intent": intent, "entities": extracted_data})

                # 9. Execute action
                ai_response = ""
                lead_id = None

                if action.get("action") == "create_booking":
                    # Ensure lead exists
                    lead_id, is_new = await lead_merge.extract_or_update_lead(
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
                        # Schedule follow-up
                        await follow_up.schedule_follow_up(
                            conversation_id=conversation_id,
                            lead_id=lead_id,
                            delay_days=1,
                            message_template="Reminder: Your visit is scheduled for tomorrow. Please confirm."
                        )

                elif action.get("action") == "ask_field":
                    # Use LLM to ask for the missing field (but system decides which field)
                    missing_field = action.get("field", "requirements")
                    agent = get_agent_for_user_compat(customer_phone, org_id)
                    ai_response = agent.predict(f"Ask the customer for: {missing_field}")

                elif action.get("action") == "show_recommendations":
                    # Use industry-specific recommendations
                    industry = self.get_industry_for_org(org_id)
                    recommendations = await industry.get_recommendations(extracted_data or {}, limit=3)
                    # Format recommendations into a message
                    if recommendations:
                        rec_text = "\n".join([f"• {r.get('title', 'Option')} – {r.get('price', 'Price on request')}" for r in recommendations])
                        ai_response = f"Here are some options matching your criteria:\n{rec_text}\nWould you like details on any?"
                    else:
                        ai_response = "I couldn't find any matching options right now. Could you adjust your criteria?"

                else:
                    # Default: use existing AI agent (fallback, should be minimised)
                    agent = get_agent_for_user_compat(customer_phone, org_id)
                    ai_response = agent.predict(message)

                # 10. Send response via WhatsApp
                success, _ = await send_whatsapp_text(customer_phone, ai_response, org_id)
                if not success:
                    logger.error(f"Failed to send WhatsApp message to {customer_phone}")

                # 11. Update conversation memory
                await memory.add_message(conversation_id, "user", message)
                await memory.add_message(conversation_id, "assistant", ai_response)

                # 12. Persist conversation state to DB
                conv.last_intent = intent
                conv.updated_at = datetime.utcnow()
                await db.commit()

                # 13. Update final cache state
                await cache.set_conversation_state(conversation_id, state)

                logger.info(f"Orchestrated message processed for {conversation_id}")

            except Exception as e:
                logger.error(f"Orchestrated processor error: {e}", exc_info=True)
                # Fallback: send a generic error message to user
                await send_whatsapp_text(customer_phone, "Sorry, I'm having trouble right now. Please try again later.", org_id)
                raise

    async def _get_active_lead_schema(self, db: AsyncSession, org_id: str) -> Optional[LeadSchema]:
        """Fetch active lead schema for organisation."""
        from sqlalchemy import select
        result = await db.execute(
            select(LeadSchema)
            .where(LeadSchema.organization_id == org_id, LeadSchema.is_active == True)
            .order_by(LeadSchema.updated_at.desc())
        )
        return result.scalars().first()