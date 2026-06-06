# modules/ai/industries/realestate/prompts.py
from modules.interactive.config_loader import get_interactive_config

class Prompts:
    def __init__(self, org_id):
        self.org_id = org_id
        self.industry = "realestate"

    def get_rule_reply(self, action: str, data: dict, state=None):
        # Check for interactive configuration
        interactive_config = get_interactive_config(self.industry, action)
        if interactive_config:
            interactive_obj = {
                "type": interactive_config["type"],
                "body": {"text": interactive_config.get("body", "")}
            }
            if interactive_config["type"] == "button":
                interactive_obj["action"] = interactive_config["action"]
            elif interactive_config["type"] == "list":
                interactive_obj["header"] = {"type": "text", "text": interactive_config.get("header", "")}
                interactive_obj["body"] = {"text": interactive_config.get("body", "")}
                if "footer" in interactive_config:
                    interactive_obj["footer"] = {"text": interactive_config["footer"]}
                interactive_obj["action"] = interactive_config["action"]
            return {
                "type": "interactive",
                "interactive": interactive_obj,
                "value_map": interactive_config.get("value_map", {})
            }

        # Plain text replies
        if action == "greeting":
            return "Hello! I'm your real estate assistant. Are you looking to buy a property?"
        if action == "ask_name":
            return "May I know your name?"
        if action == "ask_phone":
            return "Please share your mobile number."
        if action == "ask_which_field_to_correct":
            return "Which detail would you like to change? (budget / location / bhk / name / phone / possession)"
        if action == "ask_which_field":
            return "I didn't catch which field. Please say the field name (budget, location, bhk, name, phone, possession)."
        if action.startswith("ask_new_value_for_"):
            field = action.split("_")[-1]
            return f"Please provide the new value for {field}."
        if action == "ask_confirmation":
            summary = data.get("summary", {})
            return self._confirmation_prompt(summary)
        if action == "lead_complete":
            return self._lead_complete_reply(data, state)
        if action == "recommendation":
            tag = data.get("tag", "warm")
            if tag == "hot":
                return "Great! Based on your requirements, I have a few options. Here are two: one near the metro for ₹48L and another near the park for ₹52L. Would you like to schedule a site visit?"
            else:
                return "Thank you! I have all your details. Would you like me to send you a list of properties that match your criteria?"
        if action == "fallback":
            return "I'm here to help with property prices, brochures, site visits, loans, or any other details. Could you please rephrase your question?"
        return "How can I help you with your property needs today?"

    def _confirmation_prompt(self, summary):
        name = summary.get("name", "Not provided")
        budget = summary.get("budget", "Not provided")
        location = summary.get("location", "Not provided")
        bhk = summary.get("bhk", "Not provided")
        phone = summary.get("phone", "Not provided")
        possession = summary.get("possession", "Not specified")
        return (
            f"Please confirm your details:\n"
            f"• Name: {name}\n"
            f"• Budget: {budget}\n"
            f"• Location: {location}\n"
            f"• BHK: {bhk}\n"
            f"• Phone: {phone}\n"
            f"• Possession: {possession}\n"
            f"Reply with 'Confirm' or 'Change'."
        )

    def _lead_complete_reply(self, data, state):
        name = data.get("name") or ""
        bhk = data.get("bhk") or ""
        location = data.get("location") or ""
        budget = data.get("budget") or ""
        tag = data.get("lead_tag", "warm")
        if tag == "hot":
            return f"Thanks {name}! We have {bhk} BHK options in {location} within {budget}. Would you like to schedule a site visit or see photos?"
        else:
            return f"Thank you {name}! I have all your details. Would you like me to send you a list of properties that match your criteria?"