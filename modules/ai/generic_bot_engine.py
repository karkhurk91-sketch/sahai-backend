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
        if "confirmation" not in self.config:
            self.config["confirmation"] = {
                "enabled": True,
                "message": "Please confirm your details:",
                "confirm_label": "Confirm",
                "change_label": "Change"
            }
        self.confirm_label = self.config["confirmation"].get("confirm_label", "Confirm")
        self.change_label = self.config["confirmation"].get("change_label", "Change")

    def _evaluate_condition(self, condition: Dict, responses: Dict) -> bool:
        field = condition.get("field")
        operator = condition.get("operator", "eq")
        value = condition.get("value")
        if field not in responses:
            return False
        if operator == "eq":
            return responses[field] == value
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

    def _validate_input(self, field: Dict, user_input: str, is_correction: bool = False) -> Tuple[bool, Optional[str]]:
        validation = field.get("validation", {})
        regex = validation.get("regex")
        if regex:
            if not re.match(regex, user_input, re.IGNORECASE):
                error_msg = validation.get("error_message", f"Invalid format for {field['name']}")
                return False, error_msg
        if not is_correction and field.get("type") in ["button", "list"]:
            options = field.get("options", [])
            option_ids = [opt["id"] for opt in options]
            if user_input not in option_ids:
                return False, f"Please choose one of the valid options."
        return True, None

    def _build_confirmation_message(self, responses: Dict) -> str:
        visible = self._get_visible_fields(responses)
        conf = self.config.get("confirmation", {})
        msg = conf.get("message", "Please confirm your details:")
        lines = [msg]
        for field in visible:
            name = field["name"]
            value = responses.get(name, "Not provided")
            lines.append(f"• {name}: {value}")
        return "\n".join(lines)

    def _get_field_list_options(self, responses: Dict) -> List[Dict]:
        visible = self._get_visible_fields(responses)
        options = []
        for field in visible:
            if field["name"] in responses:
                options.append({"id": field["name"], "title": field["name"].capitalize()})
        return options

    def _get_field_value_options(self, field_def: Dict) -> List[Dict]:
        original = field_def.get("options", [])
        options = [opt.copy() for opt in original]
        options.append({"id": "_other", "title": "Other (type custom value)"})
        return options

    def _ask_for_new_value(self, state: Dict, field_name: str) -> Dict:
        field_def = self.field_map.get(field_name)
        if not field_def:
            return {
                "action": "ask_custom_value",
                "data": {"message": f"Please type the new value for '{field_name}':", "field": field_name},
                "new_state": state
            }
        if field_def.get("type") in ["button", "list"]:
            options = self._get_field_value_options(field_def)
            interactive_type = "button" if len(options) <= 3 else "list"
            return {
                "action": "ask_new_value_with_options",
                "data": {
                    "question": f"Choose new value for {field_name}:",
                    "options": options,
                    "type": interactive_type,
                    "field_name": field_name
                },
                "new_state": state
            }
        else:
            return {
                "action": "ask_new_value",
                "data": {"field": field_name},
                "new_state": state
            }

    def process(self, user_input: str, state: Dict) -> Dict:
        # ----- Post‑completion: user sends a new message -----
        if state.get("completed", False) and not state.get("awaiting_continue_choice", False):
            state["awaiting_continue_choice"] = True
            return {
                "action": "ask_continue_or_new",
                "data": {
                    "message": "Your previous inquiry has been completed. What would you like to do?",
                    "options": [
                        {"id": "continue", "title": "Continue (keep existing lead)"},
                        {"id": "new", "title": "Start New Inquiry"}
                    ],
                    "type": "button"
                },
                "new_state": state
            }

        if state.get("awaiting_continue_choice", False):
            if user_input == "continue":
                state["awaiting_continue_choice"] = False
                return {
                    "action": "send_text",
                    "data": {"message": "Your existing request remains confirmed. No changes made."},
                    "new_state": state
                }
            elif user_input == "new":
                # Reset all conversation state but keep the same conversation
                state = {
                    "responses": {},
                    "awaiting_confirmation": False,
                    "correction_mode": False,
                    "correction_field": None,
                    "last_asked_field": None,
                    "awaiting_custom_field": False,
                    "awaiting_custom_value": False,
                    "completed": False,
                    "awaiting_continue_choice": False
                }
                # Restart the normal flow
                return self.process(user_input, state)
            else:
                return {
                    "action": "ask_continue_or_new",
                    "data": {
                        "message": "Please choose an option:",
                        "options": [
                            {"id": "continue", "title": "Continue"},
                            {"id": "new", "title": "Start New Inquiry"}
                        ],
                        "type": "button"
                    },
                    "new_state": state
                }

        # ----- Existing process logic (unchanged below) -----
        responses = state.get("responses", {})
        awaiting_confirmation = state.get("awaiting_confirmation", False)
        correction_mode = state.get("correction_mode", False)
        correction_field = state.get("correction_field")
        awaiting_custom_field = state.get("awaiting_custom_field", False)
        awaiting_custom_value = state.get("awaiting_custom_value", False)

        if awaiting_custom_field:
            typed_field = user_input.strip().lower()
            visible_names = [f["name"].lower() for f in self._get_visible_fields(responses)]
            if typed_field in visible_names:
                state["awaiting_custom_field"] = False
                state["correction_field"] = typed_field
                return self._ask_for_new_value(state, typed_field)
            else:
                state["awaiting_custom_field"] = False
                options = self._get_field_list_options(responses)
                return {
                    "action": "ask_which_field",
                    "data": {"question": "Which field would you like to change?", "options": options, "type": "list"},
                    "new_state": state
                }

        if awaiting_custom_value and correction_field:
            field_def = self.field_map.get(correction_field)
            if not field_def:
                state["awaiting_custom_value"] = False
                return self.process(user_input, state)
            is_valid, error = self._validate_input(field_def, user_input, is_correction=True)
            if not is_valid:
                return {"action": "validation_error", "data": {"error": error}, "new_state": state}
            responses[correction_field] = user_input
            state["responses"] = responses
            state["awaiting_custom_value"] = False
            state["correction_mode"] = False
            state["correction_field"] = None
            state["awaiting_confirmation"] = True
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses),
                    "options": [{"id": "confirm", "title": self.confirm_label}, {"id": "change", "title": self.change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if correction_mode and correction_field is None and not awaiting_custom_field:
            selected = user_input.strip()
            if selected == "_other":
                state["awaiting_custom_field"] = True
                return {"action": "ask_custom_field", "data": {"message": "Please type the field name you want to change:"}, "new_state": state}
            else:
                visible_answered = [f["name"] for f in self._get_visible_fields(responses) if f["name"] in responses]
                if selected in visible_answered:
                    state["correction_field"] = selected
                    return self._ask_for_new_value(state, selected)
                else:
                    options = self._get_field_list_options(responses)
                    return {
                        "action": "ask_which_field",
                        "data": {"question": "Which field would you like to change?", "options": options, "type": "list"},
                        "new_state": state
                    }

        if correction_mode and correction_field is not None:
            field_def = self.field_map.get(correction_field)
            if not field_def:
                state["correction_mode"] = False
                state["correction_field"] = None
                return self.process(user_input, state)
            options = field_def.get("options", [])
            option_ids = [opt["id"] for opt in options]
            if user_input == "_other":
                state["awaiting_custom_value"] = True
                return {
                    "action": "ask_custom_value",
                    "data": {"message": f"Please type the new value for '{correction_field}':", "field": correction_field},
                    "new_state": state
                }
            if user_input in option_ids:
                responses[correction_field] = user_input
            else:
                is_valid, error = self._validate_input(field_def, user_input, is_correction=True)
                if not is_valid:
                    return {"action": "validation_error", "data": {"error": error}, "new_state": state}
                responses[correction_field] = user_input
            state["responses"] = responses
            state["correction_mode"] = False
            state["correction_field"] = None
            state["awaiting_confirmation"] = True
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses),
                    "options": [{"id": "confirm", "title": self.confirm_label}, {"id": "change", "title": self.change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if awaiting_confirmation:
            if user_input in ["confirm", self.confirm_label.lower()]:
                return {"action": "create_lead", "data": responses, "new_state": state}
            elif user_input in ["change", self.change_label.lower()]:
                state["correction_mode"] = True
                state["correction_field"] = None
                state["awaiting_custom_field"] = False
                state["awaiting_custom_value"] = False
                options = self._get_field_list_options(responses)
                return {
                    "action": "ask_which_field",
                    "data": {"question": "Which field would you like to change?", "options": options, "type": "list"},
                    "new_state": state
                }
            else:
                return {
                    "action": "ask_confirmation",
                    "data": {
                        "message": self._build_confirmation_message(responses),
                        "options": [{"id": "confirm", "title": self.confirm_label}, {"id": "change", "title": self.change_label}],
                        "type": "button"
                    },
                    "new_state": state
                }

        next_field = self._get_next_missing_field(responses)
        if next_field is None:
            state["awaiting_confirmation"] = True
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses),
                    "options": [{"id": "confirm", "title": self.confirm_label}, {"id": "change", "title": self.change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if state.get("last_asked_field") == next_field["name"]:
            is_valid, error = self._validate_input(next_field, user_input, is_correction=False)
            if not is_valid:
                return {"action": "validation_error", "data": {"error": error}, "new_state": state}
            responses[next_field["name"]] = user_input
            state["responses"] = responses
            state["last_asked_field"] = None
            return self.process(user_input, state)

        state["last_asked_field"] = next_field["name"]
        if next_field.get("type") in ["button", "list"]:
            return {
                "action": "ask",
                "data": {
                    "field_type": next_field.get("type", "text"),
                    "question": next_field["question"],
                    "options": next_field.get("options", []),
                    "field_name": next_field["name"]
                },
                "new_state": state
            }
        else:
            return {
                "action": "ask",
                "data": {
                    "field_type": "text",
                    "question": next_field["question"],
                    "field_name": next_field["name"]
                },
                "new_state": state
            }