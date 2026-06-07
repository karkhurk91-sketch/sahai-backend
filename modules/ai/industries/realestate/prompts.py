from typing import Dict, Optional, List
from modules.interactive.config_loader import get_interactive_config

class Prompts:
    def __init__(self, org_id):
        self.org_id = org_id
        self.industry = "realestate"

    def _get_action_config(self, action: str, state=None) -> Optional[Dict]:
        """Get configuration for an action from dynamic flow (if exists) or interactive config."""
        if state and getattr(state, "flow_steps", None):
            for step in state.flow_steps:
                if step.get("action") == action:
                    return step
        return get_interactive_config(self.industry, action)

    def _build_prompt_text(self, config: Dict, action: str, data: dict, state) -> str:
        """Build plain text prompt from step config or data."""
        if action == "ask_confirmation":
            # Try to get summary from data, otherwise fallback to state
            summary = data.get("summary") if data.get("summary") else {}
            if state and getattr(state, "flow_steps", None):
                for step in state.flow_steps:
                    field = step.get("field")
                    if field and field not in summary:
                        summary[field] = getattr(state, field, "Not provided")

            summary = summary or {
                "name": getattr(state, "name", "Not provided"),
                "budget": getattr(state, "budget", "Not provided"),
                "location": getattr(state, "location", "Not provided"),
                "bhk": getattr(state, "bhk", "Not provided"),
                "possession": getattr(state, "possession", "Not specified"),
            }

            lines = []
            for key, label in [
                ("name", "Name"),
                ("budget", "Budget"),
                ("location", "Location"),
                ("bhk", "BHK"),
                ("possession", "Possession"),
            ]:
                if key in summary:
                    lines.append(f"• {label}: {summary.get(key, 'Not provided')}")

            # Append any additional dynamic fields in flow order
            if state and getattr(state, "flow_steps", None):
                for step in state.flow_steps:
                    field = step.get("field")
                    if field and field not in {"name", "budget", "location", "bhk", "possession"}:
                        lines.append(f"• {field.replace('_', ' ').title()}: {summary.get(field, 'Not provided')}")

            confirmation_text = "Please confirm your details:\n" + "\n".join(lines)
            return confirmation_text
        # For non‑confirmation steps, extract prompt from config
        if isinstance(config.get("body"), dict):
            return config.get("body", {}).get("text", config.get("prompt", ""))
        return config.get("prompt") or config.get("body") or ""

    def _build_value_map(self, config: Dict) -> dict:
        """Build value_map from step config (supports explicit map, options, or list rows)."""
        value_map = config.get("value_map", {}) or {}
        if not value_map and config.get("options"):
            for option in config["options"]:
                option_id = option.get("id")
                if not option_id:
                    continue
                value = option.get("value") if option.get("value") is not None else option.get("title")
                if value is not None:
                    value_map[option_id] = [config.get("field"), value]

        # Support WhatsApp list row selection mapping for list-type interactive steps
        if not value_map and config.get("interactive_action") and isinstance(config.get("interactive_action"), dict):
            sections = config["interactive_action"].get("sections") or []
            for section in sections:
                for row in section.get("rows", []):
                    row_id = row.get("id")
                    if not row_id:
                        continue
                    row_value = row.get("title") if row.get("title") is not None else row.get("id")
                    value_map[row_id] = [config.get("field"), row_value]
        return value_map

    def _build_interactive_reply(self, config: Dict, action: str, data: dict, state=None, summary_text: str = None):
        """Build interactive (button/list) reply from step configuration."""
        if not config or config.get("type") not in ["button", "list"]:
            return None

        # Build value_map (auto from options if needed)
        value_map = self._build_value_map(config)
        
        # For confirmation, use the pre‑built summary_text (which includes details)
        if summary_text and action == "ask_confirmation":
            message_body = summary_text
        else:
            message_body = self._build_prompt_text(config, action, data, state)

        # Handle button type
        if config["type"] == "button":
            # Build buttons from options if present, otherwise use existing action.buttons
            if config.get("options"):
                buttons = []
                for opt in config["options"]:
                    btn = {
                        "type": "reply",
                        "reply": {
                            "id": opt["id"],
                            "title": opt["title"]
                        }
                    }
                    buttons.append(btn)
                action_obj = {"buttons": buttons}
            else:
                # Use existing action from config (if already in WhatsApp format)
                action_obj = config.get("interactive_action") or config.get("action", {})
                if not isinstance(action_obj, dict):
                    action_obj = {"buttons": []}
                # Ensure buttons is a list
                if "buttons" not in action_obj:
                    action_obj["buttons"] = []
            
            interactive_obj = {
                "type": "button",
                "body": {"text": message_body},
                "action": action_obj
            }
            return {"type": "interactive", "interactive": interactive_obj, "value_map": value_map}

        # Handle list type
        if config["type"] == "list":
            # Use interactive_action if present, otherwise build from options? (list is more complex)
            action_obj = config.get("interactive_action") or config.get("action", {})
            if not isinstance(action_obj, dict):
                # Fallback to a minimal action
                action_obj = {"button": "View options", "sections": []}
            
            interactive_obj = {
                "type": "list",
                "header": {"type": "text", "text": config.get("header", "")},
                "body": {"text": message_body},
                "action": action_obj
            }
            if config.get("footer"):
                interactive_obj["footer"] = {"text": config["footer"]}
            return {"type": "interactive", "interactive": interactive_obj, "value_map": value_map}

        return None

    def get_rule_reply(self, action: str, data: dict, state=None):
        # Try to get step configuration from dynamic flow or interactive config
        step_config = self._get_action_config(action, state)

        # If we have a step config and it's an interactive type, build reply dynamically
        if step_config and step_config.get("type") in ["button", "list"]:
            if action == "ask_confirmation":
                confirmation_text = self._build_prompt_text(step_config, action, data, state)
                interactive_reply = self._build_interactive_reply(step_config, action, data, state, summary_text=confirmation_text)
                if interactive_reply:
                    return interactive_reply
            else:
                interactive_reply = self._build_interactive_reply(step_config, action, data, state)
                if interactive_reply:
                    return interactive_reply
            # If interactive building failed but step has plain text, return that
            if step_config.get("type") == "text":
                return step_config.get("prompt") or step_config.get("body")

        # ----- HARDCODED FALLBACKS (kept for backward compatibility) -----
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

        # Plain text replies (hardcoded)
        if action == "greeting":
            return "Hello! I'm your real estate assistant. Are you looking to buy a property?"
        if action == "ask_name":
            return "May I know your name?"
        if action == "ask_phone":
            return "Could you please share your phone number so our agent can reach you?"
        if action == "ask_continue_or_new_property":
            return "Would you like to continue with the same property details, or start a new property search? Reply continue or new property."
        if action == "continue_search":
            return "Okay, continuing with your current property search. What would you like to do next?"
        if action == "ask_which_field_to_correct":
            return "Which detail would you like to change? (budget / location / bhk / name / possession)"
        if action == "ask_which_field":
            return "I didn't catch which field. Please say the field name (budget, location, bhk, name, possession)."
        if action.startswith("ask_new_value_for_"):
            field = action.split("_")[-1]
            return f"Please provide the new value for {field}."

        # Confirmation – hardcoded fallback (if dynamic failed)
        if action == "ask_confirmation":
            # Build summary from data or state
            summary = data.get("summary", {})
            if not summary and state:
                summary = {
                    "name": getattr(state, "name", "Not provided"),
                    "budget": getattr(state, "budget", "Not provided"),
                    "location": getattr(state, "location", "Not provided"),
                    "bhk": getattr(state, "bhk", "Not provided"),
                    "possession": getattr(state, "possession", "Not specified"),
                }
            confirmation_text = (
                f"Please confirm your details:\n"
                f"• Name: {summary.get('name', 'Not provided')}\n"
                f"• Budget: {summary.get('budget', 'Not provided')}\n"
                f"• Location: {summary.get('location', 'Not provided')}\n"
                f"• BHK: {summary.get('bhk', 'Not provided')}\n"
                f"• Possession: {summary.get('possession', 'Not specified')}"
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
            return "Thank you! I have all your details. Would you like me to send you a list of properties that match your criteria?"
        if action == "fallback":
            return "I'm here to help with property prices, brochures, site visits, loans, or any other details. Could you please rephrase your question?"
        return "How can I help you with your property needs today?"

    def _format_summary_lines(self, summary):
        lines = []
        if summary.get("name"):
            lines.append(f"• Name: {summary.get('name')}")
        if summary.get("budget"):
            lines.append(f"• Budget: {summary.get('budget')}")
        if summary.get("location"):
            lines.append(f"• Location: {summary.get('location')}")
        if summary.get("bhk"):
            lines.append(f"• BHK: {summary.get('bhk')}")
        if summary.get("possession"):
            lines.append(f"• Possession: {summary.get('possession')}")
        if summary.get("property_type"):
            lines.append(f"• Property Type: {summary.get('property_type')}")
        return "\n".join(lines)

    def _lead_complete_reply(self, data, state):
        current_summary = data or {}
        previous_summary = getattr(state, "previous_lead_summary", None) or {}
        same_summary = False
        if previous_summary:
            prev = {k: v for k, v in previous_summary.items() if k != "lead_tag"}
            curr = {k: v for k, v in current_summary.items() if k != "lead_tag"}
            same_summary = prev == curr

        if previous_summary and not same_summary:
            details = "Here are your two captured property requirements:\n"
            details += "Previous:\n" + self._format_summary_lines(previous_summary) + "\n\n"
            details += "Current:\n" + self._format_summary_lines(current_summary)
            return details

        name = current_summary.get("name") or ""
        bhk = current_summary.get("bhk") or ""
        location = current_summary.get("location") or ""
        budget = current_summary.get("budget") or ""
        tag = current_summary.get("lead_tag", "warm")
        if tag == "hot":
            return f"Thanks {name}! We have {bhk} BHK options in {location} within {budget}. Would you like to schedule a site visit?"
        return f"Thank you {name}! Our real estate agent will call you as soon as possible to understand your requirements and plan a site visit."
