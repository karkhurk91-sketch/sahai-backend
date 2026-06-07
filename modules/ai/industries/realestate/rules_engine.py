import re
import logging
from .state import State

logger = logging.getLogger(__name__)

class RulesEngine:
    """
    Deterministic rule engine for real estate lead capture.
    Handles Hinglish, variations, common abbreviations, and includes a confirmation step.
    """

    # Intent keywords (Hinglish + English)
    INTENTS = {
        "greeting": [
            "hi", "hello", "hey", "namaste", "good morning", "good afternoon", "good evening",
            "नमस्ते", "हेलो", "कैसे हो", "kya haal"
        ],
        "buy": ["buy", "purchase", "khareedna", "खरीदना", "flat chahiye", "property chahiye"],
        "rent": ["rent", "lease", "kiraye", "किराए", "rent pe"],
        "sell": ["sell", "bechna", "sell property", "बेचना"],
        "budget": ["budget", "price", "cost", "rate", "kitne ka", "कितने का", "range", "up to"],
        "location": ["location", "area", "city", "sector", "colony", "लोकेशन", "जगह", "में"],
        "bhk": ["bhk", "bedroom", "room", "बीएचके", "कमरा"],
        "possession": ["possession", "move in", "shift", "कब्जा", "शिफ्ट", "जल्दी"],
        "loan": ["loan", "bank", "emi", "finance", "home loan", "लोन"],
        "site_visit": ["site visit", "visit", "see property", "dekhe", "देखना", "tour"],
        "brochure": ["brochure", "price list", "rate list", "details", "specs", "floor plan"],
        "objection_price": ["too high", "expensive", "bahut zyada", "out of budget", "महंगा"],
        "objection_docs": ["paper", "document", "noc", "registry", "legal", "कागजात"],
        "objection_time": ["not now", "later", "soch raha", "thinking", "not ready", "बाद में"],
        "correction": ["actually", "change", "wrong", "not correct", "update", "modify", "galat", "sahi nahi"],
        "confirm_yes": ["yes", "haan", "ji", "ok", "theek", "sure", "confirm", "हाँ", "ठीक"],
        "confirm_no": ["no", "nahi", "cancel", "reject", "नहीं"],
        "new_property": ["new property", "another property", "new lead", "start new", "restart"],
        "continue": ["continue", "resume", "carry on", "keep going"],
        "name": ["my name is", "i am", "called", "name", "मेरा नाम"],
        "phone": ["mobile", "phone", "number", "contact", "मोबाइल", "नंबर"],
        "select_field": ["name", "budget", "location", "bhk", "phone", "possession"],
    }

    # Extraction regex (supports Hinglish, numbers, and variations)
    EXTRACTORS = {
        "name": r"(?:my name is|i am|called|name is|मेरा नाम)\s*([A-Za-z\u0900-\u097F]+(?:\s+[A-Za-z\u0900-\u097F]+){0,2})",
        "phone": r"(\d{10})",
        "budget": r"(\d+(?:\.\d+)?)\s*(lac|lakh|lakhs|cr|crore|लाख|करोड़)",
        "location": r"(?:in|at|near|location|लोकेशन|में)\s*([A-Za-z\u0900-\u097F]+(?:\s+[A-Za-z\u0900-\u097F]+)?)",
        "bhk": r"(\d+)\s*(bhk|bedroom|बीएचके|बेडरूम)",
        "possession": r"(immediate|now|asap|1[- ]?month[s]?|2[- ]?month[s]?|3[- ]?month[s]?|6[- ]?month[s]?|तुरंत|अभी|जल्दी)",
        "loan_status": r"(cash|pre[- ]approved|preapproved|apply|loan|बिना loan|कैश)",
        "is_decision_maker": r"(i am the decision|sole|myself|i will decide|main decision lunga|alone)",
        "reason": r"(job|relocation|transfer|upgrade|bigger|family|investment|rental income|परिवार|नौकरी)",
    }

    # Default flow for dynamic mode (only used if organization has no custom flow and dynamic mode is not enabled)
    # This is not used as fallback; it's for reference.
    DEFAULT_FLOW = [
        {"field": "name", "action": "ask_name", "required": True},
        {"field": "budget", "action": "ask_budget", "required": True},
        {"field": "location", "action": "ask_location", "required": True},
        {"field": "bhk", "action": "ask_bhk", "required": True},
        {"field": "possession", "action": "ask_possession", "required": True},
        {"field": "loan_status", "action": "ask_loan", "required": False},
        {"field": "is_decision_maker", "action": "ask_decision_maker", "required": False},
        {"field": "reason", "action": "ask_reason", "required": False},
    ]

    def __init__(self):
        self.compiled_extractors = {k: re.compile(v, re.IGNORECASE) for k, v in self.EXTRACTORS.items()}
        self.id_value_map = {}

    def set_id_value_map(self, id_map: dict):
        self.id_value_map = id_map

    def _has_dynamic_flow(self, state):
        return hasattr(state, "flow_steps") and state.flow_steps and len(state.flow_steps) > 0

    def _get_flow_steps(self, state):
        return state.flow_steps if self._has_dynamic_flow(state) else None

    def _field_has_value(self, state, field):
        """Return True if field is already captured (any non-None value)."""
        if not field:
            return True
        if field == "budget":
            return getattr(state, "budget_amount", None) is not None
        val = getattr(state, field, None)
        return val is not None

    def _get_current_step(self, state):
        """
        Return the step that the user is currently on (the first missing required step).
        Iterates over flow steps in order and returns the first step whose field is missing.
        This is the core of the dynamic flow.
        """
        steps = self._get_flow_steps(state)
        if not steps:
            return None
        for step in steps:
            # Only consider required steps (optional steps are skipped)
            if not step.get("required", True):
                continue
            field = step.get("field")
            if not field:
                # Steps without a field (e.g., confirmation) are considered always pending
                return step
            if not self._field_has_value(state, field):
                return step
        return None  # All steps completed

    def _get_next_missing_lead_step(self, state):
        """Legacy method – kept for compatibility, but not used in dynamic flow."""
        flow_steps = self._get_flow_steps(state)
        if not flow_steps:
            return None
        for step in flow_steps:
            if not step.get("required", True):
                continue
            field = step.get("field")
            if not field or self._field_has_value(state, field):
                continue
            return step
        return None

    def _get_action_for_field(self, state, field):
        flow_steps = self._get_flow_steps(state)
        if flow_steps:
            for step in flow_steps:
                if step.get("field") == field:
                    return step.get("action", f"ask_{field}")
        return f"ask_{field}"

    def _get_dynamic_field_names(self, state):
        flow_steps = self._get_flow_steps(state)
        if not flow_steps:
            return []
        return [step.get("field") for step in flow_steps if step.get("field")]

    def _get_available_fields(self, state):
        base_fields = [
            "name", "budget", "location", "bhk", "phone", "possession",
            "loan_status", "decision_maker", "reason"
        ]
        return list({*base_fields, *self._get_dynamic_field_names(state)})

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[_\-]+", " ", text.strip().lower())

    def _build_summary(self, state):
        summary = {
            "name": getattr(state, "name", None),
            "phone": getattr(state, "phone", None),
            "budget": getattr(state, "budget", None),
            "location": getattr(state, "location", None),
            "bhk": getattr(state, "bhk", None),
            "possession": getattr(state, "possession", None),
            "loan_status": getattr(state, "loan_status", None),
            "is_decision_maker": getattr(state, "is_decision_maker", None),
            "reason": getattr(state, "reason", None),
            "lead_tag": getattr(state, "lead_tag", None),
        }
        if self._has_dynamic_flow(state):
            for step in state.flow_steps:
                field = step.get("field")
                if field and field not in summary:
                    summary[field] = getattr(state, field, None)
        return summary

    def _summaries_are_same(self, first: dict, second: dict):
        if not first or not second:
            return False
        keys = set(first.keys()) | set(second.keys())
        for key in keys:
            fval = (first.get(key) or "").strip().lower()
            sval = (second.get(key) or "").strip().lower()
            if fval != sval:
                return False
        return True

    def _reset_for_new_property(self, state):
        state.previous_lead_summary = state.previous_lead_summary or (state.pending_summary.copy() if state.pending_summary else self._build_summary(state))
        state.name = None
        state.phone = None
        state.budget = None
        state.budget_amount = None
        state.location = None
        state.bhk = None
        state.property_type = None
        state.possession = None
        state.intent = None
        state.loan_status = None
        state.is_decision_maker = None
        state.reason = None
        state.bant_score = 0
        state.lead_tag = None
        state.confirmation_pending = False
        state.pending_summary = {}
        state.pending_correction_field = None
        state.awaiting_field = None
        state.budget_confirmed = False
        state.interactive_map = {}
        state.stage = "qualification"

    def _get_first_missing_step_action(self, state):
        if self._has_dynamic_flow(state):
            next_step = self._get_next_missing_lead_step(state)
            if next_step:
                return next_step.get("action", f"ask_{next_step.get('field')}")
        missing_lead = self._get_missing_lead_fields(state)
        if missing_lead:
            return f"ask_{missing_lead[0]}"
        return "ask_name"

    def _save_current_summary(self, state):
        if state.pending_summary:
            state.previous_lead_summary = state.pending_summary.copy()
        else:
            state.previous_lead_summary = self._build_summary(state)

    # ----- Original hardcoded missing fields (kept as fallback) -----
    def _get_missing_lead_fields(self, state):
        """Original hardcoded list of required fields (name, budget, location, bhk, possession)."""
        missing = []
        if not state.name:
            missing.append("name")
        if not state.budget_amount:
            missing.append("budget")
        if not state.location:
            missing.append("location")
        if not state.bhk:
            missing.append("bhk")
        if not state.possession:
            missing.append("possession")
        return missing

    def _get_missing_bant_fields(self, state):
        missing = []
        if not state.budget_amount:
            missing.append("budget")
        if not state.possession:
            missing.append("possession")
        if not state.loan_status:
            missing.append("loan_status")
        if state.is_decision_maker is None:
            missing.append("decision_maker")
        if not state.reason:
            missing.append("reason")
        return missing

    def _redact_value(self, field: str, value: str) -> str:
        if field == "phone" and value:
            return f"***{value[-4:]}"
        return value

    def _is_name_candidate(self, text: str) -> bool:
        trimmed = text.strip()
        words = trimmed.split()
        if not 1 <= len(words) <= 3:
            return False
        normalized = trimmed.lower()
        normalized_tokens = re.findall(r"[A-Za-z\u0900-\u097F]+", normalized)
        if any(kw in normalized for kw in ["budget", "price", "phone", "mobile", "location", "area", "city", "bhk", "bedroom", "loan", "visit", "site"]):
            return False
        if any(token in normalized_tokens for token in ["yes", "no", "thanks", "thank"]):
            return False
        return all(re.fullmatch(r"[A-Za-z\u0900-\u097F]+", w) for w in words)

    def _is_location_candidate(self, text: str) -> bool:
        trimmed = text.strip()
        if not trimmed or len(trimmed) > 50:
            return False
        if any(ch.isdigit() for ch in trimmed):
            return False
        normalized = trimmed.lower()
        normalized_tokens = re.findall(r"[A-Za-z\u0900-\u097F]+", normalized)
        if any(kw in normalized for kw in ["budget", "price", "phone", "mobile", "bhk", "loan", "visit", "site"]):
            return False
        if any(token in normalized_tokens for token in ["yes", "no", "thanks", "thank", "buy", "rent", "sell"]):
            return False
        return all(re.fullmatch(r"[A-Za-z\u0900-\u097F]+", w) for w in trimmed.split())

    def _fill_awaiting_field(self, text: str, state: State) -> bool:
        if state.awaiting_field == "name" and not state.name and self._is_name_candidate(text):
            state.name = text.strip()
            state.awaiting_field = None
            logger.info("Captured name from direct response")
            return True

        if state.awaiting_field == "location" and not state.location and self._is_location_candidate(text):
            state.location = text.strip()
            state.awaiting_field = None
            logger.info("Captured location from direct response")
            return True

        if state.awaiting_field == "budget" and not state.budget_amount:
            match = self.compiled_extractors["budget"].search(text)
            if match:
                amount = float(match.group(1))
                unit = match.group(2).lower() if len(match.groups()) > 1 else ""
                if unit in ["lac", "lakh", "lakhs", "लाख"]:
                    state.budget = f"{int(amount) if amount.is_integer() else amount} lakh"
                    state.budget_amount = amount
                elif unit in ["crore", "cr", "करोड़"]:
                    state.budget = f"{int(amount) if amount.is_integer() else amount} crore"
                    state.budget_amount = amount * 100
                else:
                    state.budget = f"{amount} lakh"
                    state.budget_amount = amount
                state.awaiting_field = None
                logger.info("Captured budget from direct response")
                return True

        if state.awaiting_field:
            field = state.awaiting_field
            value = text.strip()
            if value:
                setattr(state, field, value)
                state.awaiting_field = None
                logger.info(f"Captured {field} from direct response")
                return True

        return False

    def detect_intent(self, text: str) -> str:
        text_lower = text.strip().lower()
        if text_lower in self.INTENTS:
            return text_lower
        for intent, keywords in self.INTENTS.items():
            for kw in keywords:
                if text_lower == kw:
                    return intent
        for intent, keywords in self.INTENTS.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def _match_typed_text_to_button_option(self, text: str, state: State) -> bool:
        if not state.awaiting_field:
            return False
        flow_steps = getattr(state, "flow_steps", [])
        step = None
        for s in flow_steps:
            if s.get("field") == state.awaiting_field and s.get("type") == "button":
                step = s
                break
        if not step:
            return False
        typed = text.strip().lower()
        for opt in step.get("options", []):
            opt_title = opt.get("title", "").lower()
            if typed == opt_title or typed in opt_title or opt_title in typed:
                field = step["field"]
                value = opt.get("value", opt.get("title"))
                setattr(state, field, value)
                if field == "budget":
                    state.budget_amount = self._parse_budget_amount(value)
                    state.budget_confirmed = True
                state.awaiting_field = None
                logger.info(f"Matched typed answer '{text}' to button option {opt.get('id')} -> {field}={value}")
                return True
        return False

    def extract_fields(self, text: str, state: State) -> None:
        if text in self.id_value_map:
            mapping = self.id_value_map[text]
            if isinstance(mapping, (tuple, list)) and len(mapping) == 2:
                field, value = mapping
            elif isinstance(mapping, str):
                field = state.awaiting_field
                if not field:
                    if self._has_dynamic_flow(state):
                        next_step = self._get_next_missing_lead_step(state)
                        field = next_step.get("field") if next_step else "location"
                    else:
                        missing = self._get_missing_lead_fields(state)
                        field = missing[0] if missing else "location"
                value = mapping
                logger.info(f"String mapping for {text} -> using field={field}, value={value}")
            else:
                logger.error(f"Invalid value_map entry for {text}: {mapping}")
                return
            setattr(state, field, value)
            if field == "budget":
                state.budget_amount = self._parse_budget_amount(value)
                state.budget_confirmed = True
            if state.awaiting_field == field:
                state.awaiting_field = None
            return

        if self._match_typed_text_to_button_option(text, state):
            return

        extracted = False
        for field, pattern in self.compiled_extractors.items():
            if getattr(state, field) is None:
                match = pattern.search(text)
                if match:
                    value = match.group(1)
                    if field == "budget":
                        amount = float(match.group(1))
                        unit = match.group(2).lower() if len(match.groups()) > 1 else ""
                        if unit in ["lac", "lakh", "lakhs", "लाख"]:
                            state.budget = f"{int(amount) if amount.is_integer() else amount} lakh"
                            state.budget_amount = amount
                        elif unit in ["crore", "cr", "करोड़"]:
                            state.budget = f"{int(amount) if amount.is_integer() else amount} crore"
                            state.budget_amount = amount * 100
                        else:
                            state.budget = f"{amount} lakh"
                            state.budget_amount = amount
                        state.budget_confirmed = True
                    elif field == "possession":
                        val_lower = value.lower()
                        if "immediate" in val_lower or "now" in val_lower or "asap" in val_lower or "तुरंत" in val_lower:
                            state.possession = "immediate"
                        elif "1" in val_lower or "2" in val_lower:
                            state.possession = "1-2 months"
                        elif "3" in val_lower or "6" in val_lower:
                            state.possession = "3-6 months"
                        else:
                            state.possession = "6+ months"
                    elif field == "loan_status":
                        if "cash" in value or "कैश" in value:
                            state.loan_status = "cash"
                        elif "pre" in value:
                            state.loan_status = "pre-approved"
                        elif "apply" in value or "loan" in value:
                            state.loan_status = "apply"
                        else:
                            state.loan_status = "none"
                    elif field == "is_decision_maker":
                        state.is_decision_maker = True
                    elif field == "reason":
                        if "job" in value or "relocation" in value or "transfer" in value:
                            state.reason = "relocation"
                        elif "upgrade" in value or "bigger" in value:
                            state.reason = "upgrade"
                        elif "investment" in value:
                            state.reason = "investment"
                        else:
                            state.reason = value
                    else:
                        setattr(state, field, value)
                    logger.info(f"Extracted {field} = {self._redact_value(field, value)}")
                    extracted = True
        if not extracted:
            self._fill_awaiting_field(text, state)

    def _parse_budget_amount(self, budget_str: str) -> float:
        match = re.search(r'(\d+(?:\.\d+)?)', budget_str)
        if match:
            return float(match.group(1))
        return 0.0

    def _extract_field_to_correct(self, text, state=None):
        text_normalized = self._normalize_text(text)
        if state is not None:
            for step in self._get_flow_steps(state) or []:
                field = step.get("field")
                if not field:
                    continue
                if field.lower() in text_normalized or field.replace("_", " ").lower() in text_normalized:
                    return field
                label = step.get("label") or step.get("title") or step.get("header")
                if label and label.lower() in text_normalized:
                    return field
        if "name" in text_normalized:
            return "name"
        if "phone" in text_normalized or "mobile" in text_normalized:
            return "phone"
        if "budget" in text_normalized:
            return "budget"
        if "location" in text_normalized or "area" in text_normalized or "city" in text_normalized:
            return "location"
        if "bhk" in text_normalized or "bedroom" in text_normalized:
            return "bhk"
        if "possession" in text_normalized or "move" in text_normalized:
            return "possession"
        return None

    def process(self, user_input: str, state: State) -> dict:
        if hasattr(state, 'interactive_map') and state.interactive_map:
            self.id_value_map = state.interactive_map

        intent = self.detect_intent(user_input)
        state.last_intent = intent

        # ----- GREETING -----
        if state.stage == "greeting":
            if intent == "greeting":
                state.awaiting_field = None
                logger.info("Greeting detected")
                return {"action": "greeting", "data": {}}
            state.stage = "qualification"
            logger.info("Transitioning from greeting to qualification")

        # ----- CONFIRMATION STATE -----
        if state.confirmation_pending:
            if intent == "confirm_yes":
                state.confirmation_pending = False
                state.stage = "recommendation"
                state.awaiting_field = None
                state.calculate_bant_score()
                state.pending_summary["lead_tag"] = state.lead_tag
                self._save_current_summary(state)
                logger.info(f"Confirmation accepted; moving to recommendation stage, lead_tag={state.lead_tag}")
                return {"action": "lead_complete", "data": state.pending_summary}
            if intent == "confirm_no" or intent == "correction":
                state.confirmation_pending = False
                state.awaiting_field = None
                logger.info("Confirmation rejected; requesting correction")
                return {"action": "ask_which_field_to_correct", "data": {}}
            return {"action": "ask_confirmation_again", "data": {"summary": state.pending_summary}}

        # ----- GREETING AFTER CONFIRMATION -----
        if state.stage == "recommendation" and intent == "greeting" and getattr(state, "pending_summary", None):
            return {"action": "ask_continue_or_new_property", "data": {}}

        # ----- NEW PROPERTY / CONTINUE HANDLING -----
        if intent == "new_property":
            self._reset_for_new_property(state)
            next_action = self._get_first_missing_step_action(state)
            state.awaiting_field = next_action.replace("ask_", "")
            return {"action": next_action, "data": {}}
        if intent == "continue" and state.stage == "recommendation":
            return {"action": "continue_search", "data": {}}

        # ----- FIELD SELECTION DURING CORRECTION -----
        if intent == "select_field" and not state.pending_correction_field:
            field = user_input.strip().lower()
            if field == "mobile" or field == "contact":
                field = "phone"
            available_fields = self._get_available_fields(state)
            if field not in available_fields:
                return {"action": "ask_which_field", "data": {}}
            state.pending_correction_field = field
            state.awaiting_field = field
            logger.info(f"Field correction started for {field}")
            return {"action": f"ask_new_value_for_{field}", "data": {"field": field}}

        if state.stage == "confirmation" and not state.confirmation_pending and not state.pending_correction_field:
            field = self._extract_field_to_correct(user_input, state)
            if field:
                state.pending_correction_field = field
                state.awaiting_field = field
                logger.info(f"Field correction started for {field}")
                return {"action": f"ask_new_value_for_{field}", "data": {"field": field}}

        # ----- DIRECT INTENT HANDLING -----
        if intent == "site_visit":
            state.awaiting_field = None
            return {"action": "offer_site_visit", "data": {}}
        if intent == "brochure":
            state.awaiting_field = None
            return {"action": "reply_brochure", "data": {}}
        if intent == "loan":
            state.awaiting_field = None
            return {"action": "reply_loan", "data": {}}
        if intent.startswith("objection"):
            obj = intent.split("_")[1]
            state.awaiting_field = None
            return {"action": "handle_objection", "data": {"objection_type": obj}}
        if intent in ["sell", "rent"]:
            pass

        # ----- FIELD EXTRACTION -----
        if not state.pending_correction_field:
            self.extract_fields(user_input, state)

        # ----- QUALIFICATION STAGE (with dynamic flow) -----
        if state.stage == "qualification":
            # If we are already waiting for a field, handle it
            if state.awaiting_field:
                # If the awaited field is now filled (by extraction), clear it
                if self._field_has_value(state, state.awaiting_field):
                    state.awaiting_field = None
                else:
                    action = self._get_action_for_field(state, state.awaiting_field)
                    return {"action": action, "data": {}}

            # Get the next missing step from the dynamic flow (or fallback to hardcoded)
            next_step = self._get_current_step(state)
            if next_step:
                field = next_step.get("field")
                action = next_step.get("action", f"ask_{field}")
                state.awaiting_field = field
                logger.info(f"Next step: {action} (field={field})")
                return {"action": action, "data": {}}

            # If dynamic flow is not available, fallback to original hardcoded logic
            missing_lead = self._get_missing_lead_fields(state)
            if missing_lead:
                next_field = missing_lead[0]
                state.awaiting_field = next_field
                return {"action": f"ask_{next_field}", "data": {}}

            # All lead fields collected → move to confirmation
            state.stage = "confirmation"
            state.confirmation_pending = True
            state.awaiting_field = None
            state.calculate_bant_score()
            summary = {
                "name": state.name,
                "phone": state.phone,
                "budget": state.budget,
                "location": state.location,
                "bhk": state.bhk,
                "possession": state.possession,
                "loan_status": state.loan_status,
                "is_decision_maker": state.is_decision_maker,
                "reason": state.reason,
                "lead_tag": state.lead_tag,
            }
            if self._has_dynamic_flow(state):
                for step in state.flow_steps:
                    field = step.get("field")
                    if field and field not in summary:
                        summary[field] = getattr(state, field, None)
            state.pending_summary = summary
            logger.info("Confirmation started; summary prepared")
            return {"action": "ask_confirmation", "data": {"summary": state.pending_summary}}

        # ----- CORRECTION HANDLING -----
        if intent == "correction":
            field = self._extract_field_to_correct(user_input, state)
            if field:
                state.pending_correction_field = field
                state.awaiting_field = field
                logger.info(f"Field correction requested for {field}")
                return {"action": f"ask_new_value_for_{field}", "data": {"field": field}}
            return {"action": "ask_which_field", "data": {}}

        # ----- WAITING FOR NEW VALUE DURING CORRECTION -----
        if state.pending_correction_field:
            field = state.pending_correction_field
            new_value = user_input.strip()
            if new_value:
                setattr(state, field, new_value)
                if field == "budget":
                    match = re.search(r'(\d+(?:\.\d+)?)\s*(lac|lakh|cr|crore|लाख|करोड़)?', new_value, re.IGNORECASE)
                    if match:
                        amount = float(match.group(1))
                        unit = match.group(2).lower() if match.group(2) else ""
                        if unit in ["lac", "lakh", "लाख"]:
                            state.budget_amount = amount
                        elif unit in ["crore", "cr", "करोड़"]:
                            state.budget_amount = amount * 100
                        else:
                            state.budget_amount = amount
                state.pending_correction_field = None
                state.awaiting_field = None
                state.stage = "confirmation"
                state.confirmation_pending = True
                state.calculate_bant_score()
                summary = {
                    "name": state.name,
                    "phone": state.phone,
                    "budget": state.budget,
                    "location": state.location,
                    "bhk": state.bhk,
                    "possession": state.possession,
                    "loan_status": state.loan_status,
                    "is_decision_maker": state.is_decision_maker,
                    "reason": state.reason,
                    "lead_tag": state.lead_tag,
                }
                if self._has_dynamic_flow(state):
                    for step in state.flow_steps:
                        field = step.get("field")
                        if field and field not in summary:
                            summary[field] = getattr(state, field, None)
                state.pending_summary = summary
                logger.info(f"Field correction applied for {field}")
                return {"action": "ask_confirmation", "data": {"summary": state.pending_summary}}
            state.pending_correction_field = None
            state.awaiting_field = None
            return {"action": "ask_which_field", "data": {}}

        # ----- RECOMMENDATION STAGE -----
        if state.stage == "recommendation":
            if state.lead_tag is None:
                state.calculate_bant_score()
            logger.info(f"Recommendation stage entered, lead_tag={state.lead_tag}")
            return {"action": "recommendation", "data": {"tag": state.lead_tag}}

        logger.info("Falling back to rule-mode default reply")
        state.awaiting_field = None
        return {"action": "fallback", "data": {}}