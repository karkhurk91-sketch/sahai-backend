# modules/orchestration/workflow_engine.py
from typing import Dict, Any
from modules.ai.conversation_state_machine import ConversationStage

class WorkflowOrchestrator:
    """
    Determines the next action based on the current conversation stage,
    user intent, and extracted entities.
    """
    
    def __init__(self, state_machine):
        # state_machine is not used in this simple version, but kept for compatibility
        self.state_machine = state_machine

    async def get_next_action(
        self,
        conversation,
        user_message: str,
        context: Dict[str, Any],
        organization_id: str
    ) -> Dict[str, Any]:
        """
        Returns a deterministic action based on current stage and intent.
        
        Args:
            conversation: SQLAlchemy Conversation object (with stage, completed_fields)
            user_message: The user's message (unused but kept for signature)
            context: Contains 'intent' and 'entities'
            organization_id: The organization ID (unused in this version)
        
        Returns:
            Dict with keys like 'action', 'field', 'data'
        """
        stage = getattr(conversation, "conversation_stage", "greeting")
        intent = context.get("intent", "")
        entities = context.get("entities", {})
        
        # Action mapping table
        if stage == ConversationStage.GREETING.value:
            return {"action": "ask_field", "field": "name"}
        
        elif stage == ConversationStage.QUALIFICATION.value:
            if intent in ["booking_request", "ready_to_book"]:
                return {"action": "create_booking", "data": entities}
            elif intent in ["recommendation_request", "show_recommendations"]:
                return {"action": "show_recommendations"}
            else:
                return {"action": "ask_field", "field": "requirements"}
        
        elif stage == ConversationStage.RECOMMENDATION.value:
            if intent in ["confirmation", "accept", "yes"]:
                return {"action": "create_booking"}
            elif intent in ["rejection", "no", "reject"]:
                return {"action": "ask_field", "field": "alternative_preferences"}
            else:
                return {"action": "show_recommendations"}
        
        elif stage == ConversationStage.BOOKING.value:
            completed = getattr(conversation, "completed_fields", {}) or {}
            if "booking_date" in completed and "booking_time" in completed:
                return {"action": "confirm_booking"}
            else:
                return {"action": "ask_field", "field": "booking_date"}
        
        else:
            return {"action": "respond_generic"}