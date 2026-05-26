from modules.ai.conversation_state_machine import ConversationStateMachine, ConversationStage
from modules.ai.intent_detector import IntentDetector

class WorkflowOrchestrator:
    """
    Determines the next action (ask a question, show a menu, etc.)
    based on the current conversation state, user intent, and memory.
    """
    def __init__(self, state_manager: ConversationStateMachine):
        self.state_manager = state_manager

    async def get_next_action(self, conversation, user_message: str, memory_context: Dict) -> Dict:
        intent, entities = IntentDetector.detect(user_message)
        new_stage, _ = await self.state_manager.try_advance_stage(conversation, user_message, intent)

        # This logic table is the core of your deterministic system.
        # It maps a stage and intent to an action.
        actions = {
            (ConversationStage.QUALIFICATION.value, "qualification"): {"action": "ask_field", "field": "requirements"},
            (ConversationStage.QUALIFICATION.value, "booking_request"): {"action": "show_options", "entity": entities},
            (ConversationStage.BOOKING.value, "booking_request"): {"action": "create_booking", "data": entities},
            (ConversationStage.BOOKING.value, "confirmation"): {"action": "confirm_booking"},
        }
        action = actions.get((conversation.conversation_stage, intent), {"action": "respond_generic"})
        if new_stage:
            action["new_stage"] = new_stage
        return action