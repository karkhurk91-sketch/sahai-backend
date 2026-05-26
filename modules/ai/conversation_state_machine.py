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
        current_stage = ConversationStage[conversation.conversation_stage.upper()]
        # Use the user's intent, message content, and completed fields to determine
        # if the conversation should move to the next stage.
        # (Logic for the `else` branches is a placeholder for your business rules)
        if current_stage == ConversationStage.GREETING and "name" in (conversation.completed_fields or {}):
            return ConversationStage.QUALIFICATION.value, "Name captured"
        elif current_stage == ConversationStage.QUALIFICATION and intent == "ready_to_book":
            return ConversationStage.BOOKING.value, "User ready to book"
        else:
            return None, None

    def _is_valid_transition(self, from_stage: ConversationStage, to_stage: ConversationStage) -> bool:
        return to_stage in VALID_TRANSITIONS.get(from_stage, [])