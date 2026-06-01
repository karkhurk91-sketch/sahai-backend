from ..base import BasePrompts

class DefaultPrompts(BasePrompts):
    def __init__(self, org_id: str = None):
        self.org_id = org_id

    def get_system_prompt(self) -> str:
        from modules.ai.agent import get_system_prompt_sync
        return get_system_prompt_sync(self.org_id)
    def get_action_prompt(self, action: str, data: dict) -> str:
        # LLM‑oriented prompts (used in AI mode)
        prompts = {
            "greet": "Greet the customer warmly and ask how you can help.",
            "ask_price": "Provide pricing information (or say 'We have flexible pricing, please contact us directly for a quote').",
            "ask_hours": "Give business hours (e.g., 'We are open 9 AM to 9 PM daily').",
            "ask_location": "Share the address or directions to the store.",
            "ask_contact": "Ask if they would like to share their contact details for follow‑up.",
            "menu": "Offer to send the menu or list the main services.",
            "handle_feedback": "Acknowledge the confirmation or rejection politely.",
            "fallback": "Say 'I'm not sure I understood. Could you rephrase?'"
        }
        return prompts.get(action, "How can I help you?")

    def get_rule_reply(self, action, data, state=None):
        """
        Return a reply for a given action.
        The `state` parameter is optional (used by real estate module, ignored here).
        """
        replies = {
            "greeting": "Hello! How can I assist you today?",
            "ask_name": "May I know your name?",
            "ask_phone": "Please share your mobile number.",
            "ask_budget": "What is your budget?",
            "ask_location": "Which location are you interested in?",
            "ask_bhk": "How many bedrooms do you need?",
            "lead_complete": "Thank you! We'll get back to you shortly.",
            "order_confirmed": "Your order has been confirmed. Thank you!",
            "fallback": "I didn't understand. Could you please rephrase?",
        }
        return replies.get(action, "How can I help you?")