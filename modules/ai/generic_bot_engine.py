# modules/ai/generic_bot_engine.py
import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class GenericBotEngine:
    def __init__(self, config: Dict):
        self.config = config
        self.fields = config.get("fields", [])
        self.field_map = {f["name"]: f for f in self.fields}
        self.confirm_label = config.get("confirmation", {}).get("confirm_label", "Confirm")
        self.change_label = config.get("confirmation", {}).get("change_label", "Change")

    def _evaluate_condition(self, condition: Dict, responses: Dict) -> bool:
        field = condition.get("field")
        operator = condition.get("operator", "eq")
        value = condition.get("value")
        if field not in responses:
            return False
        if operator == "eq":
            return responses[field] == value
        # Add more operators if needed (ne, gt, lt, contains)
        return False

    def _get_visible_fields(self, responses: Dict) -> List[Dict]:
        visible = []
        for field in self.fields:
            if "condition" in field:
                if not self._evaluate_condition(field["condition"], responses):
                    continue
            visible.append(field)
        return visible

    def _get_next_missing_field(self, responses: Dict) -> Optional[Dict]:
        visible = self._get_visible_fields(responses)
        for field in visible:
            if field["name"] not in responses:
                return field
        return None

    def _validate_input(self, field: Dict, user_input: str) -> Tuple[bool, Optional[str]]:
        validation = field.get("validation", {})
        regex = validation.get("regex")
        if regex:
            if not re.match(regex, user_input, re.IGNORECASE):
                error_msg = validation.get("error_message", f"Invalid format for {field['name']}")
                return False, error_msg
        # For button/list types, check if input matches an option id
        if field.get("type") in ["button", "list"]:
            options = field.get("options", [])
            option_ids = [opt["id"] for opt in options]
            if user_input not in option_ids:
                return False, f"Please choose one of the valid options."
        return True, None

    def _build_confirmation_message(self, responses: Dict) -> str:
        visible = self._get_visible_fields(responses)
        lines = [self.config["confirmation"].get("message", "Please confirm your details:")]
        for field in visible:
            name = field["name"]
            value = responses.get(name, "Not provided")
            lines.append(f"• {name}: {value}")
        lines.append(f"Reply '{self.confirm_label}' to confirm or '{self.change_label}' to change.")
        return "\n".join(lines)

    def process(self, user_input: str, state: Dict) -> Dict:
        """
        state = {
            "responses": {},
            "awaiting_confirmation": False,
            "correction_mode": False,
            "correction_field": None,
            "last_asked_field": None
        }
        Returns action dict with keys: "action", "data"
        """
        responses = state.get("responses", {})
        awaiting_confirmation = state.get("awaiting_confirmation", False)
        correction_mode = state.get("correction_mode", False)
        correction_field = state.get("correction_field")

        # ----- Correction flow -----
        if correction_mode:
            if correction_field is None:
                # Asking which field to change
                if user_input.lower() in [f["name"].lower() for f in self._get_visible_fields(responses)]:
                    correction_field = user_input.strip().lower()
                    state["correction_field"] = correction_field
                    return {"action": "ask_new_value", "data": {"field": correction_field}}
                else:
                    return {
                        "action": "invalid_field",
                        "data": {"fields": [f["name"] for f in self._get_visible_fields(responses)]}
                    }
            else:
                # User provided new value for the field
                field_def = self.field_map.get(correction_field)
                if not field_def:
                    state["correction_mode"] = False
                    state["correction_field"] = None
                    return self.process(user_input, state)

                is_valid, error = self._validate_input(field_def, user_input)
                if not is_valid:
                    return {"action": "validation_error", "data": {"error": error}}

                responses[correction_field] = user_input
                state["responses"] = responses
                state["correction_mode"] = False
                state["correction_field"] = None
                state["awaiting_confirmation"] = True
                return {
                    "action": "ask_confirmation",
                    "data": {"message": self._build_confirmation_message(responses)}
                }

        # ----- Confirmation step -----
        if awaiting_confirmation:
            if user_input.lower() == self.confirm_label.lower():
                return {"action": "create_lead", "data": responses}
            elif user_input.lower() == self.change_label.lower():
                state["correction_mode"] = True
                state["correction_field"] = None
                return {
                    "action": "ask_which_field",
                    "data": {"fields": [f["name"] for f in self._get_visible_fields(responses)]}
                }
            else:
                return {
                    "action": "confirmation_invalid",
                    "data": {"message": self._build_confirmation_message(responses)}
                }

        # ----- Normal flow: find next missing field -----
        next_field = self._get_next_missing_field(responses)
        if next_field is None:
            # All fields collected
            state["awaiting_confirmation"] = True
            return {
                "action": "ask_confirmation",
                "data": {"message": self._build_confirmation_message(responses)}
            }

        # If we already asked this field and expect an answer
        if state.get("last_asked_field") == next_field["name"]:
            is_valid, error = self._validate_input(next_field, user_input)
            if not is_valid:
                return {"action": "validation_error", "data": {"error": error}}
            responses[next_field["name"]] = user_input
            state["responses"] = responses
            state["last_asked_field"] = None
            # Re‑process to go to next field or confirmation
            return self.process(user_input, state)

        # First time asking this field
        state["last_asked_field"] = next_field["name"]
        return {
            "action": "ask",
            "data": {
                "field_type": next_field.get("type", "text"),
                "question": next_field["question"],
                "options": next_field.get("options", []),
                "field_name": next_field["name"]
            }
        }