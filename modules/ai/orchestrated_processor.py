"""
PHASE 1: Orchestration-based Message Processor
Replaces prompt-driven chatbot with system-driven orchestration
Preserves all existing features while adding state machine stability
"""

import uuid
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from modules.ai.memory_manager import MemoryManager
from modules.ai.agent import get_agent_for_user_compat
from modules.ai.lead_capture import create_lead
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.common.database import sync_engine, AsyncSessionLocal
from modules.common.models import Conversation, Message, LeadSchema, Lead
from modules.common.logger import get_logger
from modules.leads.assignment_engine import auto_assign_lead, determine_lead_intelligence
from modules.message.sender import send_whatsapp_text, send_whatsapp_template
from modules.orchestration.conversation_state import ConversationStateManager
from modules.orchestration.intent_detector import IntentDetector
from modules.orchestration.workflow_engine import WorkflowOrchestrator
from modules.orchestration.memory_engine import EnterpriseMemoryEngine
from modules.orchestration.tool_executor import ToolExecutor
from modules.orchestration.state_sync import StateSynchronizer

logger = get_logger(__name__)
memory_manager = MemoryManager()


async def process_incoming_message_orchestrated(message: dict):
    """
    PHASE 1: New orchestration-based message processor.
    
    Flow:
    1. Load conversation state (Redis)
    2. Detect intent (rule-based)
    3. Load memory context
    4. Orchestrate next action (system-driven, not LLM-driven)
    5. Execute tools if needed
    6. Generate AI response (LLM only for language)
    7. Sync state (Redis + DB + WebSocket)
    """
    conversation_id = message.get("conversation_id")
    user_phone = message["from_number"]
    user_text = message["text"]
    org_id = message.get("org_id")
    timestamp = message.get("timestamp")

    if not conversation_id:
        logger.error("Missing conversation_id")
        return

    await _orchestrated_process_and_reply(
        conversation_id=conversation_id,
        customer_phone=user_phone,
        customer_message=user_text,
        org_id=org_id,
        timestamp=timestamp
    )


