# modules/ai/orchestrated_processor.py
import uuid
import os
import logging
import asyncio
import random
from datetime import datetime
from typing import Optional, Dict, Any, List
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
from modules.ai.agent import get_agent_for_user_compat, DEFAULT_MODEL
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.message.sender import send_whatsapp_text
from modules.common.models import Conversation, LeadSchema, AIConfig
from modules.ai.rag import search_knowledge
from celery_app import celery_app
from modules.orchestration.conversation_state import ConversationStateManager
from sqlalchemy import select
from groq import APIStatusError, APIConnectionError

def is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except ValueError:
        return False

logger = logging.getLogger(__name__)

class OrchestratedProcessor:
    FALLBACK_MODELS: List[str] = [
        "mixtral-8x7b-32768",
        "llama3-70b-8192",
        "gemma2-9b-it",
    ]
    MAX_RETRIES: int = 3
    BASE_RETRY_DELAY: float = 1.0
    MAX_RETRY_DELAY: float = 60.0

    def __init__(self):
        self.redis = get_redis_client()
        self.ws_manager = ConnectionManager()
        self.db_session = AsyncSessionLocal

    async def _get_ai_config(self, db: AsyncSession, org_id: str) -> Optional[AIConfig]:
        try:
            stmt = select(AIConfig).where(AIConfig.organization_id == org_id).order_by(AIConfig.updated_at.desc())
            result = await db.execute(stmt)
            return result.scalars().first()
        except Exception as e:
            logger.error(f"Failed to fetch AI config: {e}")
            return None

    async def _get_rag_context(self, org_id: str, query: str) -> str:
        try:
            chunks = search_knowledge(org_id, query, k=3)
            if chunks:
                return "\n\nRelevant information from our knowledge base:\n" + "\n".join(chunks)
        except Exception as e:
            logger.warning(f"RAG search failed: {e}")
        return ""

    async def _call_llm_direct(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        temperature: float,
        max_tokens: int,
        rag_context: str = ""
    ) -> str:
        from modules.ai.agent import client
        if rag_context:
            system_prompt = system_prompt + "\n\n" + rag_context
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

    async def _call_llm_with_retry(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        temperature: float,
        max_tokens: int,
        rag_context: str = ""
    ) -> str:
        models_to_try = [model] + [m for m in self.FALLBACK_MODELS if m != model]
        last_error = None
        for current_model in models_to_try:
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    return await self._call_llm_direct(
                        system_prompt, user_message, current_model,
                        temperature, max_tokens, rag_context
                    )
                except (APIStatusError, APIConnectionError) as e:
                    last_error = e
                    status_code = getattr(e, 'status_code', None)
                    if status_code == 503:
                        logger.warning(f"Model {current_model} over capacity (503), switching to next model")
                        break
                    if status_code == 429:
                        retry_after = self._parse_retry_after(e)
                        wait_time = min(retry_after, self.MAX_RETRY_DELAY)
                        logger.warning(f"Rate limited on {current_model}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    if status_code and 500 <= status_code < 600:
                        wait_time = min(
                            self.BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 0.5),
                            self.MAX_RETRY_DELAY
                        )
                        logger.warning(f"{current_model} error {status_code}, retry {attempt+1} in {wait_time:.2f}s")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"Non‑retryable error from {current_model}: {e}")
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error with {current_model}: {e}")
                    last_error = e
                    break
            logger.warning(f"Failed with model {current_model}, trying next fallback")
        raise Exception(f"All models failed. Last error: {last_error}")

    def _parse_retry_after(self, error: APIStatusError) -> float:
        try:
            headers = {}
            if hasattr(error, 'response') and error.response is not None:
                headers = getattr(error.response, 'headers', {})
            retry_after = headers.get('retry-after', headers.get('Retry-After', None))
            if retry_after:
                return float(retry_after)
        except Exception:
            pass
        return self.BASE_RETRY_DELAY * 2

    async def _get_or_create_conversation(self, db: AsyncSession, conversation_id: str, customer_phone: str, org_id: str) -> Conversation:
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
        result = await db.execute(
            select(LeadSchema)
            .where(LeadSchema.organization_id == org_id, LeadSchema.is_active == True)
            .order_by(LeadSchema.updated_at.desc())
        )
        return result.scalars().first()

    async def get_industry_for_org(self, org_id: str):
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
            from modules.ai.industries.realestate import RealEstateIndustry
            return RealEstateIndustry()

    async def process_message(self, conversation_id: str, customer_phone: str, message: str, org_id: str) -> None:
        async with self.db_session() as db:
            try:
                conv = await self._get_or_create_conversation(db, conversation_id, customer_phone, org_id)

                cache = CacheManager(redis_client=self.redis, db_session=db)
                state_manager = ConversationStateManager(redis_client=self.redis)
                memory = MemoryEngine(self.redis, db)
                parser = BookingDateTimeParser()
                booking_exec = BookingExecutor(db, parser)
                lead_merge = LeadMergeService(db)
                follow_up = FollowUpService(db, celery_app)
                sync = StateSynchronizer(cache, self.ws_manager)
                orchestrator = WorkflowOrchestrator(state_manager)
                state_machine = ConversationStateMachine()

                state = await cache.get_conversation_state(conversation_id)
                if not state:
                    state = {
                        "stage": conv.conversation_stage,
                        "completed_fields": conv.completed_fields or {},
                        "booking_status": getattr(conv, "booking_status", "none"),
                        "last_intent": getattr(conv, "last_intent", None)
                    }
                logger.info(f"Initial state completed_fields: {state.get('completed_fields', {})}")

                detect_result = IntentDetector.detect(message)
                if isinstance(detect_result, tuple):
                    intent = detect_result[0]
                    entities = detect_result[1] if len(detect_result) > 1 else {}
                else:
                    intent = detect_result
                    entities = {}

                history = await memory.get_recent_messages(conversation_id, limit=5)
                lead_schema = await self._get_active_lead_schema(db, org_id)
                extracted_data = {}
                if lead_schema:
                    extracted_data = await extract_lead_from_conversation(
                        history,
                        lead_schema.schema_fields or [],
                        lead_schema.extraction_prompt
                    )
                extracted_data.update(entities)

                if extracted_data:
                    for field, value in extracted_data.items():
                        if value:
                            await cache.update_field(conversation_id, field, value)
                            if conv.completed_fields is None:
                                conv.completed_fields = {}
                            conv.completed_fields[field] = {"value": value, "completed_at": datetime.utcnow().isoformat()}
                            if "completed_fields" not in state:
                                state["completed_fields"] = {}
                            state["completed_fields"][field] = {"value": value, "completed_at": datetime.utcnow().isoformat()}
                            logger.info(f"✅ Captured {field} = {value}. Completed: {list(state['completed_fields'].keys())}")

                new_stage, reason = await state_machine.try_advance_stage(
                    conversation=conv,
                    user_message=message,
                    intent=intent
                )
                if new_stage:
                    state["stage"] = new_stage
                    conv.conversation_stage = new_stage
                    await sync.sync_state(conversation_id, org_id, state)
                    logger.info(f"Stage advanced: {conv.conversation_stage} → {new_stage}, reason: {reason}")

                action = await orchestrator.get_next_action(conv, message, {"intent": intent, "entities": extracted_data}, org_id)

                rag_context = await self._get_rag_context(org_id, message)
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
                    ai_config = await self._get_ai_config(db, org_id)

                    # ✅ Default system prompt (prevents UnboundLocalError)
                    system_prompt = "You are a helpful real estate assistant. Never repeat known fields."
                    if ai_config and ai_config.system_prompt:
                        system_prompt = ai_config.system_prompt

                    # Replace placeholders
                    system_prompt = system_prompt.replace("{customer_name}", conv.customer_name or "")
                    system_prompt = system_prompt.replace("{current_stage}", state.get("stage", ""))
                    completed_list = ", ".join(state.get("completed_fields", {}).keys())
                    system_prompt = system_prompt.replace("{completed_fields_list}", completed_list)

                    # Append conversation history
                    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                    system_prompt = system_prompt + f"\n\nPrevious conversation:\n{history_text}\n"

                    user_prompt = f"The customer needs to provide: {missing_field}. Ask them politely for that one thing."
                    ai_response = await self._call_llm_with_retry(
                        system_prompt=system_prompt,
                        user_message=user_prompt,
                        model=ai_config.model_name if ai_config else DEFAULT_MODEL,
                        temperature=ai_config.temperature if ai_config else 0.7,
                        max_tokens=ai_config.max_tokens if ai_config else 500,
                        rag_context=rag_context
                    )

                elif action.get("action") == "show_recommendations":
                    industry = await self.get_industry_for_org(org_id)
                    recommendations = await industry.get_recommendations(extracted_data or {}, limit=3)
                    if recommendations:
                        rec_text = "\n".join([f"• {r.get('title', 'Option')} – {r.get('price', 'Price on request')}" for r in recommendations])
                        ai_response = f"Here are some options matching your criteria:\n{rec_text}\nWould you like details on any?"
                    else:
                        ai_response = "I couldn't find any matching options right now. Could you adjust your criteria?"

                else:
                    ai_config = await self._get_ai_config(db, org_id)

                    system_prompt = "You are a helpful real estate assistant. Never repeat known fields."
                    if ai_config and ai_config.system_prompt:
                        system_prompt = ai_config.system_prompt

                    system_prompt = system_prompt.replace("{customer_name}", conv.customer_name or "")
                    system_prompt = system_prompt.replace("{current_stage}", state.get("stage", ""))
                    completed_list = ", ".join(state.get("completed_fields", {}).keys())
                    system_prompt = system_prompt.replace("{completed_fields_list}", completed_list)

                    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                    system_prompt = system_prompt + f"\n\nPrevious conversation:\n{history_text}\n"

                    ai_response = await self._call_llm_with_retry(
                        system_prompt=system_prompt,
                        user_message=message,
                        model=ai_config.model_name if ai_config else DEFAULT_MODEL,
                        temperature=ai_config.temperature if ai_config else 0.7,
                        max_tokens=ai_config.max_tokens if ai_config else 500,
                        rag_context=rag_context
                    )

                if not is_valid_uuid(conversation_id):
                    logger.error(f"Invalid conversation_id: {conversation_id}")
                    await send_whatsapp_text(customer_phone, "Internal error. Please try again.", org_id)
                    return
                success, _ = await send_whatsapp_text(customer_phone, ai_response, org_id)
                if not success:
                    logger.error(f"Failed to send WhatsApp message to {customer_phone}")

                await memory.add_message(conversation_id, "user", message)
                await memory.add_message(conversation_id, "assistant", ai_response)

                conv.last_intent = intent
                conv.updated_at = datetime.utcnow()
                await db.commit()
                await cache.set_conversation_state(conversation_id, state)

                logger.info(f"Orchestrated message processed for {conversation_id}")

            except Exception as e:
                logger.error(f"Orchestrated processor error: {e}", exc_info=True)
                await send_whatsapp_text(customer_phone, "Sorry, I'm having trouble right now. Please try again later.", org_id)
                raise