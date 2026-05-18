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

    def get_rule_reply(self, action: str, data: dict) -> str | None:
        replies = {
            "greet": "Hello! Welcome. How can I assist you today?",
            "ask_menu": "Please visit our website or ask for the menu PDF.",
            "ask_price": "Our pricing varies by product. Please tell me what you're looking for.",
            "ask_hours": "We are open 9 AM to 9 PM, Monday to Saturday.",
            "ask_location": "We are located at [Address]. Would you like the Google Maps link?",
            "ask_contact": "You can reach us at +91 12345 67890 or email contact@example.com.",
            "ask_offer": "We currently have a special offer. Please ask our agent for details.",
            "handle_feedback": "Thank you for your response!",
            "fallback": "I'm sorry, I didn't understand. Could you please rephrase?"
        }
        return replies.get(action)