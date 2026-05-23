import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from modules.common.database import AsyncSessionLocal
from modules.ai.processor import process_incoming_message
from modules.ai.lead_capture import create_lead
from modules.ai.lead_extractor import extract_lead_from_conversation
from modules.ai.rag import get_relevant_context
from modules.ai.memory_manager import MemoryManager
from modules.leads.scoring_engine import score_lead
from modules.leads.nurturing_engine import check_nurturing_triggers
from modules.websocket import manager

class AIOrchestrator:
    def __init__(self):
        self.memory = MemoryManager()

    async def process_message(self, lead_id: str, message_id: str):
        async with AsyncSessionLocal() as db:
            # Load lead, conversation, messages
            lead = await db.get(Lead, lead_id)
            msg = await db.get(Message, message_id)
            conversation = await db.get(Conversation, lead.conversation_id)
            
            # Load memory
            context = await self.memory.load_context(conversation.id)
            
            # RAG
            docs = await get_relevant_context(lead.organization_id, msg.content)
            
            # Call existing AI processor (reuse)
            ai_reply, extracted_data = await process_incoming_message(
                db=db,
                message=msg,
                lead=lead,
                context=context,
                rag_docs=docs
            )
            
            # Persist extracted data using existing lead_capture
            if extracted_data:
                lead = await create_lead(
                    db=db,
                    organization_id=lead.organization_id,
                    conversation_id=conversation.id,
                    customer_phone=lead.customer_phone,
                    extracted_data=extracted_data,
                    lead_schema_id=lead.schema_id
                )
            
            # Score lead (existing function)
            lead = await score_lead(db, lead.id)
            
            # Save memory
            await self.memory.save_context(conversation.id, {
                "last_message": msg.content,
                "ai_reply": ai_reply,
                "extracted_data": extracted_data,
                "lead_score": lead.lead_score
            })
            
            # Trigger nurturing (if any)
            await check_nurturing_triggers(db, lead.id)
            
            # Real-time update via WebSocket
            await manager.broadcast({
                "type": "lead_updated",
                "lead_id": str(lead.id),
                "lead_score": lead.lead_score,
                "last_message": msg.content,
                "ai_reply": ai_reply
            })
            
            return ai_reply