from enum import Enum
from typing import Dict, Optional, Tuple

class ConversationStage(str, Enum):
    GREETING = "greeting"
    QUALIFICATION = "qualification"
    RECOMMENDATION = "recommendation"
    BOOKING = "booking"
    FOLLOWUP = "followup"
    SUPPORT = "support"
    CLOSED = "closed"

# This dictionary defines the allowed transitions between stages.
VALID_TRANSITIONS = {
    ConversationStage.GREETING: [ConversationStage.QUALIFICATION],
    ConversationStage.QUALIFICATION: [ConversationStage.RECOMMENDATION, ConversationStage.BOOKING, ConversationStage.SUPPORT],
    ConversationStage.RECOMMENDATION: [ConversationStage.BOOKING, ConversationStage.QUALIFICATION, ConversationStage.SUPPORT],
    ConversationStage.BOOKING: [ConversationStage.FOLLOWUP, ConversationStage.SUPPORT, ConversationStage.CLOSED],
    ConversationStage.FOLLOWUP: [ConversationStage.SUPPORT, ConversationStage.CLOSED],
    ConversationStage.SUPPORT: [ConversationStage.BOOKING, ConversationStage.CLOSED],
    ConversationStage.CLOSED: []
}

class ConversationStateMachine:
    """
    Manages the state of a conversation, validates transitions,
    and tracks completed fields to prevent repetition.
    """
    def __init__(self, industry_rules: Dict):
        self.industry_rules = industry_rules # For industry-specific field requirements

    async def validate_stage(self, conversation) -> Tuple[bool, Optional[str]]:
        current_stage = ConversationStage[conversation.conversation_stage.upper()]
        required_fields = self.industry_rules.get(conversation.conversation_stage, {}).get("required_fields", [])
        for field in required_fields:
            if field not in (conversation.completed_fields or {}):
                return False, f"Missing required field: {field}"
        return True, None

    async def try_advance_stage(self, conversation, user_message: str, intent: str) -> Tuple[Optional[str], Optional[str]]:
        # Get current stage and completed fields from the conversation object
        current_stage_str = getattr(conversation, "conversation_stage", "greeting")
        try:
            current_stage = ConversationStage(current_stage_str)
        except ValueError:
            current_stage = ConversationStage.GREETING
        
        completed_fields = getattr(conversation, "completed_fields", {}) or {}

        # Greeting -> Qualification (only needs name; phone can be collected later)
        if current_stage == ConversationStage.GREETING:
            if "name" in completed_fields:
                if self.is_valid_transition(ConversationStage.GREETING, ConversationStage.QUALIFICATION):
                    return ConversationStage.QUALIFICATION.value, "Collected name"
            return None, "Missing name"

        # Qualification -> Booking (if user intent is ready)
        elif current_stage == ConversationStage.QUALIFICATION and intent == "ready_to_book":
            if self.is_valid_transition(ConversationStage.QUALIFICATION, ConversationStage.BOOKING):
                return ConversationStage.BOOKING.value, "User ready to book"
            return None, "Invalid transition"

        # No advancement for other stages in this simple version
        else:
            return None, None

    def _is_valid_transition(self, from_stage: ConversationStage, to_stage: ConversationStage) -> bool:
        return to_stage in VALID_TRANSITIONS.get(from_stage, [])