from typing import Dict, Optional
from modules.interactive.config_loader import get_interactive_config

class Prompts:
    def __init__(self, org_id):
        self.org_id = org_id
        self.industry = "realestate"

    def _get_action_config(self, action: str, state=None) -> Optional[Dict]:
        if state and getattr(state, "flow_steps", None):
            for step in state.flow_steps:
                if step.get("action") == action:
                    return step
        return get_interactive_config(self.industry, action)

    def _build_prompt_text(self, config: Dict, action: str, data: dict, state) -> str:
        if action == "ask_confirmation":
            summary = data.get("summary") if data.get("summary") else {
                "name": getattr(state, "name", "Not provided"),
                "budget": getattr(state, "budget", "Not provided"),
                "location": getattr(state, "location", "Not provided"),
                "bhk": getattr(state, "bhk", "Not provided"),
                "possession": getattr(state, "possession", "Not specified"),
            }
            return (
                f"Please confirm your details:\n"
                f"• Name: {summary.get('name')}\n"
                f"• Budget: {summary.get('budget')}\n"
                f"• Location: {summary.get('location')}\n"
                f"• BHK: {summary.get('bhk')}\n"
                f"• Possession: {summary.get('possession')}"
            )
        if isinstance(config.get("body"), dict):
            return config.get("body", {}).get("text", config.get("prompt", ""))
        return config.get("prompt") or config.get("body") or ""

    def _build_value_map(self, config: Dict) -> dict:
        value_map = config.get("value_map", {}) or {}
        if not value_map and config.get("options") and config.get("field"):
            for option in config["options"]:
                option_id = option.get("id")
                if not option_id:
                    continue
                value = option.get("value") if option.get("value") is not None else option.get("title")
                if value is not None:
                    value_map[option_id] = [config.get("field"), value]
        return value_map

    def _build_interactive_reply(self, config: Dict, action: str, data: dict, state=None, summary_text: str = None):
        if not config or config.get("type") not in ["button", "list"]:
            return None

        value_map = self._build_value_map(config)
        message_body = summary_text if summary_text and action == "ask_confirmation" else self._build_prompt_text(config, action, data, state)

        if config["type"] == "button":
            interactive_obj = {
                "type": "button",
                "body": {"text": message_body},
                "action": config.get("interactive_action") or config.get("action", {})
            }
            return {"type": "interactive", "interactive": interactive_obj, "value_map": value_map}

        if config["type"] == "list":
            interactive_obj = {
                "type": "list",
                "header": {"type": "text", "text": config.get("header", "")},
                "body": {"text": message_body},
                "action": config.get("interactive_action") or config.get("action", {})
            }
            if config.get("footer"):
                interactive_obj["footer"] = {"text": config["footer"]}
            return {"type": "interactive", "interactive": interactive_obj, "value_map": value_map}

        return None

    def get_rule_reply(self, action: str, data: dict, state=None):
        step_config = self._get_action_config(action, state)
        if step_config:
            if action == "ask_confirmation":
                confirmation_text = self._build_prompt_text(step_config, action, data, state)
                interactive_reply = self._build_interactive_reply(step_config, action, data, state, summary_text=confirmation_text)
                if interactive_reply:
                    return interactive_reply
            else:
                interactive_reply = self._build_interactive_reply(step_config, action, data, state)
                if interactive_reply:
                    return interactive_reply
                if step_config.get("type") == "text":
                    return step_config.get("prompt") or step_config.get("body")

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

        if action == "greeting":
            return "Hello! I'm your real estate assistant. Are you looking to buy a property?"
        if action == "ask_name":
            return "May I know your name?"
        if action == "ask_phone":
            return "Could you please share your phone number so our agent can reach you?"
        if action == "ask_which_field_to_correct":
            return "Which detail would you like to change? (budget / location / bhk / name / possession / phone)"
        if action == "ask_which_field":
            return "I didn't catch which field. Please say the field name (budget, location, bhk, name, possession, phone)."
        if action.startswith("ask_new_value_for_"):
            field = action.split("_")[-1]
            return f"Please provide the new value for {field}."
        if action == "ask_confirmation":
            confirmation_text = self._build_prompt_text(step_config or {}, action, data, state)
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
            return "Thank you! I have all your details. Would you like me to send you a list of properties that match your criteria?"
        if action == "fallback":
            return "I'm here to help with property prices, brochures, site visits, loans, or any other details. Could you please rephrase your question?"
        return "How can I help you with your property needs today?"

    def _lead_complete_reply(self, data, state):
        name = data.get("name") or ""
        bhk = data.get("bhk") or ""
        location = data.get("location") or ""
        budget = data.get("budget") or ""
        tag = data.get("lead_tag", "warm")
        if tag == "hot":
            return f"Thanks {name}! We have {bhk} BHK options in {location} within {budget}. Would you like to schedule a site visit?"
        return f"Thank you {name}! Our real estate agent will call you as soon as possible to understand your requirements and plan a site visit."