async def _orchestrated_process_and_reply(
    conversation_id: str,
    customer_phone: str,
    customer_message: str,
    org_id: str,
    timestamp: int = None
):
    """
    Orchestration-based message processing (PHASE 1).
    """
    logger.info(f"[ORCHESTRATED] Processing message from {customer_phone}: {customer_message[:50]}")

    try:
        org_uuid = uuid.UUID(org_id) if isinstance(org_id, str) else org_id
        conv_uuid = uuid.UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id

        # ========== STEP 1: Initialize Orchestration Layer ==========
        state_manager = ConversationStateManager()
        workflow = WorkflowOrchestrator(state_manager)
        memory_engine = EnterpriseMemoryEngine()
        
        # ========== STEP 2: Load Conversation State ==========
        conv_state = await state_manager.get_state(conversation_id)
        current_stage = conv_state.get("stage", "greeting")
        logger.info(f"[STATE] Current stage: {current_stage}")

        # ========== STEP 3: Detect Intent (Rule-based) ==========
        intent = IntentDetector.detect(customer_message)
        entities = IntentDetector.extract_entities(customer_message, intent)
        logger.info(f"[INTENT] Detected: {intent.value}, Entities: {entities}")

        # ========== STEP 4: Load Memory Context ==========
        memory_context = await memory_engine.load_context(conversation_id)
        logger.debug(f"[MEMORY] Loaded context: {list(memory_context.keys())}")

        # ========== STEP 5: Orchestrate Next Action (SYSTEM-DRIVEN) ==========
        action_plan = await workflow.get_next_action(
            conversation_id=conversation_id,
            user_message=customer_message,
            memory_context=memory_context,
            organization_id=str(org_uuid),
        )
        logger.info(f"[ACTION] Orchestrated: {action_plan.get('action')}")

        # ========== STEP 6: Execute Tools if Needed ==========
        tool_result = None
        if action_plan.get("action") == "create_booking":
            # Only create booking if orchestrator decided it
            async with AsyncSessionLocal() as db:
                conv_result = await db.execute(
                    select(Conversation).where(Conversation.id == conv_uuid)
                )
                conv = conv_result.scalars().first()

                lead_result = await db.execute(
                    select(Lead).where(
                        Lead.organization_id == org_uuid,
                        Lead.customer_phone == customer_phone
                    ).order_by(Lead.created_at.desc()).limit(1)
                )
                lead = lead_result.scalars().first()

            if lead and conv:
                tool_result = await ToolExecutor.create_booking(
                    org_id=str(org_uuid),
                    lead_id=str(lead.id),
                    customer_phone=customer_phone,
                    customer_name=conv.customer_name or "",
                    service=conv.service or "site visit",
                    booking_data=action_plan.get("action_data", {}),
                )
                logger.info(f"[TOOL] Booking result: {tool_result}")

        # ========== STEP 7: Generate AI Response (LLM ONLY FOR LANGUAGE) ==========
        ai_context = action_plan.get("ai_context", {})
        
        # Construct context for LLM
        llm_context = f"""
        Current stage: {current_stage}
        User intent: {intent.value}
        Memory: {memory_context.get('summary', '')}
        Action: {action_plan.get('action')}
        Context: {ai_context}
        """

        agent = get_agent_for_user_compat(customer_phone, org_id)
        ai_response = agent.predict(customer_message)
        logger.info(f"[AI] Generated response: {ai_response[:100]}")

        # ========== STEP 8: Store Messages ==========
        async with AsyncSessionLocal() as db:
            msg_id = uuid.uuid4()
            
            # Store user message
            user_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conv_uuid,
                direction="inbound",
                message_type="text",
                content=customer_message,
                is_ai_generated=False,
                status="received",
                created_at=datetime.now(timezone.utc),
                whatsapp_timestamp=timestamp or int(datetime.now(timezone.utc).timestamp()),
                sort_timestamp=datetime.now(timezone.utc),
            )
            db.add(user_msg)

            # Store AI response
            ai_msg = Message(
                id=msg_id,
                conversation_id=conv_uuid,
                direction="outbound",
                message_type="text",
                content=ai_response,
                is_ai_generated=True,
                status="sent",
                created_at=datetime.now(timezone.utc),
                whatsapp_timestamp=int(datetime.now(timezone.utc).timestamp()),
                sort_timestamp=datetime.now(timezone.utc),
            )
            db.add(ai_msg)

            # Update conversation
            conv = await db.get(Conversation, conv_uuid)
            if conv:
                conv.last_message_at = datetime.now(timezone.utc)
                conv.last_intent = intent.value

            await db.commit()

        # ========== STEP 9: Send WhatsApp Response ==========
        success, wamid = await send_whatsapp_text(
            to_number=customer_phone,
            text=ai_response,
            org_id=str(org_uuid)
        )
        if success:
            logger.info(f"[WHATSAPP] Message sent: {wamid}")

        # ========== STEP 10: Update Conversation State ==========
        if action_plan.get("should_update_stage"):
            new_stage = action_plan.get("next_stage")
            await state_manager.update_stage(
                conversation_id=conversation_id,
                new_stage=new_stage,
                reason=f"Action: {action_plan.get('action')}"
            )
            logger.info(f"[STATE] Updated stage: {current_stage} → {new_stage}")

        # ========== STEP 11: Add to Memory ==========
        await memory_engine.add_message_to_memory(
            conversation_id=conversation_id,
            role="user",
            content=customer_message,
            metadata={"intent": intent.value, "entities": entities}
        )
        await memory_engine.add_message_to_memory(
            conversation_id=conversation_id,
            role="assistant",
            content=ai_response,
            metadata={"action": action_plan.get("action")}
        )

        # ========== STEP 12: Sync State Across Layers ==========
        # (Redis + DB + WebSocket would go here with websocket_manager)
        await StateSynchronizer.sync_to_redis(
            None,  # Redis client would be injected
            conversation_id,
            conv_state
        )

        logger.info(f"[ORCHESTRATED] Message processed successfully")

    except Exception as e:
        logger.error(f"[ERROR] Orchestrated processing failed: {e}", exc_info=True)
        # Send error response
        await send_whatsapp_text(
            to_number=customer_phone,
            text="Sorry, I encountered an issue. Please try again.",
            org_id=org_id
        )
