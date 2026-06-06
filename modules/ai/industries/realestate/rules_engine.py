# modules/ai/industries/realestate/rules_engine.py

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

    def __init__(self):
        self.compiled_extractors = {k: re.compile(v, re.IGNORECASE) for k, v in self.EXTRACTORS.items()}

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

        return False

    def detect_intent(self, text: str) -> str:
        text_lower = text.lower()
        for intent, keywords in self.INTENTS.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "unknown"

    def extract_fields(self, text: str, state: State) -> None:
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

    def _get_missing_lead_fields(self, state):
        missing = []
        if not state.name:
            missing.append("name")
        if not state.budget_amount:
            missing.append("budget")
        if not state.location:
            missing.append("location")
        if not state.bhk:
            missing.append("bhk")
        if not state.phone:
            missing.append("phone")
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

    def _extract_field_to_correct(self, text):
        text_lower = text.lower()
        if "name" in text_lower:
            return "name"
        if "phone" in text_lower or "mobile" in text_lower:
            return "phone"
        if "budget" in text_lower:
            return "budget"
        if "location" in text_lower or "area" in text_lower or "city" in text_lower:
            return "location"
        if "bhk" in text_lower or "bedroom" in text_lower:
            return "bhk"
        if "possession" in text_lower or "move" in text_lower:
            return "possession"
        return None

    def process(self, user_input: str, state: State) -> dict:
        intent = self.detect_intent(user_input)
        state.last_intent = intent

        # ----- GREETING HANDLING -----
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
                logger.info(f"Confirmation accepted; moving to recommendation stage, lead_tag={state.lead_tag}")
                return {"action": "lead_complete", "data": state.pending_summary}
            if intent == "confirm_no" or intent == "correction":
                state.confirmation_pending = False
                state.awaiting_field = None
                logger.info("Confirmation rejected; requesting correction")
                return {"action": "ask_which_field_to_correct", "data": {}}
            return {"action": "ask_confirmation_again", "data": {"summary": state.pending_summary}}

        # ----- FIELD SELECTION DURING CORRECTION -----
        if intent == "select_field" and not state.pending_correction_field:
            field = user_input.strip().lower()
            if field == "mobile" or field == "contact":
                field = "phone"
            if field not in ["name", "budget", "location", "bhk", "phone", "possession", "loan_status", "decision_maker", "reason"]:
                return {"action": "ask_which_field", "data": {}}
            state.pending_correction_field = field
            state.awaiting_field = field
            logger.info(f"Field correction started for {field}")
            return {"action": f"ask_new_value_for_{field}", "data": {"field": field}}

        if state.stage == "confirmation" and not state.confirmation_pending and not state.pending_correction_field:
            field = self._extract_field_to_correct(user_input)
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

        # ----- QUALIFICATION STAGE -----
        if state.stage == "qualification":
            missing_lead = self._get_missing_lead_fields(state)
            if missing_lead:
                next_field = missing_lead[0]
                state.awaiting_field = next_field
                return {"action": f"ask_{next_field}", "data": {}}
            state.stage = "confirmation"
            state.confirmation_pending = True
            state.awaiting_field = None
            state.calculate_bant_score()
            state.pending_summary = {
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
            logger.info("Confirmation started; summary prepared")
            return {"action": "ask_confirmation", "data": {"summary": state.pending_summary}}

        # ----- CORRECTION HANDLING -----
        if intent == "correction":
            field = self._extract_field_to_correct(user_input)
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
                state.pending_summary = {
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