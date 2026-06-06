from modules.interactive.config_loader import get_interactive_config

class Prompts:
    def __init__(self, org_id):
        self.org_id = org_id
        self.industry = "realestate"

    def get_rule_reply(self, action: str, data: dict, state=None):
        # Direct interactive replies for key actions (override config_loader)
        if action == "ask_budget":
            return {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "Please select your budget range:"},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "budget_low", "title": "< ₹20L"}},
                            {"type": "reply", "reply": {"id": "budget_mid", "title": "₹20–50L"}},
                            {"type": "reply", "reply": {"id": "budget_high", "title": "> ₹50L"}}
                        ]
                    }
                },
                "value_map": {
                    "budget_low": ("budget", "< ₹20L"),
                    "budget_mid": ("budget", "₹20–50L"),
                    "budget_high": ("budget", "> ₹50L")
                }
            }

        if action == "ask_bhk":
            return {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "How many bedrooms (BHK) do you need?"},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "bhk1", "title": "1 BHK"}},
                            {"type": "reply", "reply": {"id": "bhk2", "title": "2 BHK"}},
                            {"type": "reply", "reply": {"id": "bhk3", "title": "3 BHK"}}
                        ]
                    }
                },
                "value_map": {
                    "bhk1": ("bhk", "1 BHK"),
                    "bhk2": ("bhk", "2 BHK"),
                    "bhk3": ("bhk", "3 BHK")
                }
            }

        # For other actions, try to load from interactive config (if any)
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
        if action == "ask_which_field_to_correct":
            return "Which detail would you like to change? (budget / location / bhk / name / possession)"
        if action == "ask_which_field":
            return "I didn't catch which field. Please say the field name (budget, location, bhk, name, possession)."
        if action.startswith("ask_new_value_for_"):
            field = action.split("_")[-1]
            return f"Please provide the new value for {field}."

        # Confirmation – dynamically built with all details
        if action == "ask_confirmation":
            # Try to get summary from data, otherwise fallback to state
            if data.get("summary"):
                summary = data["summary"]
            elif state:
                summary = {
                    "name": state.name or "Not provided",
                    "budget": state.budget or "Not provided",
                    "location": state.location or "Not provided",
                    "bhk": state.bhk or "Not provided",
                    "possession": state.possession or "Not specified"
                }
            else:
                summary = {}

            name = summary.get("name", "Not provided")
            budget = summary.get("budget", "Not provided")
            location = summary.get("location", "Not provided")
            bhk = summary.get("bhk", "Not provided")
            possession = summary.get("possession", "Not specified")

            confirmation_text = (
                f"Please confirm your details:\n"
                f"• Name: {name}\n"
                f"• Budget: {budget}\n"
                f"• Location: {location}\n"
                f"• BHK: {bhk}\n"
                f"• Possession: {possession}"
            )

            return {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": confirmation_text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "confirm_yes", "title": "Confirm"}},
                            {"type": "reply", "reply": {"id": "confirm_no", "title": "Change"}}
                        ]
                    }
                },
                "value_map": {
                    "confirm_yes": ["confirm", True],
                    "confirm_no": ["confirm", False]
                }
            }

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
        # Kept for compatibility (not used directly because ask_confirmation is handled above)
        name = summary.get("name", "Not provided")
        budget = summary.get("budget", "Not provided")
        location = summary.get("location", "Not provided")
        bhk = summary.get("bhk", "Not provided")
        possession = summary.get("possession", "Not specified")
        return (
            f"Please confirm your details:\n"
            f"• Name: {name}\n"
            f"• Budget: {budget}\n"
            f"• Location: {location}\n"
            f"• BHK: {bhk}\n"
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
            return f"Thanks {name}! We have {bhk} BHK options in {location} within {budget}. Would you like to schedule a site visit?"
        else:
            return f"Thank you {name}! Our real estate agent will call you as soon as possible to understand your requirements and plan a site visit."