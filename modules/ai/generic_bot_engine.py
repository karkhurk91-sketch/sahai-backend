# modules/ai/generic_bot_engine.py
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from modules.websocket import manager  # add at top


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

    # ---------- Localisation helpers ----------
    def _get_localized_text(self, obj: Dict, key: str, lang: str, default_key: str = None) -> str:
        """Return language‑specific text (e.g., question_hi, question_en) or fallback."""
        if not lang:
            lang = "en"
        specific = obj.get(f"{key}_{lang}")
        if specific:
            return specific
        # Fallback to default key (e.g., "question") or the provided default
        return obj.get(default_key or key, "")

    def _get_field_question(self, field: Dict, lang: str) -> str:
        return self._get_localized_text(field, "question", lang, "question")

    def _get_option_title(self, option: Dict, lang: str) -> str:
        return self._get_localized_text(option, "title", lang, "title")

    def _get_confirmation_message(self, lang: str) -> str:
        conf = self.config.get("confirmation", {})
        return self._get_localized_text(conf, "message", lang, "message")

    def _get_confirm_label(self, lang: str) -> str:
        conf = self.config.get("confirmation", {})
        return self._get_localized_text(conf, "confirm_label", lang, "confirm_label") or "Confirm"

    def _get_change_label(self, lang: str) -> str:
        conf = self.config.get("confirmation", {})
        return self._get_localized_text(conf, "change_label", lang, "change_label") or "Change"

    # ---------- Core methods (unchanged except for localisation) ----------
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

    def _build_confirmation_message(self, responses: Dict, lang: str) -> str:
        visible = self._get_visible_fields(responses)
        msg = self._get_confirmation_message(lang)
        lines = [msg]
        for field in visible:
            name = field["name"]
            value = responses.get(name, "Not provided")
            # Localize field label if available (optional)
            label = self._get_localized_text(field, "label", lang, "name") or name
            lines.append(f"• {label}: {value}")
        confirm_label = self._get_confirm_label(lang)
        change_label = self._get_change_label(lang)
        lines.append(f"Reply '{confirm_label}' to confirm or '{change_label}' to change.")
        return "\n".join(lines)

    def _get_field_list_options(self, responses: Dict, lang: str) -> List[Dict]:
        visible = self._get_visible_fields(responses)
        options = []
        for field in visible:
            if field["name"] in responses:
                label = self._get_localized_text(field, "label", lang, "name") or field["name"].capitalize()
                options.append({"id": field["name"], "title": label})
        return options

    def _get_field_value_options(self, field_def: Dict, lang: str) -> List[Dict]:
        original = field_def.get("options", [])
        options = []
        for opt in original:
            options.append({
                "id": opt["id"],
                "title": self._get_option_title(opt, lang)
            })
        options.append({"id": "_other", "title": "Other (type custom value)"})
        return options

    def _ask_for_new_value(self, state: Dict, field_name: str, lang: str) -> Dict:
        field_def = self.field_map.get(field_name)
        if not field_def:
            return {
                "action": "ask_custom_value",
                "data": {"message": f"Please type the new value for '{field_name}':", "field": field_name},
                "new_state": state
            }
        if field_def.get("type") in ["button", "list"]:
            options = self._get_field_value_options(field_def, lang)
            interactive_type = "button" if len(options) <= 3 else "list"
            question = self._get_field_question(field_def, lang)
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

    def _is_general_query(self, user_input: str) -> bool:
        if len(user_input) > 50:
            return True
        question_words = ["what", "how", "why", "when", "where", "who", "which", "can you", "could you", "please tell", "explain", "about", "policy", "process", "fee", "charge", "cost"]
        lower = user_input.lower()
        for word in question_words:
            if word in lower:
                return True
        if user_input.strip().endswith('?'):
            return True
        return False

    def process(self, user_input: str, state: Dict) -> Dict:
        # ---------- Multi‑language: ask language if not set ----------
        lang = state.get("lang")
        if not lang and not state.get("awaiting_lang_selection"):
            state["awaiting_lang_selection"] = True
            return {
                "action": "ask_language",
                "data": {
                    "message": "Please select your preferred language / कृपया अपनी पसंदीदा भाषा चुनें:",
                    "options": [
                        {"id": "en", "title": "English"},
                        {"id": "hi", "title": "हिंदी"}
                    ]
                },
                "new_state": state
            }
        if state.get("awaiting_lang_selection"):
            if user_input in ["en", "hi"]:
                state["lang"] = user_input
                state["awaiting_lang_selection"] = False
                # Restart process with new language (no user input)
                return self.process("", state)
            else:
                # Invalid choice – repeat language prompt
                return {
                    "action": "ask_language",
                    "data": {
                        "message": "Please select your preferred language / कृपया अपनी पसंदीदा भाषा चुनें:",
                        "options": [
                            {"id": "en", "title": "English"},
                            {"id": "hi", "title": "हिंदी"}
                        ]
                    },
                    "new_state": state
                }

        # ---------- Post‑completion (unchanged) ----------
        if state.get("completed", False) and not state.get("awaiting_continue_choice", False):
            state["awaiting_continue_choice"] = True
            msg = "Your previous inquiry has been completed. What would you like to do?"
            if lang == "hi":
                msg = "आपकी पिछली जांच पूरी हो चुकी है। आप क्या करना चाहेंगे?"
            return {
                "action": "ask_continue_or_new",
                "data": {
                    "message": msg,
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
                msg = "Your existing request remains confirmed. No changes made."
                if lang == "hi":
                    msg = "आपका मौजूदा अनुरोध पुष्टि किया गया है। कोई बदलाव नहीं किया गया।"
                return {
                    "action": "send_text",
                    "data": {"message": msg},
                    "new_state": state
                }
            elif user_input == "new":
                state = {
                    "responses": {},
                    "awaiting_confirmation": False,
                    "correction_mode": False,
                    "correction_field": None,
                    "last_asked_field": None,
                    "awaiting_custom_field": False,
                    "awaiting_custom_value": False,
                    "completed": False,
                    "awaiting_continue_choice": False,
                    "lang": lang
                }
                return self.process(user_input, state)
            else:
                # repeat
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
                return self._ask_for_new_value(state, typed_field, lang)
            else:
                state["awaiting_custom_field"] = False
                options = self._get_field_list_options(responses, lang)
                question = "Which field would you like to change?" if lang != "hi" else "आप कौन सा फ़ील्ड बदलना चाहेंगे?"
                return {
                    "action": "ask_which_field",
                    "data": {"question": question, "options": options, "type": "list"},
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
            confirm_label = self._get_confirm_label(lang)
            change_label = self._get_change_label(lang)
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses, lang),
                    "options": [{"id": "confirm", "title": confirm_label}, {"id": "change", "title": change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if correction_mode and correction_field is None and not awaiting_custom_field:
            selected = user_input.strip()
            if selected == "_other":
                state["awaiting_custom_field"] = True
                msg = "Please type the field name you want to change:" if lang != "hi" else "कृपया वह फ़ील्ड नाम टाइप करें जिसे आप बदलना चाहते हैं:"
                return {"action": "ask_custom_field", "data": {"message": msg}, "new_state": state}
            else:
                visible_answered = [f["name"] for f in self._get_visible_fields(responses) if f["name"] in responses]
                if selected in visible_answered:
                    state["correction_field"] = selected
                    return self._ask_for_new_value(state, selected, lang)
                else:
                    options = self._get_field_list_options(responses, lang)
                    question = "Which field would you like to change?" if lang != "hi" else "आप कौन सा फ़ील्ड बदलना चाहेंगे?"
                    return {
                        "action": "ask_which_field",
                        "data": {"question": question, "options": options, "type": "list"},
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
                msg = f"Please type the new value for '{correction_field}':" if lang != "hi" else f"'{correction_field}' के लिए नया मान टाइप करें:"
                return {
                    "action": "ask_custom_value",
                    "data": {"message": msg, "field": correction_field},
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
            confirm_label = self._get_confirm_label(lang)
            change_label = self._get_change_label(lang)
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses, lang),
                    "options": [{"id": "confirm", "title": confirm_label}, {"id": "change", "title": change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if awaiting_confirmation:
            confirm_label = self._get_confirm_label(lang).lower()
            change_label = self._get_change_label(lang).lower()
            if user_input.lower() in ["confirm", confirm_label]:
                return {"action": "create_lead", "data": responses, "new_state": state}
            elif user_input.lower() in ["change", change_label]:
                state["correction_mode"] = True
                state["correction_field"] = None
                state["awaiting_custom_field"] = False
                state["awaiting_custom_value"] = False
                options = self._get_field_list_options(responses, lang)
                question = "Which field would you like to change?" if lang != "hi" else "आप कौन सा फ़ील्ड बदलना चाहेंगे?"
                return {
                    "action": "ask_which_field",
                    "data": {"question": question, "options": options, "type": "list"},
                    "new_state": state
                }
            else:
                confirm_label_btn = self._get_confirm_label(lang)
                change_label_btn = self._get_change_label(lang)
                return {
                    "action": "ask_confirmation",
                    "data": {
                        "message": self._build_confirmation_message(responses, lang),
                        "options": [{"id": "confirm", "title": confirm_label_btn}, {"id": "change", "title": change_label_btn}],
                        "type": "button"
                    },
                    "new_state": state
                }

        next_field = self._get_next_missing_field(responses)
        if next_field is None:
            state["awaiting_confirmation"] = True
            confirm_label = self._get_confirm_label(lang)
            change_label = self._get_change_label(lang)
            return {
                "action": "ask_confirmation",
                "data": {
                    "message": self._build_confirmation_message(responses, lang),
                    "options": [{"id": "confirm", "title": confirm_label}, {"id": "change", "title": change_label}],
                    "type": "button"
                },
                "new_state": state
            }

        if state.get("last_asked_field") == next_field["name"]:
            is_valid, error = self._validate_input(next_field, user_input, is_correction=False)
            if not is_valid:
                if self._is_general_query(user_input):
                    return {
                        "action": "unmatched",
                        "data": {
                            "question": self._get_field_question(next_field, lang),
                            "user_input": user_input,
                            "field_name": next_field["name"]
                        },
                        "new_state": state
                    }
                else:
                    return {"action": "validation_error", "data": {"error": error}, "new_state": state}
            responses[next_field["name"]] = user_input
            state["responses"] = responses
            state["last_asked_field"] = None
            return self.process(user_input, state)

        state["last_asked_field"] = next_field["name"]
        media = next_field.get("media")
        question = self._get_field_question(next_field, lang)

        if next_field.get("type") in ["button", "list"]:
            options = []
            for opt in next_field.get("options", []):
                options.append({
                    "id": opt["id"],
                    "title": self._get_option_title(opt, lang)
                })
            return {
                "action": "ask",
                "data": {
                    "field_type": next_field.get("type", "text"),
                    "question": question,
                    "options": options,
                    "field_name": next_field["name"],
                    "media": media
                },
                "new_state": state
            }
        if next_field.get("type") == "booking":
            # For booking fields, we expect the user to select date/time/service
            # The engine returns an action that tells webhook to fetch slots
            return {
                "action": "ask_booking",
                "data": {
                    "field_name": next_field["name"],
                    "question": next_field.get("question", "Please select your booking details:"),
                    "booking_config": next_field.get("booking_config", {})  # e.g., service type, duration
                },
                "new_state": state
            }
        else:
            return {
                "action": "ask",
                "data": {
                    "field_type": "text",
                    "question": question,
                    "field_name": next_field["name"],
                    "media": media
                },
                "new_state": state
            }